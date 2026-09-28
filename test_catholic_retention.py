"""Deadline retention and one-year catch-up checks for the Catholic/NC report."""
import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import script_catholic_southeast as scanner


class RetentionTests(unittest.TestCase):
    def test_exact_deadline_and_state_roundtrip(self):
        now = dt.datetime(2026, 9, 28, 14, 45, tzinfo=dt.timezone.utc)
        expired = scanner.Opportunity("expired", "Expired", "", active="Yes",
                                      responseDeadLine="2026-09-28T10:00:00-04:00")
        future = scanner.Opportunity("future", "Groundskeeping", "", active="Yes",
                                     responseDeadLine="2026-10-06T12:00:00-04:00")
        self.assertFalse(scanner.hard_filters_ok(expired, now))
        self.assertTrue(scanner.hard_filters_ok(future, now))
        self.assertFalse(scanner.hard_filters_ok(scanner.Opportunity("off", "", "", active="No"), now))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            scanner.save_state([future], path)
            self.assertEqual(scanner.load_state(path)["future"].responseDeadLine,
                             future.responseDeadLine)

    def test_old_nc_notice_is_discovered_and_carried_until_deadline(self):
        # An older notice resembling the supplied September 24 groundskeeping row.
        item = {"noticeId": "832ec3d8334b47c5b796c22a01719016",
                "title": "Groundskeeping", "postedDate": "2026-09-24",
                "responseDeadLine": "2026-10-06T12:00:00-04:00", "active": "Yes",
                "type": "Solicitation", "typeOfSetAside": "8A",
                "placeOfPerformance": {"state": {"code": "NC"},
                                       "country": {"code": "USA"}}}
        queries = []

        def fetch(_key, params):
            queries.append(dict(params))
            return {"opportunitiesData": [item] if "rdlfrom" in params else []}

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SAM_API_KEY": "test-only"}), \
             patch.object(scanner, "sam_search", side_effect=fetch), \
             patch.object(scanner, "sam_fetch_description", return_value=""), \
             patch.object(scanner, "send_email"):
            now = dt.datetime(2026, 9, 28, 14, 45, tzinfo=dt.timezone.utc)
            cwd = Path.cwd()
            try:
                os.chdir(directory)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(scanner.run(now), 0)
                self.assertEqual(len(json.loads(Path("catholic_opportunity_state.json").read_text())["opportunities"]), 1)
                self.assertTrue(any(p.get("state") == "NC" and p.get("rdlfrom") == "09/28/2026"
                                    and p.get("postedFrom") == "09/29/2025" for p in queries))
                with patch.object(scanner, "sam_search", return_value={"opportunitiesData": []}), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(scanner.run(now), 0)
                self.assertEqual(len(json.loads(Path("catholic_opportunity_state.json").read_text())["opportunities"]), 1)
                expired_at = dt.datetime(2026, 10, 6, 16, 1, tzinfo=dt.timezone.utc)
                with patch.object(scanner, "sam_search", return_value={"opportunitiesData": []}), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(scanner.run(expired_at), 0)
                self.assertEqual(json.loads(Path("catholic_opportunity_state.json").read_text())["opportunities"], [])
            finally:
                os.chdir(cwd)

    def test_api_failure_does_not_send_incomplete_report(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SAM_API_KEY": "test-only"}), \
             patch.object(scanner, "sam_search", side_effect=RuntimeError("API error")), \
             patch.object(scanner, "send_email") as send:
            cwd = Path.cwd()
            try:
                os.chdir(directory)
                with self.assertRaisesRegex(RuntimeError, "scan incomplete"):
                    scanner.run(dt.datetime(2026, 9, 28, tzinfo=dt.timezone.utc))
                send.assert_not_called()
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
