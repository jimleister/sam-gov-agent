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

    def test_saved_id_refreshed_daily_and_extension_wins_over_old_deadline(self):
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
            return {"opportunitiesData": [item] if "rdlfrom" in params or "noticeid" in params else []}

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
                queries.clear()
                item["responseDeadLine"] = "2026-10-20T12:00:00-04:00"
                after_old_deadline = dt.datetime(2026, 10, 6, 16, 1, tzinfo=dt.timezone.utc)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(scanner.run(after_old_deadline), 0)
                self.assertEqual(len(json.loads(Path("catholic_opportunity_state.json").read_text())["opportunities"]), 1)
                self.assertEqual(json.loads(Path("catholic_opportunity_state.json").read_text())
                                 ["opportunities"][0]["responseDeadLine"], item["responseDeadLine"])
                self.assertTrue(any(p.get("noticeid") == item["noticeId"] for p in queries))
                self.assertFalse(any("rdlfrom" in p for p in queries))
                queries.clear()
                expired_at = dt.datetime(2026, 10, 20, 16, 1, tzinfo=dt.timezone.utc)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(scanner.run(expired_at), 0)
                self.assertTrue(any(p.get("noticeid") == item["noticeId"] for p in queries))
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

    def test_missing_saved_id_sends_flagged_report_and_keeps_for_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SAM_API_KEY": "test-only"}), \
             patch.object(scanner, "sam_search", return_value={"opportunitiesData": []}), \
             patch.object(scanner, "send_email") as send:
            cwd = Path.cwd()
            try:
                os.chdir(directory)
                scanner.save_state([scanner.Opportunity("saved-id", "Still open", "", postedDate="2026-09-24",
                                                        active="Yes", responseDeadLine="2026-10-06T12:00:00-04:00")])
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(scanner.run(dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)), 0)
                send.assert_called_once()
                self.assertIn("UNVERIFIED", Path("email_draft.txt").read_text())
                saved = scanner.load_state()
                self.assertEqual(saved["saved-id"].refresh_status, "unavailable")
                self.assertEqual(saved["saved-id"].responseDeadLine, "2026-10-06T12:00:00-04:00")
            finally:
                os.chdir(cwd)

    def test_older_than_one_year_id_is_checked_in_older_date_slice(self):
        old = scanner.Opportunity("older-id", "Long deadline", "", postedDate="2025-06-02",
                                  active="Yes", responseDeadLine="2026-12-19T16:00:00-05:00")
        queries = []

        def fetch(_key, params):
            queries.append(params)
            if params["postedFrom"] == "06/02/2025":
                return {"opportunitiesData": [{"noticeId": "older-id", "title": "Long deadline",
                                                "postedDate": "2025-06-02", "active": "Yes",
                                                "responseDeadLine": "2026-12-19T16:00:00-05:00"}]}
            return {"opportunitiesData": []}

        with patch.object(scanner, "sam_search", side_effect=fetch):
            refreshed, calls = scanner.refresh_saved_notice("key", old, dt.date(2026, 9, 28))
        self.assertEqual(refreshed.noticeId, "older-id")
        self.assertEqual(calls, 2)
        self.assertEqual(queries[0]["noticeid"], "older-id")


if __name__ == "__main__":
    unittest.main()

