"""身份 / VIP 解析测试：接口字段兼容、日期识别、本地账号解析。"""

import io
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neoprobe import vip

VDF = '''
"users"
{
	"76561198000000001"
	{
		"AccountName"		"older"
		"PersonaName"		"A"
		"MostRecent"		"0"
		"timestamp"		"1700000000"
	}
	"76561198000000002"
	{
		"AccountName"		"newer"
		"PersonaName"		"B"
		"MostRecent"		"1"
		"timestamp"		"1600000000"
	}
}
'''


class AddressTests(unittest.TestCase):
    def test_identity_url_from_status_php(self):
        self.assertEqual(vip.identity_url("https://x.live/status.php"),
                         "https://x.live/identity.php")
        self.assertEqual(vip.identity_url("https://x.live/"),
                         "https://x.live/identity.php")
        self.assertEqual(vip.identity_url("https://x.live/identity.php?steamid64=1"),
                         "https://x.live/identity.php?steamid64=1")
        self.assertEqual(vip.identity_url(""), "")

    def test_mask(self):
        self.assertEqual(vip.mask_id("76561199496556634"), "7656***6634")
        self.assertEqual(vip.mask_id(""), "—")


class LoginUsersTests(unittest.TestCase):
    def test_parse_prefers_most_recent(self):
        users = vip._parse_login_users(VDF)
        self.assertEqual(users[0][1], "76561198000000002")   # MostRecent 优先于时间戳

    def test_parse_by_timestamp(self):
        text = VDF.replace('"MostRecent"\t\t"1"', '"MostRecent"\t\t"0"')
        users = vip._parse_login_users(text)
        self.assertEqual(users[0][1], "76561198000000001")   # 取时间戳最大的

    def test_empty(self):
        self.assertEqual(vip._parse_login_users(""), [])


class ExpiryTests(unittest.TestCase):
    def test_date_field(self):
        ts, src = vip._extract_expiry({"vip_expire": "2026-12-01"})
        self.assertEqual(src, "vip_expire")
        self.assertEqual(time.strftime("%Y-%m-%d", time.localtime(ts)), "2026-12-01")

    def test_unix_timestamp(self):
        ts, src = vip._extract_expiry({"expires_at": 1798761600})
        self.assertIsNotNone(ts)
        self.assertEqual(src, "expires_at")

    def test_millisecond_timestamp(self):
        ts, _ = vip._extract_expiry({"vip_expire": 1798761600000})
        self.assertAlmostEqual(ts, 1798761600, delta=1)

    def test_days_left_field(self):
        ts, src = vip._extract_expiry({"days_left": 30})
        self.assertEqual(src, "days_left")
        self.assertAlmostEqual(ts - time.time(), 30 * 86400, delta=5)

    def test_nested(self):
        ts, src = vip._extract_expiry({"vip": {"expire_at": "2027-01-05"}})
        self.assertIn(src, ("vip.expire_at", "expire_at"))
        self.assertEqual(time.strftime("%Y-%m-%d", time.localtime(ts)), "2027-01-05")

    def test_zero_means_none(self):
        ts, src = vip._extract_expiry({"expire_at": 0, "days_left": None})
        self.assertIsNone(ts)
        self.assertEqual(src, "")

    def test_from_identity_text(self):
        ts, src = vip._extract_from_text("VIP 至 2026-12-01")
        self.assertEqual(time.strftime("%Y-%m-%d", time.localtime(ts)), "2026-12-01")
        ts, src = vip._extract_from_text("VIP(剩 30 天)")
        self.assertAlmostEqual(ts - time.time(), 30 * 86400, delta=5)
        self.assertEqual(vip._extract_from_text("VIP"), (None, ""))

    def test_days_left_rounding(self):
        now = time.time()
        self.assertEqual(vip.days_left(now + 10 * 86400, now), 10)
        self.assertEqual(vip.days_left(now + 10.5 * 86400, now), 11)  # 半天算作还剩 11 天
        self.assertEqual(vip.days_left(now - 86400, now), 0)         # 过期
        self.assertIsNone(vip.days_left(None))


class FetchTests(unittest.TestCase):
    def _mock(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return mock.patch("urllib.request.urlopen", return_value=Resp(body))

    def test_parse_real_payload(self):
        with self._mock({"steamid64": "76561199496556634", "is_admin": False,
                         "is_vip": True, "identity": "VIP"}):
            res = vip.fetch("https://x.live/status.php", "76561199496556634")
        self.assertTrue(res["ok"])
        self.assertTrue(res["is_vip"])
        self.assertEqual(res["identity"], "VIP")
        self.assertIsNone(res["days_left"])      # 服务端确实没给

    def test_missing_account(self):
        res = vip.fetch("https://x.live/status.php", "")
        self.assertFalse(res["ok"])
        self.assertIn("Steam", res["error"])

    def test_bad_json(self):
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch("urllib.request.urlopen", return_value=Resp(b"<html>")):
            res = vip.fetch("https://x.live/status.php", "76561199496556634")
        self.assertFalse(res["ok"])
        self.assertIn("JSON", res["error"])


if __name__ == "__main__":
    unittest.main()
