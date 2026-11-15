"""服务器目录（server_catalog.php）解析。

新版启动器 1.0.0.87 把服务器列表改成在线更新，走的就是这个接口；
面板据此同步列表，避免"官方列表变了、面板还是旧的"。
"""

import unittest

from neoprobe import rounds

SAMPLE = {
    "schema_version": 1,
    "servers": [
        {"name": "[CN]Neo RXBreach 娘娘测试服", "ip": "202.189.21.228", "port": 27076,
         "category": "奶龙", "expected_mode": "scp_plus+", "expected_round_rule": "round",
         "visible_to_steam_ids": []},
        {"name": "私密服", "ip": "202.189.21.228", "port": 29999,
         "visible_to_steam_ids": ["76561198000000000"]},
        {"name": "坏端口", "ip": "1.2.3.4", "port": 0},
        {"ip": "", "port": 27015},
    ],
}


class CatalogUrlTest(unittest.TestCase):
    def test_derive_from_status_php(self):
        self.assertEqual(rounds.catalog_url("https://x/status.php"),
                         "https://x/server_catalog.php")

    def test_no_status_php_no_catalog(self):
        self.assertEqual(rounds.catalog_url("https://x/rounds.json"), "")
        self.assertEqual(rounds.catalog_url(""), "")


class ParseCatalogTest(unittest.TestCase):
    def test_skips_invalid_entries(self):
        items = rounds.parse_catalog(SAMPLE)
        self.assertEqual([i["address"] for i in items], ["202.189.21.228:27076",
                                                         "202.189.21.228:29999"])

    def test_fields(self):
        item = rounds.parse_catalog(SAMPLE)[0]
        self.assertEqual(item["name"], "[CN]Neo RXBreach 娘娘测试服")
        self.assertEqual(item["mode"], "scp_plus+")
        self.assertEqual(item["round_rule"], "round")

    def test_visibility_list(self):
        items = rounds.parse_catalog(SAMPLE)
        self.assertEqual(items[0]["visible_to"], [])
        self.assertEqual(items[1]["visible_to"], ["76561198000000000"])

    def test_garbage_input(self):
        self.assertEqual(rounds.parse_catalog(None), [])
        self.assertEqual(rounds.parse_catalog({"servers": "x"}), [])


class PayloadTest(unittest.TestCase):
    """status.php 现在会同时给多台服的真实回合（兑换服则是 -1 + 空闲）。"""

    def test_three_rounds_one_idle(self):
        data = {
            "server_time": 1000,
            "servers": [
                {"ip": "1.1.1.1", "port": 27015, "rounds_left": 8,
                 "round_time_left": 230, "round_phase": "回合中", "updated_at": 999},
                {"ip": "1.1.1.1", "port": 31284, "rounds_left": -1,
                 "round_time_left": -1, "round_phase": "空闲", "updated_at": 999},
            ],
        }
        res = rounds.parse_payload(data, now=1000.0)
        a = res.statuses["1.1.1.1:27015"]
        self.assertEqual(a.rounds_left, 8)
        self.assertEqual(a.time_left, 229)      # 补偿了 1 秒
        self.assertEqual(a.phase, "回合中")

        b = res.statuses["1.1.1.1:31284"]
        self.assertIsNone(b.rounds_left)
        self.assertIsNone(b.time_left)
        self.assertEqual(b.phase, "空闲")


if __name__ == "__main__":
    unittest.main()
