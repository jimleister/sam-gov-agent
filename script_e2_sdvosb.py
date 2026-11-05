#!/usr/bin/env python3
"""WTC + E2 Federal Services: daily SDVOSB set-aside team opportunity report. Python 3.10+.

Discovery pulls ONLY notices carrying a structured SDVOSB set-aside (SDVOSBC/SDVOSBS).
Opportunities are ranked for the WTC/E2 team under either delivery pathway:
  - current state: WTC (SDVOSB) prime with E2 Federal Services as subcontractor
  - future state: WTC-E2 Federal SBA mentor-protege joint venture, WTC managing venturer
Staffing, workshare, size and complexity are review notes, never exclusions.
No certifications, resources, margins or win probability are inferred.
Attachments require human review. Run --demo for synthetic examples.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

UTC = timezone.utc
EASTERN = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent
SEARCH_URL = "https://api.sam.gov/opportunities/v2/search"
STATE_VERSION = 1
# Corroborated SAM-derived profiles, 2026-10-29. Not a direct SAM entity export.
# https://govtribe.com/vendors/e2-federal-services-llc-14te2
# https://www.sweetspot.so/markets/federal/contractors/e2-federal-services-llc-rrm2yjmntpx1/
REGISTERED = {
    "561210": "Facilities Support Services (primary)",
    "236220": "Commercial and Institutional Building Construction",
    "238220": "Plumbing, Heating, and Air-Conditioning Contractors",
    "332710": "Machine Shops",
    "541370": "Surveying and Mapping (except Geophysical) Services",
    "541513": "Computer Facilities Management Services",
    "541611": "Administrative Management and General Management Consulting Services",
    "541618": "Other Management Consulting Services",
    "541620": "Environmental Consulting Services",
    "541690": "Other Scientific and Technical Consulting Services",
    "541990": "All Other Professional, Scientific, and Technical Services",
    "561110": "Office Administrative Services",
    "561320": "Temporary Help Services",
    "561730": "Landscaping Services",
    "561790": "Other Services to Buildings and Dwellings",
    "562111": "Solid Waste Collection",
    "562910": "Remediation Services",
}
# Strategic scope expansions, NOT asserted to be E2 Federal's registrations.
ADJACENT = {
    "562112": "Hazardous Waste Collection (strategic expansion)",
    "541330": "Engineering Services (parent profile; verify delivering entity)",
    "541350": "Building Inspection Services (strategic expansion)",
    "541380": "Testing Laboratories and Services (strategic expansion)",
    "237110": "Water and Sewer Line and Related Structures Construction (expansion)",
    "237120": "Oil and Gas Pipeline and Related Structures Construction (expansion)",
}
# family: (scope terms, possible team roles). No standalone-capacity scores.
FAMILIES = {
    "inspection / construction oversight": (
        ["construction inspection", "construction management", "welding inspection",
         "quality assurance", "quality control", "coating inspection", "project controls",
         "commissioning", "building inspection", "non-destructive testing"],
        "WTC: SDVOSB lead, program management and field staffing. E2: inspection, QA/QC and technical specialists."),
    "environmental / safety": (
        ["environmental consulting", "environmental compliance", "environmental assessment",
         "remediation", "industrial hygiene", "asbestos", "lead-based paint", "hazardous waste",
         "stormwater", "safety and health"],
        "WTC: SDVOSB lead, program management and field delivery. E2: environmental and scientific expertise, technical review."),
    "facilities / utilities": (
        ["facilities support", "facility maintenance", "facilities maintenance", "base operations",
         "boiler", "chiller", "hvac", "utility systems", "water treatment", "wastewater",
         "electrical maintenance", "preventive maintenance", "building maintenance"],
        "WTC: SDVOSB lead and operating management. E2: facilities, utility and technical support."),
    "professional staffing / management": (
        ["staff augmentation", "technical staffing", "project management", "program management",
         "administrative support", "work planning", "records management"],
        "WTC: SDVOSB lead, program management and recruiting. E2: specialist staff and proposal support."),
    "site / logistics support": (
        ["warehousing", "warehouse", "fleet management", "grounds maintenance", "landscaping",
         "solid waste", "logistics support", "expeditionary", "life support", "transportation"],
        "WTC: SDVOSB lead, logistics and program management. E2: facilities, environmental, utility and technical work packages."),
}
CODE_FAMILY = {
    "541350": "inspection / construction oversight", "541380": "inspection / construction oversight",
    "541330": "inspection / construction oversight", "541370": "inspection / construction oversight",
    "541620": "environmental / safety", "562910": "environmental / safety",
    "562112": "environmental / safety",
    "541690": "environmental / safety", "561210": "facilities / utilities",
    "238220": "facilities / utilities", "236220": "facilities / utilities",
    "237110": "facilities / utilities", "237120": "facilities / utilities",
    "561790": "facilities / utilities", "541611": "professional staffing / management",
    "541618": "professional staffing / management", "561110": "professional staffing / management",
    "561320": "professional staffing / management", "561730": "site / logistics support",
    "562111": "site / logistics support",
}
RISK_TERMS = {
    "Develop staffing/mobilization plan for continuous or multi-site coverage":
        ["24/7", "24 hour", "24-hour", "nationwide", "multi-site", "multiple sites"],
    "Professional licensing / SF330 / prime A-E qualifications require review":
        ["sf330", "sf 330", "architect-engineer", "architect engineer", "professional engineer"],
    "Clearance / cybersecurity requirement requires documentary confirmation":
        ["facility clearance", "top secret", "secret clearance", "cmmc level 2", "cmmc level 3"],
    "Develop bonding and working-capital arrangements as needed":
        ["performance bond", "payment bond", "bid bond", "bonding capacity"],
    "Healthcare-site controls and specialist qualifications require team planning":
        ["infection control", "icra", "asbestos", "radiological", "nuclear facility"],
    "Contract-vehicle/holder access must be verified for the offering entity":
        ["gsa schedule", "oasis+", "oasis plus", "seaport", "contract holders only",
         "idiq holders", "holders of", "under existing contract"],
}
TYPE_NAMES = {"r": "Sources Sought", "p": "Presolicitation", "o": "Solicitation",
              "k": "Combined Synopsis/Solicitation", "a": "Award Notice", "s": "Special Notice"}
DEFAULTS = {
    "sdvosb_status": "user-confirmed; verify active SBA certification before offer",
    "hubzone_certified": False, "include_adjacent_naics": True,
    "discovery_days": 7, "initial_days": 90, "max_api_calls": 220,
    "max_pages_per_query": 40, "description_limit": 45,
    "top_per_lane": 5, "max_highlights": 10, "shortlist_max": 15,
    "preferred_states": ["NC", "SC", "VA", "CO", "PA"],
    "email_to": "jleister@westontrolley.com",
}
SDVOSB_CODES = ["SDVOSBC", "SDVOSBS"]
NOTICE_TYPES = "o,k,p,r"  # solicitation, combined, presolicitation, sources sought
SDVOSB_BACKFILL = "sdvosb-only-v2"
LANE_COMPETITIVE = "Competitive SDVOSB set-asides"
LANE_EARLY = "Early-stage SDVOSB (sources sought / presolicitation)"
LANE_SOLE = "SDVOSB sole source (market intelligence)"
LANE_OUTSIDE = "SDVOSB, outside team NAICS (attachment only)"
LANE_BLOCKED = "Excluded / blocked"
PATHWAY = ("Current: WTC prime with E2 Federal Services as subcontractor (teaming agreement). "
           "Future: WTC-E2 Federal SBA mentor-protege JV with WTC as managing venturer.")


def plain(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def has(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I) is not None


def url_ok(value: Any, sam_only: bool = False) -> str:
    s = str(value or "")
    p = urlsplit(s)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        return ""
    if sam_only and p.hostname not in {"sam.gov", "www.sam.gov"}:
        return ""
    return urlunsplit((p.scheme, p.netloc, p.path,
                      urlencode([(k, v) for k, v in parse_qsl(p.query)
                                 if k.lower() not in {"api_key", "apikey"}]), p.fragment))


def due_date(value: Any) -> tuple[datetime | None, str]:
    if not value:
        return None, "Deadline not provided"
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            d = datetime.fromisoformat(text).replace(hour=23, minute=59, second=59, tzinfo=EASTERN)
            return d.astimezone(UTC), "Date-only deadline: Eastern end-of-day assumed; verify exact time"
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        note = ""
        if d.tzinfo is None:
            d = d.replace(tzinfo=EASTERN)
            note = "Deadline timezone missing: Eastern assumed; verify local time"
        return d.astimezone(UTC), note
    except ValueError:
        return None, "Unparseable deadline; manual verification required"


def normalize(raw: dict) -> dict:
    pop = raw.get("placeOfPerformance") or {}
    pops = pop if isinstance(pop, list) else [pop]
    pops = [p for p in pops if isinstance(p, dict)]
    def field(p: dict, key: str) -> str:
        v = p.get(key) or ""
        return str(v.get("code") or v.get("name") or "") if isinstance(v, dict) else str(v)
    code = raw.get("naicsCode")
    codes = raw.get("naicsCodes") or ([code] if code else [])
    if not isinstance(codes, list):
        codes = [codes]
    codes = [str(x.get("code") or x.get("naicsCode") or "") if isinstance(x, dict) else str(x) for x in codes]
    code = str(code or (codes[0] if codes else ""))
    nid = str(raw.get("noticeId") or "")
    kind = str(raw.get("type") or raw.get("baseType") or "")
    link = url_ok(raw.get("uiLink"), sam_only=True)
    if not link and re.fullmatch(r"[A-Za-z0-9-]+", nid):
        link = f"https://sam.gov/opp/{nid}/view"
    return {
        "id": nid, "title": plain(raw.get("title")), "url": link,
        "solicitation": str(raw.get("solicitationNumber") or ""),
        "agency": plain(raw.get("fullParentPathName") or raw.get("department")),
        "office_code": str(raw.get("fullParentPathCode") or ""),
        "posted": str(raw.get("postedDate") or ""),
        "deadline": str(raw.get("responseDeadLine") or raw.get("responseDeadline") or raw.get("reponseDeadLine") or ""),
        "type": TYPE_NAMES.get(kind.lower(), kind), "naics": code,
        "setaside_code": str(raw.get("typeOfSetAside") or raw.get("setAsideCode") or "").upper(),
        "setaside_text": plain(raw.get("typeOfSetAsideDescription") or raw.get("setAside") or ""),
        "active": str(raw.get("active") if raw.get("active") is not None else "unknown").lower(),
        "states": sorted({field(p, "state") for p in pops if field(p, "state")}),
        "location": "; ".join(", ".join(field(p, k) for k in ["city", "state", "country"] if field(p, k)) for p in pops) or "Place of performance not provided",
        "description_url": url_ok(raw.get("description")),
        "description": plain(raw.get("description_text")),
        "description_status": "provided" if raw.get("description_text") else "not fetched",
        "attachments": [url_ok(x) for x in (raw.get("resourceLinks") or []) if isinstance(x, str) and url_ok(x)],
        "refresh": "current", "prior_ids": [],
    }


def setaside(o: dict) -> str:
    c = o["setaside_code"]
    known = {"SDVOSBC": "SDVOSB", "SDVOSBS": "SDVOSB sole source",
             "VSA": "VOSB", "VSS": "VOSB sole source", "SBA": "Small business", "SBP": "Partial small business",
             "HZC": "HUBZone", "HZS": "HUBZone sole source", "8A": "8(a)", "8AN": "8(a) sole source",
             "WOSB": "WOSB", "WOSBSS": "WOSB sole source", "EDWOSB": "EDWOSB", "EDWOSBSS": "EDWOSB sole source",
             "IEE": "Indian enterprise", "ISBEE": "Indian small business", "BICIV": "Buy Indian", "LAS": "Local area"}
    if c in known:
        return known[c]
    if c and c not in {"NONE", "N/A", "NULL"}:
        return "Unknown designation: " + c
    t = o["setaside_text"].lower()
    for terms, label in [(["hubzone"], "HUBZone"), (["8(a)"], "8(a)"),
                         (["economically disadvantaged women", "edwosb"], "EDWOSB"),
                         (["women-owned", "wosb"], "WOSB"),
                         (["service-disabled", "service disabled", "sdvosb"], "SDVOSB"),
                         (["veteran-owned", "vosb"], "VOSB"), (["total small business"], "Small business")]:
        if any(term in t for term in terms):
            return label + (" sole source" if "sole source" in t else "")
    return "Not designated"


def workshare(code: str) -> str:
    jv = (" | Mentor-protege JV: the JV is the offeror and must meet the limitation as a whole; "
          "WTC as protege generally performs at least 40% of the work the JV performs.")
    if code.startswith(("236", "237")):
        now = "Prime/sub: general construction, normally <=85% to non-similarly-situated subs, excluding materials."
    elif code.startswith("238"):
        now = "Prime/sub: specialty trade, normally <=75% to non-similarly-situated subs, excluding materials."
    elif code.startswith(("31", "32", "33")):
        now = "Prime/sub: supply/manufacturing, verify nonmanufacturer rule and the 50% limitation."
    else:
        now = "Prime/sub: services, normally <=50% of amounts paid to non-similarly-situated subs."
    return now + jv


def in_team_scope(o: dict, cfg: dict) -> bool:
    code = o["naics"]
    if code in REGISTERED or (cfg["include_adjacent_naics"] and code in ADJACENT):
        return True
    text = (o["title"] + " " + o["description"]).lower()
    return any(has(text, t) for spec in FAMILIES.values() for t in spec[0])


def score(o: dict, cfg: dict, now: datetime) -> dict:
    o = dict(o)
    text = (o["title"] + " " + o["description"]).lower()
    sa, code = setaside(o), o["naics"]
    early = o["type"].lower() in {"sources sought", "presolicitation", "pre-solicitation"}
    va = "VETERANS AFFAIRS" in o["agency"].upper()
    matches = {name: [t for t in spec[0] if has(text, t)] for name, spec in FAMILIES.items()}
    matches = {name: terms for name, terms in matches.items() if terms}
    fam = max(matches, key=lambda k: len(matches[k])) if matches else CODE_FAMILY.get(code, "unverified specialty")
    reasons, risks, blocked = [], [], []
    if code in REGISTERED:
        fit = 35
        reasons.append("E2 Federal NAICS " + code)
    elif cfg["include_adjacent_naics"] and code in ADJACENT:
        fit = 30
        reasons.append("Adjacent team NAICS " + code)
    else:
        fit = 8 if matches else 0
    fit = min(50, fit + (15 if matches else 0))
    if matches:
        reasons.append("scope: " + ", ".join(t for ts in matches.values() for t in ts)[:200])
    sole = sa == "SDVOSB sole source" or has(text, "intent to sole source") or has(text, "intent to award sole source")
    if not sa.startswith("SDVOSB"):
        blocked.append("Not an SDVOSB set-aside (" + sa + ")")
        route, lane = 0, LANE_BLOCKED
    elif sole:
        route, lane = 2, LANE_SOLE
        risks.append("Sole source: not an open competition; review any capability-response avenue")
    elif early:
        route, lane = 12, LANE_EARLY
    else:
        route, lane = 20, LANE_COMPETITIVE
    if va:
        reasons.append("VA buyer (Veterans First)")
    due, date_note = due_date(o["deadline"])
    days = (due - now).total_seconds() / 86400 if due else None
    o["days_left"] = round(days, 1) if days is not None else None
    if o["refresh"] == "unavailable":
        lane = "Unverified saved notices"
        risks.append("Saved ID unavailable: cached status, scope and deadline are UNVERIFIED")
    elif o["active"] in {"no", "false", "0", "inactive", "archived", "cancelled"} or re.search(r"\bcancell?ed\b", o["title"], re.I):
        blocked.append("Notice inactive, archived or cancelled")
    elif days is not None and days < 0:
        blocked.append("Response deadline passed on refreshed notice")
    if o["active"] not in {"yes", "true", "1"} and o["refresh"] == "current":
        risks.append("Active status not affirmatively confirmed")
    if date_note:
        risks.append(date_note)
    timing = 15 if days is not None and days >= 21 else 12 if days is not None and days >= 10 else 7 if days is not None and days >= 4 else 2
    for risk, terms in RISK_TERMS.items():
        if any(has(text, t) for t in terms):
            risks.append(risk)
    if code.startswith(("236", "237", "238")):
        risks.append("Construction: plan licensing, bonding, safety and workshare for the offering entity")
    if code == "541330":
        risks.append("Check whether this is a qualifications-based A-E procurement (SF330)")
    if any(has(text, t) for t in ["clinical staffing", "nursing services", "physician services", "medical residency", "registered nurse", "anesthesiology"]):
        risks.append("Clinical/specialist delivery needs a qualified team; retained for review, not excluded.")
    agency = 10 if va else 7 if any(k in o["agency"].upper() for k in ["ENERGY", "NAVY", "CORPS OF ENGINEERS", "ENVIRONMENTAL PROTECTION"]) else 3
    geo = 5 if set(o["states"]) & set(cfg["preferred_states"]) else 3 if o["states"] else 1
    parts = {"team_scope_fit_50": fit, "contracting_route_20": route,
             "response_time_15": timing, "agency_fit_10": agency, "location_5": geo}
    total = sum(parts.values())
    if fam == "unverified specialty":
        risks.append("Specialty team structure requires team review; not excluded")
    if not o["description"] or o["description_status"].startswith("cached"):
        risks.append("Description not fetched today: title-only assessment")
        total = min(total, 64)
    if not due or o["active"] not in {"yes", "true", "1"} or o["refresh"] == "unavailable":
        total = min(total, 49)
    scoped = in_team_scope(o, cfg)
    if not scoped and lane in {LANE_COMPETITIVE, LANE_EARLY, LANE_SOLE}:
        lane = LANE_OUTSIDE
        risks.append("NAICS/scope outside the configured team list; retained for team review")
    if o["type"].lower() not in {"sources sought", "presolicitation", "pre-solicitation", "solicitation", "combined synopsis/solicitation"}:
        blocked.append("Not an actionable solicitation / market-research notice")
    if lane == LANE_SOLE:
        total = min(total, 54)  # intelligence only; never outranks open competitions
    if blocked:
        total, lane = 0, LANE_BLOCKED
    rating = "Priority review" if total >= 75 else "Qualify" if total >= 55 else "Watch / verify"
    if early and not blocked:
        rating = "Shape requirement - not a bid"
    if blocked:
        rating = "Do not pursue as currently classified"
    risks.append("Past performance: under prime/sub, E2 experience counts where the solicitation credits proposed subcontractors; under an approved mentor-protege JV, each member's experience is considered.")
    o.update(score=total, rating=rating, lane=lane, family=fam, setaside=sa, in_scope=scoped,
             components=parts, why=reasons, risks=risks, blockers=blocked,
             workshare=workshare(code), pathway=PATHWAY,
             roles=FAMILIES.get(fam, ([], "WTC: SDVOSB lead. E2: technical delivery. Identify any additional specialist partners."))[1],
             next_step="Review the solicitation and attachments, confirm E2 Federal interest and scope, and choose the delivery pathway (prime/sub now, mentor-protege JV once approved).")
    return o


class SamClient:
    def __init__(self, key: str, cfg: dict):
        if not key:
            raise RuntimeError("Missing SAM_API_KEY")
        self.key, self.cfg = key, cfg
        self.calls = 0
        self.queries: list[dict] = []
        self.session = requests.Session()

    def get(self, url: str, params: dict, description: bool = False) -> Any:
        p = urlsplit(url)
        if p.scheme != "https" or p.hostname != "api.sam.gov" or p.username or p.password:
            raise RuntimeError("Refusing credentialed request outside https://api.sam.gov")
        safe_query = {k: v for k, v in parse_qsl(p.query) if k.lower() not in {"api_key", "apikey"}}
        safe_query.update(params)
        safe_query["api_key"] = self.key
        clean_url = urlunsplit((p.scheme, p.netloc, p.path, "", ""))
        for attempt in range(4):
            if self.calls >= int(self.cfg["max_api_calls"]):
                raise RuntimeError("Configured API-call budget reached; discovery is INCOMPLETE")
            self.calls += 1
            time.sleep(0.15)
            try:
                r = self.session.get(clean_url, params=safe_query, timeout=45, allow_redirects=False)
            except requests.RequestException:
                if attempt == 3:
                    raise RuntimeError("SAM network failure after bounded retries") from None
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    if description:
                        return plain(r.text)[:40000]
                    raise RuntimeError("SAM search returned non-JSON response") from None
                if description:
                    if isinstance(data, dict):
                        return plain(data.get("description") or data.get("noticeDesc") or data.get("data"))[:40000]
                    return plain(data)[:40000]
                if not isinstance(data, dict) or "totalRecords" not in data:
                    raise RuntimeError("SAM response missing totalRecords; not treated as zero results")
                return data
            if r.status_code == 404 and description:
                return ""
            if r.status_code == 404 and "no data found" in r.text.lower():
                return {"totalRecords": 0, "opportunitiesData": []}
            if r.status_code == 429:
                try:
                    q = r.json()
                except ValueError:
                    q = {}
                if isinstance(q, dict) and q.get("nextAccessTime"):
                    raise RuntimeError("SAM daily quota exhausted; incomplete scan, prior state retained")
            if r.status_code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"SAM HTTP {r.status_code}; no credentials or response body logged")
            try:
                delay = float(r.headers.get("Retry-After", 2 ** attempt))
            except ValueError:
                delay = 2 ** attempt
            time.sleep(max(0, min(delay, 60)))
        raise RuntimeError("SAM retries exhausted")

    def search(self, params: dict) -> list[dict]:
        started, before = time.monotonic(), self.calls
        results, seen = [], set()
        try:
            for page in range(int(self.cfg["max_pages_per_query"])):
                data = self.get(SEARCH_URL, {**params, "limit": 1000, "offset": page})
                items = data.get("opportunitiesData") or []
                if not isinstance(items, list):
                    raise RuntimeError("SAM opportunitiesData is not a list")
                total = int(data["totalRecords"])
                if total == 0 and not items:
                    return results
                if not items:
                    raise RuntimeError("Pagination ended before reported total; scan incomplete")
                new = [x for x in items if x.get("noticeId") and x["noticeId"] not in seen]
                if not new:
                    raise RuntimeError("Repeated/invalid pagination page; scan incomplete")
                results.extend(new)
                seen.update(x["noticeId"] for x in new)
                if len(seen) >= total:
                    return results
            raise RuntimeError("Per-query page cap reached; scan incomplete")
        finally:
            self.queries.append({"params": params, "calls": self.calls - before,
                                 "records": len(results), "seconds": round(time.monotonic() - started, 2)})


def bounds(start, end) -> dict:
    return {"postedFrom": start.strftime("%m/%d/%Y"), "postedTo": end.strftime("%m/%d/%Y")}


def discover(client: SamClient, cfg: dict, now: datetime, previous: dict) -> dict:
    """Pull every SDVOSB set-aside notice posted in the window; team scope is scored locally."""
    today = now.date()
    first = not previous.get("last_success") or SDVOSB_BACKFILL not in previous.get("completed_backfills", [])
    days = int(cfg["initial_days"] if first else cfg["discovery_days"])
    seen = {}
    for code in SDVOSB_CODES:
        params = {**bounds(today - timedelta(days=days), today), "typeOfSetAside": code, "ptype": NOTICE_TYPES}
        for raw in client.search(params):
            o = normalize(raw)
            seen[o["id"]] = o
    return seen


def refresh_saved(client: SamClient, previous: dict, seen: dict, now: datetime) -> dict:
    """Refresh ID BEFORE using its old deadline; preserve unavailable IDs for retry."""
    for nid, old in previous.get("notices", {}).items():
        if nid in seen:
            continue
        try:
            posted = datetime.fromisoformat(old["posted"][:10]).date()
        except (ValueError, KeyError):
            posted = now.date() - timedelta(days=364)
        end, found = now.date(), None
        while end >= posted:
            start = max(posted, end - timedelta(days=364))
            rows = client.search({**bounds(start, end), "noticeid": nid})
            found = next((normalize(x) for x in rows if x.get("noticeId") == nid), None)
            if found:
                break
            end = start - timedelta(days=1)
        if found:
            found["prior_ids"] = old.get("prior_ids", [])
            seen[nid] = found
        else:
            candidates = [x for x in seen.values() if old.get("solicitation") and old.get("office_code")
                          and x["solicitation"] == old["solicitation"] and x["office_code"] == old["office_code"]
                          and x["posted"] > old.get("posted", "") and x["type"] == old.get("type")]
            if len(candidates) == 1:
                candidates[0]["prior_ids"] = list(dict.fromkeys(old.get("prior_ids", []) + [nid]))
            else:
                seen[nid] = {**old, "refresh": "unavailable"}
    return seen


def fingerprint(o: dict) -> str:
    fields = ["title", "solicitation", "agency", "office_code", "deadline", "type", "naics",
              "setaside_code", "setaside_text", "active", "location", "description", "attachments"]
    return hashlib.sha256(json.dumps({k: o.get(k) for k in fields}, sort_keys=True).encode()).hexdigest()


def classify_change(o: dict, previous: dict) -> str:
    old = previous.get("notices", {}).get(o["id"])
    if not old:
        old = next((previous.get("notices", {}).get(n) for n in o.get("prior_ids", [])
                    if previous.get("notices", {}).get(n)), None)
    if o["refresh"] == "unavailable":
        return "UNVERIFIED"
    return "NEW" if not old else "UPDATED" if fingerprint(o) != fingerprint(old) else "STILL OPEN"


REPORTABLE = (LANE_COMPETITIVE, LANE_EARLY, LANE_SOLE)


def ranked(rows: list[dict]) -> list[dict]:
    return sorted((o for o in rows if o["lane"] in REPORTABLE),
                  key=lambda x: (-x["score"], x["deadline"] or "9999"))


def choose(rows: list[dict], cfg: dict) -> list[dict]:
    """Top opportunities. No minimum score; headline count only limits email length."""
    return ranked(rows)[:int(cfg["max_highlights"])]


def shortlist(rows: list[dict], top: list[dict], cfg: dict) -> list[dict]:
    ids = {o["id"] for o in top}
    return [o for o in ranked(rows) if o["id"] not in ids][:int(cfg.get("shortlist_max", 15))]


def csv_safe(v: Any) -> str:
    text = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v if v is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")) else text


def urgency(o: dict) -> str:
    return "\u2757" if o.get("days_left") is not None and 0 <= o["days_left"] <= 3 else ""


def short_due(o: dict) -> str:
    due, _ = due_date(o["deadline"])
    return due.astimezone(EASTERN).strftime("%b %d, %Y %I:%M %p ET") if due else (o["deadline"] or "\u2014")


def tags(o: dict) -> list[str]:
    t = []
    if o.get("change") in {"NEW", "UPDATED"}:
        t.append(o["change"])
    t.append({LANE_COMPETITIVE: "SDVOSB set-aside", LANE_EARLY: "Early stage", LANE_SOLE: "Sole source"}.get(o["lane"], o["lane"]))
    if "VETERANS AFFAIRS" in o["agency"].upper():
        t.append("VA")
    if o["family"] != "unverified specialty":
        t.append(o["family"].title())
    return t


def why(o: dict) -> str:
    return "; ".join(o["why"][:3]) or "SDVOSB set-aside; review scope"


def stats_for(rows: list[dict]) -> dict:
    rep = [o for o in rows if o["lane"] in REPORTABLE]
    return {"in_scope": len(rep),
            "competitive": sum(o["lane"] == LANE_COMPETITIVE for o in rep),
            "early": sum(o["lane"] == LANE_EARLY for o in rep),
            "sole": sum(o["lane"] == LANE_SOLE for o in rep),
            "va": sum("VETERANS AFFAIRS" in o["agency"].upper() for o in rep),
            "outside": sum(o["lane"] == LANE_OUTSIDE for o in rows),
            "pulled": len(rows)}


EXPORT_FIELDS = ["rank_group", "score", "rating", "lane", "change", "title", "agency", "location", "type",
                 "setaside", "naics", "deadline", "days_left", "solicitation", "url", "why", "roles",
                 "workshare", "risks", "blockers", "components", "description_status", "refresh", "id"]


def export_rows(rows: list[dict], top: list[dict], short: list[dict]) -> list[dict]:
    t, sl = {o["id"] for o in top}, {o["id"] for o in short}
    out = []
    for o in sorted(rows, key=lambda x: -x["score"]):
        group = "Top" if o["id"] in t else "Other strong match" if o["id"] in sl else o["lane"]
        out.append({**o, "rank_group": group})
    return out


def write_xlsx(path: Path, rows: list[dict], st: dict, now: datetime) -> Path | None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except Exception:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = "SDVOSB Opportunities"
    ws.append(EXPORT_FIELDS)
    for o in rows:
        ws.append([csv_safe(o.get(k, "")) for k in EXPORT_FIELDS])
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=1):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes, ws.auto_filter.ref = "A2", ws.dimensions
    sm = wb.create_sheet("Summary")
    for r in [["Metric", "Value"], ["Generated", now.astimezone(EASTERN).strftime("%Y-%m-%d %H:%M ET")],
              ["SDVOSB notices pulled", st["pulled"]], ["In team scope", st["in_scope"]],
              ["Competitive SDVOSB set-asides", st["competitive"]], ["Early stage", st["early"]],
              ["Sole source (intel)", st["sole"]], ["VA buyers", st["va"]],
              ["SDVOSB outside team NAICS", st["outside"]], ["Team pathway", PATHWAY]]:
        sm.append(r)
    sm.column_dimensions["A"].width, sm.column_dimensions["B"].width = 34, 90
    wb.save(path)
    return path


def write_report(rows: list[dict], selected: list[dict], cfg: dict, now: datetime, out: Path, demo: bool) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    esc = lambda x: html.escape(str(x if x is not None else ""))
    top = selected
    short = shortlist(rows, top, cfg)
    st = stats_for(rows)
    local = now.astimezone(EASTERN)
    demo_tag = "DEMO - SYNTHETIC DATA - " if demo else ""
    title = demo_tag + "SDVOSB Team Opportunities \u2014 WTC + E2 Federal Services"

    # ---------- text ----------
    L = ["Good morning,", "",
         f"Today's SAM.gov scan of SDVOSB set-aside notices for the WTC / E2 Federal Services team.",
         "Team pathway: " + PATHWAY,
         f"New postings: last ~{cfg['discovery_days']} days. Open notices from prior reports refreshed daily through their deadlines.",
         f"SDVOSB notices pulled: {st['pulled']}",
         f"In team scope: {st['in_scope']}",
         f"  Competitive SDVOSB set-asides: {st['competitive']}",
         f"  Early stage (sources sought / presolicitation): {st['early']}",
         f"  Sole source (market intelligence): {st['sole']}",
         f"  VA buyers: {st['va']}",
         f"Top opportunities: {len(top)}",
         f"Other strong matches: {len(short)}",
         "\u2757 = response due within 3 days. NEW/UPDATED compare against prior reports.", "",
         "HIGH PRIORITY / TOP OPPORTUNITIES", "=" * 72]
    if not top:
        L.append("No top opportunities found for this run.")
    for n, o in enumerate(top, 1):
        L += [f"{n}) {urgency(o)} {o['title']}".replace(")  ", ") "),
              f"   - Score: {o['score']}/100 | {o['rating']}",
              f"   - Tags: {' | '.join(tags(o))}",
              f"   - Agency/Office: {o['agency'] or chr(8212)}",
              f"   - Location: {o['location']}",
              f"   - Set-aside: {o['setaside']} | Type: {o['type']}",
              f"   - Posted: {o['posted'][:10] or chr(8212)} | Due: {short_due(o)}",
              f"   - NAICS: {o['naics'] or chr(8212)} | Solicitation: {o['solicitation'] or chr(8212)}",
              f"   - Why it matters: {why(o)}",
              f"   - Team roles: {o['roles']}",
              f"   - Next step: {o['next_step']}",
              f"   - SAM link: {o['url']}", ""]
    L += ["OTHER STRONG MATCHES", "=" * 72]
    if not short:
        L.append("No additional matches for this run.")
    for o in short:
        label = {LANE_COMPETITIVE: "SDVOSB", LANE_EARLY: "Early stage", LANE_SOLE: "Sole source"}[o["lane"]]
        L += [f"- {urgency(o)} [{label}] {o['title']} | Score {o['score']} | "
              f"{o['location']} | Due {short_due(o)}".replace("-  [", "- ["), f"  {o['url']}"]
    L += ["", "Lower-ranked in-scope notices are not excluded; the full ranked list is attached (Excel/CSV), "
          "with team roles, workshare notes for both pathways, and review notes per row.",
          "Scores rank team fit (scope, set-aside route, time to respond, agency, location); they are not win probability or bid decisions."]
    unverified = sum(o["refresh"] == "unavailable" for o in rows)
    if unverified:
        L.append(f"{unverified} previously reported notice(s) could not be refreshed today; listed in the attachment for retry.")

    # ---------- html ----------
    td = "vertical-align:top;padding:8px;border-bottom:1px solid #ddd;"
    def card(n, o):
        chips = " ".join(f"<span style='background:#0B3D91;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-right:4px;'>{esc(t)}</span>" for t in tags(o))
        link = f"<a href=\"{esc(o['url'])}\">Open in SAM.gov</a>" if o["url"] else ""
        return (f"<tr><td style='{td}'>{n}</td><td style='{td}'>"
                f"<div style='font-weight:700;font-size:14px;'>{esc((urgency(o) + ' ' + o['title']).strip())}</div>"
                f"<div style='margin-top:4px;'>{chips}</div><div style='margin-top:4px;'>{link}</div>"
                f"<div style='margin-top:6px;color:#444;'><strong>Why it matters:</strong> {esc(why(o))}</div>"
                f"<div style='margin-top:4px;color:#444;'><strong>Team roles:</strong> {esc(o['roles'])}</div></td>"
                f"<td style='{td}'>{esc(o['agency'] or chr(8212))}</td><td style='{td}'>{esc(o['location'])}</td>"
                f"<td style='{td}'>{esc(o['setaside'])}<br><span style='color:#666;font-size:12px;'>{esc(o['type'])}</span></td>"
                f"<td style='{td}'>{esc(short_due(o))}</td>"
                f"<td style='{td}text-align:right;'>{o['score']}<br><span style='color:#666;font-size:12px;'>{esc(o['rating'])}</span></td></tr>")
    rows_html = "".join(card(n, o) for n, o in enumerate(top, 1)) or "<tr><td colspan='7' style='padding:10px;'>No high-priority opportunities found for this run.</td></tr>"
    items = "".join(
        f"<li style='margin-bottom:8px;'><strong>{esc((urgency(o) + ' ' + o['title']).strip())}</strong><br>"
        f"Score {o['score']} | {esc(o['location'])} | {esc(o['setaside'])} | Due {esc(short_due(o))}<br>"
        + (f"<a href=\"{esc(o['url'])}\">Open in SAM.gov</a>" if o["url"] else "") + "</li>"
        for o in short) or "<li>No additional matches for this run.</li>"
    th = "text-align:left;padding:8px;border-bottom:2px solid #ccc;"
    stat = lambda k, v: f"<td style='padding:8px 18px 8px 0;'><strong>{k}</strong><br>{v}</td>"
    page = f"""<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial, Helvetica, sans-serif;color:#222;line-height:1.35;">
  <h2 style="margin-bottom:4px;">{esc(title)}</h2>
  <p style="margin-top:0;color:#555;">Generated {local:%b %d, %Y %H:%M} ET. New SDVOSB postings: last ~{cfg['discovery_days']} days; open notices from prior reports refreshed daily.</p>
  <p style="color:#333;"><strong>Team pathway.</strong> {esc(PATHWAY)}</p>
  <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:12px 0 18px 0;"><tr>
    {stat('In team scope', st['in_scope'])}{stat('Competitive SDVOSB', st['competitive'])}{stat('Early stage', st['early'])}
    {stat('Sole source (intel)', st['sole'])}{stat('VA buyers', st['va'])}{stat('High priority', len(top))}
  </tr></table>
  <h3 style="margin-bottom:8px;">High Priority / Top Opportunities</h3>
  <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;width:100%;font-size:13px;">
    <thead><tr style="background:#f2f2f2;"><th style="{th}">#</th><th style="{th}">Opportunity</th><th style="{th}">Agency / Office</th>
    <th style="{th}">Location</th><th style="{th}">Set-aside</th><th style="{th}">Due</th><th style="text-align:right;padding:8px;border-bottom:2px solid #ccc;">Score</th></tr></thead>
    <tbody>{rows_html}</tbody></table>
  <h3 style="margin-top:22px;">Other Strong Matches</h3>
  <ol>{items}</ol>
  <p style="margin-top:18px;">Lower-ranked in-scope notices are not excluded. The full ranked list is attached (Excel/CSV) with team roles, workshare notes for both pathways, and review notes per row.</p>
  <p style="color:#666;font-size:12px;">Scores rank team fit (scope, set-aside route, time to respond, agency, location), not win probability or bid decisions. Attachments on SAM.gov are linked, not reviewed. Validate eligibility, workshare and past-performance treatment against each solicitation.</p>
</body></html>"""

    ex = export_rows(rows, top, short)
    paths = [out / "email_draft.txt", out / "email_draft.html", out / "sdvosb_team_opportunities.csv", out / "opportunities.json"]
    paths[0].write_text(("" if not demo else demo_tag + "\n\n") + "\n".join(L) + "\n", encoding="utf-8")
    paths[1].write_text(page, encoding="utf-8")
    with paths[2].open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        w.writeheader()
        w.writerows({k: csv_safe(o.get(k, "")) for k in EXPORT_FIELDS} for o in ex)
    paths[3].write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    x = write_xlsx(out / "sdvosb_team_opportunities.xlsx", ex, st, now)
    if x:
        paths.append(x)
    return paths


def email_report(paths: list[Path], cfg: dict, now: datetime, send: bool, demo: bool, rows: list[dict] | None = None, top_n: int = 0) -> None:
    recipients = [a for _, a in getaddresses([os.getenv("REPORT_TO") or os.getenv("EMAIL_TO") or cfg["email_to"]])]
    if not recipients or any("@" not in a or "\n" in a or "\r" in a for a in recipients):
        raise RuntimeError("Invalid report recipient")
    st = stats_for(rows or [])
    msg = EmailMessage()
    msg["Subject"] = (("DEMO - " if demo else "") + f"SDVOSB Team Opportunities \u2014 WTC + E2 Federal Services "
                      f"({st['in_scope']} in scope | {top_n} high priority | {st['va']} VA) \u2014 {now.astimezone(EASTERN):%b %d, %Y}")
    sender = os.getenv("FROM_EMAIL") or os.getenv("SMTP_USER") or cfg["email_to"]
    msg["From"], msg["To"] = sender, ", ".join(recipients)
    msg.set_content(paths[0].read_text(encoding="utf-8"))
    msg.add_alternative(paths[1].read_text(encoding="utf-8"), subtype="html")
    msg.add_attachment(paths[2].read_bytes(), maintype="text", subtype="csv", filename=paths[2].name)
    for extra in paths[4:]:
        msg.add_attachment(extra.read_bytes(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=extra.name)
    (paths[0].parent / "email_draft.eml").write_bytes(msg.as_bytes())
    if not send:
        return
    if demo:
        raise RuntimeError("Demo mode can never send email")
    user, password = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not user or not password:
        raise RuntimeError("SMTP_USER and SMTP_PASS are required for SEND_EMAIL=1; draft retained")
    host, port = os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=60, context=context) as smtp:
            smtp.login(user, password)
            refused = smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(user, password)
            refused = smtp.send_message(msg)
    if refused:
        raise RuntimeError("SMTP refused one or more recipients; state not advanced")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--config", type=Path, default=ROOT / "e2_sdvosb_config.json")
    parser.add_argument("--output", type=Path, default=ROOT / "e2_sdvosb_output")
    parser.add_argument("--state", type=Path, default=ROOT / "e2_sdvosb_state.json")
    args = parser.parse_args(argv)
    cfg = {**DEFAULTS, **(json.loads(args.config.read_text()) if args.config.exists() else {})}
    now, started = datetime.now(UTC), time.monotonic()
    client, success = None, False
    args.output.mkdir(parents=True, exist_ok=True)
    previous = {"version": STATE_VERSION, "notices": {}}
    try:
        if args.state.exists() and not args.demo:
            previous = json.loads(args.state.read_text())
            if previous.get("version") != STATE_VERSION or not isinstance(previous.get("notices"), dict):
                raise RuntimeError("Unsupported state file; refusing to reset the watchlist")
        if args.demo:
            raw = json.loads((ROOT / "examples/e2_sdvosb_demo.json").read_text())
            for i, item in enumerate(raw):
                item["postedDate"] = (now - timedelta(days=2)).isoformat()
                item["responseDeadLine"] = (now + timedelta(days=25 - i)).isoformat()
            seen = {o["id"]: o for o in map(normalize, raw)}
        else:
            client = SamClient(os.getenv("SAM_API_KEY", ""), cfg)
            seen = refresh_saved(client, previous, discover(client, cfg, now, previous), now)
            preliminary = sorted([score(o, cfg, now) for o in seen.values()], key=lambda o: -o["score"])
            eligible = [o for o in preliminary if not o["blockers"] and o["refresh"] == "current" and o["lane"] in REPORTABLE]
            eligible.sort(key=lambda o: (o["id"] not in previous.get("notices", {}), -o["score"]))
            for o in eligible[:int(cfg["description_limit"])]:
                target = seen[o["id"]]
                u = target["description_url"]
                if not u or urlsplit(u).hostname != "api.sam.gov":
                    target["description_status"] = "missing or untrusted description URL"
                    continue
                target["description"] = client.get(u, {}, description=True)
                target["description_status"] = "fetched" if target["description"] else "not available"
        for nid, o in seen.items():
            old = previous.get("notices", {}).get(nid, {})
            if not o["description"] and old.get("description") and o["refresh"] == "current":
                o["description"] = old["description"]
                o["description_status"] = "cached; not re-fetched today"
        rows = [score(o, cfg, now) for o in seen.values()]
        for o in rows:
            o["change"] = classify_change(o, previous)
        selected = choose(rows, cfg)
        paths = write_report(rows, selected, cfg, now, args.output, args.demo)
        email_report(paths, cfg, now, send=os.getenv("SEND_EMAIL", "0") == "1" and not args.demo, demo=args.demo,
                     rows=rows, top_n=len(selected))
        if not args.demo:
            tracked = set(previous["notices"]) | {o["id"] for o in selected}
            retained = {o["id"]: o for o in rows if o["id"] in tracked or any(i in tracked for i in o.get("prior_ids", []))}
            retained = {nid: o for nid, o in retained.items() if o["refresh"] == "unavailable" or not any(
                b in {"Notice inactive, archived or cancelled", "Response deadline passed on refreshed notice"}
                or b.startswith("Not an SDVOSB set-aside") for b in o["blockers"])}
            state = {"version": STATE_VERSION, "last_success": now.isoformat(), "notices": retained,
                     "completed_backfills": sorted(set(previous.get("completed_backfills", [])) | {SDVOSB_BACKFILL})}
            args.state.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.state.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            tmp.replace(args.state)
        success = True
        print(f"SDVOSB team report complete: {len(rows)} evaluated, {len(selected)} highlighted; email={'sent' if os.getenv('SEND_EMAIL') == '1' and not args.demo else 'draft only'}")
        return 0
    except Exception as exc:
        message = str(exc).replace(os.getenv("SAM_API_KEY") or "__NO_KEY__", "[REDACTED]")
        (args.output / "scan_failure.txt").write_text("SCAN FAILED - NOT A ZERO-OPPORTUNITY RESULT\n" + message + "\nPrior state retained.\n", encoding="utf-8")
        print("E2 scan failed: " + message, file=sys.stderr)
        return 1
    finally:
        metrics = {"success": success, "demo": args.demo, "generated_at": now.isoformat(),
                   "seconds": round(time.monotonic() - started, 2), "api_calls": client.calls if client else 0,
                   "queries": client.queries if client else [], "max_api_calls": cfg["max_api_calls"]}
        (args.output / "runtime_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
