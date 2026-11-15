"""
回合状态（对局时间 / 剩余局数）。

数据来自启动器用的那个 status.php：
    {"server_time": <unix>, "servers": [
        {"server_name": "...", "ip": "...", "port": 27015,
         "rounds_left": 3, "round_time_left": 245,
         "round_phase": "回合中", "updated_at": <unix>}]}

要点：
  * 服务端有 1 次/秒 限流，命中时返回 {"error": "rate limit exceeded", "retry_after": N}
    —— 这里把 retry_after 带回去，让上层退避，不当作致命错误
  * round_time_left 是"数据产生那一刻"的剩余秒数，要按 (server_time - updated_at)
    做一次时间差补偿，之后由前端/调用方本地走秒，不再重复请求

覆盖范围与字段语义（2026-11-15 实测，5 秒采样跟了一整局）：
  * 只收录 202.189.21.228 上的 3 台测试服 + 兑换服；6 台 mio 正式服不在接口里
  * 测试服每秒刷新（updated_at 与 server_time 同步），兑换服回合字段恒为 -1
  * 一局的完整周期：
        回合中   time_left 从 ~1080（= br_time_round）往下走
        回合中   time_left = 0 —— 倒计时提前归零但回合**还在打**（实测持续约 3 分钟，
                 期间玩家分数仍在涨），不能显示成 00:00 当作"马上结束"
        回合结束 time_left 30 → 0（= br_time_postround）
        准备阶段 time_left = -1；rounds_left 在这个阶段减 1
        回合中   新一局开始
"""

from __future__ import annotations

import json
import time

DEFAULT_ROUNDS_API = "https://neomio.nigigasaki.live/status.php"
USER_AGENT = "Neobreach/1.0.0.86 (NeoProbe)"

# 服务端已经返回中文时直接透传；以下映射用于兼容返回英文枚举的情况（与原启动器一致）
PHASE_MAP = {
    "idle": "空闲",
    "waiting": "等待玩家",
    "preparing": "准备阶段",
    "round": "回合中",
    "postround": "回合结束",
    "warhead_starting": "核弹启动中",
    "warhead": "核弹倒计时",
    "offline": "离线",
    "": "-",
}


def norm_phase(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return "-"
    return PHASE_MAP.get(text.lower(), text)


class RoundStatus:
    """一台服务器的回合状态（__slots__，见 a2s.ServerAddress 的说明）。"""

    __slots__ = ("key", "phase", "rounds_left", "time_left", "synced_at",
                 "updated_at", "server_name", "server_time")

    def __init__(self, key: str, phase: str = "-", rounds_left: int | None = None,
                 time_left: int | None = None, synced_at: float = 0.0,
                 updated_at: int = 0, server_name: str = "",
                 server_time: int = 0) -> None:
        self.key = key
        self.phase = phase
        self.rounds_left = rounds_left
        self.time_left = time_left
        self.synced_at = synced_at
        self.updated_at = updated_at
        self.server_name = server_name
        self.server_time = server_time

    def remaining(self, now: float | None = None) -> int | None:
        """按本地时钟插值出"现在"的剩余秒数。"""
        if self.time_left is None:
            return None
        now = time.time() if now is None else now
        elapsed = max(0.0, now - self.synced_at)
        return max(0, int(round(self.time_left - elapsed)))

    @property
    def timer(self) -> str:
        """倒计时该怎么理解。

        countdown  正常倒计时，可以本地走秒
        expired    "回合中"但 time_left 已是 0：回合还在打，只是倒计时归零了，
                   不知道还要多久——界面不能把它画成 00:00
        none       没有倒计时（准备阶段 / 空闲 / 未上报）
        """
        if self.time_left is None:
            return "none"
        if self.time_left == 0 and self.phase == "回合中":
            return "expired"
        return "countdown"

    def to_dict(self) -> dict:
        return {
            "timer": self.timer,
            "phase": self.phase,
            "rounds_left": self.rounds_left,
            "time_left": self.time_left,
            "remaining": self.remaining(),
            "synced_at": round(self.synced_at, 2),
            "updated_at": self.updated_at,
            "stale": self.updated_at > 0 and (time.time() - self.updated_at) > 120,
            "server_name": self.server_name,
        }


class FetchResult:
    """一次请求的结果。失败不抛异常，把原因放在 error 里。"""

    __slots__ = ("statuses", "ok", "error", "retry_after", "fetched_at", "server_time")

    def __init__(self, statuses: dict[str, RoundStatus] | None = None, ok: bool = False,
                 error: str | None = None, retry_after: float = 0.0,
                 fetched_at: float = 0.0, server_time: int = 0) -> None:
        self.statuses = statuses if statuses is not None else {}
        self.ok = ok
        self.error = error
        self.retry_after = retry_after
        self.fetched_at = fetched_at
        self.server_time = server_time

    @property
    def count(self) -> int:
        return len(self.statuses)


DEFAULT_CATALOG_FILE = "server_catalog.php"


def catalog_url(rounds_url: str) -> str:
    """由回合接口推导服务器目录接口。

    新版启动器（1.0.0.87）把服务器列表改成在线更新，走的就是 server_catalog.php。
    它和 status.php 同目录，所以可以直接由回合地址推出来。
    """
    u = (rounds_url or "").strip()
    if not u or "status.php" not in u:
        return ""
    return u.replace("status.php", DEFAULT_CATALOG_FILE)


def parse_catalog(data) -> list[dict]:
    """解析 server_catalog.php。

    结构：{"schema_version":1,"servers":[{"name","ip","port","category",
           "expected_mode","expected_round_rule","visible_to_steam_ids":[]}]}
    """
    if not isinstance(data, dict):
        return []
    out: list[dict] = []
    for item in data.get("servers") or []:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip") or "").strip()
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if not ip or port <= 0 or port > 65535:
            continue
        vis = item.get("visible_to_steam_ids") or []
        out.append({
            "address": build_key(ip, port),
            "name": str(item.get("name") or "").strip(),
            "category": str(item.get("category") or "").strip(),
            "mode": str(item.get("expected_mode") or "").strip(),
            "round_rule": str(item.get("expected_round_rule") or "").strip(),
            "visible_to": [str(v) for v in vis] if isinstance(vis, list) else [],
        })
    return out


def fetch_catalog(url: str, timeout: float = 4.0) -> tuple[list[dict], str | None]:
    """拉一次服务器目录。返回 (列表, 错误)。失败不抛异常。"""
    if not url:
        return [], "未配置目录接口"
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(256 * 1024)
    except urllib.error.HTTPError as exc:
        return [], f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [], f"网络错误: {getattr(exc, 'reason', exc)}"
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return [], "响应不是合法 JSON"
    return parse_catalog(data), None


def build_key(ip: str, port: int) -> str:
    return f"{(ip or '').strip()}:{int(port)}".lower()


def fetch(url: str = DEFAULT_ROUNDS_API, timeout: float = 4.0) -> FetchResult:
    """拉一次回合状态。失败不抛异常，把原因放进 FetchResult。"""
    result = FetchResult(fetched_at=time.time())
    if not url:
        result.error = "未配置回合接口"
        return result

    # 延后导入：urllib.request 会连带拉 http.client / email / ssl，约 130 ms，
    # 而只有真正要联网时才需要它（面板/CLI 启动时不该付这个成本）
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(256 * 1024)
    except urllib.error.HTTPError as exc:
        result.error = f"HTTP {exc.code}"
        return result
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result.error = f"网络错误: {getattr(exc, 'reason', exc)}"
        return result

    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        result.error = "响应不是合法 JSON"
        return result

    parsed = parse_payload(data, now=time.time())
    parsed.fetched_at = result.fetched_at
    return parsed


def parse_payload(data, now: float | None = None) -> FetchResult:
    """纯解析：给一份 status.php 的 JSON（dict），返回 FetchResult。"""
    result = FetchResult(fetched_at=time.time())
    if not isinstance(data, dict):
        result.error = "响应结构异常"
        return result

    if data.get("error"):
        result.error = str(data.get("error"))
        try:
            result.retry_after = float(data.get("retry_after") or 0)
        except (TypeError, ValueError):
            result.retry_after = 0.0
        return result

    servers = data.get("servers")
    if not isinstance(servers, list):
        result.error = "缺少 servers 字段"
        return result

    try:
        server_time = int(data.get("server_time") or 0)
    except (TypeError, ValueError):
        server_time = 0
    result.server_time = server_time
    if now is None:
        now = time.time()

    for item in servers:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip") or "").strip()
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if not ip or port <= 0:
            continue

        updated_at = _as_int(item.get("updated_at"), 0)
        rounds_left = _as_int(item.get("rounds_left"), -1)
        time_left = _as_int(item.get("round_time_left"), -1)

        # 补偿"数据生成 → 我们收到"之间的时间差（与原启动器一致，上限 300 秒）
        if time_left >= 0 and updated_at > 0 and server_time > 0:
            delta = server_time - updated_at
            if 0 < delta < 300:
                time_left = max(0, time_left - delta)

        result.statuses[build_key(ip, port)] = RoundStatus(
            key=build_key(ip, port),
            phase=norm_phase(item.get("round_phase")),
            rounds_left=None if rounds_left < 0 else rounds_left,
            time_left=None if time_left < 0 else time_left,
            synced_at=now,
            updated_at=updated_at,
            server_time=server_time,
            server_name=str(item.get("server_name") or "").strip(),
        )

    result.ok = True
    return result


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_clock(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


__all__ = [
    "DEFAULT_ROUNDS_API", "RoundStatus", "FetchResult", "fetch",
    "build_key", "norm_phase", "format_clock", "PHASE_MAP",
]
