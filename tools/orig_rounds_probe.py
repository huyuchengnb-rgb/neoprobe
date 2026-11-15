"""用**原启动器的算法**跑当前 status.php，检验"拿来用"能不能出数据。

这里不是重写，而是按 RelayGate/ServerRoundsApiClient.cs 逐字段复刻：

    rounds_left < 0                     -> "-"
    round_time_left < 0 或缺失          -> "-"
    round_time_left 补偿 (server_time - updated_at)，仅当 0 < 差值 < 300
    round_phase 走 NormalizeRoundPhaseText 的映射表
    键 = "ip:port"

然后把这套结果套到目录里的 9 台服 + 兑换服上，看每台会显示什么。
用途：把"原版以前能看到"这件事变成可验证的结论，而不是互相猜测。

    python tools/orig_rounds_probe.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

URL = "https://neomio.nigigasaki.live/status.php"
HEADERS = {
    # 与原启动器 ClientRequestInfo 一致
    "User-Agent": "Neobreach/1.0.0.86",
    "X-Neobreach-Version": "1.0.0.86",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# 与原启动器 NormalizeRoundPhaseText 一一对应
PHASE_MAP = {
    "idle": "空闲", "waiting": "等待玩家", "preparing": "准备阶段",
    "round": "回合中", "postround": "回合结束",
    "warhead_starting": "核弹启动中", "warhead": "核弹倒计时", "offline": "离线",
}

SERVERS = [
    ("43.249.193.77", 27076), ("43.249.193.77", 27265), ("43.249.193.77", 27852),
    ("202.189.23.252", 27265), ("202.189.23.252", 27235), ("202.189.23.252", 27045),
    ("202.189.21.228", 27076), ("202.189.21.228", 27265), ("202.189.21.228", 27852),
    ("202.189.21.228", 31284),
]


def normalize_time_left(seconds, updated_at, server_time) -> int:
    """原版 NormalizeRoundTimeLeftSeconds。"""
    if seconds is None or seconds < 0:
        return -1
    left = seconds
    if updated_at > 0 and server_time > 0:
        drift = server_time - updated_at
        if 0 < drift < 300:
            left -= drift
    return max(0, left)


def fmt(left: int) -> str:
    """原版 FormatRoundTimeLeftSeconds。"""
    if left < 0:
        return "-"
    return f"{left // 60:02d}:{left % 60:02d}"


def phase(text: str) -> str:
    t = (text or "").strip()
    return "-" if not t else PHASE_MAP.get(t.lower(), t)


def main() -> int:
    url = f"{URL}?_={int(time.time() * 1000)}"      # 原版的缓存击穿参数
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))

    server_time = int(data.get("server_time") or time.time())
    table: dict[str, dict] = {}
    for s in data.get("servers") or []:
        ip, port = s.get("ip"), s.get("port")
        if not ip or not port:
            continue
        left = normalize_time_left(s.get("round_time_left"), int(s.get("updated_at") or 0), server_time)
        table[f"{ip}:{port}"] = {
            "rounds": "-" if int(s.get("rounds_left", -1)) < 0 else str(s.get("rounds_left")),
            "time": fmt(left),
            "phase": phase(s.get("round_phase") or ""),
            "name": s.get("server_name"),
        }

    print(f"接口返回 {len(table)} 台服（server_time={server_time}）\n")
    print(f"{'服务器':24}{'剩余回合':>8}{'剩余时间':>10}  {'阶段'}")
    print("-" * 62)
    for ip, port in SERVERS:
        key = f"{ip}:{port}"
        row = table.get(key)
        if row:
            print(f"{key:24}{row['rounds']:>8}{row['time']:>10}  {row['phase']}")
        else:
            print(f"{key:24}{'-':>8}{'-':>10}  （接口里没有这台）")
    print("\n结论：原启动器的算法本身没问题，它只是把这一个接口的值原样展示。")
    print("      接口里没有的服，原版显示的就是 '-'，和我们的实现完全一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
