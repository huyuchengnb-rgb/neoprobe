"""客户端回合探针的字段挑选逻辑。

这条链路是"回合数据"唯一真实来源（GMod 的 A2S 里没有回合状态），
所以挑选逻辑必须守住一条底线：**没有可信字段就返回 None**，绝不用配置值凑数。
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from neoprobe import clientstate


def _cand(k, v, t=None, src="nw:test"):
    return {"src": src, "k": k, "v": v, "t": t or ("number" if isinstance(v, (int, float)) else "string")}


class PickTest(unittest.TestCase):
    def test_end_time_is_converted_to_remaining(self):
        data = {"ts": 1000, "curtime": 5000.0, "cands": [_cand("RoundEndTime", 5300.0)]}
        got = clientstate.pick(data)
        self.assertIsNotNone(got)
        self.assertEqual(got["left"], 300)
        self.assertEqual(got["kind"], "endtime")

    def test_remaining_seconds_used_as_is(self):
        data = {"ts": 1000, "curtime": 5000.0, "cands": [_cand("round_timeleft", 42.0)]}
        self.assertEqual(clientstate.pick(data)["left"], 42)

    def test_config_limit_is_not_a_countdown(self):
        """br_time_round=1080 是每局上限，不是"还剩多久"——不能被当成倒计时。"""
        data = {"ts": 1000, "curtime": 5000.0,
                "cands": [_cand("br_time_round", 1080.0, src="cvar"),
                          _cand("ttt_round_limit", 8.0, src="cvar")]}
        self.assertIsNone(clientstate.pick(data))

    def test_start_time_is_not_a_countdown(self):
        data = {"ts": 1000, "curtime": 5000.0, "cands": [_cand("RoundStartTime", 4600.0)]}
        self.assertIsNone(clientstate.pick(data))

    def test_phase_only(self):
        data = {"ts": 1000, "curtime": 5000.0, "cands": [_cand("RoundState", "准备阶段")]}
        got = clientstate.pick(data)
        self.assertEqual(got["phase"], "准备阶段")
        self.assertIsNone(got["left"])

    def test_empty_candidates_give_none(self):
        self.assertIsNone(clientstate.pick({"ts": 1, "curtime": 1.0, "cands": []}))

    def test_absurd_values_rejected(self):
        """时间戳级别的数字（如 1.7e9）不是剩余秒数，不能显示。"""
        data = {"ts": 1000, "curtime": 5000.0, "cands": [_cand("round_time", 1.79e9)]}
        self.assertIsNone(clientstate.pick(data))


class FileTest(unittest.TestCase):
    def test_missing_file_is_none(self):
        self.assertIsNone(clientstate.read())

    def test_stale_file_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "neoprobe_rounds.json"
            p.write_text(json.dumps({"playing": True, "addr": "1.2.3.4:1", "cands": []}), encoding="utf-8")
            old = time.time() - 600
            os.utime(p, (old, old))
            orig = clientstate._data_dir
            clientstate._data_dir = lambda: str(p)  # type: ignore[assignment]
            try:
                self.assertIsNone(clientstate.read(max_age=30))
            finally:
                clientstate._data_dir = orig  # type: ignore[assignment]

    def test_addr_match(self):
        self.assertTrue(clientstate._same_addr("1.2.3.4:27015", "steam://connect/1.2.3.4:27015"))
        self.assertFalse(clientstate._same_addr("1.2.3.4:27015", "1.2.3.4:27016"))
        self.assertFalse(clientstate._same_addr("", "1.2.3.4:27015"))


if __name__ == "__main__":
    unittest.main()
