"""
服务器清单 + 后台并发查询调度。

设计要点（对着原启动器的毛病改）：
  * 查询全在后台线程池，绝不阻塞调用方
  * 单个地址失败不影响其它地址；失败原因逐条记录
  * 有 TTL 缓存，重复刷新不会打爆网络
  * 自动刷新可在窗口不可见时暂停（由前端调用 /api/config 控制）
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import a2s, clientstate, launch, queue, rounds, slots, vip


def default_data_dir() -> Path:
    env = os.environ.get("NEOPROBE_HOME")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "NeoProbe"
    return Path.home() / ".neoprobe"


class Entry:
    """一个被监视的服务器。"""

    __slots__ = ("address", "key", "label", "added_at", "info", "rtt_ms", "state",
                 "error", "checked_at", "history", "map_now", "map_changes", "map_since")

    def __init__(self, address: str, label: str = "") -> None:
        self.address = address
        self.key = address.lower()
        self.label = label
        self.added_at = time.time()
        self.info: dict | None = None
        self.rtt_ms: float | None = None
        self.state = "pending"  # pending | querying | ok | error
        self.error: str | None = None
        self.checked_at: float | None = None
        self.history: list[list[float]] = []  # [[ts, players, rtt], ...]
        # 换图观测：地图变了 = 这一局翻篇了。比 A2S 里任何字段都实在
        self.map_now: str = ""
        self.map_changes: list[float] = []     # 最近若干次换图时刻
        self.map_since: float = 0.0            # 当前这张图从什么时候开始

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "label": self.label,
            "state": self.state,
            "error": self.error,
            "rtt_ms": self.rtt_ms,
            "checked_at": self.checked_at,
            "info": self.info,
            "history": self.history[-60:],
            "mapinfo": self.mapinfo(),
        }

    def mapinfo(self) -> dict | None:
        """当前地图 + 换图节奏（全部来自实测：A2S_INFO 的 map 字段变化）。"""
        if not self.map_now:
            return None
        changes = self.map_changes[-8:]
        spans = [b - a for a, b in zip(changes, changes[1:]) if 60 <= b - a <= 6 * 3600]
        avg = sum(spans) / len(spans) if spans else None
        return {
            "map": self.map_now,
            "since": round(time.time() - self.map_since, 1) if self.map_since else None,
            "changes": len(changes),
            "avg_duration": round(avg, 1) if avg else None,
            "spans": len(spans),
        }


class QueryManager:
    def __init__(self, data_dir: Path | None = None, timeout: float = 1.5,
                 samples: int = 2, workers: int = 16, interval: float = 15.0,
                 rounds_url: str = rounds.DEFAULT_ROUNDS_API,
                 rounds_enabled: bool = True,
                 rounds_interval: float = 10.0,
                 gmod_path: str = "", retries: int = 3,
                 vip_api: str = "") -> None:
        self.data_dir = data_dir or default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_path = self.data_dir / "servers.json"
        self.timeout = timeout
        self.samples = samples
        self.retries = max(1, int(retries))
        self.interval = interval
        self.auto = True

        self.rounds_url = rounds_url
        self.rounds_enabled = bool(rounds_enabled) and bool(rounds_url)
        self.rounds_interval = max(3.0, float(rounds_interval))
        self.gmod_path = gmod_path
        self.catalog_url = rounds.catalog_url(self.rounds_url)   # 新版启动器的在线服务器列表
        self._catalog_meta: dict[str, Any] = {
            "ok": False, "error": None, "count": 0, "added": 0,
            "fetched_at": 0.0, "url": self.catalog_url,
        }
        self._catalog_at = 0.0
        self._rounds: dict[str, rounds.RoundStatus] = {}
        self._rounds_meta: dict[str, Any] = {
            "ok": False, "error": None, "fetched_at": 0.0, "count": 0,
            "url": self.rounds_url, "enabled": self.rounds_enabled,
            "interval": self.rounds_interval, "retry_after": 0.0,
        }
        self._rounds_stop = threading.Event()
        self._rounds_thread: threading.Thread | None = None
        self._slots: dict[str, slots.SlotTracker] = {}
        self._slots_interval = 20.0        # 空位观测间隔（只查"快满/已满"的服）
        self._slots_rev = 0
        self._slots_stop = threading.Event()
        self._slots_thread: threading.Thread | None = None
        self._game_cache: tuple[float, dict] | None = None
        self._queue: queue.QueueWatcher | None = None
        self.queue_interval = 3.0
        self._rev = 0                      # 任何会影响 snapshot 的变化都 +1
        self._vip: dict[str, Any] | None = None
        self._vip_at = 0.0
        self._vip_expire = ""              # 本地登记的到期日（YYYY-MM-DD）
        self.vip_api = (vip_api or "").strip()   # 身份接口；空 = 由 rounds_url 推导
        self._steamid: tuple[float, str, str] | None = None
        self._vip_stop = threading.Event()
        self._vip_thread: threading.Thread | None = None
        self._game_thread: threading.Thread | None = None
        self._game_stop = threading.Event()

        self._lock = threading.RLock()
        self._entries: "OrderedDict[str, Entry]" = OrderedDict()
        self._inflight: set[str] = set()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="probe")
        self._auto_thread: threading.Thread | None = None
        self._stop = threading.Event()

        self._load()

    # ------------------------------------------------------------ 持久化

    def _load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            data = json.loads(self.store_path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.interval = float(data.get("interval") or self.interval)
            self.auto = bool(data.get("auto", True))
            self.gmod_path = str(data.get("gmod_path") or self.gmod_path)
            cfg = data.get("rounds") or {}
            if isinstance(cfg, dict):
                if cfg.get("url"):
                    self.rounds_url = str(cfg["url"])
                if cfg.get("interval"):
                    self.rounds_interval = max(3.0, float(cfg["interval"]))
                if "enabled" in cfg:
                    self.rounds_enabled = bool(cfg["enabled"]) and bool(self.rounds_url)
            self._rounds_meta.update({
                "url": self.rounds_url, "enabled": self.rounds_enabled,
                "interval": self.rounds_interval,
            })
            items = data.get("servers") or []
        else:
            items = data if isinstance(data, list) else []

        for item in items:
            addr = item.get("address") if isinstance(item, dict) else str(item)
            label = item.get("label", "") if isinstance(item, dict) else ""
            if not addr:
                continue
            try:
                parsed = a2s.parse_address(addr)
            except ValueError:
                continue
            if parsed.key not in self._entries:
                self._entries[parsed.key] = Entry(str(parsed), label)

    def save(self) -> None:
        with self._lock:
            payload = {
                "interval": self.interval,
                "auto": self.auto,
                "gmod_path": self.gmod_path,
                "rounds": {
                    "url": self.rounds_url,
                    "interval": self.rounds_interval,
                    "enabled": self.rounds_enabled,
                },
                "queue": {"interval": self.queue_interval},
                "vip": {"expire": self._vip_expire, "api": self.vip_api},
                "servers": [{"address": e.address, "label": e.label}
                            for e in self._entries.values()],
            }
        tmp = self.store_path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
            os.replace(tmp, self.store_path)
        except OSError:
            pass

    # ------------------------------------------------------------ 增删

    def add(self, raw: str, label: str = "") -> str:
        addr = a2s.parse_address(raw)  # 抛 ValueError 交给上层
        key = addr.key
        with self._lock:
            if key in self._entries:
                return key
            self._entries[key] = Entry(str(addr), label)
            self._rev += 1
        self.save()
        self.refresh([key])
        return key

    def add_many(self, raws: list[Any]) -> dict[str, Any]:
        """批量添加。元素可以是 "ip:port" 字符串，也可以是 {"address","label"}。"""
        added, skipped, failed = 0, 0, []
        for raw in raws:
            label = ""
            if isinstance(raw, dict):
                label = str(raw.get("label") or "").strip()
                raw = raw.get("address")
            raw = (str(raw) if raw is not None else "").strip()
            if not raw:
                continue
            try:
                addr = a2s.parse_address(raw)
            except ValueError as exc:
                failed.append({"input": raw, "error": str(exc)})
                continue
            with self._lock:
                if addr.key in self._entries:
                    skipped += 1
                    if label and not self._entries[addr.key].label:
                        self._entries[addr.key].label = label
                    continue
                self._entries[addr.key] = Entry(str(addr), label)
                added += 1
        if added:
            with self._lock:
                self._rev += 1
        if added or skipped:
            self.save()
        if added:
            self.refresh()
        return {"added": added, "skipped": skipped, "failed": failed}

    def remove(self, raw: str) -> bool:
        try:
            key = a2s.parse_address(raw).key
        except ValueError:
            return False
        with self._lock:
            existed = self._entries.pop(key, None) is not None
            if existed:
                self._rev += 1
        if existed:
            self.save()
        return existed

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
        self.save()

    # ------------------------------------------------------------ 查询

    def refresh(self, keys: list[str] | None = None, force: bool = True) -> int:
        with self._lock:
            targets = [k for k in (keys or list(self._entries)) if k in self._entries]
            todo = []
            for key in targets:
                if key in self._inflight:
                    continue
                entry = self._entries[key]
                if not force and entry.checked_at and (time.time() - entry.checked_at) < self.interval:
                    continue
                self._inflight.add(key)
                entry.state = "querying"
                todo.append(entry)
        for entry in todo:
            self._pool.submit(self._run, entry)
        return len(todo)

    def _run(self, entry: Entry) -> None:
        try:
            addr = a2s.parse_address(entry.address)
            info = self._query_with_retry(addr)
            with self._lock:
                self._rev += 1
                # 换图观测：map 变了说明这一局翻篇（原版没有任何这类信号，是我们额外测的）
                new_map = (info or {}).get("map") or ""
                if new_map and new_map != entry.map_now:
                    if entry.map_now:
                        entry.map_changes.append(time.time())
                        del entry.map_changes[:-20]
                    entry.map_now = new_map
                    entry.map_since = time.time()
                entry.info = info
                entry.rtt_ms = info.get("rtt_ms")
                entry.state = "ok"
                entry.error = None
                entry.checked_at = time.time()
                entry.history.append([round(entry.checked_at, 1),
                                      info.get("players", 0),
                                      entry.rtt_ms or 0])
                del entry.history[:-60]
        except (a2s.A2SError, ValueError, OSError) as exc:
            with self._lock:
                self._rev += 1
                entry.state = "error"
                entry.error = str(exc)
                entry.info = None
                entry.rtt_ms = None
                entry.checked_at = time.time()
        finally:
            with self._lock:
                self._inflight.discard(a2s.parse_address(entry.address).key
                                       if _is_valid(entry.address) else entry.address)

    def _query_with_retry(self, addr: a2s.ServerAddress) -> dict:
        """满载服务器会丢 A2S 包（实测约 20% 单次超时），短重试比长超时更有效。"""
        last: Exception | None = None
        for attempt in range(max(1, self.retries)):
            try:
                return a2s.query_info(addr, self.timeout, self.samples)
            except a2s.A2SProtocolError:
                raise                      # 协议错误重试也没用
            except (a2s.A2SError, OSError) as exc:
                last = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.25)
        raise last or a2s.A2SError("无有效响应")

    def detail(self, raw: str, players: bool = True, rules: bool = False) -> dict:
        """按需查询详情（不进缓存，直接返回）。"""
        addr = a2s.parse_address(raw)
        return a2s.query_all(addr, timeout=max(self.timeout, 2.0), samples=1,
                             with_players=players, with_rules=rules)

    # ------------------------------------------------------------ 自动刷新

    def start_auto(self) -> None:
        if self._auto_thread and self._auto_thread.is_alive():
            return
        self._stop.clear()
        self._auto_thread = threading.Thread(target=self._auto_loop, name="probe-auto", daemon=True)
        self._auto_thread.start()

    def _auto_loop(self) -> None:
        while not self._stop.wait(max(2.0, self.interval)):
            if not self.auto:
                continue
            try:
                self.refresh(force=False)
            except Exception:  # 永不因单轮异常中断
                pass

    def stop(self) -> None:
        self._stop.set()
        self._rounds_stop.set()
        self._slots_stop.set()
        self._game_stop.set()
        self._vip_stop.set()
        with self._lock:
            if self._queue:
                self._queue.stop("程序退出")
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------ 空位观测（挤服用）

    def start_slots(self) -> None:
        if self._slots_thread and self._slots_thread.is_alive():
            return
        self._slots_stop.clear()
        self._slots_thread = threading.Thread(target=self._slots_loop,
                                              name="slots", daemon=True)
        self._slots_thread.start()

    def _slots_loop(self) -> None:
        # 首轮稍等，让 info 查询先落地（要知道人数才知道该不该查名单）
        self._slots_stop.wait(3.0)
        while not self._slots_stop.is_set():
            try:
                self._slots_tick()
            except Exception:
                pass
            self._slots_stop.wait(self._slots_interval)

    def _slots_tick(self) -> None:
        """只对"快满/已满"的服拉玩家名单——挤服只关心这些，也避免无谓开销。"""
        targets: list[Entry] = []
        with self._lock:
            for entry in self._entries.values():
                if not _is_valid(entry.address) or not entry.info:
                    continue
                players = entry.info.get("players") or 0
                cap = entry.info.get("max_players") or 0
                near_full = cap and players >= max(1, int(cap * 0.85))
                queued = bool(self._queue and self._queue.active
                              and self._queue.address == entry.address)
                if near_full or queued:
                    targets.append(entry)
        for entry in targets:
            if self._slots_stop.is_set():
                return
            self._pool.submit(self._slots_probe, entry)

    def _slots_probe(self, entry: Entry) -> None:
        try:
            addr = a2s.parse_address(entry.address)
            players = a2s.query_players(addr, max(self.timeout, 2.0))
            names = [p.get("name") or "" for p in players]
            info_players = (entry.info or {}).get("players") or len(names)
        except (a2s.A2SError, ValueError, OSError) as exc:
            with self._lock:
                tr = self._slots.get(a2s.parse_address(entry.address).key)
                if tr:
                    tr.fail(str(exc))
                self._slots_rev += 1
            return
        with self._lock:
            key = addr.key
            tr = self._slots.get(key)
            if tr is None:
                tr = slots.SlotTracker(key, str(addr))
                self._slots[key] = tr
            tr.feed(time.time(), names, info_players)
            self._slots_rev += 1

    # ------------------------------------------------------------ 回合状态

    def start_rounds(self) -> None:
        if not self.rounds_enabled:
            return
        if self._rounds_thread and self._rounds_thread.is_alive():
            return
        self._rounds_stop.clear()
        self._rounds_thread = threading.Thread(target=self._rounds_loop,
                                               name="rounds", daemon=True)
        self._rounds_thread.start()

    def _rounds_loop(self) -> None:
        # 立刻拉一次，之后按间隔；命中限流时按 retry_after 退避
        backoff = 0.0
        while not self._rounds_stop.is_set():
            if not self.rounds_enabled:
                self._rounds_stop.wait(2.0)
                continue
            try:
                res = rounds.fetch(self.rounds_url, timeout=4.0)
            except Exception as exc:  # 绝不因单次异常中断
                res = rounds.FetchResult(error=str(exc), fetched_at=time.time())

            with self._lock:
                if res.ok:
                    self._rounds = dict(res.statuses)
                    self._rounds_meta.update({
                        "ok": True, "error": None, "fetched_at": res.fetched_at,
                        "count": res.count, "retry_after": 0.0,
                    })
                    backoff = 0.0
                else:
                    self._rounds_meta.update({
                        "ok": False, "error": res.error, "fetched_at": res.fetched_at,
                        "retry_after": res.retry_after,
                    })
                    backoff = min(60.0, max(res.retry_after, 2.0 if not backoff else backoff * 2))

            # 服务器列表在线更新（新版启动器同款 server_catalog.php），10 分钟一次
            if time.time() - self._catalog_at > 600:
                self._catalog_at = time.time()
                try:
                    self._sync_catalog()
                except Exception:
                    pass

            wait = max(backoff, self.rounds_interval) if backoff else self.rounds_interval
            self._rounds_stop.wait(wait)

    def _sync_catalog(self) -> None:
        """把服务器目录里的服并进列表：只增不减，不改用户手动加的那些。"""
        if not self.catalog_url:
            return
        servers, err = rounds.fetch_catalog(self.catalog_url, timeout=max(self.timeout, 3.0))
        added = 0
        for item in servers:
            if item.get("visible_to"):
                # 限定可见的服需要知道本机 SteamID，拿不到就跳过（不乱加）
                continue
            try:
                key = a2s.parse_address(item["address"]).key
            except ValueError:
                continue
            with self._lock:
                exists = key in self._entries
            if exists:
                continue
            try:
                self.add(item["address"], item.get("name") or "")
                added += 1
            except (ValueError, OSError):
                continue
        with self._lock:
            self._catalog_meta.update({
                "ok": err is None, "error": err, "count": len(servers),
                "added": added, "fetched_at": time.time(), "url": self.catalog_url,
            })
            if added:
                self._rev += 1

    def rounds_for(self, address: str) -> dict | None:
        try:
            key = a2s.parse_address(address).key
        except ValueError:
            return None
        with self._lock:
            status = self._rounds.get(key)
            return status.to_dict() if status else None

    # ------------------------------------------------------------ 启动游戏

    def game_info(self, ttl: float = 2.0) -> dict:
        """只读缓存：刷新交给后台线程（全量进程枚举约 7 ms，不该压在 HTTP 请求上）。"""
        if self._game_cache and ttl > 0:
            return self._game_cache[1]
        now = time.time()
        try:
            info = launch.game_status(self.gmod_path)
        except Exception as exc:
            info = {"gmod_path": "", "found": False, "running": False,
                    "steam_running": False, "steam_exe": "", "libraries": [],
                    "error": str(exc)}
        self._game_cache = (now, info)
        return info

    def start_game_watch(self, interval: float = 2.0) -> None:
        if self._game_thread and self._game_thread.is_alive():
            return
        self._game_stop.clear()

        def loop() -> None:
            while not self._game_stop.wait(max(1.0, interval)):
                try:
                    self.game_info(ttl=0)
                except Exception:
                    pass

        self._game_thread = threading.Thread(target=loop, name="game-watch", daemon=True)
        self._game_thread.start()

    def launch_game(self, address: str | None = None, dry_run: bool = False) -> dict:
        result = launch.launch(address=address, configured_gmod=self.gmod_path,
                               dry_run=dry_run)
        launch.invalidate_process_cache()
        self.game_info(ttl=0)          # 立刻反映"已启动"，别等后台线程下一轮
        self._game_cache = None  # 状态变了，下次重新探测
        return result

    # ------------------------------------------------------------ 身份 / VIP

    def _steam_account(self, ttl: float = 60.0) -> tuple[str, str]:
        """本机 SteamID64，缓存 60 秒（要读 loginusers.vdf / 注册表）。"""
        now = time.time()
        if self._steamid and now - self._steamid[0] < ttl:
            return self._steamid[1], self._steamid[2]
        sid, source = vip.local_steamid64()
        self._steamid = (now, sid, source)
        return sid, source

    def vip_info(self, force: bool = False, ttl: float = 300.0) -> dict[str, Any]:
        """查一次身份（是不是 VIP、到期时间）。

        identity.php 有 1 次/秒的限流（超了直接 429），所以：成功结果缓存 5 分钟，
        失败结果只缓存 20 秒；force 也至少间隔 2 秒，避免连点刷新把自己限流住。
        """
        now = time.time()
        fresh_for = ttl if (self._vip and self._vip.get("ok")) else min(ttl, 20.0)
        if force and self._vip and now - self._vip_at < 2.0:
            return self._apply_manual_expiry(dict(self._vip))
        if not force and self._vip and now - self._vip_at < fresh_for:
            return self._apply_manual_expiry(dict(self._vip))

        sid, source = self._steam_account()
        if not sid:
            data = {"ok": False, "steamid64": "", "identity": "", "is_vip": None,
                    "is_admin": None, "expire_at": None, "expire_source": "",
                    "days_left": None, "source": "", "account_source": source,
                    "fetched_at": now, "error": "没有找到 Steam 账号（未登录 / 装在别处）"}
            self._vip, self._vip_at = data, now
            return self._apply_manual_expiry(dict(data))

        data = vip.fetch(self.vip_api or self.rounds_url, sid)
        data["account_source"] = source
        self._vip, self._vip_at = data, now
        self._rev += 1
        return self._apply_manual_expiry(dict(data))

    def _apply_manual_expiry(self, data: dict[str, Any]) -> dict[str, Any]:
        """服务端没给到期时间时，用本地登记的日期补上（并标明来源）。"""
        if not data.get("expire_at") and self._vip_expire:
            ts = vip._as_timestamp(self._vip_expire)
            if ts:
                data["expire_at"] = ts
                data["expire_source"] = "本地记录（手动填写）"
                data["source"] = "manual"
        data["days_left"] = vip.days_left(data.get("expire_at"))
        data["manual_expire"] = self._vip_expire
        data["api_url"] = self.vip_api or vip.identity_url(self.rounds_url)
        data["checked_at"] = data.get("fetched_at") or self._vip_at
        return data

    def set_vip_expire(self, date_text: str) -> dict[str, Any]:
        """登记/清除本地到期日（空字符串 = 清除）。"""
        text = (date_text or "").strip()
        if text and not vip._as_timestamp(text):
            raise ValueError("日期格式看不懂，用 2026-12-01 这种写法")
        self._vip_expire = text
        self._vip_at = 0.0                 # 让下次读取重新套用
        self._rev += 1
        self.save()
        return self.vip_info(force=False, ttl=0)

    def vip_snapshot(self) -> dict[str, Any] | None:
        if not self._vip:
            return None
        data = self._apply_manual_expiry(dict(self._vip))
        data.pop("raw", None)              # 原始响应不往每 15 秒的快照里塞
        return data

    def start_vip_watch(self, interval: float = 600.0) -> None:
        if self._vip_thread and self._vip_thread.is_alive():
            return
        self._vip_stop.clear()

        def loop() -> None:
            try:
                self.vip_info(force=True)
            except Exception:
                pass
            while not self._vip_stop.wait(max(60.0, interval)):
                try:
                    self.vip_info(force=True)
                except Exception:
                    pass

        self._vip_thread = threading.Thread(target=loop, name="vip-watch", daemon=True)
        self._vip_thread.start()

    # ------------------------------------------------------------ 版本号

    def _bump(self) -> None:
        with self._lock:
            self._rev += 1

    def stamp(self) -> tuple:
        """(数据版本, 排队版本, 客户端探针版本)。

        客户端探针的文件每 2 秒变一次，必须计入版本号——否则 /api/state 会一直
        复用旧字节，探针数据永远不刷新（实测踩过：提示里的数字冻住不动）。
        """
        with self._lock:
            q = self._queue.revision if self._queue else 0
            return self._rev, q, clientstate.version(), self._slots_rev

    # ------------------------------------------------------------ 自动挤服

    def start_queue(self, raw: str, label: str = "", interval: float | None = None,
                    dry_run: bool = False) -> dict[str, Any]:
        """对一台满员服务器开启自动挤服；已有排队进行中时拒绝。"""
        addr = a2s.parse_address(raw)      # 非法地址抛 ValueError 交给上层
        with self._lock:
            if self._queue and self._queue.active:
                if self._queue.key == addr.key:
                    return {"ok": True, "reused": True, "queue": self._queue.snapshot()}
                return {"ok": False, "error": "已有排队进行中，先取消再换服",
                        "queue": self._queue.snapshot()}

            # 先看一眼现在到底满没满：有空位就别排队，直接进
            info = self._probe_now(addr)
            if info and info.get("max_players") and \
                    info.get("players", 0) < info["max_players"]:
                result = launch.launch(str(addr), self.gmod_path, dry_run=dry_run)
                return {"ok": bool(result.get("ok")), "launched": True,
                        "message": result.get("message") or result.get("error"),
                        "error": result.get("error"), "result": result,
                        "queue": None, "info": info}

            watcher = queue.QueueWatcher(
                str(addr), label=label or self._label_of(addr.key),
                interval=interval or self.queue_interval,
                timeout=self.timeout, retries=self.retries,
                gmod_path=self.gmod_path, dry_run=dry_run,
            )
            if info:
                watcher._record(info)      # 把刚查到的数字直接摆上去，避免空一帧
            self._queue = watcher
            self._rev += 1
            watcher.start()
            return {"ok": True, "launched": False, "queue": watcher.snapshot()}

    def stop_queue(self, reason: str = "已取消排队") -> dict[str, Any]:
        with self._lock:
            watcher = self._queue
            if watcher and not watcher.active:
                # 已经结束（进服成功/已取消/失败）时再点一次 = 关掉横幅，直接忘掉
                self._queue = None
                self._rev += 1
                return {"ok": True, "queue": None}
        if watcher:
            watcher.stop(reason)
            return {"ok": True, "queue": watcher.snapshot()}
        return {"ok": True, "queue": None}

    def queue_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return self._queue.snapshot() if self._queue else None

    def _label_of(self, key: str) -> str:
        with self._lock:
            entry = self._entries.get(key)
            return entry.label if entry else ""

    def _probe_now(self, addr: a2s.ServerAddress) -> dict | None:
        try:
            return a2s.query_info(addr, self.timeout, 1)
        except (a2s.A2SError, OSError):
            return None

    # ------------------------------------------------------------ 快照

    def set_config(self, interval: float | None = None, auto: bool | None = None,
                   rounds_interval: float | None = None,
                   rounds_enabled: bool | None = None,
                   rounds_url: str | None = None,
                   gmod_path: str | None = None,
                   vip_api: str | None = None) -> None:
        restart_rounds = False
        with self._lock:
            if interval and interval >= 2:
                self.interval = float(interval)
            if auto is not None:
                self.auto = bool(auto)
            if rounds_interval and rounds_interval >= 3:
                self.rounds_interval = float(rounds_interval)
                self._rounds_meta["interval"] = self.rounds_interval
            if rounds_url is not None:
                self.rounds_url = rounds_url.strip()
                self._rounds_meta["url"] = self.rounds_url
                restart_rounds = True
            if rounds_enabled is not None:
                want = bool(rounds_enabled) and bool(self.rounds_url)
                if want != self.rounds_enabled:
                    self.rounds_enabled = want
                    self._rounds_meta["enabled"] = want
                    restart_rounds = want
            if gmod_path is not None:
                self.gmod_path = gmod_path.strip()
                self._game_cache = None
            if vip_api is not None:
                self.vip_api = vip_api.strip()
                self._vip_at = 0.0           # 换接口后立刻重查
                self._rev += 1
        with self._lock:
            self._rev += 1
        self.save()
        if restart_rounds:
            if self.rounds_enabled:
                self.start_rounds()
            else:
                self._rounds_stop.set()

    def snapshot(self) -> dict[str, Any]:
        # 客户端探针：只有你正在玩的那台服才会有数据，其余保持 None，不做任何推断
        client = clientstate.read()
        with self._lock:
            servers = []
            for entry in self._entries.values():
                item = entry.to_dict()
                status = self._rounds.get(a2s.parse_address(entry.address).key) \
                    if _is_valid(entry.address) else None
                item["rounds"] = status.to_dict() if status else None
                item["client"] = clientstate.for_server(entry.address, data=client)
                tr = self._slots.get(a2s.parse_address(entry.address).key) \
                    if _is_valid(entry.address) else None
                item["slots"] = tr.to_dict() if tr else None
                servers.append(item)
            return {
                "ts": time.time(),
                "interval": self.interval,
                "auto": self.auto,
                "count": len(servers),
                "online": sum(1 for s in servers if s["state"] == "ok"),
                "servers": servers,
                "rounds_meta": dict(self._rounds_meta),
                "client_meta": clientstate.meta(),
                "catalog_meta": dict(self._catalog_meta),
                "game": self.game_info(),
                "queue": self.queue_snapshot(),
                "vip": self.vip_snapshot(),
            }


def _is_valid(raw: str) -> bool:
    try:
        a2s.parse_address(raw)
        return True
    except ValueError:
        return False
