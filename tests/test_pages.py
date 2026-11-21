"""Tests for the GitHub Pages static site & snapshot builder."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from neoprobe import a2s, rounds, server
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


class _DummyManager:
    def stamp(self):
        return (1, 0, (0, 0), 0)

    def snapshot(self):
        return {"servers": [], "rounds_meta": {}, "client_meta": {}, "game": {}, "queue": None, "vip": {}}


class ServerCorsTest(unittest.TestCase):
    def test_cors_allows_configured_origin_and_pna_only(self):
        api = server.Api(_DummyManager())
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(
            api, cors_origins=["https://huyuchengnb-rgb.github.io"],
        ))
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("OPTIONS", "/api/queue", headers={
                "Origin": "https://huyuchengnb-rgb.github.io",
                "Access-Control-Request-Private-Network": "true",
            })
            r1 = conn.getresponse()
            r1.read()
            self.assertEqual(r1.status, 204)
            self.assertEqual(r1.getheader("Access-Control-Allow-Origin"), "https://huyuchengnb-rgb.github.io")
            self.assertEqual(r1.getheader("Access-Control-Allow-Private-Network"), "true")

            conn.request("OPTIONS", "/api/queue", headers={"Origin": "https://evil.example"})
            r2 = conn.getresponse()
            r2.read()
            self.assertEqual(r2.status, 403)
            self.assertIsNone(r2.getheader("Access-Control-Allow-Origin"))
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


class LocalWebIntegrationTest(unittest.TestCase):
    def test_serves_index_goc_and_range_audio(self):
        api = server.Api(_DummyManager())
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(api))
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)

            conn.request("GET", "/")
            r_idx = conn.getresponse()
            idx_html = r_idx.read().decode("utf-8")
            self.assertEqual(r_idx.status, 200)
            self.assertIn('id="tab-goc"', idx_html)
            self.assertIn('id="tab-rx"', idx_html)
            self.assertIn('id="goc-frame"', idx_html)
            self.assertIn("https://rx.l1ght.xyz", idx_html)

            conn.request("GET", "/goc.html?embed=1")
            r_goc = conn.getresponse()
            goc_html = r_goc.read().decode("utf-8")
            self.assertEqual(r_goc.status, 200)
            self.assertIn("GOC 奇术终端", goc_html)
            self.assertIn("./assets/goc-yuai.mp3", goc_html)

            conn.request("GET", "/favicon.png")
            r_fav = conn.getresponse()
            fav_bytes = r_fav.read()
            self.assertEqual(r_fav.status, 200)
            self.assertEqual(r_fav.getheader("Content-Type"), "image/png")
            self.assertGreater(len(fav_bytes), 100)

            conn.request("GET", "/assets/goc-yuai.mp3", headers={"Range": "bytes=0-15"})
            r_mp3 = conn.getresponse()
            chunk = r_mp3.read()
            self.assertEqual(r_mp3.status, 206)
            self.assertEqual(r_mp3.getheader("Content-Type"), "audio/mpeg")
            self.assertEqual(r_mp3.getheader("Accept-Ranges"), "bytes")
            self.assertTrue((r_mp3.getheader("Content-Range") or "").startswith("bytes 0-15/"))
            self.assertEqual(len(chunk), 16)

            conn.request("GET", "/assets/../server.py")
            r_bad = conn.getresponse()
            r_bad.read()
            self.assertEqual(r_bad.status, 403)
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
