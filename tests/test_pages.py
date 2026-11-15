"""Tests for the GitHub Pages static site & snapshot builder."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from neoprobe import a2s, rounds
from tools import build_pages


class MergeServersTest(unittest.TestCase):
    def test_merges_public_catalog_and_skips_private(self):
        base = [{"address": "1.1.1.1:27015", "label": "Server A"}]
        cat = [
            {"address": "1.1.1.1:27015", "name": "Ignored Override", "visible_to": []},
            {"address": "2.2.2.2:27016", "name": "Server B", "visible_to": []},
            {"address": "3.3.3.3:27017", "name": "Private", "visible_to": ["76561198000000000"]},
            {"address": "1.2.3.4:abc", "name": "Bad", "visible_to": []},
        ]
        merged = build_pages.merge_servers(base, cat)
        self.assertEqual(
            merged,
            [
                {"address": "1.1.1.1:27015", "label": "Server A"},
                {"address": "2.2.2.2:27016", "label": "Server B"},
            ],
        )


class CollectSnapshotTest(unittest.TestCase):
    def test_collects_online_offline_and_rounds(self):
        servers = [
            {"address": "1.1.1.1:27015", "label": "Alpha"},
            {"address": "2.2.2.2:27016", "label": "Beta"},
        ]

        def fake_query(addr: str) -> dict:
            if addr.startswith("2.2.2.2"):
                raise a2s.A2STimeout("timeout")
            return {
                "address": addr,
                "info": {"name": "Alpha Real", "map": "gm_test", "players": 42, "max_players": 70, "rtt_ms": 18.5},
                "players": [{"index": 0, "name": "Alice", "score": 3, "duration": 120.0}],
                "rules": {"br_time_round": "1080"},
            }

        def fake_rounds(_url: str) -> rounds.FetchResult:
            st = rounds.RoundStatus(
                key="1.1.1.1:27015",
                phase="回合中",
                rounds_left=5,
                time_left=300,
                synced_at=1000.0,
                updated_at=999,
            )
            return rounds.FetchResult(statuses={"1.1.1.1:27015": st}, ok=True, fetched_at=1000.0)

        snap = build_pages.collect_snapshot(
            servers=servers,
            rounds_url="https://example.invalid/status.php",
            query_fn=fake_query,
            rounds_fn=fake_rounds,
            catalog_fn=lambda _u: ([], None),
        )

        self.assertEqual(snap["count"], 2)
        self.assertEqual(snap["online"], 1)
        self.assertEqual(snap["total_players"], 42)
        self.assertTrue(snap["rounds_meta"]["ok"])

        a, b = snap["servers"]
        self.assertEqual(a["state"], "ok")
        self.assertEqual(a["rtt_ms"], 18.5)
        self.assertEqual(a["rounds"]["rounds_left"], 5)
        self.assertEqual(a["rounds"]["timer"], "countdown")
        self.assertEqual(b["state"], "error")
        self.assertIn("timeout", b["error"])
        self.assertIsNone(b["rounds"])

    def test_build_site_writes_bundle(self):
        snap = {"schema_version": 1, "count": 0, "online": 0, "total_players": 0, "servers": []}
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "_site"
            state_path = build_pages.build_site(out, snap)
            self.assertTrue((out / "index.html").is_file())
            self.assertTrue((out / ".nojekyll").is_file())
            self.assertTrue(state_path.is_file())
            loaded = json.loads(state_path.read_text("utf-8"))
            self.assertEqual(loaded["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
