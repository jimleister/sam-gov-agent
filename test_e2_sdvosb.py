"""Offline regression tests. No SAM calls and no email are sent."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import script_e2_sdvosb as s

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def notice(**changes):
    raw = {
        "noticeId": "test-001", "title": "VA construction inspection and quality assurance",
        "solicitationNumber": "TEST-001", "fullParentPathName": "VETERANS AFFAIRS, DEPARTMENT OF.TEST",
        "fullParentPathCode": "TEST.VA", "postedDate": "2026-10-28T12:00:00Z",
        "responseDeadLine": "2026-11-30T17:00:00-05:00", "type": "Solicitation",
        "naicsCode": "541350", "typeOfSetAside": "SDVOSBC", "active": "Yes",
        "placeOfPerformance": {"state": {"code": "NC"}, "country": {"code": "USA"}},
        "description_text": "Construction inspection, quality assurance and project controls."
    }
    raw.update(changes)
    return s.normalize(raw)


class FeasibilityTests(unittest.TestCase):
    def assess(self, **changes):
        return s.score(notice(**changes), s.DEFAULTS, NOW)

    def test_registered_entity_has_17_codes(self):
        self.assertEqual(len(s.REGISTERED), 17)
        self.assertIn("561210", s.REGISTERED)
        self.assertNotIn("541330", s.REGISTERED)
        self.assertIn("541330", s.ADJACENT)

    def test_sdvosb_prime_has_priority(self):
        row = self.assess()
        self.assertGreaterEqual(row["score"], 75)
        self.assertEqual(row["lane"], "SDVOSB prime candidates")
        self.assertIn("Weston", row["roles"])
        self.assertIn("50%", row["workshare"])

    def test_va_priority_over_other_agency(self):
        self.assertGreater(self.assess()["score"], self.assess(fullParentPathName="OTHER AGENCY")["score"])

    def test_no_geographic_hard_filter(self):
        row = self.assess(placeOfPerformance={"country": {"code": "NPL"}})
        self.assertGreater(row["score"], 0)
        self.assertEqual(row["lane"], "SDVOSB prime candidates")

    def test_sources_sought_not_bid(self):
        row = self.assess(type="Sources Sought", typeOfSetAside="")
        self.assertEqual(row["lane"], "Early-stage / market shaping")
        self.assertEqual(row["rating"], "Shape requirement - not a bid")

    def test_hubzone_not_assumed(self):
        row = self.assess(typeOfSetAside="HZC")
        self.assertEqual(row["score"], 0)
        self.assertTrue(any("HUBZone" in x for x in row["blockers"]))

    def test_other_certifications_blocked(self):
        for code in ["8A", "8AN", "WOSB", "EDWOSB", "IEE", "ISBEE", "BICIV"]:
            with self.subTest(code=code):
                self.assertEqual(self.assess(typeOfSetAside=code)["score"], 0)

    def test_generic_text_does_not_override_structured_setaside(self):
        row = self.assess(typeOfSetAside="8A", description_text="SDVOSB firms are invited to subcontract; environmental compliance.")
        self.assertEqual(row["setaside"], "8(a)")
        self.assertEqual(row["score"], 0)

    def test_generic_sdvosb_mention_is_not_actual_setaside(self):
        row = self.assess(typeOfSetAside="", description_text="All firms including SDVOSB may reply; construction inspection.")
        self.assertEqual(row["setaside"], "Not designated")
        self.assertNotEqual(row["lane"], "SDVOSB prime candidates")

    def test_sole_source_not_competitive_top_lane(self):
        row = self.assess(typeOfSetAside="SDVOSBS")
        self.assertEqual(row["lane"], "Market intelligence / sole-source watch")

    def test_wexmac_separate(self):
        row = self.assess(title="WEXMAC logistics support", naicsCode="561210", type="Special Notice")
        self.assertEqual(row["lane"], "WEXMAC public-notice watch")
        self.assertTrue(any("TITUS" in r for r in row["risks"]))

    def test_non_navy_titus_not_wexmac(self):
        row = self.assess(title="Titus building inspection", fullParentPathName="OTHER AGENCY")
        self.assertNotEqual(row["lane"], "WEXMAC public-notice watch")

    def test_awards_not_actionable(self):
        self.assertEqual(self.assess(type="Award Notice")["score"], 0)

    def test_expired_and_inactive_removed(self):
        self.assertEqual(self.assess(responseDeadLine="2026-10-01T12:00:00Z")["score"], 0)
        self.assertEqual(self.assess(active="No")["score"], 0)

    def test_cancellation_not_bid(self):
        self.assertEqual(self.assess(title="CANCELLED - construction inspection")["score"], 0)

    def test_missing_deadline_not_high_feasibility(self):
        self.assertLessEqual(self.assess(responseDeadLine="")["score"], 49)

    def test_malformed_deadline_does_not_crash(self):
        row = self.assess(responseDeadLine="confirm with contracting officer")
        self.assertLessEqual(row["score"], 49)
        self.assertTrue(any("Unparseable" in x for x in row["risks"]))

    def test_unknown_active_status_capped(self):
        self.assertLessEqual(self.assess(active=None)["score"], 49)

    def test_description_absence_capped(self):
        self.assertLessEqual(self.assess(description_text="")["score"], 64)

    def test_clearance_or_vehicle_capped(self):
        for term in ["facility clearance", "gsa schedule", "contract holders only"]:
            with self.subTest(term=term):
                self.assertLessEqual(self.assess(description_text="Construction inspection; " + term)["score"], 59)

    def test_clinical_staffing_excluded(self):
        self.assertEqual(self.assess(naicsCode="561320", description_text="Clinical staffing and physician services")["score"], 0)

    def test_workshare_depends_on_contract_industry(self):
        self.assertIn("85%", s.workshare("236220"))
        self.assertIn("75%", s.workshare("238220"))
        self.assertIn("50%", s.workshare("541620"))
        self.assertIn("nonmanufacturer", s.workshare("332710"))

    def test_unavailable_is_retained_not_falsely_open(self):
        old = notice(responseDeadLine="2026-01-01T00:00:00Z")
        old["refresh"] = "unavailable"
        row = s.score(old, s.DEFAULTS, NOW)
        self.assertEqual(row["lane"], "Unverified saved notices")
        self.assertFalse(any("deadline passed" in b for b in row["blockers"]))

    def test_complex_execution_downgraded(self):
        base = self.assess()
        difficult = self.assess(description_text="Construction inspection, quality assurance, project controls, 24/7, multi-site, infection control, performance bond.")
        self.assertLess(difficult["score"], base["score"])


class DataSafetyTests(unittest.TestCase):
    def test_html_script_removed(self):
        self.assertEqual(s.plain("<script>alert(1)</script><p>Safe &amp; clear</p>"), "Safe & clear")

    def test_csv_formula_injection_escaped(self):
        for value in ["=1+1", "+SUM(A1:A2)", "-2+3", "@SUM(A1)", " =CMD()", "\tformula"]:
            self.assertTrue(s.csv_safe(value).startswith("'"))

    def test_unsafe_urls_rejected(self):
        for url in ["javascript:alert(1)", "http://sam.gov/x", "https://user:pass@sam.gov/x"]:
            self.assertEqual(s.url_ok(url), "")
        self.assertEqual(s.url_ok("https://evil.example/x", sam_only=True), "")

    def test_credentials_removed_from_links(self):
        self.assertNotIn("secret", s.url_ok("https://api.sam.gov/x?api_key=secret&noticeid=123"))

    def test_deadline_timezone_explained(self):
        due, note = s.due_date("2026-10-29T17:00:00")
        self.assertEqual(due.hour, 21)
        self.assertIn("Eastern assumed", note)
        self.assertIsNotNone(s.due_date("2026-10-29")[0])

    def test_only_substantive_changes_mark_updated(self):
        o = notice()
        old = copy.deepcopy(o)
        state = {"notices": {o["id"]: old}}
        self.assertEqual(s.classify_change(o, state), "STILL OPEN")
        o["deadline"] = "2027-01-01T12:00:00Z"
        self.assertEqual(s.classify_change(o, state), "UPDATED")
        self.assertEqual(s.classify_change(o, {"notices": {}}), "NEW")

    def test_report_escapes_title(self):
        row = s.score(notice(title="<img src=x onerror=bad> inspection"), s.DEFAULTS, NOW)
        row["change"] = "NEW"
        row["title"] = "<img src=x onerror=bad>"
        with tempfile.TemporaryDirectory() as d:
            paths = s.write_report([row], [row], s.DEFAULTS, NOW, Path(d), True)
            markup = paths[1].read_text()
            self.assertNotIn("<img src=x", markup)
            self.assertIn("&lt;img", markup)
            self.assertIn("SYNTHETIC DATA", markup)


class SamApiTests(unittest.TestCase):
    def test_page_index_not_record_offset(self):
        client = s.SamClient("not-a-real-key", s.DEFAULTS)
        client.get = Mock(side_effect=[
            {"totalRecords": 2, "opportunitiesData": [{"noticeId": "a"}]},
            {"totalRecords": 2, "opportunitiesData": [{"noticeId": "b"}]},
        ])
        rows = client.search({"ncode": "561210"})
        self.assertEqual(len(rows), 2)
        self.assertEqual([c.args[1]["offset"] for c in client.get.call_args_list], [0, 1])

    def test_repeated_page_fails_visibly(self):
        client = s.SamClient("not-a-real-key", s.DEFAULTS)
        client.get = Mock(return_value={"totalRecords": 2, "opportunitiesData": [{"noticeId": "a"}]})
        with self.assertRaisesRegex(RuntimeError, "Repeated"):
            client.search({})

    def test_truncated_pagination_not_success(self):
        client = s.SamClient("not-a-real-key", s.DEFAULTS)
        client.get = Mock(side_effect=[
            {"totalRecords": 3, "opportunitiesData": [{"noticeId": "a"}]},
            {"totalRecords": 3, "opportunitiesData": []},
        ])
        with self.assertRaisesRegex(RuntimeError, "Pagination ended"):
            client.search({})

    def test_key_never_sent_to_other_host(self):
        client = s.SamClient("not-a-real-key", s.DEFAULTS)
        with self.assertRaisesRegex(RuntimeError, "Refusing"):
            client.get("https://evil.example/?x=1", {})
        self.assertEqual(client.calls, 0)

    def test_quota_exhaustion_fails_without_retry_loop(self):
        client = s.SamClient("not-a-real-key", s.DEFAULTS)
        response = Mock(status_code=429)
        response.json.return_value = {"nextAccessTime": "tomorrow"}
        client.session.get = Mock(return_value=response)
        with patch.object(s.time, "sleep"), self.assertRaisesRegex(RuntimeError, "daily quota"):
            client.get(s.SEARCH_URL, {})
        self.assertEqual(client.calls, 1)

    def test_request_budget_enforced(self):
        client = s.SamClient("not-a-real-key", {**s.DEFAULTS, "max_api_calls": 0})
        with self.assertRaisesRegex(RuntimeError, "budget"):
            client.get(s.SEARCH_URL, {})

    def test_api_error_not_reported_as_zero(self):
        client = s.SamClient("not-a-real-key", s.DEFAULTS)
        response = Mock(status_code=200)
        response.json.return_value = {"error": "bad key"}
        client.session.get = Mock(return_value=response)
        with patch.object(s.time, "sleep"), self.assertRaisesRegex(RuntimeError, "missing totalRecords"):
            client.get(s.SEARCH_URL, {})

    def test_refresh_precedes_expired_cached_deadline(self):
        old = notice(responseDeadLine="2026-09-01T00:00:00Z")
        client = Mock()
        raw = {"noticeId": old["id"], "postedDate": "2026-10-28", "responseDeadLine": "2026-12-01T12:00:00Z", "active": "Yes"}
        client.search.return_value = [raw]
        found = s.refresh_saved(client, {"notices": {old["id"]: old}}, {}, NOW)
        self.assertTrue(client.search.called)
        self.assertEqual(found[old["id"]]["deadline"], raw["responseDeadLine"])

    def test_missing_refresh_kept_for_retry(self):
        old = notice()
        client = Mock()
        client.search.return_value = []
        found = s.refresh_saved(client, {"notices": {old["id"]: old}}, {}, NOW)
        self.assertEqual(found[old["id"]]["refresh"], "unavailable")

    def test_successor_requires_solicitation_and_office(self):
        old, new = notice(), notice(noticeId="new", postedDate="2026-10-29")
        client = Mock()
        client.search.return_value = []
        found = s.refresh_saved(client, {"notices": {old["id"]: old}}, {new["id"]: new}, NOW)
        self.assertNotIn(old["id"], found)
        self.assertIn(old["id"], found[new["id"]]["prior_ids"])
        wrong = notice(noticeId="wrong", postedDate="2026-10-29", fullParentPathCode="OTHER")
        found = s.refresh_saved(client, {"notices": {old["id"]: old}}, {wrong["id"]: wrong}, NOW)
        self.assertEqual(found[old["id"]]["refresh"], "unavailable")


class TransactionTests(unittest.TestCase):
    def test_demo_never_calls_api_or_email_and_leaves_state_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "state.json"
            state.write_text("do not touch demo state")
            with patch.object(s, "SamClient") as client, patch.object(s.smtplib, "SMTP") as smtp, patch.dict(os.environ, {"SEND_EMAIL": "1"}):
                code = s.main(["--demo", "--state", str(state), "--output", str(Path(d) / "out")])
            self.assertEqual(code, 0)
            client.assert_not_called()
            smtp.assert_not_called()
            self.assertEqual(state.read_text(), "do not touch demo state")
            self.assertTrue((Path(d) / "out/email_draft.eml").exists())

    def test_failed_email_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "state.json"
            before = json.dumps({"version": 1, "notices": {}, "last_success": "2026-10-28T00:00:00Z"})
            state.write_text(before)
            with patch.object(s, "SamClient"), patch.object(s, "discover", return_value={}), patch.object(s, "email_report", side_effect=RuntimeError("SMTP failed")):
                code = s.main(["--state", str(state), "--output", str(Path(d) / "out")])
            self.assertEqual(code, 1)
            self.assertEqual(state.read_text(), before)
            self.assertIn("NOT A ZERO", (Path(d) / "out/scan_failure.txt").read_text())

    def test_failed_scan_does_not_send_email(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(s, "SamClient"), patch.object(s, "discover", side_effect=RuntimeError("SAM quota")), patch.object(s, "email_report") as sender:
                code = s.main(["--state", str(Path(d) / "state.json"), "--output", str(Path(d) / "out")])
            self.assertEqual(code, 1)
            sender.assert_not_called()

    def test_empty_success_is_not_filled_with_fake_results(self):
        self.assertEqual(s.choose([], s.DEFAULTS), [])


if __name__ == "__main__":
    unittest.main()
