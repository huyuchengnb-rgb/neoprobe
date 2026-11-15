"""一条命令产出可交付的成品：dist/NeoProbe.exe + dist/NeoProbe-<版本>-win64.zip

    python tools/release.py            # 打包 exe + 说明 + zip
    python tools/release.py --pyz-only # 只出 .pyz（不装 PyInstaller 的环境）

exe 需要 PyInstaller（`pip install pyinstaller`）；缺了会自动跳过 exe，只出 .pyz，
不会让整个导出失败。图标需要 Pillow 才能重新生成，没装就用已有 assets/neoprobe.ico。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ASSETS = ROOT / "assets"
ICON = ASSETS / "neoprobe.ico"

HELP_TEXT = """\
NeoProbe —— 服务器监控面板
==========================

【怎么看】
  双击 NeoProbe.exe。
  会弹出一个黑色窗口（这是程序的日志，别关），浏览器自动打开面板；
  如果没有自动打开，手动访问：http://127.0.0.1:8777/

【怎么关】
  关掉那个黑色窗口就退出了。面板本身不常驻后台。

【能做什么】
  · 一览所有服务器的人数 / 延迟 / 地图 / 在线状态（默认 15 秒刷新）
  · 一键进服：点「进服」直接启动 Garry's Mod 连上指定服务器
  · 自动挤服：服务器满员时点「挤服」，一有空位自动进服
  · 查看身份：右上角标签显示是否 VIP（有到期数据时显示剩余天数）

【数据存在哪】
  %LOCALAPPDATA%\\NeoProbe\\servers.json
  删掉这个文件等于恢复初始设置。

【常见问题】
  · Windows 提示"已保护你的电脑" → 点「更多信息」→「仍要运行」。
    程序没有购买代码签名证书，首次运行都会这样提示。
  · 面板打不开 → 8777 端口被占用了。命令行执行：
        NeoProbe.exe --serve --port 8888
    然后访问 http://127.0.0.1:8888/
  · 想指定 Garry's Mod 路径：
        NeoProbe.exe --serve --gmod "D:\\SteamLibrary\\steamapps\\common\\GarrysMod"
  · 没装 Steam / 装在别的盘也能用，只是「进服」会提示找不到游戏。

【回合倒计时是怎么来的（重要）】
  数据来自社区接口 status.php（和原启动器同一个地址、同一套字段），
  面板每 10 秒拉一次，界面上由本地时钟走秒，不再重复请求。

  覆盖范围取决于服务端有没有上报：
    · 已上报的服 → 显示「剩 N 局」+ 倒计时 + 阶段（回合中/准备阶段/回合结束…）
    · 接口收录但当前没在打 → 显示「空闲 · 无对局」（兑换服这类地图不打回合）
    · 接口里没有这台服 → 显示「未上报」，不会用配置值冒充倒计时

  服务器列表同时从 server_catalog.php 在线更新（新版启动器同款机制），
  社区加了新服，面板重启后会自动并进来，不用手动录地址。

【其余情况怎么办】
  · 你正在玩的那台服，客户端探针会给出实测回合（列表标「本机」）
  · 没在接口里的服，可以看「空位节奏」（多久空一次位）和「本图已持续」，
    这两个都是实测值，对挑服/挤服同样有用
  · 想让某台服也有回合数，只能由那台服自己上报（见下方套件）

【想让接口没收录的服也有回合数？】
  随包附带了服务端插件与接收端，服主装一次即可：
    tools/gmod/neoprobe_reporter.lua   服务端插件（放到 addons/，改一行接收地址）
    tools/server/rounds.php            接收端（丢到任意 PHP 站点）
  装好后把面板的「回合接口」改成 rounds.php 的地址就行，不用改代码。
"""


def run(cmd: list[str]) -> int:
    print("$ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def build_icon() -> None:
    if ICON.exists():
        return
    try:
        run([sys.executable, str(ROOT / "tools" / "make_icon.py")])
    except Exception:
        print("! 没有图标也能打，只是 exe 用默认图标")


def build_pyz() -> Path | None:
    out = DIST / "neoprobe.pyz"
    if run([sys.executable, str(ROOT / "tools" / "pack.py")]) != 0 or not out.exists():
        return None
    return out


def build_exe() -> Path | None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("! 未安装 PyInstaller，跳过 exe（pip install pyinstaller 后可出单文件 exe）")
        return None

    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
        "--name", "NeoProbe",
        "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(BUILD),
        "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'neoprobe' / 'web'};neoprobe/web",
        "--version-file", str(ROOT / "tools" / "version_info.txt"),
        str(ROOT / "tools" / "entry.py"),
    ]
    if ICON.exists():
        cmd[-1:-1] = ["--icon", str(ICON)]
    exe = DIST / "NeoProbe.exe"
    if run(cmd) != 0:
        # 最常见的原因：这个 exe 正在运行，Windows 不让覆盖
        if exe.exists():
            print("! 打包失败（多半是 NeoProbe.exe 正在运行），沿用 dist 里已有的 exe")
            return exe
        print("! PyInstaller 打包失败")
        return None
    return exe if exe.exists() else None


def make_zip(exe: Path | None, pyz: Path | None) -> Path | None:
    version = "1.0.0"
    try:
        sys.path.insert(0, str(ROOT))
        from neoprobe import __version__ as version  # type: ignore
    except Exception:
        pass

    target = DIST / f"NeoProbe-{version}-win64.zip"
    if target.exists():
        target.unlink()

    help_path = DIST / "使用说明.txt"
    help_path.write_text(HELP_TEXT, encoding="utf-8-sig")   # 带 BOM，记事本不乱码

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        if exe and exe.exists():
            zf.write(exe, "NeoProbe.exe")
        if pyz:
            zf.write(pyz, "备用-py版本/neoprobe.pyz")
            # 这份 cmd 是给"只有 Python、拿不到 exe"的人用的，直接跑同目录的 pyz
            cmd_text = (
                "@echo off\r\n"
                "chcp 65001 >nul\r\n"
                'cd /d "%~dp0"\r\n'
                "echo 正在启动 NeoProbe ...\r\n"
                "python neoprobe.pyz --serve\r\n"
                "if errorlevel 1 (\r\n"
                "  echo.\r\n"
                "  echo 启动失败：需要 Python 3.10+ 并已加入 PATH。\r\n"
                "  echo 也可以直接双击上一层的 NeoProbe.exe。\r\n"
                "  pause\r\n"
                ")\r\n"
            )
            zf.writestr("备用-py版本/启动（需Python）.cmd", cmd_text.encode("utf-8-sig"))
        zf.write(help_path, "使用说明.txt")
        # 回合上报套件：服主装一次，九台服就有真实回合数（客户端拿不到别人那台服的状态）
        for src, arc in (
            (ROOT / "tools" / "gmod" / "neoprobe_reporter.lua",
             "回合上报套件/服务端插件/neoprobe_reporter.lua"),
            (ROOT / "tools" / "server" / "rounds.php",
             "回合上报套件/接收端/rounds.php"),
            (ROOT / "tools" / "gmod" / "neoprobe_rounds.lua",
             "回合上报套件/客户端探针（可选）/neoprobe_rounds.lua"),
        ):
            if src.exists():
                zf.write(src, arc)
        zf.write(ROOT / "README.md", "技术说明.md")
    return target


def human(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n > 1024 * 1024 else f"{n / 1024:.0f} KB"


def main() -> int:
    ap = argparse.ArgumentParser(description="导出可交付的成品")
    ap.add_argument("--pyz-only", action="store_true", help="只打 .pyz，不尝试 exe")
    args = ap.parse_args()

    DIST.mkdir(exist_ok=True)
    build_icon()

    exe = None if args.pyz_only else build_exe()
    pyz = build_pyz()
    target = make_zip(exe, pyz)

    print("\n===== 导出结果 =====")
    for item in (exe, pyz, target):
        if item and item.exists():
            print(f"  {item.relative_to(ROOT)}  {human(item.stat().st_size)}")
    if target:
        print(f"\n分发这个文件即可：{target}")
    return 0 if target else 1


if __name__ == "__main__":
    raise SystemExit(main())
