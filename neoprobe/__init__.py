"""NeoProbe —— 任意地址的 Garry's Mod / Source 服务器探测工具。

用法：
    python -m neoprobe 1.2.3.4:27015                     单次查询
    python -m neoprobe 1.2.3.4:27015 --players --rules    带玩家与规则
    python -m neoprobe a:27015 b:27016 --json             批量，JSON 输出
    python -m neoprobe --desktop                          启动桌面窗口（双击 exe 默认）
    python -m neoprobe --serve                            启动本地 Web 面板（用浏览器看）
"""

from __future__ import annotations

import sys

# 尽早把 stdout 切成 UTF-8，避免 Windows 控制台在中文/特殊字符上抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

__version__ = "1.10.0"
