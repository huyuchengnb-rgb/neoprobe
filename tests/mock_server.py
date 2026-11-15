"""一个极简的模拟 Source 服务器，用于在没有外网的情况下验证 A2S 实现。

故意把所有难点都打开：
  * 强制 challenge 握手（现代 Source 就是这样）
  * 分包响应（3 个包）
  * bzip2 压缩分包（带 size / uncompressed_size / crc32 头）
  * 带 EDF 扩展字段（port / steamid / tags / gameid）
"""

from __future__ import annotations

import bz2
import socket
import struct
import threading
import zlib

SINGLE = b"\xff\xff\xff\xff"
SPLIT = b"\xfe\xff\xff\xff"

CHALLENGE = 0x11223344


def _cstr(s: str) -> bytes:
    return s.encode("utf-8") + b"\x00"


def build_info(challenge_ok: bool = True, players: int = 7, max_players: int = 32) -> bytes:
    body = b"I"
    body += bytes([17])                     # protocol
    body += _cstr("Test GMod Server 测试服")
    body += _cstr("ttt_minecraft_b5")
    body += _cstr("garrysmod")
    body += _cstr("Garry's Mod")
    body += struct.pack("<h", 4000)         # appid
    body += bytes([max(0, min(255, players)), max(0, min(255, max_players)), 1])  # players / max / bots
    body += b"d"                            # dedicated
    body += b"l"                            # linux
    body += bytes([0])                      # visibility
    body += bytes([1])                      # vac
    body += _cstr("2024.01.01")
    edf = 0x80 | 0x10 | 0x20 | 0x01
    body += bytes([edf])
    body += struct.pack("<H", 27015)        # port
    body += struct.pack("<Q", 90071996842377216)  # steamid
    body += _cstr("gm:ttt gm:darkrp tag2")  # tags
    body += struct.pack("<Q", 4000)         # gameid
    return body


def build_players() -> bytes:
    rows = [(0, "Alice", 15, 620.0), (1, "鲍勃", -3, 61.5), (2, "Charlie", 0, 5.0)]
    body = b"D" + bytes([len(rows)])
    for idx, name, score, dur in rows:
        body += bytes([idx]) + _cstr(name) + struct.pack("<i", score) + struct.pack("<f", dur)
    return body


def build_rules() -> bytes:
    rules = {
        "gmod_gamemode": "ttt",
        "sv_cheats": "0",
        "ttt_postroundtime": "8",
        "中文键": "中文值",
        "very_long_key_name_for_testing": "x" * 120,
    }
    body = b"E" + struct.pack("<H", len(rules))
    for k, v in rules.items():
        body += _cstr(k) + _cstr(v)
    return body


def split_packets(payload: bytes, total: int = 3, compressed: bool = False,
                  size_field: bool = False, keep_prefix: bool = True,
                  chunk_size: int | None = None) -> list[bytes]:
    """把完整响应切成 total 个分包。

    size_field   : 在头部额外写 uint16 size（部分实现这么做，头变成 12 字节）
    keep_prefix  : 重组后的载荷是否保留 FF FF FF FF 单包头
    compressed   : 每个分片独立 bzip2 压缩，头部再加 size/uncompressed_size/crc32
    """
    if keep_prefix:
        payload = SINGLE + payload
    if chunk_size is None:
        chunk_size = (len(payload) + total - 1) // total
    chunks = [payload[i * chunk_size:(i + 1) * chunk_size] for i in range(total)]

    out = []
    for i, chunk in enumerate(chunks):
        if compressed:
            comp = bz2.compress(chunk)
            head = (SPLIT + struct.pack("<I", 0xFFFFFFFE)
                    + bytes([total, i]) + struct.pack("<H", 1248)
                    + struct.pack("<i", len(chunk)) + struct.pack("<I", zlib.crc32(chunk)))
            out.append(head + comp)
        else:
            head = SPLIT + struct.pack("<i", 0x0BADF00D) + bytes([total, i])
            if size_field:
                head += struct.pack("<H", 1248)
            out.append(head + chunk)
    return out



class MockServer(threading.Thread):
    def __init__(self, split: bool = False, compressed: bool = False,
                 require_challenge: bool = True, silent: bool = False,
                 size_field: bool = True, keep_prefix: bool = True,
                 players: int = 7, max_players: int = 32) -> None:
        super().__init__(daemon=True)
        self.players = players
        self.max_players = max_players
        self.split = split
        self.compressed = compressed
        self.size_field = size_field
        self.keep_prefix = keep_prefix
        self.require_challenge = require_challenge
        self.silent = silent
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self.requests = 0

    def run(self) -> None:
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                data, peer = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self.requests += 1
            if self.silent:
                continue
            try:
                self._handle_packet(data, peer)
            except OSError:
                break

    def _send(self, payload: bytes, peer) -> None:
        if not self.split:
            self.sock.sendto(SINGLE + payload, peer)
            return
        for pkt in split_packets(payload, 3, self.compressed,
                                 self.size_field, self.keep_prefix):
            self.sock.sendto(pkt, peer)

    def _handle_packet(self, data: bytes, peer) -> None:
        if len(data) < 5 or data[:4] != SINGLE:
            return
        kind = data[4]

        if kind == 0x54:  # A2S_INFO
            has_challenge = len(data) >= 29
            if self.require_challenge:
                if not has_challenge:
                    self.sock.sendto(SINGLE + b"A" + struct.pack("<i", CHALLENGE), peer)
                    return
                if struct.unpack_from("<i", data, 25)[0] != CHALLENGE:
                    self.sock.sendto(SINGLE + b"A" + struct.pack("<i", CHALLENGE), peer)
                    return
            self._send(build_info(players=self.players, max_players=self.max_players), peer)
            return

        if kind == 0x55:  # A2S_PLAYER
            if len(data) >= 9 and struct.unpack_from("<i", data, 5)[0] == CHALLENGE:
                self._send(build_players(), peer)
            else:
                self.sock.sendto(SINGLE + b"A" + struct.pack("<i", CHALLENGE), peer)
            return

        if kind == 0x56:  # A2S_RULES
            if len(data) >= 9 and struct.unpack_from("<i", data, 5)[0] == CHALLENGE:
                self._send(build_rules(), peer)
            else:
                self.sock.sendto(SINGLE + b"A" + struct.pack("<i", CHALLENGE), peer)
            return

    def stop(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
