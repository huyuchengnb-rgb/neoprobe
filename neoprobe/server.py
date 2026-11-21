"""本地 HTTP 服务：静态 UI + JSON API（标准库实现，无第三方依赖）。"""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse

from . import a2s
from .manager import QueryManager

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 1 << 20
_MIME_FALLBACK = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
}


def _safe_rel_web_path(raw_rel: str) -> PurePosixPath | None:
    """校验静态文件相对路径，拒绝绝对路径、空段异常与 .. 目录穿越。"""
    text = unquote(raw_rel or "").replace("\\", "/")
    if not text or text.startswith("/") or "\x00" in text:
        return None
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return PurePosixPath(*parts)


def _parse_range(header: str | None, total: int) -> tuple[int, int] | None | str:
    """解析单个 HTTP Range（bytes=start-end）。无效返回 'invalid'，无头返回 None。"""
    if not header:
        return None
    val = header.strip()
    if not val.lower().startswith("bytes="):
        return None
    spec = val[6:].split(",", 1)[0].strip()
    if "-" not in spec:
        return "invalid"
    start_s, end_s = spec.split("-", 1)
    try:
        if not start_s:
            length = int(end_s)
            if length <= 0 or total <= 0:
                return "invalid"
            start = max(0, total - length)
            end = total - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else total - 1
    except ValueError:
        return "invalid"
    if start < 0 or end < start or start >= total:
        return "invalid"
    return start, min(end, total - 1)


class Api:
    def __init__(self, manager: QueryManager) -> None:
        self.m = manager
        self._snap_stamp: tuple[int, int] | None = None
        self._snap_bytes: bytes = b""
        self._snap_lock = threading.Lock()

    def state_bytes(self) -> bytes:
        """数据没变就直接复用上次序列化好的字节（1 秒一次轮询时几乎零成本）。"""
        stamp = self.m.stamp()
        with self._snap_lock:
            if self._snap_stamp == stamp and self._snap_bytes:
                return self._snap_bytes
        payload = {"ok": True, **self.m.snapshot()}
        body = json.dumps(payload, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        with self._snap_lock:
            self._snap_stamp = stamp
            self._snap_bytes = body
        return body


def _normalize_origins(origins) -> set[str]:
    out: set[str] = set()
    for raw in origins or ():
        s = str(raw or "").strip().rstrip("/")
        if s:
            out.add(s)
    return out


def make_handler(api: Api, cors_origins=()):
    allowed_origins = _normalize_origins(cors_origins)

    class Handler(BaseHTTPRequestHandler):
        server_version = "NeoProbe/1.0"
        protocol_version = "HTTP/1.1"      # 长连接：1 秒一次轮询复用同一条 TCP
        timeout = 70                       # 空闲连接超时回收，避免线程越攒越多

        # -------------------------------------------------- 基础
        def log_message(self, fmt: str, *args) -> None:  # 静音默认日志
            pass

        def _cors_origin(self) -> str | None:
            if not allowed_origins:
                return None
            origin = (self.headers.get("Origin") or "").strip().rstrip("/")
            if not origin:
                return None
            if "*" in allowed_origins or origin in allowed_origins:
                return origin
            return None

        def _send_cors_headers(self, origin: str | None = None) -> bool:
            matched = origin if origin is not None else self._cors_origin()
            if not matched:
                return False
            self.send_header("Access-Control-Allow-Origin", matched)
            self.send_header("Vary", "Origin")
            if (self.headers.get("Access-Control-Request-Private-Network") or "").lower() == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
            return True

        def do_OPTIONS(self) -> None:
            origin = self._cors_origin()
            self.send_response(204 if origin else 403)
            if self._send_cors_headers(origin):
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _json(self, payload, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            self._raw(body, status)

        def _raw(self, body: bytes, status: int = 200) -> None:
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _err(self, message: str, status: int = 400) -> None:
            self._json({"ok": False, "error": message}, status)

        def _body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return {}
            if length <= 0 or length > MAX_BODY:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
                return data if isinstance(data, dict) else {}
            except (ValueError, UnicodeDecodeError):
                return {}

        # -------------------------------------------------- 路由
        def do_HEAD(self) -> None:
            url = urlparse(self.path)
            path = url.path
            if self._try_serve_static(path, head_only=True):
                return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _try_serve_static(self, path: str, head_only: bool = False) -> bool:
            if path in ("/", "/index.html"):
                self._serve_rel(PurePosixPath("index.html"), head_only=head_only)
                return True
            if path == "/goc.html":
                self._serve_rel(PurePosixPath("goc.html"), head_only=head_only)
                return True
            if path == "/favicon.png":
                self._serve_rel(PurePosixPath("favicon.png"), head_only=head_only)
                return True
            if path.startswith("/assets/"):
                rel = _safe_rel_web_path("assets/" + path[len("/assets/"):])
                if rel is None:
                    self._err("非法路径", 403)
                else:
                    self._serve_rel(rel, head_only=head_only)
                return True
            if path.startswith("/static/"):
                rel = _safe_rel_web_path(path[len("/static/"):])
                if rel is None:
                    self._err("非法路径", 403)
                else:
                    self._serve_rel(rel, head_only=head_only)
                return True
            return False

        def do_GET(self) -> None:
            url = urlparse(self.path)
            path = url.path
            qs = parse_qs(url.query)

            if self._try_serve_static(path):
                return

            if path == "/api/state":
                return self._raw(api.state_bytes())

            if path == "/api/vip":
                force = (qs.get("refresh") or ["0"])[0] not in ("0", "false", "")
                try:
                    data = api.m.vip_info(force=force)
                except Exception as exc:
                    return self._json({"ok": False, "error": f"身份查询失败: {exc}"})
                return self._json({"ok": bool(data.get("ok")), "vip": data})

            if path == "/api/pulse":
                # 极轻量：前端每秒问一次"数据变了没"，变了才去拉全量
                return self._json({"ok": True, "rev": list(api.m.stamp())})

            if path == "/api/detail":
                raw = (qs.get("address") or [""])[0]
                if not raw:
                    return self._err("缺少 address 参数")
                want_players = (qs.get("players") or ["1"])[0] not in ("0", "false")
                want_rules = (qs.get("rules") or ["1"])[0] not in ("0", "false")
                try:
                    detail = api.m.detail(raw, players=want_players, rules=want_rules)
                except (a2s.A2SError, ValueError, OSError) as exc:
                    return self._json({"ok": False, "error": str(exc)}, 200)
                return self._json({"ok": True, **detail})

            if path == "/api/export":
                snap = api.m.snapshot()
                return self._json({
                    "ok": True,
                    "servers": [{"address": s["address"], "label": s["label"]} for s in snap["servers"]],
                })

            if path == "/api/health":
                return self._json({"ok": True, "ts": __import__("time").time()})

            if path == "/api/game":
                return self._json({"ok": True, **api.m.game_info(ttl=0)})

            if path == "/api/rounds":
                snap = api.m.snapshot()
                return self._json({"ok": True, "meta": snap["rounds_meta"],
                                   "servers": {s["address"]: s["rounds"] for s in snap["servers"]}})

            return self._err("未找到该路径", 404)

        def do_POST(self) -> None:
            url = urlparse(self.path)
            body = self._body()

            if url.path == "/api/add":
                raw = str(body.get("address") or "").strip()
                if not raw:
                    return self._err("address 不能为空")
                try:
                    key = api.m.add(raw, str(body.get("label") or ""))
                except ValueError as exc:
                    return self._err(str(exc))
                return self._json({"ok": True, "key": key})

            if url.path == "/api/add-many":
                items = body.get("addresses")
                if isinstance(items, str):
                    items = [ln for ln in items.replace(",", "\n").splitlines()]
                if not isinstance(items, list):
                    return self._err("addresses 必须是数组或文本")
                return self._json({"ok": True, **api.m.add_many(
                    [x if isinstance(x, dict) else str(x) for x in items])})

            if url.path == "/api/remove":
                raw = str(body.get("address") or "").strip()
                return self._json({"ok": api.m.remove(raw)})

            if url.path == "/api/clear":
                api.m.clear()
                return self._json({"ok": True})

            if url.path == "/api/refresh":
                raw = str(body.get("address") or "").strip()
                keys = None
                if raw:
                    try:
                        keys = [a2s.parse_address(raw).key]
                    except ValueError as exc:
                        return self._err(str(exc))
                n = api.m.refresh(keys)
                return self._json({"ok": True, "queued": n})

            if url.path == "/api/config":
                interval = body.get("interval")
                auto = body.get("auto")
                r_interval = body.get("rounds_interval")
                r_enabled = body.get("rounds_enabled")
                gmod = body.get("gmod_path")
                r_url = body.get("rounds_url")
                vip_api = body.get("vip_api")
                api.m.set_config(
                    float(interval) if isinstance(interval, (int, float)) else None,
                    bool(auto) if isinstance(auto, bool) else None,
                    float(r_interval) if isinstance(r_interval, (int, float)) else None,
                    bool(r_enabled) if isinstance(r_enabled, bool) else None,
                    r_url if isinstance(r_url, str) else None,
                    gmod if isinstance(gmod, str) else None,
                    vip_api if isinstance(vip_api, str) else None,
                )
                return self._json({"ok": True, **api.m.snapshot()["rounds_meta"]})

            if url.path == "/api/launch":
                address = str(body.get("address") or "").strip() or None
                dry = bool(body.get("dry_run"))
                if address:
                    try:
                        a2s.parse_address(address)
                    except ValueError as exc:
                        return self._err(str(exc))
                try:
                    result = api.m.launch_game(address, dry_run=dry)
                except Exception as exc:  # 启动链路的任何异常都回给前端
                    return self._json({"ok": False, "error": f"启动失败: {exc}"})
                return self._json(result)

            if url.path == "/api/queue":
                address = str(body.get("address") or "").strip()
                if not address:
                    return self._err("address 不能为空")
                interval = body.get("interval")
                try:
                    result = api.m.start_queue(
                        address,
                        label=str(body.get("label") or ""),
                        interval=float(interval) if isinstance(interval, (int, float)) else None,
                        dry_run=bool(body.get("dry_run")),
                    )
                except ValueError as exc:
                    return self._err(str(exc))
                except Exception as exc:
                    return self._json({"ok": False, "error": f"挤服启动失败: {exc}"})
                return self._json(result)

            if url.path == "/api/vip/expire":
                try:
                    data = api.m.set_vip_expire(str(body.get("date") or ""))
                except ValueError as exc:
                    return self._err(str(exc))
                return self._json({"ok": True, "vip": data})

            if url.path == "/api/queue/stop":
                return self._json(api.m.stop_queue(str(body.get("reason") or "已取消排队")))

            return self._err("未找到该路径", 404)

        # -------------------------------------------------- 静态文件
        def _serve_rel(self, rel: PurePosixPath, head_only: bool = False) -> None:
            rel_posix = rel.as_posix()
            web_root = WEB_DIR.resolve()
            disk_path = WEB_DIR.joinpath(*rel.parts)
            data: bytes | None = None
            try:
                resolved = disk_path.resolve()
                if web_root not in resolved.parents:
                    return self._err("非法路径", 403)
                data = resolved.read_bytes()
            except OSError:
                # 单文件 .pyz 里 web/ 在 zip 内，不是真实路径，改用包资源读取
                import pkgutil
                data = pkgutil.get_data(__package__, f"web/{rel_posix}")
                if data is None:
                    return self._err("文件不存在", 404)

            suffix = rel.suffix.lower()
            ctype = _MIME_FALLBACK.get(suffix) or mimetypes.guess_type(rel_posix)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"

            total = len(data)
            rng = _parse_range(self.headers.get("Range"), total)
            if rng == "invalid":
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if rng is not None:
                start, end = rng
                chunk = data[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                if not head_only:
                    self.wfile.write(chunk)
                return

            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(total))
            self.end_headers()
            if not head_only:
                self.wfile.write(data)

    return Handler


def create_server(manager: QueryManager, host: str = "127.0.0.1", port: int = 8777,
                  cors_origins=()) -> ThreadingHTTPServer:
    """起后台采集线程 + 建好 HTTP 服务，但不进入阻塞循环。

    桌面窗口版要把服务跑在子线程里，所以把"准备好"和"开始 serve_forever"拆开。
    端口可以传 0，让系统分配空闲端口（窗口版就这么用，避免和已开的实例抢端口）。
    """
    manager.start_auto()
    manager.start_rounds()
    manager.start_slots()
    manager.start_game_watch()
    manager.start_vip_watch()
    manager.refresh()
    httpd = ThreadingHTTPServer((host, port), make_handler(Api(manager), cors_origins=cors_origins))
    httpd.daemon_threads = True
    return httpd


def serve(manager: QueryManager, host: str = "127.0.0.1", port: int = 8777,
          open_browser: bool = True, cors_origins=()) -> None:
    httpd = create_server(manager, host=host, port=port, cors_origins=cors_origins)
    port = httpd.server_address[1]
    url = f"http://{host}:{port}/"
    print(f"NeoProbe 已启动: {url}")
    print(f"数据目录: {manager.data_dir}")
    if open_browser:
        def _open() -> None:
            import webbrowser
            webbrowser.open(url)
        threading.Timer(0.6, _open).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        manager.stop()
        httpd.server_close()
