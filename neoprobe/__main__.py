"""命令行入口：python -m neoprobe ..."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, a2s, launch as launcher, queue as queue_mod, rounds
from .vip import mask_id as vip_mask
from .manager import QueryManager, default_data_dir


# ---------------------------------------------------------------- 彩色输出


class C:
    on = sys.stdout.isatty()

    @classmethod
    def _w(cls, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if cls.on else s

    @classmethod
    def dim(cls, s): return cls._w("2", s)
    @classmethod
    def bold(cls, s): return cls._w("1", s)
    @classmethod
    def green(cls, s): return cls._w("32", s)
    @classmethod
    def yellow(cls, s): return cls._w("33", s)
    @classmethod
    def red(cls, s): return cls._w("31", s)
    @classmethod
    def cyan(cls, s): return cls._w("36", s)


def _lat_color(rtt: float | None):
    if rtt is None:
        return C.dim
    if rtt < 60:
        return C.green
    if rtt < 150:
        return C.yellow
    return C.red


def _w(s: str) -> int:
    """控制台显示宽度（中文按 2 格算）。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    gap = width - _w(s)
    return s + " " * max(0, gap)


def _truncate(s: str, width: int) -> str:
    if _w(s) <= width:
        return s
    out, acc = "", 0
    for ch in s:
        w = 2 if __import__("unicodedata").east_asian_width(ch) in "WF" else 1
        if acc + w > width - 1:
            break
        out += ch
        acc += w
    return out + "…"


# ---------------------------------------------------------------- 输出


def print_table(results: list[dict]) -> None:
    cols = [("服务器", 30), ("地图", 14), ("回合", 15), ("人数", 8), ("延迟", 8),
            ("模式", 13), ("地址", 22)]
    header = "  ".join(_pad(C.dim(t), w) for t, w in cols)
    print(header)
    print(C.dim("─" * (_w(header) + 2)))
    for r in results:
        info = r.get("info")
        if not info:
            addr = r.get("address", "?")
            err = (r.get("error") or "无响应")
            line = (f"{C.red('× 离线')}  {_pad(_truncate(addr, 30), 30)}  "
                    f"{_pad('—', 14)}  {_pad('—', 15)}  {_pad('—', 8)}  {_pad('—', 8)}  "
                    f"{_pad('—', 13)}  {C.dim(_truncate(err, 30))}")
            print(line)
            continue
        name = _truncate(info.get("name") or "(无名称)", 30)
        mode = _truncate(a2s.gamemode_of(info, r.get("rules")), 13)
        rtt = info.get("rtt_ms")
        lat = _lat_color(rtt)(f"{rtt:.0f}ms" if rtt is not None else "—")
        players = f"{info.get('players', 0)}/{info.get('max_players', 0)}"
        print("  ".join([
            _pad(C.bold(name), 30),
            _pad(_truncate(info.get("map") or "—", 14), 14),
            _pad(_round_cell(r), 15),
            _pad(C.cyan(players), 8),
            _pad(lat, 8),
            _pad(C.dim(mode), 13),
            _pad(C.dim(r.get("address", "")), 22),
        ]))


def _round_clock(rd: dict) -> str:
    """倒计时文本；"回合中但计时归零"不显示 00:00（回合还在打，只是不知道还剩多久）。"""
    left = rd.get("remaining")
    if rd.get("timer") == "expired":
        return C.yellow("计时归零")
    clock = rounds.format_clock(left)
    if left == 0:
        return C.yellow(clock)
    return C.cyan(clock) if left is not None else C.dim(clock)


def _round_cell(r: dict) -> str:
    rd = r.get("rounds")
    if not rd:
        return C.dim("—")
    n = rd.get("rounds_left")
    clock = _round_clock(rd)
    return f"{clock} {n}局" if n is not None else clock


def print_detail(r: dict) -> None:
    info = r.get("info")
    addr = r.get("address", "?")
    if not info:
        print(f"\n{C.red('×')} {C.bold(addr)}  {C.red(r.get('error') or '无响应')}")
        return
    rtt = info.get("rtt_ms")
    players_txt = f"{info.get('players', 0)}/{info.get('max_players', 0)}"
    lat_txt = f"{rtt:.0f} ms" if rtt is not None else "—"
    mode_txt = a2s.gamemode_of(info, r.get("rules"))

    print(f"\n{C.bold(info.get('name') or '(无名称)')}   {C.dim(addr)}")
    print(f"  {C.dim('地图')} {info.get('map')}   "
          f"{C.dim('人数')} {C.cyan(players_txt)}   "
          f"{C.dim('延迟')} {_lat_color(rtt)(lat_txt)}   "
          f"{C.dim('模式')} {mode_txt}")
    extra = []
    for k, label in (("version", "版本"), ("folder", "目录"), ("app_id", "AppID"),
                     ("environment", "平台"), ("vac", "VAC")):
        v = info.get(k)
        if v not in (None, "", 0):
            extra.append(f"{label}={v}")
    if info.get("tags"):
        extra.append(f"tags={info['tags']}")
    rd = r.get("rounds")
    if rd:
        n = rd.get("rounds_left")
        colored = _round_clock(rd)
        parts = [f"{C.dim('阶段')} {rd.get('phase') or '-'}",
                 f"{C.dim('剩余时间')} {colored}",
                 f"{C.dim('剩余局数')} {n if n is not None else '—'}"]
        print("  " + "   ".join(parts))

    if extra:
        print("  " + C.dim("  ".join(extra)))

    players = r.get("players")
    if players is not None:
        print(f"\n  {C.dim('玩家')} ({len(players)})")
        if not players:
            print("    " + C.dim("（空）"))
        for p in players:
            print(f"    {C.dim(str(p['index']).rjust(3))}  {_pad(_truncate(p['name'] or '(无名)', 30), 30)}"
                  f"  {C.dim('分数')} {str(p['score']).rjust(5)}  "
                  f"{C.dim('时长')} {a2s.format_duration(p['duration'])}")
    elif r.get("players_error"):
        print(f"\n  {C.dim('玩家')} " + C.red(r["players_error"]))

    rules = r.get("rules")
    if rules:
        print(f"\n  {C.dim('规则')} ({len(rules)})")
        for k in sorted(rules):
            print(f"    {C.dim(_pad(_truncate(k, 24), 24))} {_truncate(rules[k], 60)}")
    elif r.get("rules_error"):
        print(f"\n  {C.dim('规则')} " + C.red(r["rules_error"]))


def attach_rounds(results: list[dict], url: str, enabled: bool = True) -> None:
    """一次性拉回合接口，按 ip:port 挂到各条结果上。"""
    if not enabled or not url:
        return
    res = rounds.fetch(url, timeout=4.0)
    for item in results:
        try:
            key = a2s.parse_address(item["address"]).key
        except (KeyError, ValueError):
            continue
        status = res.statuses.get(key)
        item["rounds"] = status.to_dict() if status else None
        if res.ok is False and not item.get("rounds_error"):
            item["rounds_error"] = res.error


def query_one(raw: str, args) -> dict:
    try:
        addr = a2s.parse_address(raw)
    except ValueError as exc:
        return {"address": raw, "info": None, "error": str(exc)}
    try:
        return a2s.query_all(addr, timeout=args.timeout, samples=args.samples,
                             with_players=args.players, with_rules=args.rules)
    except (a2s.A2SError, OSError) as exc:
        return {"address": str(addr), "info": None, "error": str(exc)}


# ---------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="neoprobe",
        description="查询任意地址的 Garry's Mod / Source 服务器（A2S 协议）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python -m neoprobe 1.2.3.4:27015\n"
               "  python -m neoprobe 1.2.3.4:27015 --players --rules\n"
               "  python -m neoprobe a.com:27015 b.com:27015 --json\n"
               "  python -m neoprobe --serve\n",
    )
    p.add_argument("addresses", nargs="*", help="服务器地址，可多个")
    p.add_argument("-p", "--players", action="store_true", help="附加查询玩家列表（A2S_PLAYER）")
    p.add_argument("-r", "--rules", action="store_true", help="附加查询服务器规则（A2S_RULES）")
    p.add_argument("-j", "--json", action="store_true", help="以 JSON 输出")
    p.add_argument("-t", "--timeout", type=float, default=1.5, help="单次请求超时秒数（默认 1.5）")
    p.add_argument("-n", "--samples", type=int, default=2, help="INFO 采样次数，取最快 RTT（默认 2）")
    p.add_argument("--retries", type=int, default=3,
                   help="失败后的短重试次数（默认 3，满载服务器丢包时很有用）")
    p.add_argument("-w", "--watch", type=float, metavar="SEC", help="循环刷新间隔秒数")
    p.add_argument("--no-rounds", action="store_true", help="不查询回合状态（对局时间/剩余局数）")
    p.add_argument("--rounds-api", metavar="URL", default=rounds.DEFAULT_ROUNDS_API,
                   help="回合状态接口，默认启动器用的 status.php")
    p.add_argument("--gmod", metavar="PATH", help="Garry's Mod 安装目录或 gmod.exe 路径")
    p.add_argument("--launch", nargs="?", const="", metavar="ADDR",
                   help="启动游戏；带地址则直接进服（--launch 1.2.3.4:27015）")
    p.add_argument("--queue", metavar="ADDR", help="自动挤服：等这台满员服务器空出位置后自动进服")
    p.add_argument("--queue-interval", type=float, default=3.0, metavar="SEC",
                   help="挤服探测间隔秒数（默认 3）")
    p.add_argument("--vip", action="store_true",
                   help="查本机 Steam 账号的身份（是否 VIP、到期天数）")
    p.add_argument("--vip-api", metavar="URL",
                   help="身份接口地址（默认由 --rounds-api 推导成 identity.php）")
    p.add_argument("--vip-expire", metavar="DATE",
                   help="登记本地到期日（YYYY-MM-DD），服务端不返回到期时间时用它倒数；传空串清除")
    p.add_argument("--game", action="store_true", help="只打印 Garry's Mod / Steam 的检测结果")
    p.add_argument("--dry-run", action="store_true", help="只打印将要执行的启动命令，不真的启动")
    p.add_argument("--serve", action="store_true", help="启动本地 Web 面板")
    p.add_argument("--host", default="127.0.0.1", help="Web 面板监听地址（默认 127.0.0.1）")
    p.add_argument("--port", type=int, default=8777, help="Web 面板端口（默认 8777）")
    p.add_argument("--cors-origin", action="append", default=[], metavar="ORIGIN",
                   help="允许跨域访问本地 API 的来源（如 https://huyuchengnb-rgb.github.io），可多次指定")
    p.add_argument("--no-browser", action="store_true", help="启动 Web 面板时不自动打开浏览器")
    p.add_argument("--data-dir", metavar="DIR",
                   help="数据目录（默认 %%LOCALAPPDATA%%\\NeoProbe）")
    p.add_argument("--add", nargs="+", metavar="ADDR", help="向收藏列表添加地址后退出")
    p.add_argument("--list", action="store_true", help="列出收藏的服务器并查询")
    p.add_argument("-V", "--version", action="version", version=f"neoprobe {__version__}")
    return p


def _make_manager(args, data_dir: Path) -> QueryManager:
    return QueryManager(
        data_dir,
        timeout=args.timeout,
        samples=args.samples,
        retries=args.retries,
        rounds_url=args.rounds_api,
        rounds_enabled=not args.no_rounds,
        gmod_path=args.gmod or "",
        vip_api=getattr(args, "vip_api", "") or "",
    )


def _fmt_elapsed(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _run_queue(args) -> int:
    try:
        watcher = queue_mod.QueueWatcher(
            args.queue, interval=args.queue_interval,
            timeout=args.timeout, retries=args.retries,
            gmod_path=args.gmod or "", dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(C.red(f"地址无效：{exc}"))
        return 2

    watcher.start()
    last_line = ""
    try:
        while True:
            snap = watcher.snapshot()
            if snap["status"] != "watching":
                break
            players = snap["players"]
            cap = snap["max_players"]
            head = f"⏳ {snap['address']}"
            body = (f"{players}/{cap}" if players is not None else "—")
            line = (f"{head}  {C.cyan(body)}  {C.dim('探测')} {snap['attempts']:>3}"
                    f"  {C.dim('已等')} {_fmt_elapsed(snap['elapsed'])}")
            if snap.get("reserved"):
                line += C.yellow("  · 有预留位")
            if line != last_line:
                print("\r" + line + (" " * 8), end="", flush=True)
                last_line = line
            time.sleep(1.0)
    except KeyboardInterrupt:
        watcher.stop("用户中断")
        print("\r" + C.dim("已取消挤服") + " " * 40)
        return 130

    snap = watcher.snapshot()
    print("\r" + " " * (len(last_line) + 10), end="\r")
    if snap["status"] == "launched":
        print(C.green("✓ ") + (snap.get("message") or "已进入服务器"))
        res = snap.get("result") or {}
        if res.get("command"):
            print(C.dim("命令: ") + res["command"])
        return 0
    print(C.red("× ") + (snap.get("message") or "挤服失败"))
    return 1


def _print_vip(info: dict) -> int:
    if not info.get("ok"):
        print(C.red("× ") + str(info.get("error") or "查询失败"))
        return 1

    is_vip = info.get("is_vip")
    badge = C.green("VIP") if is_vip else C.dim(str(info.get("identity") or "普通用户"))
    if info.get("is_admin"):
        badge += C.yellow(" · 管理员")
    print(f"{C.dim('身份')}      {badge}")

    acc = info.get("account_source") or ""
    print(f"{C.dim('SteamID')}   {vip_mask(info.get('steamid64') or '')}"
          f"{C.dim('  ← ' + acc) if acc else ''}")

    days = info.get("days_left")
    expire_at = info.get("expire_at")
    if expire_at:
        when = time.strftime("%Y-%m-%d", time.localtime(expire_at))
        src = info.get("expire_source") or ""
        left = C.green(f"{days} 天") if (days or 0) > 7 else C.yellow(f"{days} 天")
        print(f"{C.dim('到期')}      {when}  {C.dim('（' + src + '）') if src else ''}")
        print(f"{C.dim('剩余')}      {left}")
    else:
        print(f"{C.dim('到期')}      {C.dim('服务端未提供')}")
        print(f"{C.dim('剩余')}      {C.dim('—')}"
              f"   {C.dim('可登记本地日期: --vip-expire 2026-12-01')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()

    # --vip：身份 / VIP
    if args.vip or args.vip_expire is not None:
        mgr = _make_manager(args, data_dir)
        if args.vip_expire is not None:
            try:
                mgr.set_vip_expire(args.vip_expire)
            except ValueError as exc:
                print(C.red(f"× {exc}"))
                return 2
        info = mgr.vip_info(force=True)
        return _print_vip(info)

    # --queue：自动挤服
    if args.queue:
        return _run_queue(args)

    # --game：只报环境
    if args.game:
        info = launcher.game_status(args.gmod or "")
        print(f"{C.dim('GMod')}      {info['gmod_path'] or C.red('未找到')}")
        print(f"{C.dim('游戏进程')}  {C.green('运行中') if info['running'] else C.dim('未运行')}")
        print(f"{C.dim('Steam')}     {C.green('运行中') if info['steam_running'] else C.dim('未运行')}"
              f"  {C.dim(info['steam_exe'])}")
        if info["libraries"]:
            print(f"{C.dim('Steam 库')}  " + C.dim(" | ".join(info["libraries"])))
        return 0 if info["found"] else 1

    # --launch：启动游戏（可带地址直接进服）
    if args.launch is not None:
        target = args.launch.strip() or None
        if target:
            try:
                a2s.parse_address(target)
            except ValueError as exc:
                print(C.red(f"地址无效：{exc}"))
                return 2
        result = launcher.launch(target, args.gmod or "", dry_run=args.dry_run)
        if result.get("command"):
            print(C.dim("命令: ") + result["command"])
        if result.get("ok"):
            print(C.green("✓ ") + (result.get("message") or "已启动"))
            return 0
        print(C.red("× ") + (result.get("error") or "启动失败"))
        return 1

    # --add：只写清单
    if args.add:
        mgr = _make_manager(args, data_dir)
        result = mgr.add_many(args.add)
        print(f"已添加 {result['added']} 个，跳过 {result['skipped']} 个重复")
        for f in result["failed"]:
            print(f"  {C.red('×')} {f['input']}: {f['error']}")
        mgr.stop()
        return 0 if result["added"] else 1

    # --list：查询收藏列表
    if args.list and not args.addresses:
        mgr = _make_manager(args, data_dir)
        snap = mgr.snapshot()
        args.addresses = [s["address"] for s in snap["servers"]]
        mgr.stop()
        if not args.addresses:
            print(C.dim("收藏列表为空。用 --add 添加，或直接传地址。"))
            return 1

    # --serve：Web 面板
    if args.serve:
        from .server import serve
        mgr = _make_manager(args, data_dir)
        try:
            serve(
                mgr,
                host=args.host,
                port=args.port,
                open_browser=not args.no_browser,
                cors_origins=args.cors_origin,
            )
        except OSError as exc:
            print(C.red(f"无法启动服务：{exc}"))
            return 1
        return 0

    if not args.addresses:
        build_parser().print_help()
        return 2

    # 单次 / 批量 / 循环
    first = True
    try:
        while True:
            if not first:
                time.sleep(max(1.0, args.watch or 1))
                print("\033[2J\033[H", end="")  # 清屏，仅 watch 模式
            first = False

            results = [query_one(a, args) for a in args.addresses]
            attach_rounds(results, args.rounds_api, not args.no_rounds)

            if args.json:
                print(json.dumps(results, ensure_ascii=False, indent=2))
            elif len(results) == 1:
                print_detail(results[0])
            else:
                print_table(results)
                online = sum(1 for r in results if r.get("info"))
                total_players = sum(r["info"].get("players", 0) for r in results if r.get("info"))
                print()
                print(C.dim(f"在线 {online}/{len(results)}  总玩家 {total_players}  "
                            f"{time.strftime('%H:%M:%S')}"))

            if not args.watch:
                break
    except KeyboardInterrupt:
        print()
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
