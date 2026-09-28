import unittest
from unittest.mock import Mock, patch

import requests

from sam_common import sam_search_with_retry, deadline_urgency_flag


class SamCommonTests(unittest.TestCase):
    def test_success(self):
        response = Mock(status_code=200)
        response.json.return_value = {"opportunitiesData": [{"noticeId": "x"}]}
        with patch("sam_common.requests.get", return_value=response) as get:
            result = sam_search_with_retry(
                "https://example.invalid", "secret", {"limit": 1}
            )
        self.assertEqual(result["opportunitiesData"][0]["noticeId"], "x")
        self.assertEqual(get.call_count, 1)

    def test_retries_429_then_succeeds(self):
        r1 = Mock(
            status_code=429,
            text="slow down",
            headers={"Retry-After": "0"},
        )
        r2 = Mock(status_code=200)
        r2.json.return_value = {"ok": True}
        with patch(
            "sam_common.requests.get", side_effect=[r1, r2]
        ) as get, patch("sam_common.time.sleep"):
            result = sam_search_with_retry(
                "https://example.invalid", "secret", {}, max_attempts=3
            )
        self.assertTrue(result["ok"])
        self.assertEqual(get.call_count, 2)

    def test_nonretryable_400_fails_immediately(self):
        response = Mock(status_code=400, text="bad request", headers={})
        with patch("sam_common.requests.get", return_value=response) as get:
            with self.assertRaisesRegex(RuntimeError, "SAM API error 400"):
                sam_search_with_retry(
                    "https://example.invalid", "secret", {}
                )
        self.assertEqual(get.call_count, 1)

    def test_network_error_is_bounded(self):
        with patch(
            "sam_common.requests.get",
            side_effect=requests.Timeout("timeout"),
        ) as get, patch("sam_common.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
                sam_search_with_retry(
                    "https://example.invalid",
                    "secret",
                    {},
                    max_attempts=3,
                )
        self.assertEqual(get.call_count, 3)

    def test_deadline_urgency_flag(self):
        from datetime import datetime, timezone

        now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            deadline_urgency_flag("2026-09-30T12:00:00Z", now),
            "❗",
        )
        self.assertEqual(
            deadline_urgency_flag("2026-10-05T12:00:00Z", now),
            "",
        )


if __name__ == "__main__":
    unittest.main()
