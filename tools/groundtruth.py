"""Ground-truth recorder: status.php (real round state for the test servers) + A2S for every server.

Purpose: the test servers on 202.189.21.228 report real round state to status.php,
and they run the same gamemode/config as the mio servers. So we can check which A2S
signals (score reset / player-count dips / duration) line up with real round boundaries,
then apply the validated ones to the mio servers that don't report.

    py tools/groundtruth.py --minutes 30 --interval 5 --out .groundtruth.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neoprobe import a2s, rounds  # noqa: E402

SERVERS = [
    "43.249.193.77:27076", "43.249.193.77:27265", "43.249.193.77:27852",
    "202.189.23.252:27045", "202.189.23.252:27235", "202.189.23.252:27265",
    "202.189.21.228:27076", "202.189.21.228:27265", "202.189.21.228:27852",
]


def sample(address: str) -> dict:
    addr = a2s.parse_address(address)
    row: dict = {"t": round(time.time(), 2), "addr": address}
    try:
        with a2s._Session(addr, 3.0) as sess:  # noqa: SLF001
            info = a2s.query_info(addr, 3.0, 1, sess)
            row["n"] = info.get("players")
            row["map"] = info.get("map")
            try:
                pl = a2s.query_players(addr, 3.0, sess)
                row["pl"] = [[p.get("name"), p.get("score"), round(p.get("duration") or 0, 1)] for p in pl]
            except a2s.A2SError as exc:
                row["pl_err"] = str(exc)
    except (a2s.A2SError, OSError, ValueError) as exc:
        row["err"] = str(exc)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".groundtruth.jsonl")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--minutes", type=float, default=30.0)
    args = ap.parse_args()

    deadline = time.time() + args.minutes * 60
    with Path(args.out).open("a", encoding="utf-8") as fh, ThreadPoolExecutor(10) as pool:
        while time.time() < deadline:
            tick = time.time()
            fut_rounds = pool.submit(rounds.fetch, rounds.DEFAULT_ROUNDS_API, 4.0)
            rows = list(pool.map(sample, SERVERS))
            res = fut_rounds.result()
            truth = {k: {"phase": s.phase, "rl": s.rounds_left, "tl": s.time_left, "upd": s.updated_at}
                     for k, s in res.statuses.items()} if res.ok else {"_err": res.error}
            fh.write(json.dumps({"t": round(tick, 2), "truth": truth, "a2s": rows}, ensure_ascii=False) + "\n")
            fh.flush()
            brief = " ".join(f"{k.split(':')[1]}:{v.get('rl')}/{v.get('tl')}/{v.get('phase')}"
                             for k, v in truth.items() if isinstance(v, dict))
            print(f"[{time.strftime('%H:%M:%S')}] {brief}", flush=True)
            time.sleep(max(1.2, args.interval - (time.time() - tick)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
