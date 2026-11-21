"""桌面窗口版：原生窗口 + 内置服务，双击即用。

和原来的 `--serve` 有什么区别：

    --serve   起一个本地 HTTP 服务，再叫你用浏览器打开它（要浏览器，要命令行）
    本模块    自己开一个原生窗口，把界面装在窗口里。没有控制台、没有浏览器、
              没有地址栏，就是一个普通桌面程序。

界面还是同一份 `web/index.html`（渲染在 WebView2 里，Win10/11 自带），
所以功能完全一致，不用重写 UI，也不会出现"网页版和桌面版长得不一样"。

服务只监听 127.0.0.1，端口随机（避免和已开实例抢 8777）。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

APP_TITLE = "NeoProbe"
MUTEX_NAME = "Local\\NeoProbe-Desktop-SingleInstance"
DEFAULT_SIZE = (1280, 860)
MIN_SIZE = (960, 600)
BG_COLOR = "#f6f7fb"


# ------------------------------------------------------------------ 日志


def _log_path(data_dir: Path) -> Path:
    return data_dir / "desktop.log"


def _write_log(data_dir: Path, text: str) -> None:
    """窗口版没有控制台，异常只能落到这里，否则用户什么都看不到。"""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(_log_path(data_dir), "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text.rstrip()}\n")
    except OSError:
        pass


def _install_excepthook(data_dir: Path) -> None:
    def hook(exc_type, exc, tb):
        _write_log(data_dir, "".join(traceback.format_exception(exc_type, exc, tb)))
        _msgbox(f"程序遇到错误：\n\n{exc_type.__name__}: {exc}\n\n日志：{_log_path(data_dir)}",
                APP_TITLE, 0x10)

    sys.excepthook = hook


def _bind_streams(data_dir: Path) -> None:
    """打包成 --noconsole 后 stdout/stderr 是 None，任何 print 都无处可去。

    把它们接到日志文件上：出问题时至少能翻到最后几行发生了什么。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        fh = open(_log_path(data_dir), "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = fh
    if sys.stderr is None:
        sys.stderr = fh


# ------------------------------------------------------------------ Win32 小工具


def _msgbox(text: str, title: str = APP_TITLE, flags: int = 0x40) -> None:
    """flags: 0x40 信息 / 0x30 警告 / 0x10 错误（MB_ICON*）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception:
        print(text, file=sys.stderr)


def _single_instance() -> int | None:
    """同名互斥体已存在 → 返回 None（说明已经开着一个）。

    Windows 上双击第二次不该再开一个窗口，而是把原来那个叫到前面来。
    """
    if os.name != "nt":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        # 64 位下句柄是 8 字节，不声明 restype 会被截断成 int，CloseHandle 就会失败
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return 0
        if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
            k32.CloseHandle(handle)
            return None
        return int(handle)
    except Exception:
        return 0


def _focus_existing() -> bool:
    """把已经开着的主窗口提到前台。找不到就返回 False。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hits: list[int] = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _lparam):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith(APP_TITLE):
                    hits.append(hwnd)
            return True

        user32.EnumWindows(proto(cb), 0)
        if not hits:
            return False
        hwnd = hits[0]
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _webview2_missing() -> bool:
    """WebView2 运行时是否缺失（Win11 自带，Win10 旧机器可能没有）。"""
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False
    keys = (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    )
    for root, path in keys:
        try:
            with winreg.OpenKey(root, path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                if version and version != "0.0.0.0":
                    return False
        except OSError:
            continue
    return True


# ------------------------------------------------------------------ 窗口尺寸记忆


def _state_path(data_dir: Path) -> Path:
    return data_dir / "window.json"


def _load_window_state(data_dir: Path) -> dict[str, Any]:
    try:
        raw = json.loads(_state_path(data_dir).read_text("utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_window_state(data_dir: Path, win) -> None:
    try:
        state = {
            "width": int(win.width), "height": int(win.height),
            "x": int(win.x), "y": int(win.y),
        }
    except Exception:
        return
    try:
        _state_path(data_dir).write_text(json.dumps(state), "utf-8")
    except OSError:
        pass


def _screen_size() -> tuple[int, int]:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return DEFAULT_SIZE


def _dpi_aware() -> None:
    """量屏幕之前先声明 DPI 感知。

    pywebview 自己也会调 SetProcessDPIAware，但那时窗口尺寸已经算完了：
    在 125%/150% 缩放的机器上，会按"逻辑像素"算出比屏幕还大的窗口。
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # PROCESS_SYSTEM_DPI_AWARE
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _system_scaling() -> float:
    """系统缩放比例（1.0 = 100%，1.5 = 150%）。"""
    if os.name != "nt":
        return 1.0
    try:
        import ctypes
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    try:
        import ctypes
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.GetDC.restype = ctypes.c_void_p
        hdc = user32.GetDC(None)
        dpi = int(gdi32.GetDeviceCaps(ctypes.c_void_p(hdc), 88))   # LOGPIXELSX
        user32.ReleaseDC(None, ctypes.c_void_p(hdc))
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _window_geometry(data_dir: Path) -> tuple[int, int, int | None, int | None]:
    """窗口大小（逻辑像素）：上次用过就沿用，否则取桌面 84%，并限制在合理范围内。

    注意这里返回的是**逻辑**像素：pywebview 的 WinForms 层会按 DPI 缩放再换成物理像素，
    所以传物理像素会在 125%/150% 的机器上得到一个超出屏幕的窗口。
    """
    sw, sh = _screen_size()
    k = _system_scaling() or 1.0
    lw, lh = sw / k, sh / k
    state = _load_window_state(data_dir)
    w = int(state.get("width") or min(max(int(lw * 0.84), MIN_SIZE[0]), 1600))
    h = int(state.get("height") or min(max(int(lh * 0.84), MIN_SIZE[1]), 1000))
    w = max(MIN_SIZE[0], min(w, int(lw) - 40))
    h = max(MIN_SIZE[1], min(h, int(lh) - 80))
    x = state.get("x")
    y = state.get("y")
    # 上次的位置如果已经跑到屏幕外（换过显示器），就别用了
    if isinstance(x, int) and isinstance(y, int):
        if not (-40 <= x <= lw - 200 and -20 <= y <= lh - 200):
            x = y = None
    return w, h, (int(x) if isinstance(x, int) else None), (int(y) if isinstance(y, int) else None)


# ------------------------------------------------------------------ 主程序


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class DesktopApp:
    def __init__(self, manager, data_dir: Path, *, debug: bool = False) -> None:
        self.manager = manager
        self.data_dir = data_dir
        self.debug = debug
        self.httpd = None
        self.url = ""
        self._title_stop = threading.Event()

    # -------------------------------------------------- 生命周期

    def _start_backend(self) -> str:
        from .server import create_server

        port = _free_port()
        self.httpd = create_server(self.manager, host="127.0.0.1", port=port)
        port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever,
                         name="http", daemon=True).start()
        self.url = f"http://127.0.0.1:{port}/"
        _write_log(self.data_dir, f"窗口版启动: {self.url}  数据目录 {self.data_dir}")
        return self.url

    def _stop_backend(self) -> None:
        self._title_stop.set()
        try:
            if self.httpd:
                self.httpd.shutdown()
                self.httpd.server_close()
        except Exception:
            pass
        try:
            self.manager.stop()
        except Exception:
            pass

    # -------------------------------------------------- 标题栏

    def _watch_title(self, window) -> None:
        """标题栏显示"在线 x/y"：最小化时也能一眼看出服务器状态。"""
        last = ""
        while not self._title_stop.is_set():
            try:
                snap = self.manager.snapshot()
                online = snap.get("online") or 0
                total = snap.get("count") or 0
                text = f"{APP_TITLE} · 在线 {online}/{total}"
                if text != last:
                    window.set_title(text)
                    last = text
            except Exception:
                pass
            self._title_stop.wait(5.0)

    # -------------------------------------------------- 运行

    def run(self) -> int:
        try:
            import webview
        except ImportError:
            _msgbox("缺少窗口组件（pywebview）。\n请改用 NeoProbe.exe --serve 的浏览器模式。",
                    APP_TITLE, 0x10)
            return 1

        if _webview2_missing():
            _msgbox(
                "这台机器缺少 Microsoft Edge WebView2 运行时，窗口无法显示。\n\n"
                "装一次即可（约 2 MB，微软官方，Win10 常见）：\n"
                "https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n"
                "不想装的话，也可以用原来的浏览器模式：\n"
                "NeoProbe.exe --serve",
                APP_TITLE, 0x30)
            return 1

        url = self._start_backend()
        _dpi_aware()
        w, h, x, y = _window_geometry(self.data_dir)
        window = webview.create_window(
            f"{APP_TITLE} · 加载中…", url,
            width=w, height=h, x=x, y=y,
            min_size=MIN_SIZE,
            background_color=BG_COLOR,
            text_select=True,
            zoomable=True,
        )

        threading.Thread(target=self._watch_title, args=(window,), daemon=True).start()

        storage = self.data_dir / "webview"
        try:
            storage.mkdir(parents=True, exist_ok=True)
            # 允许下载美化包/护眼补丁，并用系统默认浏览器打开外部新窗口链接
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
            webview.start(
                private_mode=False,           # 记住排序/筛选等界面偏好
                storage_path=str(storage),
                debug=self.debug,
            )
        except Exception as exc:
            _write_log(self.data_dir, f"窗口启动失败: {exc}\n{traceback.format_exc()}")
            _msgbox(f"窗口启动失败：{exc}\n\n日志：{_log_path(self.data_dir)}\n"
                    f"可以改用浏览器模式：NeoProbe.exe --serve", APP_TITLE, 0x10)
            self._stop_backend()
            return 1
        finally:
            _save_window_state(self.data_dir, window)
            self._stop_backend()
        _write_log(self.data_dir, "窗口已关闭，程序退出")
        return 0

def run(args) -> int:
    """从命令行参数起窗口版（`--desktop`，或不带参数双击时走这里）。"""
    from .__main__ import _make_manager
    from .manager import default_data_dir

    data_dir = Path(args.data_dir) if getattr(args, "data_dir", None) else default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    _bind_streams(data_dir)
    _install_excepthook(data_dir)

    handle = _single_instance()
    if handle is None:
        _focus_existing()
        return 0

    manager = _make_manager(args, data_dir)
    app = DesktopApp(manager, data_dir, debug=bool(getattr(args, "debug_window", False)))
    try:
        return app.run()
    finally:
        try:
            import ctypes
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass
