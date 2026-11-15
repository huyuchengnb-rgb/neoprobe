"""Summarize per-tick ground-truth vs A2S player/score deltas from .groundtruth.jsonl.

Usage:
    py tools/gt_analyze.py [.groundtruth.jsonl] [ip:port]
"""

from __future__ import annotations

import json
import sys
import time


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else ".groundtruth.jsonl"
    want = sys.argv[2] if len(sys.argv) > 2 else "202.189.21.228:27265"
    prev: dict[str, tuple[int, float]] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            tr = d["truth"].get(want, {})
            row = next((r for r in d["a2s"] if r["addr"] == want), None)
            if not row or "pl" not in row:
                print(time.strftime("%H:%M:%S", time.localtime(d["t"])), tr, "a2s err")
                continue
            pl = {p[0]: (p[1], p[2]) for p in row["pl"]}
            scores = [v[0] for v in pl.values()]
            zero = sum(1 for s in scores if s == 0)
            dec = sum(1 for k, v in pl.items() if k in prev and v[0] < prev[k][0])
            inc = sum(1 for k, v in pl.items() if k in prev and v[0] > prev[k][0])
            neg = sum(1 for s in scores if s < 0)
            joined = sum(1 for k in pl if k not in prev) if prev else 0
            left = sum(1 for k in prev if k not in pl) if prev else 0
            print(
                f"{time.strftime('%H:%M:%S', time.localtime(d['t']))} "
                f"rl={tr.get('rl')} tl={tr.get('tl')!s:>5} "
                f"n={row.get('n')} pl={len(pl)} sum={sum(scores):5} "
                f"zero={zero:2} neg={neg:2} inc={inc:2} dec={dec:2} +{joined} -{left}"
            )
            prev = pl
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
