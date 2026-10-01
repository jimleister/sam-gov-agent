import datetime as dt
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import bootstrap_opportunity_state as bootstrap


class BootstrapTests(unittest.TestCase):
    def test_reads_csv_inside_result_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("sam_results_weston_wexmac_2026-09-28.csv",
                             "notice_id,title,response_deadline\nabc,Open,2026-10-06T12:00:00-04:00\n")
        class Response:
            content = buffer.getvalue()
            def raise_for_status(self):
                pass
        with patch.object(bootstrap.requests, "get", return_value=Response()) as get:
            rows = bootstrap.artifact_csv_rows("https://api.github.com/artifact.zip", "token")
        self.assertEqual(rows[0]["notice_id"], "abc")
        self.assertEqual(get.call_args.kwargs["timeout"], 120)

    def test_recent_artifacts_seed_open_ids_with_latest_row(self):
        now = dt.datetime.now(dt.timezone.utc)
        recent = (now - dt.timedelta(days=1)).isoformat().replace("+00:00", "Z")
        older = (now - dt.timedelta(days=2)).isoformat().replace("+00:00", "Z")
        future = (now + dt.timedelta(days=10)).isoformat()
        past = (now - dt.timedelta(days=1)).isoformat()

        def api(url, _token):
            if "/workflows/" in url:
                return {"workflow_runs": [{"id": 2, "created_at": recent},
                                          {"id": 1, "created_at": older}]}
            run_id = 2 if "/runs/2/" in url else 1
            return {"artifacts": [{"name": f"sam-results-{run_id}",
                                   "archive_download_url": f"https://example.test/{run_id}",
                                   "expired": False}]}

        def csv_rows(url, _token):
            if url.endswith("/2"):
                return [{"rank_group": "Top", "notice_id": "same", "title": "Extended", "posted_date": "2026-09-01",
                         "response_deadline": future},
                        {"rank_group": "Top", "notice_id": "expired", "title": "Past", "response_deadline": past}]
            return [{"rank_group": "Top", "notice_id": "same", "title": "Old title", "response_deadline": future},
                    {"rank_group": "Shortlist", "notice_id": "another", "title": "Open", "response_deadline": future},
                    {"rank_group": "All Matches", "notice_id": "background", "title": "Archive only", "response_deadline": future}]

        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"GH_TOKEN": "test", "GITHUB_REPOSITORY": "owner/repo"}), \
             patch.object(bootstrap, "api_json", side_effect=api), \
             patch.object(bootstrap, "artifact_csv_rows", side_effect=csv_rows):
            path = Path(directory) / "state.json"
            self.assertEqual(bootstrap.bootstrap("run.yml", "sam-results-", path), 2)
            records = {r["noticeId"]: r for r in json.loads(path.read_text())["opportunities"]}
            self.assertEqual(set(records), {"same", "another"})
            self.assertEqual(records["same"]["title"], "Extended")


if __name__ == "__main__":
    unittest.main()
