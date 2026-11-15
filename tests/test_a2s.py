"""A2S 实现自测：不依赖外网，用 tests/mock_server.py 模拟真实服务器行为。

运行：  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_server import MockServer            # noqa: E402
from neoprobe import a2s                      # noqa: E402


class TestAddress(unittest.TestCase):
    def test_variants(self):
        cases = {
            "1.2.3.4:27015": ("1.2.3.4", 27015),
            "1.2.3.4": ("1.2.3.4", 27015),
            "example.com:27016": ("example.com", 27016),
            "steam://connect/1.2.3.4:27015": ("1.2.3.4", 27015),
            "steam://connect/1.2.3.4:27015/extra": ("1.2.3.4", 27015),
            "  [2001:db8::1]:27015  ": ("2001:db8::1", 27015),
            "[::1]": ("::1", 27015),
            "a2s://5.6.7.8:27020": ("5.6.7.8", 27020),
        }
        for raw, (host, port) in cases.items():
            with self.subTest(raw=raw):
                addr = a2s.parse_address(raw)
                self.assertEqual((addr.host, addr.port), (host, port))

    def test_invalid(self):
        for raw in ("", "1.2.3.4:abc", "[::1"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                a2s.parse_address(raw)

    def test_str_roundtrip(self):
        self.assertEqual(str(a2s.parse_address("[::1]:27015")), "[::1]:27015")
        self.assertEqual(str(a2s.parse_address("1.2.3.4:27015")), "1.2.3.4:27015")


class TestQuery(unittest.TestCase):
    def _addr(self, srv: MockServer) -> a2s.ServerAddress:
        return a2s.ServerAddress("127.0.0.1", srv.port)

    def test_info_with_challenge(self):
        srv = MockServer()
        srv.start()
        try:
            info = a2s.query_info(self._addr(srv), timeout=1.0, samples=1)
        finally:
            srv.stop()
        self.assertEqual(info["name"], "Test GMod Server 测试服")
        self.assertEqual(info["map"], "ttt_minecraft_b5")
        self.assertEqual(info["players"], 7)
        self.assertEqual(info["max_players"], 32)
        self.assertEqual(info["app_id"], 4000)
        self.assertEqual(info["vac"], 1)
        self.assertEqual(info["version"], "2024.01.01")
        # EDF 扩展
        self.assertEqual(info["game_port"], 27015)
        self.assertEqual(info["steam_id"], 90071996842377216)
        self.assertIn("gm:ttt", info["tags"])
        self.assertEqual(info["game_id"], 4000)
        self.assertGreater(info["rtt_ms"], 0)

    def test_info_split_all_layouts(self):
        """分包头的四种布局组合都要能正确重组。"""
        for size_field in (True, False):
            for keep_prefix in (True, False):
                with self.subTest(size_field=size_field, keep_prefix=keep_prefix):
                    srv = MockServer(split=True, size_field=size_field, keep_prefix=keep_prefix)
                    srv.start()
                    try:
                        info = a2s.query_info(self._addr(srv), timeout=1.5, samples=1)
                    finally:
                        srv.stop()
                    self.assertEqual(info["name"], "Test GMod Server 测试服")
                    self.assertEqual(info["map"], "ttt_minecraft_b5")

    def test_info_split_compressed(self):
        srv = MockServer(split=True, compressed=True)
        srv.start()
        try:
            info = a2s.query_info(self._addr(srv), timeout=2.0, samples=1)
        finally:
            srv.stop()
        self.assertEqual(info["map"], "ttt_minecraft_b5")
        self.assertEqual(info["players"], 7)

    def test_players(self):
        srv = MockServer()
        srv.start()
        try:
            players = a2s.query_players(self._addr(srv), timeout=1.5)
        finally:
            srv.stop()
        self.assertEqual(len(players), 3)
        self.assertEqual(players[0]["name"], "Alice")
        self.assertEqual(players[0]["score"], 15)
        self.assertAlmostEqual(players[0]["duration"], 620.0, places=1)
        self.assertEqual(players[1]["name"], "鲍勃")
        self.assertEqual(players[1]["score"], -3)

    def test_rules(self):
        srv = MockServer()
        srv.start()
        try:
            rules = a2s.query_rules(self._addr(srv), timeout=1.5)
        finally:
            srv.stop()
        self.assertEqual(rules["gmod_gamemode"], "ttt")
        self.assertEqual(rules["中文键"], "中文值")
        self.assertEqual(len(rules), 5)

    def test_query_all_shares_session(self):
        srv = MockServer()
        srv.start()
        try:
            result = a2s.query_all(self._addr(srv), timeout=1.5, samples=1,
                                   with_players=True, with_rules=True)
        finally:
            srv.stop()
        self.assertEqual(result["info"]["players"], 7)
        self.assertEqual(len(result["players"]), 3)
        self.assertEqual(result["rules"]["gmod_gamemode"], "ttt")
        self.assertNotIn("players_error", result)

    def test_timeout(self):
        srv = MockServer(silent=True)
        srv.start()
        try:
            with self.assertRaises(a2s.A2STimeout):
                a2s.query_info(self._addr(srv), timeout=0.25, samples=1)
        finally:
            srv.stop()

    def test_no_server(self):
        # 关闭的端口：应抛 A2SError 家族异常而不是卡死
        srv = MockServer()
        port = srv.port
        srv.stop()
        import time
        time.sleep(0.05)
        with self.assertRaises(a2s.A2SError):
            a2s.query_info(a2s.ServerAddress("127.0.0.1", port), timeout=0.3, samples=1)


class TestGamemode(unittest.TestCase):
    def test_from_rules(self):
        self.assertEqual(a2s.gamemode_of({}, {"gmod_gamemode": "darkrp"}), "darkrp")
        self.assertEqual(a2s.gamemode_of({"tags": "gm:ttt"}, {"gamemode": "sandbox"}), "sandbox")

    def test_from_tags(self):
        self.assertEqual(a2s.gamemode_of({"tags": "foo gm:ttt bar"}, {}), "ttt")
        self.assertEqual(a2s.gamemode_of({"tags": "darkrp"}, {}), "darkrp")

    def test_fallback(self):
        self.assertEqual(a2s.gamemode_of({"folder": "garrysmod"}, {}), "garrysmod")
        self.assertEqual(a2s.gamemode_of({}, {}), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
