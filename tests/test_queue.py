"""自动挤服的行为测试：满员等待 → 空位 → 启动；以及取消、并发、直接进。"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_server import MockServer
from neoprobe import a2s, launch, queue
from neoprobe.manager import QueryManager

FAKE_LAUNCH = {"ok": True, "action": "spawn", "command": "gmod.exe -steam +connect 1.2.3.4:27015",
               "message": "已启动 Garry's Mod", "pid": 4242}


class QueueWatcherTests(unittest.TestCase):
    def _server(self, players: int, max_players: int = 32) -> MockServer:
        srv = MockServer(players=players, max_players=max_players)
        srv.start()
        return srv

    def test_waits_while_full_then_launches(self):
        srv = self._server(players=32)
        try:
            with mock.patch.object(launch, "launch", return_value=dict(FAKE_LAUNCH)) as fake:
                w = queue.QueueWatcher(f"127.0.0.1:{srv.port}", interval=0.4,
                                       timeout=0.6, retries=1)
                w.start()
                time.sleep(0.9)
                snap = w.snapshot()
                self.assertTrue(snap["active"])
                self.assertFalse(snap["has_slot"])
                self.assertEqual(snap["players"], 32)
                self.assertGreaterEqual(snap["attempts"], 1)

                srv.players = 31          # 有人掉线
                deadline = time.time() + 5
                while time.time() < deadline and w.snapshot()["status"] == "watching":
                    time.sleep(0.1)
                snap = w.snapshot()

            self.assertEqual(snap["status"], "launched")
            self.assertFalse(snap["active"])
            self.assertTrue(snap["has_slot"])
            self.assertIn("message", snap)
            fake.assert_called_once()
            self.assertEqual(fake.call_args[0][0], f"127.0.0.1:{srv.port}")
        finally:
            srv.stop()

    def test_stop_cancels(self):
        srv = self._server(players=32)
        try:
            w = queue.QueueWatcher(f"127.0.0.1:{srv.port}", interval=0.4, timeout=0.6)
            w.start()
            time.sleep(0.4)
            w.stop()
            snap = w.snapshot()
            self.assertEqual(snap["status"], "cancelled")
            self.assertFalse(snap["active"])
        finally:
            srv.stop()

    def test_reserved_slot_hint(self):
        # 70 人上限、人数到 62 以上（且已满）时给预留位提示，与原启动器一致
        srv = self._server(players=70, max_players=70)
        try:
            w = queue.QueueWatcher(f"127.0.0.1:{srv.port}", interval=0.4, timeout=0.6)
            w.start()
            time.sleep(0.5)
            snap = w.snapshot()
            self.assertTrue(snap["reserved"])
            self.assertIn("预留位", snap["message"])
        finally:
            w.stop()
            srv.stop()

    def test_probe_failure_does_not_launch(self):
        # 指向一个没有监听者的端口：应当只是记错误，绝不能误判成"有空位"
        with mock.patch.object(launch, "launch", return_value=dict(FAKE_LAUNCH)) as fake:
            w = queue.QueueWatcher("127.0.0.1:1", interval=0.3, timeout=0.3, retries=1)
            w.start()
            time.sleep(1.0)
            w.stop()
            snap = w.snapshot()
        self.assertEqual(snap["status"], "cancelled")
        self.assertFalse(snap["has_slot"])
        self.assertTrue(snap["last_error"])
        fake.assert_not_called()

    def test_drops_counted(self):
        srv = self._server(players=30)
        try:
            w = queue.QueueWatcher(f"127.0.0.1:{srv.port}", interval=0.35, timeout=0.6)
            w.start()
            deadline = time.time() + 3
            while time.time() < deadline and w.snapshot()["attempts"] < 1:
                time.sleep(0.05)
            srv.players = 28
            time.sleep(0.9)
            self.assertGreaterEqual(w.snapshot()["drops"], 1)
        finally:
            w.stop()
            srv.stop()


class ManagerQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_server_enters_queue(self):
        srv = MockServer(players=32)
        srv.start()
        try:
            mgr = QueryManager(self.data_dir, timeout=0.6, samples=1)
            try:
                res = mgr.start_queue(f"127.0.0.1:{srv.port}", interval=0.4)
                self.assertTrue(res["ok"])
                self.assertFalse(res["launched"])
                self.assertEqual(res["queue"]["status"], "watching")
                self.assertTrue(mgr.snapshot()["queue"]["active"])
            finally:
                mgr.stop()
        finally:
            srv.stop()

    def test_slot_available_launches_immediately(self):
        srv = MockServer(players=3)
        srv.start()
        try:
            mgr = QueryManager(self.data_dir, timeout=0.6, samples=1)
            try:
                with mock.patch.object(launch, "launch", return_value=dict(FAKE_LAUNCH)) as fake:
                    res = mgr.start_queue(f"127.0.0.1:{srv.port}")
                self.assertTrue(res["ok"])
                self.assertTrue(res["launched"])
                fake.assert_called_once()
                self.assertIsNone(res["queue"])
            finally:
                mgr.stop()
        finally:
            srv.stop()

    def test_second_queue_rejected(self):
        srv = MockServer(players=32)
        srv.start()
        try:
            mgr = QueryManager(self.data_dir, timeout=0.6, samples=1)
            try:
                first = mgr.start_queue(f"127.0.0.1:{srv.port}", interval=0.5)
                self.assertTrue(first["ok"])
                second = mgr.start_queue("127.0.0.1:29999")
                self.assertFalse(second["ok"])
                self.assertIn("已有排队", second["error"])
                self.assertTrue(second["queue"]["active"])
            finally:
                mgr.stop()
        finally:
            srv.stop()

    def test_stop_queue(self):
        srv = MockServer(players=32)
        srv.start()
        try:
            mgr = QueryManager(self.data_dir, timeout=0.6, samples=1)
            try:
                mgr.start_queue(f"127.0.0.1:{srv.port}", interval=0.5)
                res = mgr.stop_queue()
                self.assertEqual(res["queue"]["status"], "cancelled")
                self.assertFalse(mgr.snapshot()["queue"]["active"])
            finally:
                mgr.stop()
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
