"""在指定主机上扫 A2S 端口，用来确认"目录里的服务器是不是全都加进去了"。

只发标准 A2S_INFO 查询（和启动器本身做的一样），不发起任何写操作。

用法：
    python tools/scan_ports.py 43.249.193.77 202.189.23.252 202.189.21.228
    python tools/scan_ports.py --ports 27000-27900,31000-32000 202.189.21.228
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")

from neoprobe import a2s

DEFAULT_PORTS = ["27000-27900", "31000-32000"]


def parse_ranges(specs: list[str]) -> list[int]:
    ports: list[int] = []
    for spec in specs:
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                lo, hi = part.split("-", 1)
                ports.extend(range(int(lo), int(hi) + 1))
            else:
                ports.append(int(part))
    return sorted({p for p in ports if 0 < p < 65536})


def probe(job):
    host, port, timeout = job
    try:
        return host, port, a2s.query_info(a2s.ServerAddress(host, port),
                                          timeout=timeout, samples=1)
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="扫主机的 A2S 端口")
    ap.add_argument("hosts", nargs="+", help="目标主机（IP 或域名）")
    ap.add_argument("--ports", default=",".join(DEFAULT_PORTS),
                    help="端口范围，可逗号分隔多个，如 27000-27900,31000-32000")
    ap.add_argument("--timeout", type=float, default=0.9, help="单次查询超时秒数")
    ap.add_argument("--workers", type=int, default=220, help="并发数")
    args = ap.parse_args(argv)

    ports = parse_ranges([args.ports])
    jobs = [(h, p, args.timeout) for h in args.hosts for p in ports]
    print(f"扫描 {len(args.hosts)} 台主机 × {len(ports)} 端口 = {len(jobs)} 次查询", flush=True)

    t0, hits = time.time(), []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(probe, jobs):
            if res:
                hits.append(res)
                host, port, info = res
                print(f"  ✓ {host}:{port:<6} {info['players']:>3}/{info['max_players']:<3} "
                      f"{info['name'][:48]}", flush=True)

    print(f"\n用时 {time.time() - t0:.0f}s，共 {len(hits)} 个在线实例", flush=True)
    for host, port, _ in hits:
        print(f"  {host}:{port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
