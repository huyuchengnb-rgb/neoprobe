"""把整个工具打成一个单文件 .pyz（零依赖，双击/`python neoprobe.pyz` 即可）。

    python tools/pack.py            # 生成 dist/neoprobe.pyz
    python dist/neoprobe.pyz --serve

体积对比：源码目录约 230 KB，打包后约 90 KB（zip 压缩 + 去掉注释外的空白增益有限，
主要是把十几个文件压成一份，便于拷来拷去）。
"""

from __future__ import annotations

import os
import py_compile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "neoprobe"
OUT_DIR = ROOT / "dist"
OUT = OUT_DIR / "neoprobe.pyz"

LAUNCHER = """import sys

from neoprobe.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
"""


def iter_files() -> list[tuple[Path, str]]:
    items: list[tuple[Path, str]] = []
    for path in sorted(PKG.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        if path.suffix not in (".py", ".html", ".md"):
            continue
        items.append((path, str(path.relative_to(ROOT)).replace(os.sep, "/")))
    return items


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    files = iter_files()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("__main__.py", LAUNCHER)
        for path, arc in files:
            zf.write(path, arc)
    src_size = sum(p.stat().st_size for p, _ in files)
    print(f"打包完成: {OUT}")
    print(f"  源文件 {len(files)} 个 / {src_size / 1024:.0f} KB  ->  {OUT.stat().st_size / 1024:.0f} KB")
    print(f"  试运行: python {OUT.relative_to(ROOT)} -V")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
