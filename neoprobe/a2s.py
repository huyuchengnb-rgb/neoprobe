"""
A2S (Source Engine Query) 协议实现。

从 Neobreach / RelayGate.ServerQueryService 提取并修正：
  * 支持 A2S_INFO / A2S_PLAYER / A2S_RULES
  * challenge 自动应答与缓存（原实现每轮重握手）
  * 分包重组（原实现仅支持未压缩分包）
  * 压缩分包（bzip2，原实现直接抛 "Compressed split responses are not supported."）
  * 字符串解码不再逐字节 List<byte> 堆积

只依赖标准库。
"""

from __future__ import annotations

import bz2
import socket
import struct
import time
import zlib

# ---------------------------------------------------------------- 常量

SINGLE_HEADER = b"\xff\xff\xff\xff"
SPLIT_HEADER = b"\xfe\xff\xff\xff"  # int32 -2 (little endian)

A2S_INFO = 0x54
A2S_PLAYER = 0x55
A2S_RULES = 0x56
S2C_CHALLENGE = 0x41  # 'A'
S2A_INFO_SRC = 0x49  # 'I'  Source
S2A_INFO_GOLDSRC = 0x6D  # 'm'
S2A_PLAYER = 0x44  # 'D'
S2A_RULES = 0x45  # 'E'

CHALLENGE_TTL = 30.0  # 秒，challenge 有效期
MAX_REPLY = 1400  # 单个 UDP 包的安全读长


class A2SError(Exception):
    """查询失败的统一异常。"""


class A2STimeout(A2SError):
    pass


class A2SProtocolError(A2SError):
    pass


# ---------------------------------------------------------------- 地址


class ServerAddress:
    """地址值对象。用 __slots__ 而不是 dataclass：
    dataclasses 会额外拉起 inspect/enum，光 import 就要 90 ms。"""

    __slots__ = ("host", "port")

    def __init__(self, host: str, port: int = 27015) -> None:
        self.host = host
        self.port = port

    def __str__(self) -> str:
        if ":" in self.host:  # IPv6
            return f"[{self.host}]:{self.port}"
        return f"{self.host}:{self.port}"

    def __repr__(self) -> str:
        return f"ServerAddress({self.host!r}, {self.port})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ServerAddress):
            return NotImplemented
        return self.host == other.host and self.port == other.port

    def __hash__(self) -> int:
        return hash((self.host, self.port))

    @property
    def key(self) -> str:
        return str(self).lower()


def parse_address(raw: str, default_port: int = 27015) -> ServerAddress:
    """解析任意常见写法：ip:port / host:port / [v6]:port / steam://connect/ip:port / ip"""
    if not raw:
        raise ValueError("地址为空")
    text = raw.strip().strip('"').strip("'")

    # steam://connect/1.2.3.4:27015  或  steam://connect/1.2.3.4:27015/xxx
    low = text.lower()
    if low.startswith("steam://"):
        text = text.split("connect/", 1)[-1].split("/", 1)[0]
    # 允许 URL 形式  a2s://1.2.3.4:27015
    elif "://" in text:
        text = text.split("://", 1)[1]

    text = text.split()[0] if text.split() else text

    if text.startswith("["):  # IPv6 带端口
        end = text.find("]")
        if end < 0:
            raise ValueError(f"IPv6 地址缺少 ]：{raw}")
        host = text[1:end]
        rest = text[end + 1 :]
        port = int(rest[1:]) if rest.startswith(":") and rest[1:] else default_port
        return ServerAddress(host, port)

    if text.count(":") == 1:  # v4 或域名带端口
        host, _, port_s = text.partition(":")
        if not port_s.isdigit():
            raise ValueError(f"端口无效：{raw}")
        return ServerAddress(host, int(port_s))

    if text.count(":") > 1:  # 裸 IPv6，无端口
        return ServerAddress(text, default_port)

    # 纯 IP 或域名 / 单数字（Steam 短 ID 之类，不做猜测）
    return ServerAddress(text, default_port)


# ---------------------------------------------------------------- 编解码


def _build_request(kind: int, challenge: int | None = None) -> bytes:
    if kind == A2S_INFO:
        payload = b"Source Engine Query\x00"
        if challenge is not None:
            payload += struct.pack("<i", challenge)
        return SINGLE_HEADER + bytes([A2S_INFO]) + payload
    if kind in (A2S_PLAYER, A2S_RULES):
        return SINGLE_HEADER + bytes([kind]) + struct.pack("<i", -1 if challenge is None else challenge)
    raise ValueError(kind)


class _Reader:
    """在 bytes 上顺序读取，越界抛 A2SProtocolError 而不是悄悄返回 0。"""

    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.pos = 0

    @property
    def remaining(self) -> int:
        return len(self.buf) - self.pos

    def byte(self) -> int:
        if self.pos + 1 > len(self.buf):
            raise A2SProtocolError("响应意外结束（byte）")
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def short(self) -> int:
        if self.pos + 2 > len(self.buf):
            raise A2SProtocolError("响应意外结束（short）")
        v = struct.unpack_from("<h", self.buf, self.pos)[0]
        self.pos += 2
        return v

    def ushort(self) -> int:
        if self.pos + 2 > len(self.buf):
            raise A2SProtocolError("响应意外结束（ushort）")
        v = struct.unpack_from("<H", self.buf, self.pos)[0]
        self.pos += 2
        return v

    def long(self) -> int:
        if self.pos + 4 > len(self.buf):
            raise A2SProtocolError("响应意外结束（long）")
        v = struct.unpack_from("<i", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def float(self) -> float:
        if self.pos + 4 > len(self.buf):
            raise A2SProtocolError("响应意外结束（float）")
        v = struct.unpack_from("<f", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def string(self) -> str:
        end = self.buf.find(b"\x00", self.pos)
        if end < 0:
            raw = self.buf[self.pos :]
            self.pos = len(self.buf)
        else:
            raw = self.buf[self.pos : end]
            self.pos = end + 1
        return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------- 传输层


class _Session:
    """一次查询会话：复用同一个 UDP socket，缓存 challenge。"""

    def __init__(self, addr: ServerAddress, timeout: float) -> None:
        self.addr = addr
        self.timeout = timeout
        self._challenge: int | None = None
        self._challenge_at = 0.0
        try:
            self.sock = socket.socket(socket.AF_INET6 if ":" in addr.host else socket.AF_INET,
                                      socket.SOCK_DGRAM)
        except OSError as exc:  # IPv6 不可用等
            raise A2SError(f"无法创建 socket：{exc}") from exc
        self.sock.settimeout(timeout)
        try:
            self.sock.connect((addr.host, addr.port))
        except OSError as exc:
            self.sock.close()
            raise A2SError(f"无法连接 {addr}：{exc}") from exc

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- 原始收发 ---------------------------------------------------

    def _send(self, data: bytes) -> None:
        try:
            self.sock.send(data)
        except OSError as exc:
            raise A2SError(f"发送失败：{exc}") from exc

    def _recv(self) -> bytes:
        try:
            return self.sock.recv(65535)
        except socket.timeout as exc:
            raise A2STimeout(f"{self.addr} 响应超时（{int(self.timeout * 1000)} ms）") from exc
        except OSError as exc:
            raise A2SError(f"接收失败：{exc}") from exc

    def _recv_datagram(self) -> bytes:
        """收一个完整响应，必要时重组分包（支持 bzip2 压缩）。

        分包头长度在不同引擎版本里不一致：
            未压缩：header(4) id(4) total(1) number(1)            = 10
            带 size 字段的变体还要多 2 字节                          = 12
            压缩：  header(4) id(4) total(1) number(1)
                    size(2) uncompressed_size(4) crc32(4)          = 20
        所以不硬编码偏移，而是用锚点探测：
            * 未压缩：第 0 个分片的载荷必然以 FF FF FF FF 开头
            * 压缩：  载荷必然以 bzip2 魔数 "BZh" 开头
        """
        first = self._recv()
        if len(first) < 4 or first[:4] != SPLIT_HEADER:
            return first

        if len(first) < 10:
            raise A2SProtocolError("分包响应过短")
        resp_id = struct.unpack_from("<i", first, 4)[0]
        compressed = bool(resp_id & 0x80000000)
        resp_id &= 0x7FFFFFFF
        total = first[8]
        if total == 0 or total > 32:
            raise A2SProtocolError(f"分包数量异常：{total}")

        packets: dict[int, bytes] = {}

        def accept(pkt: bytes) -> None:
            if len(pkt) < 10 or pkt[:4] != SPLIT_HEADER:
                return
            pid = struct.unpack_from("<i", pkt, 4)[0] & 0x7FFFFFFF
            if pid != resp_id:
                return
            idx = pkt[9]
            if idx < total:
                packets[idx] = pkt

        accept(first)
        deadline = time.monotonic() + max(self.timeout, 0.4) * max(2, total)
        while len(packets) < total:
            if time.monotonic() > deadline:
                raise A2STimeout(f"分包重组超时（{len(packets)}/{total}）")
            accept(self._recv())

        # 用第 0 个分片定位载荷起点
        head0 = packets.get(0)
        if head0 is None:
            raise A2SProtocolError("缺少首个分片")
        if compressed:
            offset = _find_bz2(head0)
            if offset is None:
                raise A2SProtocolError("压缩分包中找不到 bzip2 数据")
        else:
            offset = _find_payload_start(head0)

        chunks = []
        for i in range(total):
            pkt = packets.get(i)
            if pkt is None:
                raise A2SProtocolError(f"缺少第 {i} 个分片")
            chunks.append(pkt[offset:])

        blob = b"".join(chunks)
        if compressed:
            blob = _inflate_bz2(blob)
        return blob


    # -- 高层请求 ---------------------------------------------------

    def request(self, kind: int, attempts: int = 2) -> tuple[bytes, float]:
        """发一次 A2S 请求，返回 (完整响应体, 最近一次 RTT 毫秒)。

        自动处理 S2C_CHALLENGE：命中则带上 challenge 重发。
        """
        challenge = self._challenge if (time.monotonic() - self._challenge_at) < CHALLENGE_TTL else None
        last_err: Exception | None = None
        rtt_ms = 0.0

        for _ in range(attempts):
            t0 = time.perf_counter()
            self._send(_build_request(kind, challenge))
            try:
                data = self._recv_datagram()
            except A2STimeout as exc:
                last_err = exc
                challenge = None  # 超时后 challenge 可能已过期
                continue
            rtt_ms = (time.perf_counter() - t0) * 1000.0

            body = _strip_header(data)
            if body and body[0] == S2C_CHALLENGE and len(body) >= 5:
                challenge = struct.unpack_from("<i", body, 1)[0]
                self._challenge = challenge
                self._challenge_at = time.monotonic()
                continue  # 带 challenge 重发
            return body, rtt_ms

        if last_err:
            raise last_err
        raise A2STimeout(f"{self.addr} 无响应")


def _strip_header(data: bytes) -> bytes:
    if len(data) >= 4 and data[:4] == SINGLE_HEADER:
        return data[4:]
    return data


def _find_bz2(pkt: bytes) -> int | None:
    """在分包头部里定位 bzip2 数据起点（兼容带/不带 size、crc32 的各种布局）。"""
    idx = pkt.find(b"BZh", 10, 40)
    return idx if idx > 0 else None


def _find_payload_start(pkt: bytes) -> int:
    """未压缩分包：推断载荷起点。

    各引擎版本的分包头长度不同（10 / 12 / 甚至带 crc 的更长），且部分实现会在
    重组载荷里保留原始的 FF FF FF FF 单包头、部分不保留。这里用"看起来像响应头"
    打分来选偏移，比硬编码安全。
    """
    known_types = (A2S_INFO, A2S_PLAYER, A2S_RULES, S2A_INFO_SRC,
                   S2A_PLAYER, S2A_RULES, S2C_CHALLENGE, S2A_INFO_GOLDSRC)
    best_off, best_score = 12, -1
    for off in (10, 12, 14, 16, 20):
        head = pkt[off:off + 5]
        if len(head) < 5:
            break
        if head[:4] == SINGLE_HEADER and head[4] in known_types:
            score = 100
        elif head[0] in known_types:
            score = 50
        elif head[:4] == SINGLE_HEADER:
            score = 20
        else:
            score = 0
        if score > best_score:
            best_off, best_score = off, score
    return best_off



def _inflate_bz2(blob: bytes) -> bytes:
    start = blob.find(b"BZh")
    if start < 0:
        raise A2SProtocolError("压缩分包中找不到 bzip2 数据")
    try:
        return bz2.decompress(blob[start:])
    except OSError as exc:
        raise A2SProtocolError(f"bzip2 解压失败：{exc}") from exc


# ---------------------------------------------------------------- 三个查询


def query_info(addr: ServerAddress, timeout: float = 1.5, samples: int = 2,
               session: _Session | None = None) -> dict:
    """查询服务器基础信息。samples>1 时取最快的 RTT（与原启动器一致）。"""
    own = session is None
    sess = session or _Session(addr, timeout)
    try:
        best: dict | None = None
        best_rtt = float("inf")
        last_err: Exception | None = None
        for _ in range(max(1, samples)):
            try:
                body, rtt = sess.request(A2S_INFO)
                info = _parse_info(body)
                info["rtt_ms"] = round(rtt, 1)
                if rtt < best_rtt:
                    best, best_rtt = info, rtt
            except A2SError as exc:
                last_err = exc
                if isinstance(exc, A2SProtocolError):
                    raise
        if best is None:
            raise last_err or A2SError("无有效响应")
        best["rtt_ms"] = round(best_rtt, 1)
        return best
    finally:
        if own:
            sess.close()


def query_players(addr: ServerAddress, timeout: float = 2.0,
                  session: _Session | None = None) -> list[dict]:
    own = session is None
    sess = session or _Session(addr, timeout)
    try:
        body, _ = sess.request(A2S_PLAYER)
        return _parse_players(body)
    finally:
        if own:
            sess.close()


def query_rules(addr: ServerAddress, timeout: float = 2.0,
                session: _Session | None = None) -> dict[str, str]:
    own = session is None
    sess = session or _Session(addr, timeout)
    try:
        body, _ = sess.request(A2S_RULES)
        return _parse_rules(body)
    finally:
        if own:
            sess.close()


def query_all(addr: ServerAddress, timeout: float = 1.5, samples: int = 2,
              with_players: bool = False, with_rules: bool = False) -> dict:
    """一次会话完成 info（+ 可选 players / rules），复用 challenge 与 socket。"""
    with _Session(addr, timeout) as sess:
        result: dict = {"address": str(addr), "info": query_info(addr, timeout, samples, sess)}
        if with_rules:
            try:
                result["rules"] = query_rules(addr, timeout, sess)
            except A2SError as exc:
                result["rules_error"] = str(exc)
        if with_players:
            try:
                result["players"] = query_players(addr, timeout, sess)
            except A2SError as exc:
                result["players_error"] = str(exc)
        return result


# ---------------------------------------------------------------- 解析


def _parse_info(body: bytes) -> dict:
    if not body:
        raise A2SProtocolError("空响应")
    kind = body[0]
    r = _Reader(body)
    r.byte()

    if kind == S2A_INFO_GOLDSRC:  # 老 GoldSrc
        return {
            "protocol": 0,
            "name": r.string(),
            "map": r.string(),
            "folder": r.string(),
            "game": r.string(),
            "players": r.byte(),
            "max_players": r.byte(),
            "protocol_version": r.byte(),
            "server_type": chr(r.byte()) if r.remaining else "",
            "environment": chr(r.byte()) if r.remaining else "",
            "visibility": r.byte() if r.remaining else 0,
            "is_mod": r.byte() if r.remaining else 0,
            "engine": "goldsrc",
        }

    if kind != S2A_INFO_SRC:
        raise A2SProtocolError(f"非 A2S_INFO 响应（0x{kind:02X}）")

    info: dict = {"engine": "source"}
    info["protocol"] = r.byte()
    info["name"] = r.string()
    info["map"] = r.string()
    info["folder"] = r.string()
    info["game"] = r.string()
    info["app_id"] = r.short()
    info["players"] = r.byte()
    info["max_players"] = r.byte()
    info["bots"] = r.byte()
    info["server_type"] = chr(r.byte())
    info["environment"] = chr(r.byte())
    info["visibility"] = r.byte()
    info["vac"] = r.byte()
    info["version"] = r.string() if r.remaining else ""

    # EDF 扩展字段（0x80 port / 0x10 steamid / 0x40 sourcetv / 0x20 tags / 0x01 gameid）
    if r.remaining:
        edf = r.byte()
        info["edf"] = edf
        if edf & 0x80 and r.remaining >= 2:
            info["game_port"] = r.ushort()
        if edf & 0x10 and r.remaining >= 8:
            info["steam_id"] = struct.unpack_from("<Q", r.buf, r.pos)[0]
            r.pos += 8
        if edf & 0x40 and r.remaining >= 2:
            info["source_tv_port"] = r.ushort()
            info["source_tv_name"] = r.string()
        if edf & 0x20 and r.remaining:
            info["tags"] = r.string()
        if edf & 0x01 and r.remaining >= 8:
            info["game_id"] = struct.unpack_from("<Q", r.buf, r.pos)[0]
            r.pos += 8

    return info


def _parse_players(body: bytes) -> list[dict]:
    if not body or body[0] != S2A_PLAYER:
        kind = body[0] if body else 0
        raise A2SProtocolError(f"非 A2S_PLAYER 响应（0x{kind:02X}）")
    r = _Reader(body)
    r.byte()
    count = r.byte()
    players: list[dict] = []
    for _ in range(count):
        if r.remaining <= 0:
            break
        idx = r.byte()
        name = r.string()
        if r.remaining < 8:
            players.append({"index": idx, "name": name, "score": 0, "duration": 0.0})
            break
        players.append({
            "index": idx,
            "name": name,
            "score": r.long(),
            "duration": round(r.float(), 1),
        })
    return players


def _parse_rules(body: bytes) -> dict[str, str]:
    if not body or body[0] != S2A_RULES:
        kind = body[0] if body else 0
        raise A2SProtocolError(f"非 A2S_RULES 响应（0x{kind:02X}）")
    r = _Reader(body)
    r.byte()
    rules: dict[str, str] = {}
    try:
        count = r.ushort()
    except A2SProtocolError:
        return rules
    for _ in range(count):
        if r.remaining <= 0:
            break
        key = r.string()
        value = r.string()
        if key:
            rules[key] = value
    return rules


# ---------------------------------------------------------------- 便利函数


def gamemode_of(info: dict, rules: dict[str, str] | None = None) -> str:
    """按原启动器 ResolveMode 的顺序推断 gamemode。"""
    if rules:
        for key in ("gmod_gamemode", "gamemode", "gm", "game_mode", "mode"):
            v = rules.get(key)
            if v and v.strip():
                return v.strip()
    tags = (info.get("tags") or "").strip()
    for token in tags.split():
        for key in ("gm:", "gamemode:"):
            if token.lower().startswith(key):
                return token[len(key):].strip() or token
    return tags or info.get("folder") or "unknown"


def format_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


__all__ = [
    "ServerAddress", "parse_address", "A2SError", "A2STimeout", "A2SProtocolError",
    "query_info", "query_players", "query_rules", "query_all",
    "gamemode_of", "format_duration",
]
