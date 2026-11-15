"""Steam 账号身份查询：是不是 VIP、什么时候到期。

数据来源（按可靠性排序）：

1. `identity.php?steamid64=...` —— 原启动器用的就是这个。实测返回：
       {"steamid64":"...","is_admin":false,"is_vip":true,"identity":"VIP"}
   注意：**当前服务端不返回到期时间**，所以这里把所有常见字段名都兼容一遍
   （vip_expire / expires_at / vip_until / days_left ...），将来服务端加了字段就能直接用。
2. 身份文本里自带的日期或天数，例如 "VIP 至 2026-12-01"、"VIP(剩 30 天)"。
3. 本地手动登记的到期日（`--vip-expire` 或面板里填），明确标注"本地记录"。

SteamID64 从本机 Steam 拿：优先 `config/loginusers.vdf` 里最近登录的账号，
其次读注册表 `HKCU\\Software\\Valve\\Steam\\ActiveProcess\\ActiveUser`（32 位账号 ID + 76561197960265728）。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

try:
    import winreg  # type: ignore
except ImportError:  # 非 Windows
    winreg = None  # type: ignore

IDENTITY_FILE = "identity.php"
STEAM_ID64_BASE = 76561197960265728

# 服务端可能用到的到期字段（大小写不敏感）
_EXPIRE_KEYS = (
    "vip_expire", "vip_expires", "vip_expire_at", "vip_expired_at",
    "expire_at", "expires_at", "expired_at", "expire", "expires",
    "vip_until", "vip_end", "vip_end_at", "vip_end_date", "vip_expire_date",
    "vip_expire_time", "vip_deadline", "deadline",
)
_DAYS_KEYS = ("days_left", "remaining_days", "vip_days", "vip_days_left", "left_days")

_DATE_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
_DAYS_TEXT_RE = re.compile(r"(?:剩|剩余|还有)\s*(\d{1,4})\s*天")


# ---------------------------------------------------------------- 本机账号


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    if winreg is not None:
        for hive, key, name in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    value, _ = winreg.QueryValueEx(k, name)
                if value:
                    roots.append(Path(str(value)))
            except OSError:
                pass
    for guess in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isdir(guess):
            roots.append(Path(guess))
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = os.path.normcase(str(root))
        if key not in seen and root.is_dir():
            seen.add(key)
            out.append(root)
    return out


def _parse_login_users(text: str) -> list[tuple[int, str]]:
    """从 loginusers.vdf 解析出 [(最近登录时间, steamid64)]。"""
    users: list[tuple[int, str]] = []
    for sid, body in re.findall(r'"(7\d{16})"\s*\{(.*?)\n\t*\}', text, re.S):
        ts = re.search(r'"timestamp"\s+"(\d+)"', body)
        recent = re.search(r'"MostRecent"\s+"1"', body)
        stamp = int(ts.group(1)) if ts else 0
        if recent:                     # MostRecent 标记优先，其次看时间戳
            stamp = max(stamp, 1 << 62)
        users.append((stamp, sid))
    users.sort(reverse=True)
    return users


def local_steamid64() -> tuple[str, str]:
    """返回 (steamid64, 来源说明)。取不到就是 ("", "未找到 Steam 账号")。"""
    for root in _steam_roots():
        vdf = root / "config" / "loginusers.vdf"
        try:
            text = vdf.read_text("utf-8", "ignore")
        except OSError:
            continue
        users = _parse_login_users(text)
        if users:
            account = ""
            m = re.search(rf'"{users[0][1]}"\s*\{{\s*"AccountName"\s+"([^"]*)"', text)
            if m:
                account = m.group(1)
            return users[0][1], f"loginusers.vdf（{account}）" if account else "loginusers.vdf"

    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Valve\Steam\ActiveProcess") as k:
                account_id, _ = winreg.QueryValueEx(k, "ActiveUser")
            if account_id:
                return str(STEAM_ID64_BASE + int(account_id)), "注册表 ActiveUser"
        except (OSError, ValueError):
            pass
    return "", "未找到 Steam 账号"


# ---------------------------------------------------------------- 解析


def _as_timestamp(value: Any) -> float | None:
    """把各种到期写法统一成 unix 时间戳。"""
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d{10,13}", text):          # 秒/毫秒时间戳
            v = float(text)
            if v > 1e12:
                v /= 1000.0
            return v
        m = _DATE_RE.search(text)
        if not m:
            return None
        year, month, day = (int(x) for x in m.groups())
        try:
            return time.mktime((year, month, day, 23, 59, 59, 0, 0, -1))
        except (ValueError, OverflowError):
            return None
    if v > 1e12:                                       # 毫秒
        v /= 1000.0
    # 明显是"剩余秒数"或"剩余天数"的小数值，按相对时间处理
    if 0 < v < 1e6:
        return time.time() + (v * 86400 if v < 1000 else v)
    return v


def _extract_expiry(data: dict) -> tuple[float | None, str]:
    """在响应里找到期时间，返回 (时间戳, 字段来源)。"""
    flat: dict[str, Any] = {}
    for k, v in data.items():
        flat[str(k).lower()] = v
        if isinstance(v, dict):
            for k2, v2 in v.items():
                flat[f"{str(k).lower()}.{str(k2).lower()}"] = v2
                flat[str(k2).lower()] = v2

    for key in _EXPIRE_KEYS:
        if key in flat:
            ts = _as_timestamp(flat[key])
            if ts:
                return ts, key
    for key in _DAYS_KEYS:
        if key in flat:
            try:
                days = float(flat[key])
            except (TypeError, ValueError):
                continue
            return time.time() + days * 86400, key
    return None, ""


def _extract_from_text(identity: str) -> tuple[float | None, str]:
    m = _DATE_RE.search(identity or "")
    if m:
        ts = _as_timestamp(m.group(0))
        if ts:
            return ts, "identity 文本里的日期"
    m = _DAYS_TEXT_RE.search(identity or "")
    if m:
        return time.time() + int(m.group(1)) * 86400, "identity 文本里的天数"
    return None, ""


def days_left(expire_at: float | None, now: float | None = None) -> int | None:
    if not expire_at:
        return None
    now = time.time() if now is None else now
    return max(0, int((expire_at - now + 86399) // 86400))


# ---------------------------------------------------------------- 查询


def fetch(api_base: str, steamid64: str, timeout: float = 6.0) -> dict[str, Any]:
    """查一次身份。失败不抛异常，把原因放在 error 里。"""
    result: dict[str, Any] = {
        "ok": False, "steamid64": steamid64, "identity": "",
        "is_vip": None, "is_admin": None,
        "expire_at": None, "expire_source": "", "days_left": None,
        "source": "", "fetched_at": time.time(), "error": None,
        "raw": None,
    }
    if not steamid64:
        result["error"] = "没有 Steam 账号可查"
        return result

    import urllib.error
    import urllib.parse
    import urllib.request

    url = identity_url(api_base)
    full = f"{url}?steamid64={urllib.parse.quote(steamid64)}"
    req = urllib.request.Request(full, headers={
        "User-Agent": "NeoProbe/1.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(64 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            result["error"] = "接口限流（每秒一次），稍后再试"
        else:
            result["error"] = f"HTTP {exc.code}"
        return result
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result["error"] = f"请求失败：{exc}"
        return result

    try:
        data = json.loads(body)
    except ValueError:
        result["error"] = "响应不是合法 JSON"
        return result
    if not isinstance(data, dict):
        result["error"] = "响应结构异常"
        return result

    result["ok"] = True
    result["raw"] = data
    result["identity"] = str(data.get("identity") or "")
    result["is_vip"] = data.get("is_vip")
    result["is_admin"] = data.get("is_admin")
    if data.get("steamid64"):
        result["steamid64"] = str(data["steamid64"])

    expire, source = _extract_expiry(data)
    if not expire:
        expire, source = _extract_from_text(result["identity"])
    if expire:
        result["expire_at"] = expire
        result["expire_source"] = source
        result["days_left"] = days_left(expire)
        result["source"] = "server"
    return result


def identity_url(api_base: str) -> str:
    """把 status.php 形式的基址换成 identity.php（和原启动器一致）。"""
    base = (api_base or "").strip()
    if not base:
        return ""
    if "identity.php" in base.lower():
        return base
    if "status.php" in base.lower():
        return re.sub(r"status\.php.*$", IDENTITY_FILE, base, flags=re.I)
    if not base.endswith("/"):
        base += "/"
    return base + IDENTITY_FILE


def mask_id(steamid64: str) -> str:
    if len(steamid64) <= 8:
        return steamid64 or "—"
    return f"{steamid64[:4]}***{steamid64[-4:]}"
