"""回合状态与启动逻辑的自测（不联网、不启动游戏）。

运行：  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neoprobe import a2s, launch, rounds     # noqa: E402


class TestRoundsParse(unittest.TestCase):
    NOW = 1_700_000_000.0

    def payload(self, **over):
        item = {
            "server_name": "[CN]测试服",
            "ip": "1.2.3.4",
            "port": 27015,
            "rounds_left": 3,
            "round_time_left": 240,
            "round_phase": "回合中",
            "updated_at": 1_700_000_000 - 5,
        }
        item.update(over)
        return {"server_time": 1_700_000_000, "servers": [item]}

    def test_basic(self):
        res = rounds.parse_payload(self.payload(), now=self.NOW)
        self.assertTrue(res.ok)
        self.assertEqual(res.count, 1)
        st = res.statuses["1.2.3.4:27015"]
        self.assertEqual(st.phase, "回合中")
        self.assertEqual(st.rounds_left, 3)
        # server_time - updated_at = 5 秒，要补偿掉
        self.assertEqual(st.time_left, 235)
        self.assertEqual(st.remaining(now=self.NOW), 235)

    def test_countdown_interpolation(self):
        st = rounds.parse_payload(self.payload(), now=self.NOW).statuses["1.2.3.4:27015"]
        self.assertEqual(st.remaining(now=self.NOW + 100), 135)
        self.assertEqual(st.remaining(now=self.NOW + 10_000), 0)   # 不会变负

    def test_negative_values(self):
        res = rounds.parse_payload(self.payload(rounds_left=-1, round_time_left=-1,
                                               round_phase="空闲"), now=self.NOW)
        st = res.statuses["1.2.3.4:27015"]
        self.assertIsNone(st.rounds_left)
        self.assertIsNone(st.time_left)
        self.assertIsNone(st.remaining())
        self.assertEqual(st.phase, "空闲")

    def test_english_phase_mapped(self):
        res = rounds.parse_payload(self.payload(round_phase="postround"), now=self.NOW)
        self.assertEqual(res.statuses["1.2.3.4:27015"].phase, "回合结束")

    def test_unknown_phase_passthrough(self):
        res = rounds.parse_payload(self.payload(round_phase="自定义阶段"), now=self.NOW)
        self.assertEqual(res.statuses["1.2.3.4:27015"].phase, "自定义阶段")

    def test_skew_ignored_when_too_large(self):
        # updated_at 比 server_time 早了 10 分钟 → 不做补偿（避免把时间算成负数）
        res = rounds.parse_payload(self.payload(updated_at=1_700_000_000 - 600), now=self.NOW)
        self.assertEqual(res.statuses["1.2.3.4:27015"].time_left, 240)

    def test_rate_limit(self):
        res = rounds.parse_payload({"error": "rate limit exceeded", "retry_after": 1}, now=self.NOW)
        self.assertFalse(res.ok)
        self.assertEqual(res.retry_after, 1.0)
        self.assertIn("rate limit", res.error)

    def test_bad_payloads(self):
        for bad in ({"foo": 1}, {"servers": "nope"}, [], None):
            with self.subTest(bad=bad):
                res = rounds.parse_payload(bad, now=self.NOW)
                self.assertFalse(res.ok)

    def test_skips_invalid_entries(self):
        data = {"server_time": 1_700_000_000, "servers": [
            {"ip": "", "port": 1},
            {"ip": "1.1.1.1", "port": 0},
            {"ip": "2.2.2.2", "port": 27015, "rounds_left": 1, "round_time_left": 10,
             "round_phase": "round", "updated_at": 1_700_000_000},
        ]}
        res = rounds.parse_payload(data, now=self.NOW)
        self.assertEqual(res.count, 1)
        self.assertIn("2.2.2.2:27015", res.statuses)

    def test_key_case_insensitive(self):
        self.assertEqual(rounds.build_key("A.B.C.D", 27015), rounds.build_key("a.b.c.d", 27015))

    def test_format_clock(self):
        self.assertEqual(rounds.format_clock(95), "01:35")
        self.assertEqual(rounds.format_clock(0), "00:00")
        self.assertEqual(rounds.format_clock(None), "—")
        self.assertEqual(rounds.format_clock(-1), "—")
        self.assertEqual(rounds.format_clock(3725), "1:02:05")


class TestLaunch(unittest.TestCase):
    def test_connect_target(self):
        self.assertEqual(launch.build_connect_target("1.2.3.4:27015"), "1.2.3.4:27015")
        self.assertEqual(launch.build_connect_target("1.2.3.4"), "1.2.3.4:27015")
        self.assertEqual(launch.build_connect_target("[::1]:27015"), "[::1]:27015")

    def test_steam_url(self):
        url = launch.build_steam_rungame_url("1.2.3.4:27015")
        self.assertTrue(url.startswith("steam://rungame/4000/"))
        self.assertTrue(url.endswith("+connect 1.2.3.4:27015"))

    def test_game_argv(self):
        argv = launch.build_game_argv(r"D:\GM\gmod.exe", "1.2.3.4:27015")
        self.assertEqual(argv[1:], ["-steam", "-game", "garrysmod", "+connect", "1.2.3.4:27015"])

    def test_resolve_gmod_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GarrysMod"
            (root / "garrysmod").mkdir(parents=True)
            (root / "gmod.exe").write_bytes(b"MZ")
            (root / "gmod_win64.exe").write_bytes(b"MZ")
            (root / "bin" / "win64").mkdir(parents=True)

            # 目录 / 32 位 exe / bin\win64 目录 都要能归一
            self.assertTrue(launch.resolve_gmod(str(root)).endswith("gmod_win64.exe"))
            self.assertTrue(launch.resolve_gmod(str(root / "gmod.exe")).endswith("gmod.exe"))
            self.assertTrue(launch.resolve_gmod(str(root / "bin" / "win64")).endswith("gmod_win64.exe"))
            # 没有 garrysmod 子目录 → 拒绝
            empty = Path(tmp) / "NotGmod"
            empty.mkdir()
            (empty / "gmod.exe").write_bytes(b"MZ")
            self.assertEqual(launch.resolve_gmod(str(empty)), "")
            # 不存在的路径
            self.assertEqual(launch.resolve_gmod(str(Path(tmp) / "nope")), "")
            self.assertEqual(launch.resolve_gmod(""), "")

    def test_launch_dry_run_uses_resolved_path(self):
        # 固定进程快照：否则机器上真开着 Steam/GMod 时结果会变（这里要测的是 spawn 分支）
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(launch, "_process_names", return_value=set()), \
                mock.patch.object(launch, "find_gmod", return_value=""):
            root = Path(tmp) / "GarrysMod"
            (root / "garrysmod").mkdir(parents=True)
            (root / "gmod.exe").write_bytes(b"MZ")

            res = launch.launch("1.2.3.4:27015", configured_gmod=str(root), dry_run=True)
            self.assertTrue(res["ok"])
            self.assertEqual(res["action"], "spawn")
            self.assertIn("+connect", res["command"])
            self.assertIn("1.2.3.4:27015", res["command"])

    def test_launch_missing_game(self):
        # 屏蔽 Steam 库回退，确定性地走到"找不到游戏"分支
        with mock.patch.object(launch, "_process_names", return_value=set()), \
                mock.patch.object(launch, "find_gmod", return_value=""), \
                mock.patch.object(launch, "find_steam_exe", return_value=""):
            res = launch.launch(None, configured_gmod="", dry_run=True)
        self.assertFalse(res["ok"])
        self.assertEqual(res["action"], "noop")
        self.assertIn("Garry", res["error"])

    def test_launch_falls_back_to_steam_library(self):
        # 配置为空时应当回退到 Steam 库自动定位
        with mock.patch.object(launch, "_process_names", return_value=set()), \
                mock.patch.object(launch, "find_gmod", return_value=r"D://Lib//GarrysMod//gmod.exe"):
            res = launch.launch("1.2.3.4:27015", configured_gmod="", dry_run=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["action"], "spawn")
        self.assertIn("gmod.exe", res["command"])

    def test_process_snapshot(self):
        names = launch._process_names()
        if sys.platform == "win32":
            self.assertIsInstance(names, set)
            # 至少能看到当前 python 进程
            self.assertTrue(any("python" in n for n in names) or names)


class TestAddressForLaunch(unittest.TestCase):
    """启动用的地址解析要和查询保持一致。"""

    def test_same_key(self):
        for raw in ("1.2.3.4:27015", "1.2.3.4", "steam://connect/1.2.3.4:27015"):
            with self.subTest(raw=raw):
                self.assertEqual(a2s.parse_address(raw).key, "1.2.3.4:27015")


if __name__ == "__main__":
    unittest.main(verbosity=2)
