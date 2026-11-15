"""PyInstaller 入口：双击 exe（不带参数）时直接起面板。

`python -m neoprobe` 的 `__main__.py` 里，无子命令时是打印帮助；但 exe 是给人双击的，
双击带不出参数，所以这里把"没有参数"翻译成 `--serve`（起面板并自动开浏览器）。
命令行用法不受影响：`NeoProbe.exe --vip`、`NeoProbe.exe --queue 1.2.3.4:27015` 照旧。
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    from neoprobe.__main__ import main as cli

    argv = sys.argv[1:]
    if not argv:
        argv = ["--serve"]
        # 开机自启/脚本拉起时不想弹浏览器：设 NEOPROBE_NO_BROWSER=1 即可
        if os.environ.get("NEOPROBE_NO_BROWSER"):
            argv.append("--no-browser")
    return cli(argv)


if __name__ == "__main__":
    sys.exit(main())
