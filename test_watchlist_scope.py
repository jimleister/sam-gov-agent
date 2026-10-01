"""Regression checks for all five reported-only daily refresh queues."""
import contextlib
import datetime as dt
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import bootstrap_opportunity_state as bootstrap
import sam_common as common

SCANNERS = ("script", "script_pest", "script_usace_asia",
            "script_inspection_oilgas", "script_catholic_southeast")


class WatchlistTests(unittest.TestCase):
    def test_all_five_archive_full_pool_but_refresh_only_reported(self):
        for name in SCANNERS:
            with self.subTest(scanner=name):
                module = importlib.import_module(name)
                items = [{"noticeId": f"item-{i}", "title": "Pipeline inspection pest logistics in Nepal",
                          "postedDate": "2026-09-29", "active": "Yes", "type": "Solicitation",
                          "responseDeadLine": "2026-10-20T12:00:00Z",
                          "placeOfPerformance": {"state": {"code": "NC"},
                                                "country": {"code": "NPL", "name": "NEPAL"}}}
                         for i in range(65)]
                queries = []
                def fetch(_key, params):
                    queries.append(dict(params))
                    if params.get("noticeid"):
                        return {"opportunitiesData": [x for x in items if x["noticeId"] == params["noticeid"]]}
                    return {"opportunitiesData": items}
                with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SAM_API_KEY": "offline"}), \
                     patch.object(module, "sam_search", side_effect=fetch), \
                     patch.object(module, "sam_fetch_description", return_value="Pipeline inspection pest logistics in Nepal"), \
                     patch.object(module, "send_email"), \
                     patch.object(module, "write_results_csv", return_value="") as csv, \
                     patch.object(module, "write_results_xlsx", return_value=""):
                    cwd = Path.cwd()
                    try:
                        os.chdir(directory)
                        for day in (29, 30):
                            queries.clear()
                            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                                self.assertEqual(module.run(dt.datetime(2026, 9, day, tzinfo=dt.timezone.utc)), 0)
                            self.assertEqual(len(csv.call_args.args[0]), 65)
                            saved = common.load_opportunity_state(module.STATE_FILE, module.Opportunity)
                            reported = csv.call_args.args[1] | csv.call_args.args[2]
                            self.assertEqual(set(saved), reported)
                            self.assertEqual(len(saved), 30)
                            refreshed = [p["noticeid"] for p in queries if "noticeid" in p]
                            self.assertEqual(len(refreshed), 0 if day == 29 else 30)
                            if day == 30:
                                self.assertEqual(set(refreshed), reported)
                    finally:
                        os.chdir(cwd)

    def test_prior_reported_and_explicit_saves_survive_falling_out_of_rank(self):
        module = importlib.import_module("script")
        prior = module.Opportunity("old", "Previously reported", "")
        explicit = module.Opportunity("manual", "Explicit save", "", explicitly_saved=True)
        reported = module.Opportunity("new", "Today's top", "")
        background = module.Opportunity("background", "Archive only", "")
        result = common.select_watchlist([prior, explicit, reported, background], {"old": prior}, [reported])
        self.assertEqual({o.noticeId for o in result}, {"old", "manual", "new"})

    def test_all_five_failed_email_preserves_previous_queue(self):
        for name in SCANNERS:
            with self.subTest(scanner=name):
                module = importlib.import_module(name)
                with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SAM_API_KEY": "offline"}), \
                     patch.object(module, "sam_search", return_value={"opportunitiesData": []}), \
                     patch.object(module, "send_email", side_effect=RuntimeError("SMTP offline")), \
                     patch.object(module, "write_results_csv", return_value=""), \
                     patch.object(module, "write_results_xlsx", return_value=""):
                    cwd = Path.cwd()
                    try:
                        os.chdir(directory)
                        common.save_opportunity_state(module.STATE_FILE, [module.Opportunity("saved", "Tracked", "")])
                        before = module.STATE_FILE.read_bytes()
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            with self.assertRaisesRegex(RuntimeError, "SMTP offline"):
                                module.run(dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc))
                        self.assertEqual(module.STATE_FILE.read_bytes(), before)
                    finally:
                        os.chdir(cwd)

    def test_legacy_full_pool_cannot_be_refreshed_without_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"version": 1, "opportunities": []}))
            with self.assertRaisesRegex(ValueError, "requires.*migration"):
                common.load_opportunity_state(path, importlib.import_module("script").Opportunity)


class VersionTests(unittest.TestCase):
    def records(self, **overrides):
        cls = importlib.import_module("script").Opportunity
        old = cls("old", "Courier", "", postedDate="2026-09-28",
                  fullParentPathCode="036.3600.36C250", solicitationNumber="36C25026Q1234",
                  resourceLinks=["https://sam.gov/file/a", "https://sam.gov/file/b"],
                  refresh_status="unavailable", explicitly_saved=True)
        new = cls("new", "Courier", "", postedDate="2026-09-29",
                  fullParentPathCode=old.fullParentPathCode, solicitationNumber=old.solicitationNumber,
                  resourceLinks=old.resourceLinks)
        for field, value in overrides.items():
            setattr(new, field, value)
        return old, new

    def test_explicit_solicitation_and_office_reconnect_newer_id(self):
        old, new = self.records()
        seen = {"old": old, "new": new}
        with contextlib.redirect_stdout(io.StringIO()):
            tracked = common.reconcile_notice_versions(seen, {"old": old})
        self.assertEqual(set(seen), {"new"}); self.assertEqual(set(tracked), {"new"})
        self.assertEqual(new.previous_notice_ids, ["old"])
        self.assertTrue(new.explicitly_saved)

    def test_legacy_requires_shared_attachments_not_title_alone(self):
        old, new = self.records(); old.solicitationNumber = None
        self.assertTrue(common.successor_matches(old, new))
        new.resourceLinks = []
        self.assertFalse(common.successor_matches(old, new))

    def test_wrong_office_solicitation_older_or_ambiguous_stay_unverified(self):
        for overrides in ({"fullParentPathCode": "other"}, {"solicitationNumber": "other"},
                          {"postedDate": "2026-09-27"}, {"refresh_status": "unavailable"}):
            old, new = self.records(**overrides)
            self.assertFalse(common.successor_matches(old, new))
        old, new = self.records()
        other = importlib.import_module("script").Opportunity(**vars(new))
        other.noticeId = "other-new"
        seen = {"old": old, "new": new, "other-new": other}
        tracked = common.reconcile_notice_versions(seen, {"old": old})
        self.assertEqual(set(tracked), {"old"}); self.assertIn("old", seen)

    def test_all_five_preserve_solicitation_in_normalized_records(self):
        for name in SCANNERS:
            module = importlib.import_module(name)
            opp = module.normalize({"noticeId": "id", "solicitationNumber": "SOL-123"})
            self.assertEqual(opp.solicitationNumber, "SOL-123")
            self.assertEqual(module.opp_to_row(opp)["solicitation_number"], "SOL-123")


class MigrationTests(unittest.TestCase):
    def test_existing_full_pool_migrates_only_reported_and_explicit_with_backup(self):
        now = dt.datetime.now(dt.timezone.utc)
        future = (now + dt.timedelta(days=10)).isoformat()
        legacy = {"version": 1, "opportunities": [
            {"noticeId": "reported", "title": "Richer cached record", "responseDeadLine": future},
            {"noticeId": "background", "title": "Archive only"},
            {"noticeId": "manual", "title": "Saved manually", "explicitly_saved": True},
            {"noticeId": "missing", "title": "Previously reported", "refresh_status": "unavailable",
             "responseDeadLine": "2020-01-01"}]}
        runs = {"workflow_runs": [{"id": 1, "created_at": now.isoformat()}]}
        artifacts = {"artifacts": [{"name": "sam-results-1", "archive_download_url": "offline", "expired": False}]}
        rows = [{"notice_id": "reported", "rank_group": "Top", "response_deadline": future},
                {"notice_id": "background", "rank_group": "All Matches", "response_deadline": future},
                {"notice_id": "missing", "rank_group": "Shortlist", "response_deadline": "2020-01-01"}]
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"GH_TOKEN": "offline", "GITHUB_REPOSITORY": "owner/repo"}), \
             patch.object(bootstrap, "api_json", side_effect=[runs, artifacts]), \
             patch.object(bootstrap, "artifact_csv_rows", return_value=rows), \
             patch.object(common.requests, "get") as sam:
            cwd = Path.cwd()
            try:
                os.chdir(directory)
                path = Path("state.json"); path.write_text(json.dumps(legacy))
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(bootstrap.bootstrap("run.yml", "sam-results-", path), 3)
                data = json.loads(path.read_text())
                self.assertEqual(data["watchlist_scope"], common.WATCHLIST_SCOPE)
                self.assertEqual({o["noticeId"] for o in data["opportunities"]}, {"reported", "manual", "missing"})
                self.assertEqual(json.loads(Path("watchlist_migration_archive.json").read_text()), legacy)
                sam.assert_not_called()
                with patch.object(bootstrap, "api_json") as api:
                    self.assertEqual(bootstrap.bootstrap("run.yml", "sam-results-", path), 3)
                    api.assert_not_called()
            finally:
                os.chdir(cwd)

    def test_failed_migration_preserves_original_state(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"GH_TOKEN": "offline", "GITHUB_REPOSITORY": "owner/repo"}), \
             patch.object(bootstrap, "api_json", return_value={"workflow_runs": []}):
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"version": 1, "opportunities": [{"noticeId": "old"}]}))
            before = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "original state preserved"):
                bootstrap.bootstrap("run.yml", "sam-results-", path)
            self.assertEqual(path.read_bytes(), before)

    def test_all_five_workflows_migrate_after_restore_and_ci_runs_full_suite(self):
        for path in Path(".github/workflows").glob("run*.yml"):
            workflow = path.read_text()
            restore = workflow.split("      - name: Run ")[0]
            self.assertIn("          fi\n          python bootstrap_opportunity_state.py", restore)
            self.assertIn("watchlist_migration_archive.json", workflow)
        self.assertIn("unittest discover", Path(".github/workflows/validate.yml").read_text())


class QuotaTests(unittest.TestCase):
    def test_daily_quota_does_not_retry_until_tomorrow_in_short_backoff(self):
        response = Mock(status_code=429, headers={}, text="Daily quota")
        response.json.return_value = {"nextAccessTime": "2026-Oct-02 00:00:00+0000 UTC"}
        with patch.object(common.requests, "get", return_value=response) as get, patch.object(common.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "daily API quota exhausted.*2026-Oct-02"):
                common.sam_search_with_retry("https://example.invalid", "secret", {})
            get.assert_called_once(); sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
