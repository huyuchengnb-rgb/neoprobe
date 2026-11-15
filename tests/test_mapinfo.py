"""换图观测：本面板能测到的、最接近"这局还剩多久"的信号。"""

import time
import unittest

from neoprobe.manager import Entry


class MapInfoTest(unittest.TestCase):
    def test_no_map_yet(self):
        self.assertIsNone(Entry("1.2.3.4:1").mapinfo())

    def test_since_only(self):
        e = Entry("1.2.3.4:1")
        e.map_now = "rx_a"
        e.map_since = time.time() - 300
        info = e.mapinfo()
        self.assertEqual(info["map"], "rx_a")
        self.assertAlmostEqual(info["since"], 300, delta=2)
        self.assertEqual(info["changes"], 0)
        self.assertIsNone(info["avg_duration"])

    def test_average_from_observed_spans(self):
        e = Entry("1.2.3.4:1")
        now = time.time()
        e.map_now = "rx_b"
        e.map_since = now - 100
        e.map_changes = [now - 1300, now - 700, now - 100]   # 两次间隔都是 600 秒
        info = e.mapinfo()
        self.assertEqual(info["spans"], 2)
        self.assertAlmostEqual(info["avg_duration"], 600, delta=2)

    def test_absurd_spans_ignored(self):
        e = Entry("1.2.3.4:1")
        now = time.time()
        e.map_now = "rx_b"
        e.map_since = now - 10
        e.map_changes = [now - 86400 * 3, now - 10]          # 隔了三天，不算节奏
        self.assertIsNone(e.mapinfo()["avg_duration"])


if __name__ == "__main__":
    unittest.main()
