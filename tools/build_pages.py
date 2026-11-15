"""Build the static GitHub Pages bundle (HTML + live A2S/status.php snapshot).

Usage:
    python tools/build_pages.py --out _site
    python tools/build_pages.py --out docs --skip-copy   # refresh docs/data/state.json only
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neoprobe import a2s, rounds  # noqa: E402

DOCS_DIR = ROOT / "docs"
ASSETS_DIR = ROOT / "assets"

# Default public server list; server_catalog.php entries are merged automatically.
PUBLIC_SERVERS: list[dict[str, str]] = [
    {"address": "43.249.193.77:27076", "label": "mio服①"},
    {"address": "43.249.193.77:27265", "label": "mio服②"},
    {"address": "43.249.193.77:27852", "label": "mio服③"},
    {"address": "202.189.23.252:27045", "label": "mio服④"},
    {"address": "202.189.23.252:27235", "label": "mio服⑤"},
    {"address": "202.189.23.252:27265", "label": "mio服⑥"},
    {"address": "202.189.21.228:27076", "label": "娘娘测试服"},
    {"address": "202.189.21.228:27265", "label": "白菜测试服"},
    {"address": "202.189.21.228:27852", "label": "猫娘窝测试服"},
    {"address": "202.189.21.228:31284", "label": "兑换服"},
]


def merge_servers(
    base: list[dict[str, str]],
    catalog_items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Merge public catalog servers after base list without duplicates."""
    seen: dict[str, dict[str, str]] = {}
    order: list[str] = []

    for item in base:
        raw = (item.get("address") or "").strip()
        if not raw:
            continue
        try:
            addr = a2s.parse_address(raw)
        except ValueError:
            continue
        key = addr.key
        if key not in seen:
            seen[key] = {"address": str(addr), "label": str(item.get("label") or "").strip()}
            order.append(key)

    for item in catalog_items:
        if item.get("visible_to"):
            continue
        raw = (item.get("address") or "").strip()
        if not raw:
            continue
        try:
            addr = a2s.parse_address(raw)
        except ValueError:
            continue
        key = addr.key
        name = str(item.get("name") or "").strip()
        if key not in seen:
            seen[key] = {"address": str(addr), "label": name}
            order.append(key)
        elif name and not seen[key]["label"]:
            seen[key]["label"] = name

    return [seen[k] for k in order]


def query_server_full(
    address: str,
    timeout: float = 2.0,
    samples: int = 2,
    retries: int = 3,
) -> dict[str, Any]:
    """Query A2S info + players + rules with short retries on packet loss."""
    addr = a2s.parse_address(address)
    last_exc: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return a2s.query_all(
                addr, timeout=timeout, samples=samples,
                with_players=True, with_rules=True,
            )
        except a2s.A2SProtocolError:
            raise
        except (a2s.A2SError, OSError) as exc:
            last_exc = exc
            if attempt + 1 < retries:
                time.sleep(0.25)
    raise last_exc or a2s.A2SError("无有效响应")


def collect_snapshot(
    servers: list[dict[str, str]] | None = None,
    rounds_url: str = rounds.DEFAULT_ROUNDS_API,
    timeout: float = 2.0,
    samples: int = 2,
    retries: int = 3,
    workers: int = 10,
    query_fn: Callable[[str], dict[str, Any]] | None = None,
    rounds_fn: Callable[[str], rounds.FetchResult] | None = None,
    catalog_fn: Callable[[str], tuple[list[dict[str, Any]], str | None]] | None = None,
) -> dict[str, Any]:
    """Collect A2S snapshots + catalog + status.php into a static JSON payload."""
    base = list(PUBLIC_SERVERS if servers is None else servers)
    cat_url = rounds.catalog_url(rounds_url)
    cat_meta: dict[str, Any] = {"ok": False, "error": None, "count": 0, "url": cat_url}

    if cat_url:
        fetch_cat = catalog_fn or (lambda u: rounds.fetch_catalog(u, timeout=max(timeout, 4.0)))
        try:
            cat_items, cat_err = fetch_cat(cat_url)
        except Exception as exc:
            cat_items, cat_err = [], str(exc)
        cat_meta.update({"ok": cat_err is None, "error": cat_err, "count": len(cat_items)})
        merged = merge_servers(base, cat_items)
    else:
        merged = merge_servers(base, [])

    fetch_rounds = rounds_fn or (lambda u: rounds.fetch(u, timeout=max(timeout, 4.0)))
    qfn = query_fn or (lambda addr: query_server_full(addr, timeout=timeout, samples=samples, retries=retries))

    def probe_one(entry: dict[str, str]) -> dict[str, Any]:
        addr_str = entry["address"]
        checked_at = time.time()
        try:
            res = qfn(addr_str)
            info = res.get("info")
            return {
                "address": addr_str,
                "label": entry.get("label") or "",
                "state": "ok",
                "error": None,
                "rtt_ms": info.get("rtt_ms") if isinstance(info, dict) else None,
                "checked_at": round(checked_at, 2),
                "info": info,
                "players": res.get("players"),
                "players_error": res.get("players_error"),
                "rules": res.get("rules"),
                "rules_error": res.get("rules_error"),
            }
        except Exception as exc:
            return {
                "address": addr_str,
                "label": entry.get("label") or "",
                "state": "error",
                "error": str(exc),
                "rtt_ms": None,
                "checked_at": round(checked_at, 2),
                "info": None,
                "players": None,
                "players_error": None,
                "rules": None,
                "rules_error": None,
            }

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(merged) or 1))) as pool:
        rounds_future = pool.submit(fetch_rounds, rounds_url) if rounds_url else None
        rows = list(pool.map(probe_one, merged))

    if rounds_future is not None:
        try:
            r_res = rounds_future.result()
        except Exception as exc:
            r_res = rounds.FetchResult(error=str(exc), fetched_at=time.time())
    else:
        r_res = rounds.FetchResult(error="未配置回合接口", fetched_at=time.time())

    rounds_meta = {
        "ok": r_res.ok,
        "error": r_res.error,
        "fetched_at": round(r_res.fetched_at, 2),
        "count": r_res.count,
        "url": rounds_url,
    }

    for row in rows:
        try:
            key = a2s.parse_address(row["address"]).key
        except ValueError:
            key = row["address"].lower()
        st = r_res.statuses.get(key)
        row["rounds"] = st.to_dict() if st else None

    now = time.time()
    online = sum(1 for r in rows if r["state"] == "ok")
    total_players = sum((r["info"] or {}).get("players") or 0 for r in rows if r["state"] == "ok")

    return {
        "schema_version": 1,
        "generated_at": round(now, 2),
        "collector": "github-actions" if _in_ci() else "local-build",
        "count": len(rows),
        "online": online,
        "total_players": total_players,
        "rounds_meta": rounds_meta,
        "catalog_meta": cat_meta,
        "servers": rows,
    }


def _in_ci() -> bool:
    import os
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def build_site(
    out_dir: Path,
    snapshot: dict[str, Any],
    skip_copy: bool = False,
) -> Path:
    """Write static site bundle into out_dir and return the state.json path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if not skip_copy and DOCS_DIR.exists() and out_dir.resolve() != DOCS_DIR.resolve():
        for item in DOCS_DIR.iterdir():
            dest = out_dir / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    icon_src = ASSETS_DIR / "neoprobe.png"
    if icon_src.exists():
        shutil.copy2(icon_src, out_dir / "favicon.png")

    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / "state.json"
    state_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return state_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 GitHub Pages 静态站点与 A2S 快照")
    ap.add_argument("--out", default="_site", help="输出目录（默认 _site）")
    ap.add_argument("--timeout", type=float, default=2.5, help="单次 A2S 超时秒数（默认 2.5）")
    ap.add_argument("--samples", type=int, default=2, help="INFO 采样次数（默认 2）")
    ap.add_argument("--retries", type=int, default=3, help="失败重试次数（默认 3）")
    ap.add_argument("--rounds-api", default=rounds.DEFAULT_ROUNDS_API, help="回合接口地址")
    ap.add_argument("--skip-copy", action="store_true", help="仅刷新 data/state.json，不复制静态页面")
    args = ap.parse_args(argv)

    snap = collect_snapshot(
        rounds_url=args.rounds_api,
        timeout=args.timeout,
        samples=args.samples,
        retries=args.retries,
    )
    state_path = build_site(Path(args.out), snap, skip_copy=args.skip_copy)
    print(
        f"Pages 构建完成: {state_path} "
        f"(在线 {snap['online']}/{snap['count']}, 总玩家 {snap['total_players']}, "
        f"体积 {state_path.stat().st_size / 1024:.1f} KB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
