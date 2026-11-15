"""回合边界观测器。

目的：GMod（TTT / Breach）的 A2S 协议不提供回合状态，只能从可观测信号里找边界。
本脚本按固定间隔采样玩家列表与分数，落盘 JSONL，用于**验证**下面这些信号是否真的成立：

  1) 分数归零潮 —— 若每回合重置，所有玩家的 score 会在某一时刻同时回到 0
  2) 地图变化   —— 若换图即换回合
  3) 人数锯齿   —— 回合结束/开始时人数是否规律性塌陷

只有观测到确实存在的信号，才会把它写进面板；观测不到就不写。

用法：
    python tools/roundwatch.py --out .roundwatch.jsonl --interval 10 --minutes 25 \
        43.249.193.77:27076 202.189.23.252:27265 202.189.21.228:31284
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neoprobe import a2s  # noqa: E402


def sample(address: str) -> dict:
    addr = a2s.parse_address(address)
    row: dict = {"t": round(time.time(), 1), "addr": address}
    try:
        with a2s._Session(addr, 3.0) as sess:  # noqa: SLF001  复用 challenge，省一次往返
            info = a2s.query_info(addr, 3.0, 1, sess)
            row["players"] = info.get("players")
            row["max"] = info.get("max_players")
            row["map"] = info.get("map")
            try:
                pl = a2s.query_players(addr, 3.0, sess)
                row["pl"] = [[p.get("name"), p.get("score"), p.get("duration")] for p in pl]
            except a2s.A2SError as exc:
                row["pl_err"] = str(exc)
    except (a2s.A2SError, OSError, ValueError) as exc:
        row["err"] = str(exc)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("servers", nargs="+")
    ap.add_argument("--out", default=".roundwatch.jsonl")
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--minutes", type=float, default=25.0)
    args = ap.parse_args()

    out = Path(args.out)
    deadline = time.time() + args.minutes * 60
    n = 0
    with out.open("a", encoding="utf-8") as fh:
        while time.time() < deadline:
            tick = time.time()
            for s in args.servers:
                row = sample(s)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
            fh.flush()
            print(f"[{time.strftime('%H:%M:%S')}] 采样 {n} 行", flush=True)
            time.sleep(max(1.0, args.interval - (time.time() - tick)))
    print(f"完成，共 {n} 行 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
