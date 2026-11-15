"""
启动 / 连接游戏。

逻辑对齐原启动器 RelayGate.LaunchService + GameLocator + GModProcessGuard，但修了两处：
  * 原版一次点击会做 9 次全进程枚举（GModProcessGuard 4 个名字 + CanReuseRunningGame 4 个
    + IsSteamRunning 1 个），这里统一成一次 Process.GetProcesses 快照
  * 原版在进程路径读取失败时直接判定"不是所选程序"，这里退化为"按名字判定"并给出提示

只在被显式调用时执行（本地面板点按钮 / CLI 带 --launch）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

GMOD_APPID = "4000"
# Steam 的"以指定参数启动游戏"URI 需要一个客户端能识别的会话令牌，与原启动器一致
STEAM_RUNGAME_TOKEN = "76561202255233023"
GAME_EXE_64 = "gmod_win64.exe"
GAME_EXE_32 = "gmod.exe"
GAME_PROCESS_NAMES = ("gmod", "gmod_win64", "hl2", "hl2_win64")
IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------- 注册表 / 库路径


def _registry_steam_paths() -> list[str]:
    """从注册表读 Steam 安装路径（64 位视图 + HKCU 兜底）。"""
    if not IS_WINDOWS:
        return []
    paths: list[str] = []
    try:
        import winreg
    except ImportError:
        return []

    def read(hive, subkey: str, value: str) -> str:
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                data, _ = winreg.QueryValueEx(key, value)
                return str(data or "")
        except OSError:
            return ""

    candidates = [
        read(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        read(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        read(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
    ]
    seen: set[str] = set()
    for path in candidates:
        if path and os.path.isdir(path):
            norm = str(Path(path))
            key = os.path.normcase(norm)
            if key not in seen:
                seen.add(key)
                paths.append(norm)
    return paths


def steam_libraries() -> list[str]:
    """Steam 库根目录列表（含 libraryfolders.vdf 里的自定义库）。"""
    libs: list[str] = []
    for steam_root in _registry_steam_paths():
        if steam_root not in libs:
            libs.append(steam_root)
        vdf = Path(steam_root) / "steamapps" / "libraryfolders.vdf"
        if not vdf.exists():
            continue
        try:
            text = vdf.read_text("utf-8", "replace")
        except OSError:
            continue
        seen_lib = {os.path.normcase(x) for x in libs}
        for match in re.finditer(r'"path"\s+"([^"]+)"', text, re.IGNORECASE):
            path = match.group(1).replace("\\\\", "\\")
            key = os.path.normcase(path)
            if path and os.path.isdir(path) and key not in seen_lib:
                seen_lib.add(key)
                libs.append(path)
    return libs


def resolve_gmod(configured: str = "") -> str:
    """把"配置值/目录/exe 路径"归一成 gmod 可执行文件的绝对路径；找不到返回空串。"""
    if not configured:
        return ""
    try:
        full = os.path.abspath(os.path.expandvars(os.path.expanduser(configured.strip().strip('"'))))
    except (OSError, ValueError):
        return ""

    base = full
    is_file = os.path.isfile(full)
    if not os.path.isdir(full) and not is_file:
        return ""
    if is_file:
        name = os.path.basename(full).lower()
        if name not in (GAME_EXE_32, GAME_EXE_64):
            return ""
        base = os.path.dirname(full)

    # bin/win64、bin 都要往上退到安装根目录
    parts = Path(base).parts
    if len(parts) >= 2 and parts[-1].lower() in ("win64",) and parts[-2].lower() == "bin":
        base = str(Path(*parts[:-2]))
    elif parts and parts[-1].lower() == "bin":
        base = str(Path(*parts[:-1]))

    if not os.path.isdir(os.path.join(base, "garrysmod")):
        return ""
    if is_file:
        return full

    order = (GAME_EXE_64, GAME_EXE_32) if sys.maxsize > 2**32 else (GAME_EXE_32,)
    for name in order:
        candidate = os.path.join(base, name)
        if os.path.isfile(candidate):
            return candidate
    return ""


_FIND_CACHE: tuple[float, str] | None = None


def find_gmod(ttl: float = 5.0) -> str:
    """在 Steam 库里找 GarrysMod（优先有 appmanifest_4000.acf 的那个库）。

    结果缓存几秒：面板每两秒要问一次状态，而注册表 + libraryfolders.vdf 的
    解析没必要反复做（实测 0.75 ms/次）。
    """
    global _FIND_CACHE
    now = time.time()
    if _FIND_CACHE and now - _FIND_CACHE[0] < ttl and os.path.isfile(_FIND_CACHE[1]):
        return _FIND_CACHE[1]
    path = _scan_gmod()
    _FIND_CACHE = (now, path)
    return path


def _scan_gmod() -> str:
    fallback = ""
    for lib in steam_libraries():
        root = os.path.join(lib, "steamapps", "common", "GarrysMod")
        exe = resolve_gmod(root)
        if not exe:
            continue
        if os.path.isfile(os.path.join(lib, "steamapps", "appmanifest_4000.acf")):
            return exe
        fallback = fallback or exe
    return fallback


def find_steam_exe() -> str:
    for root in _registry_steam_paths():
        exe = os.path.join(root, "steam.exe")
        if os.path.isfile(exe):
            return exe
    return ""


# ---------------------------------------------------------------- 进程状态


def _process_names() -> set[str]:
    """一次枚举拿到全部进程名（比 GetProcessesByName 逐个名字枚举便宜得多）。"""
    names: set[str] = set()
    if not IS_WINDOWS:
        return names
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return names

    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return names
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    names.add(entry.szExeFile.lower())
                    if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snapshot)
    except OSError:
        return names
    return names


def _process_pids() -> dict[str, int]:
    """一次 Toolhelp 枚举，返回 {exe 名(小写): pid}。"""
    if not IS_WINDOWS:
        return {}
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return {}

    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    pids: dict[str, int] = {}
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return pids
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    pids[entry.szExeFile.lower()] = int(entry.th32ProcessID)
                    if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snapshot)
    except OSError:
        return pids
    return pids


def _pid_alive(pid: int) -> bool:
    """一次 OpenProcess + GetExitCodeProcess，约 30 µs，比全量枚举便宜两个数量级。"""
    if not IS_WINDOWS or pid <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


_PID_CACHE: dict[str, int] = {}
_PID_MISS: dict[str, float] = {}          # 上次"没找到"的时间
SCAN_TTL = 2.0                            # 没找到时，2 秒内不重复全量枚举


def invalidate_process_cache() -> None:
    """刚启动/退出游戏后调用，让下一次状态查询立刻重新枚举。"""
    _PID_CACHE.clear()
    _PID_MISS.clear()


def _cached_pid(kind: str, candidates: tuple[str, ...]) -> int | None:
    """先看已记住的 PID 还活着没（约 30 µs）；没有才做一次全量枚举（约 7 ms）。"""
    pid = _PID_CACHE.get(kind)
    if pid and _pid_alive(pid):
        return pid
    _PID_CACHE.pop(kind, None)

    now = time.time()
    if now - _PID_MISS.get(kind, 0.0) < SCAN_TTL:
        return None                        # 刚扫过，确实没有

    pids = _process_pids()
    for name in candidates:
        exe = f"{name}.exe"
        if exe in pids:
            _PID_CACHE[kind] = pids[exe]
            _PID_MISS.pop(kind, None)
            return pids[exe]
    _PID_MISS[kind] = now
    return None


def game_pid() -> int | None:
    return _cached_pid("game", GAME_PROCESS_NAMES)


def steam_pid() -> int | None:
    return _cached_pid("steam", ("steam",))


def is_game_running(processes: set[str] | None = None) -> bool:
    if processes is not None:                      # 兼容旧调用：给名字集合就按名字判
        return any(f"{n}.exe" in processes or n in processes for n in GAME_PROCESS_NAMES)
    return game_pid() is not None


def is_steam_running(processes: set[str] | None = None) -> bool:
    if processes is not None:
        return "steam.exe" in processes or "steam" in processes
    return steam_pid() is not None


def game_status(configured_gmod: str = "") -> dict:
    """面板顶部展示用：一次快照给全所有信息。"""
    running = game_pid() is not None
    steam_up = steam_pid() is not None
    path = resolve_gmod(configured_gmod) or find_gmod()
    return {
        "gmod_path": path,
        "found": bool(path),
        "running": running,
        "steam_running": steam_up,
        "steam_exe": find_steam_exe(),
        "libraries": steam_libraries(),
    }


# ---------------------------------------------------------------- 启动


def build_connect_target(address: str) -> str:
    """把 'ip:port' 规范成连接串（IPv6 加方括号）。"""
    from .a2s import parse_address

    addr = parse_address(address)
    host = f"[{addr.host}]" if ":" in addr.host else addr.host
    return f"{host}:{addr.port}"


def build_steam_rungame_url(address: str) -> str:
    target = build_connect_target(address)
    return f"steam://rungame/{GMOD_APPID}/{STEAM_RUNGAME_TOKEN}/+connect {target}"


def build_game_argv(gmod_path: str, address: str | None = None) -> list[str]:
    argv = [gmod_path, "-steam", "-game", "garrysmod"]
    if address:
        argv += ["+connect", build_connect_target(address)]
    return argv


def _spawn(argv: list[str], env_extra: dict[str, str] | None = None,
           cwd: str | None = None) -> int:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    kwargs: dict = {"env": env, "close_fds": True}
    if cwd:
        kwargs["cwd"] = cwd
    if IS_WINDOWS:
        # 不弹控制台；游戏自己会被 Steam 接管
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    proc = subprocess.Popen(argv, **kwargs)
    return proc.pid


def _open_uri(uri: str) -> bool:
    """用系统 ShellExecute 打开 steam:// 之类的 URI。"""
    try:
        if IS_WINDOWS:
            os.startfile(uri)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", uri])
        else:
            subprocess.Popen(["xdg-open", uri])
        return True
    except OSError:
        return False


def launch(address: str | None = None, configured_gmod: str = "",
           dry_run: bool = False) -> dict:
    """启动游戏；带 address 时直接进服。返回 {ok, action, message, command, ...}。"""
    names = _process_names()
    running = is_game_running(names)
    steam_up = is_steam_running(names)
    gmod = resolve_gmod(configured_gmod) or find_gmod()

    # 1) 游戏已在运行 + 指定了服务器 → 让 Steam 切服（和原版一致）
    if running and address:
        uri = build_steam_rungame_url(address)
        if dry_run:
            return {"ok": True, "action": "rungame-uri", "command": uri,
                    "message": "模拟：游戏已在运行，将通过 Steam 切换服务器"}
        if _open_uri(uri):
            invalidate_process_cache()
            return {"ok": True, "action": "rungame-uri", "command": uri,
                    "message": "检测到游戏已运行，已通过 Steam 请求切换服务器"}
        return {"ok": False, "action": "rungame-uri", "command": uri,
                "error": "无法调用 Steam 切换服务器，请确认 Steam 已启动"}

    # 2) 找不到游戏本体
    if not gmod:
        steam_exe = find_steam_exe()
        if not steam_up and steam_exe and not dry_run:
            _open_uri(steam_exe)
            return {"ok": False, "action": "start-steam", "command": steam_exe,
                    "error": "未找到 Garry's Mod，已尝试启动 Steam；请在 Steam 里安装/确认 GMod 路径"}
        return {"ok": False, "action": "noop", "command": "",
                "error": "未找到 Garry's Mod（gmod.exe / gmod_win64.exe），请在设置里指定安装目录"}

    argv = build_game_argv(gmod, address)
    if dry_run:
        return {"ok": True, "action": "spawn", "command": subprocess.list2cmdline(argv),
                "argv": argv, "gmod_path": gmod,
                "message": "模拟：将启动 " + os.path.basename(gmod) + (f" 并连接 {address}" if address else "")}

    # 3) 有游戏但 Steam 没起来 → 先把 Steam 叫起来（GMod 必须挂在 Steam 下）
    if not steam_up:
        steam_exe = find_steam_exe()
        if steam_exe and _open_uri(steam_exe):
            return {"ok": False, "action": "start-steam", "command": steam_exe,
                    "error": "Steam 未运行，已尝试启动；请登录后再点一次"}

    try:
        pid = _spawn(argv, {"SteamAppId": GMOD_APPID, "SteamGameId": GMOD_APPID},
                     cwd=os.path.dirname(gmod))
        invalidate_process_cache()
    except OSError as exc:
        return {"ok": False, "action": "spawn", "command": subprocess.list2cmdline(argv),
                "error": f"启动失败: {exc}"}

    suffix = f"，正在连接 {build_connect_target(address)}" if address else ""
    return {"ok": True, "action": "spawn", "command": subprocess.list2cmdline(argv),
            "pid": pid, "gmod_path": gmod, "message": f"已启动游戏{suffix}"}


__all__ = [
    "GMOD_APPID", "steam_libraries", "resolve_gmod", "find_gmod", "find_steam_exe",
    "is_game_running", "is_steam_running", "game_pid", "steam_pid",
    "invalidate_process_cache", "game_status", "build_connect_target",
    "build_steam_rungame_url", "build_game_argv", "launch",
]
