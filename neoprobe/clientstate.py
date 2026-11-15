"""读取本机 GMod 客户端回合探针的输出。

数据来源：garrysmod/lua/autorun/client/neoprobe_rounds.lua 每 2 秒写一次的
garrysmod/data/neoprobe_rounds.json。里面的字段名不做假设——由客户端把看到的
所有可能字段原样吐出来，这里按打分挑一个最像"本回合剩余秒数"的。

为什么要这么绕：GMod 的 A2S 查询里**没有任何回合状态**（已实测：445 条规则全静态、
分数整图累计不随回合归零、地图不变），社区 status.php 只收录 3 台测试服 + 兑换服，
6 台 mio 正式服完全不上报。客户端是唯一一定知道回合状态的地方，因为 HUD 倒计时必须靠网络同步。

重要限制（2026-11-15 核实）：这 10 台服的 A2S_RULES 都是 sv_allowcslua 0。
在这种服上，GMod 客户端只执行服务器下发的 Lua，本地 lua/autorun/client/ 里的文件不会被加载，
所以这个探针在这些服上**拿不到数据**——面板会如实显示"未上报"。不要尝试绕过
（那就是外挂行为，原启动器还带反作弊上报）。探针只对 sv_allowcslua 1 的服有用。
"""

from __future__ import annotations

import json
import os
import re
import time

from . import launch

_CACHE: dict = {"mtime": 0.0, "data": None, "path": ""}

# 常见命名 → 含义权重
_END_WORDS = ("endtime", "end_time", "finish", "endat", "expire", "stop")
_LEFT_WORDS = ("timeleft", "time_left", "remaining", "remain", "countdown", "left", "timer")
_ROUND_WORDS = ("round", "phase", "wave", "stage")
_PHASE_RE = re.compile(r"回合|准备|结束|等待|空闲|round|prep|post|idle|wait|interval|intermission", re.I)
_NOT_PHASE_RE = re.compile(r"name|nick|model|class|map|mode$", re.I)
_STATE_KEY_RE = re.compile(r"state|phase|status|stage", re.I)


_PATH: dict = {"at": 0.0, "path": ""}


def _data_dir(ttl: float = 30.0) -> str:
    """探针文件的绝对路径。find_gmod() 要扫注册表/库目录，这里再缓一层。"""
    now = time.time()
    if _PATH["path"] and now - _PATH["at"] < ttl:
        return _PATH["path"]
    exe = launch.find_gmod()
    path = ""
    if exe:
        # <root>/garrysmod/data/neoprobe_rounds.json
        path = os.path.join(os.path.dirname(exe), "garrysmod", "data", "neoprobe_rounds.json")
    _PATH.update(at=now, path=path)
    return path


def version() -> tuple:
    """给 /api/state 的缓存做版本判断用：文件一变就必须重新序列化。"""
    path = _data_dir()
    if not path:
        return (0, 0)
    try:
        st = os.stat(path)
        return (round(st.st_mtime, 3), st.st_size)
    except OSError:
        return (0, 0)


def read(max_age: float = 30.0) -> dict | None:
    """返回探针数据；文件不存在/过期/坏掉都返回 None（不编造）。"""
    path = _data_dir()
    if not path or not os.path.isfile(path):
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if time.time() - mtime > max_age:
        return None
    if _CACHE["path"] == path and _CACHE["mtime"] == mtime and _CACHE["data"] is not None:
        return _CACHE["data"]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    _CACHE.update(path=path, mtime=mtime, data=data)
    return data


def _score_key(key: str) -> int:
    k = (key or "").lower()
    score = 0
    if any(w in k for w in _END_WORDS):
        score += 3
    if any(w in k for w in _LEFT_WORDS):
        score += 3
    if any(w in k for w in _ROUND_WORDS):
        score += 2
    if "start" in k:
        score -= 2          # 开始时间不是剩余时间
    if "total" in k or "max" in k or "limit" in k or "len" in k:
        score -= 3          # 配置上限，不是当前进度
    return score


def pick(data: dict) -> dict | None:
    """从候选里挑出一个看来是"本回合剩余秒数"的字段。

    返回 None 表示没有可信字段——此时面板必须显示"客户端未提供"，不许猜。
    """
    cands = data.get("cands") or []
    curtime = data.get("curtime") or 0.0
    best = None

    for c in cands:
        if c.get("t") != "number":
            continue
        # cvar 是服务端配置（br_time_round=1080 表示"每局最多 18 分钟"），
        # 不是当前进度。拿它当倒计时就会变成"每台服永远剩 18:00"——正是要避免的假数据。
        if c.get("src") == "cvar":
            continue
        try:
            val = float(c.get("v"))
        except (TypeError, ValueError):
            continue
        key = str(c.get("k") or "")
        score = _score_key(key)
        if score <= 0:
            continue

        # 绝对结束时刻（游戏内 CurTime 基准）或剩余秒数
        left = None
        kind = ""
        if curtime and val > curtime and 0 <= val - curtime <= 7200:
            left, kind = val - curtime, "endtime"
            score += 1
        elif 0 <= val <= 7200:
            left, kind = val, "remaining"

        if left is None:
            continue
        # 越接近"一整局"的量级越可信（1 秒/1 毫秒的东西不要）
        if 0 < left < 3:
            score -= 1
        if best is None or score > best["score"]:
            best = {"score": score, "left": int(round(left)), "key": key,
                    "src": c.get("src") or "", "kind": kind, "raw": val}

    phase = None
    for c in cands:
        if c.get("t") != "string":
            continue
        key, val = str(c.get("k") or ""), str(c.get("v") or "")
        if _NOT_PHASE_RE.search(key) or not val:
            continue
        # 值里带"回合/准备/round"等字样最可靠；若键名本身就是 state/phase/stage
        # 且值是短文本，也收下（自定义 gamemode 常用英文枚举，如 "Preparing"）
        looks_like_state = (
            _STATE_KEY_RE.search(key) and len(val) <= 16 and not val.replace(".", "").isdigit()
            and not val.lstrip("-").isdigit()
        )
        if _PHASE_RE.search(val) or looks_like_state:
            phase = {"key": key, "value": val}
            break

    if best is None and phase is None:
        return None

    out = {"ts": data.get("ts") or int(time.time()),
           "curtime": curtime,
           "phase": phase["value"] if phase else None,
           "phase_key": phase["key"] if phase else None,
           "left": best["left"] if best else None,
           "key": best["key"] if best else None,
           "src": best["src"] if best else None,
           "kind": best["kind"] if best else None,
           "cands": len(cands)}
    return out


def for_server(address: str, data: dict | None = None) -> dict | None:
    """若探针当前连的正是这台服，返回挑好的回合数据。"""
    data = read() if data is None else data
    if not data or not data.get("playing"):
        return None
    if not _same_addr(data.get("addr") or "", address):
        return None
    picked = pick(data)
    if not picked:
        return None
    picked["addr"] = data.get("addr")
    return picked


def meta() -> dict:
    data = read()
    if not data:
        return {"ok": False, "reason": "没有探针数据（游戏未启动或未装探针）"}
    return {
        "ok": bool(data.get("playing")),
        "addr": data.get("addr") or "",
        "map": data.get("map") or "",
        "mode": data.get("mode") or "",
        "ts": data.get("ts"),
        "cands": len(data.get("cands") or []),
        "age": max(0, int(time.time() - os.path.getmtime(_data_dir()))) if _data_dir() else None,
    }


def _same_addr(a: str, b: str) -> bool:
    def norm(x: str) -> str:
        x = (x or "").strip().lower()
        if x.startswith("steam://connect/"):
            x = x[len("steam://connect/"):]
        return x
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # 允许缺端口时按 IP 前缀匹配
    return a.split(":")[0] == b.split(":")[0] and (":" not in a or ":" not in b)
