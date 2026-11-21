"""PyInstaller 入口：双击 exe（不带参数）时开原生窗口。

`python -m neoprobe` 的 `__main__.py` 里，无子命令时是打印帮助；但 exe 是给人双击的，
双击带不出参数，所以这里把"没有参数"翻译成 `--desktop`（原生窗口，不需要浏览器）。
命令行用法不受影响：`NeoProbe.exe --vip`、`NeoProbe.exe --queue 1.2.3.4:27015` 照旧。

想回到旧的浏览器模式：`NeoProbe.exe --serve`，
或者设环境变量 NEOPROBE_SERVER_MODE=1 后双击（脚本/开机自启时有用）。
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    from neoprobe.__main__ import main as cli

    argv = sys.argv[1:]
    if not argv:
        if os.environ.get("NEOPROBE_SERVER_MODE"):
            argv = ["--serve", "--no-browser"]
        else:
            argv = ["--desktop"]
    return cli(argv)


if __name__ == "__main__":
    sys.exit(main())
