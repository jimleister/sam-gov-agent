"""Offline integration checks for the four non-Catholic retained reports."""
import contextlib
import datetime as dt
import importlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sam_common import load_opportunity_state, refresh_saved_opportunities, save_opportunity_state


SCANNERS = ("script", "script_pest", "script_usace_asia", "script_inspection_oilgas")


class RetainedScannerTests(unittest.TestCase):
    def test_saved_description_survives_unavailable_detail_fetch(self):
        module = importlib.import_module("script_inspection_oilgas")
        old = module.Opportunity("id", "Inspection", "", postedDate="2026-09-24",
                                 active="Yes", description_text="Pipeline inspection")
        item = {"noticeId": "id", "title": "Inspection", "postedDate": "2026-09-24", "active": "Yes"}
        refreshed, _, _ = refresh_saved_opportunities(
            "key", {"id": old}, dt.date(2026, 9, 28),
            lambda _key, _params: {"opportunitiesData": [item]}, module.normalize)
        self.assertEqual(refreshed["id"].description_text, "Pipeline inspection")

    def test_each_report_refreshes_saved_id_before_old_deadline_removal(self):
        for name in SCANNERS:
            with self.subTest(scanner=name):
                module = importlib.import_module(name)
                item = {
                    "noticeId": f"saved-{name}",
                    "title": "Pipeline inspection and pest management logistics in Nepal",
                    "postedDate": "2026-09-24",
                    "responseDeadLine": "2026-10-20T12:00:00-04:00",
                    "active": "Yes", "type": "Solicitation",
                    "placeOfPerformance": {"country": {"code": "NPL", "name": "NEPAL"}},
                }
                queries = []

                def fetch(_key, params):
                    queries.append(dict(params))
                    return {"opportunitiesData": [item] if params.get("noticeid") == item["noticeId"] else []}

                old = module.normalize({**item, "responseDeadLine": "2026-10-06T12:00:00-04:00"})
                with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SAM_API_KEY": "test-only"}), \
                     patch.object(module, "sam_search", side_effect=fetch), \
                     patch.object(module, "sam_fetch_description", return_value="Pipeline inspection pest logistics in Nepal"), \
                     patch.object(module, "send_email"):
                    cwd = Path.cwd()
                    try:
                        os.chdir(directory)
                        save_opportunity_state(module.STATE_FILE, [old])
                        after_old_deadline = dt.datetime(2026, 10, 6, 16, 1, tzinfo=dt.timezone.utc)
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(module.run(after_old_deadline), 0)
                        self.assertTrue(any(p.get("noticeid") == item["noticeId"] for p in queries))
                        saved = load_opportunity_state(module.STATE_FILE, module.Opportunity)
                        self.assertEqual(saved[item["noticeId"]].responseDeadLine, item["responseDeadLine"])
                        queries.clear()
                        after_new_deadline = dt.datetime(2026, 10, 20, 16, 1, tzinfo=dt.timezone.utc)
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(module.run(after_new_deadline), 0)
                        self.assertTrue(any(p.get("noticeid") == item["noticeId"] for p in queries))
                        self.assertNotIn(item["noticeId"], load_opportunity_state(module.STATE_FILE, module.Opportunity))
                    finally:
                        os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
