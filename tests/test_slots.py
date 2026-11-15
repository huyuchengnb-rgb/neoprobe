"""空位观测：挤服的数据基础。

要点：人数满员时，光看"人数"这个数字看不出有人在走（位置会被秒补），
必须比对玩家名单。这里的用例就是钉住"名单差异 → 空位事件 → 节奏统计"这条链。
"""

import unittest

from neoprobe import slots


def _feed_names(t, names, players=70):
    t.feed(1000.0 + t._offset, names, players)  # noqa: SLF001


class SlotTrackerTest(unittest.TestCase):
    def setUp(self):
        self.t = slots.SlotTracker("k", "1.2.3.4:27015")

    def test_first_sample_records_no_event(self):
        self.t.feed(1000.0, ["a", "b"], 70)
        self.assertEqual(len(self.t.events), 0)

    def test_departure_is_detected_even_when_count_stays_full(self):
        """70 人满员 → 有人走、位置被秒补：人数没变，但名单能看出来。"""
        self.t.feed(1000.0, ["a", "b", "c"], 70)
        self.t.feed(1020.0, ["a", "b", "d"], 70)   # c 走了，d 补上
        self.assertEqual(len(self.t.events), 1)
        ts, left, joined, players = self.t.events[0]
        self.assertEqual((left, joined, players), (1, 1, 70))

    def test_stats_after_two_details(self):
        self.t.feed(1000.0, ["a", "b", "c"], 70)
        self.t.feed(1040.0, ["a", "b"], 69)          # 走了 c
        self.t.feed(1060.0, ["a", "b", "d"], 70)     # c 的位置被 d 补上
        self.t.feed(1120.0, ["a"], 68)               # 又走两个
        st = self.t.stats(1140.0)
        self.assertIsNotNone(st)
        self.assertEqual(st["free_events"], 2)
        self.assertEqual(st["freed_players"], 3)
        self.assertAlmostEqual(st["since_last_free"], 20.0)
        self.assertAlmostEqual(st["avg_gap"], 80.0)

    def test_no_departures_still_returns_zero_counts(self):
        self.t.feed(1000.0, ["a", "b"], 70)
        self.t.feed(1020.0, ["a", "b"], 70)
        st = self.t.stats(1030.0)
        self.assertEqual(st["free_events"], 0)
        self.assertIsNone(st["last_free_at"])

    def test_single_sample_is_not_enough(self):
        self.t.feed(1000.0, ["a"], 70)
        self.assertIsNone(self.t.stats(1001.0))

    def test_eta_never_negative(self):
        # 需要至少两次空位才能算出间隔，否则 eta 只能是 None（样本不足）
        self.t.feed(1000.0, ["a", "b"], 70)
        self.t.feed(1030.0, ["a"], 69)        # 走 b
        self.t.feed(1060.0, ["a", "b"], 70)   # 补回来
        self.t.feed(1090.0, ["a"], 69)        # 又走 b
        st = self.t.stats(1200.0)             # 距上次空位 110 秒，已超过平均间隔
        self.assertEqual(st["avg_gap"], 60.0)
        self.assertEqual(st["eta"], 0.0)

    def test_burst_period_needs_stable_rhythm(self):
        # 每 600 秒一次集体退服（走 10 人），节奏稳定 → 应被识别为周期
        t = self.t
        t.feed(1000.0, [f"p{i}" for i in range(20)], 70)
        base = [f"p{i}" for i in range(20)]
        ts = 1000.0
        for k in range(4):
            ts += 600
            staying = base[:10] if k % 2 == 0 else [f"q{k}{i}" for i in range(10)]
            t.feed(ts, staying + [f"q{k}{i}" for i in range(10)], 70)
        st = t.stats(ts + 10)
        self.assertIsNotNone(st)
        self.assertGreaterEqual(st["bursts"], 2)
        self.assertIsNotNone(st["burst_period"])
        self.assertAlmostEqual(st["burst_period"], 600.0, delta=1.0)

    def test_failure_is_recorded_not_fatal(self):
        self.t.fail("timeout")
        self.assertEqual(self.t.poll_fail, 1)
        self.assertEqual(self.t.last_error, "timeout")


if __name__ == "__main__":
    unittest.main()
