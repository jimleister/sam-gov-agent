#!/usr/bin/env python3
"""Weston-prime / E2-subcontractor SAM.gov daily capture report. Python 3.10+.

Evaluate potential TEAM opportunities, not Weston's standalone delivery capacity.
Staffing, specialist partners, workshare, size and complexity are review notes,
never capacity-based exclusions or score penalties. No certifications, resources,
margins or win probability are inferred. Attachments require human review.
Run --demo for synthetic examples without API calls, production state or email.
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
# One-time historical discovery for newly added scope, even on an established watchlist.
DISCOVERY_BACKFILLS = {"562112": 90}
# family: (scope terms, possible team roles). No standalone-capacity scores.
FAMILIES = {
    "inspection / construction oversight": (
        ["construction inspection", "construction management", "welding inspection",
         "quality assurance", "quality control", "coating inspection", "project controls",
         "commissioning", "building inspection", "non-destructive testing"],
        "Possible team: Weston prime management and inspection delivery; E2 technical specialists, QA and surge support. Final staffing and work allocation to be developed."),
    "environmental / safety": (
        ["environmental consulting", "environmental compliance", "environmental assessment",
         "remediation", "industrial hygiene", "asbestos", "lead-based paint", "hazardous waste",
         "stormwater", "safety and health"],
        "Possible team: Weston prime management and field delivery; E2 environmental/scientific expertise and technical review; additional qualified partners as needed."),
    "facilities / utilities": (
        ["facilities support", "facility maintenance", "facilities maintenance", "base operations",
         "boiler", "chiller", "hvac", "utility systems", "water treatment", "wastewater",
         "electrical maintenance", "preventive maintenance", "building maintenance"],
        "Possible team: Weston prime operating management; E2 facilities, utility and technical support. Build the staffing and compliant workshare plan rather than assuming existing capacity."),
    "professional staffing / management": (
        ["staff augmentation", "technical staffing", "project management", "program management",
         "administrative support", "work planning", "records management"],
        "Possible team: Weston prime management and recruited delivery team; E2 specialist staff and proposal support. Employment, subcontracting and work allocation remain planning decisions."),
    "site / logistics support": (
        ["warehousing", "warehouse", "fleet management", "grounds maintenance", "landscaping",
         "solid waste", "logistics support", "expeditionary", "life support", "transportation"],
        "Possible team: Weston logistics/prime management; E2 facilities, environmental, utility and technical work packages; additional delivery partners as appropriate."),
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
    "Existing vehicle/holder access must be verified; E2 access does not transfer to Weston":
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
    "top_per_lane": 5, "max_highlights": 10,
    "preferred_states": ["NC", "SC", "VA", "CO", "PA"],
    "email_to": "jleister@westontrolley.com",
}


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
    if code.startswith(("236", "237")):
        return "General construction: normally <=85% to non-similarly-situated subs, excluding materials. Develop and validate the actual contract workshare."
    if code.startswith("238"):
        return "Specialty-trade construction: normally <=75% to non-similarly-situated subs, excluding materials. Develop and validate the actual contract workshare."
    if code.startswith(("31", "32", "33")):
        return "Supply/manufacturing: verify nonmanufacturer rule/waiver and applicable 50% subcontract limitation; do not apply a services shortcut."
    return "Services: normally <=50% of government payments to non-similarly-situated subs. Evaluate hiring, similarly situated partners and other compliant structures; not a reason to exclude the opportunity."


def score(o: dict, cfg: dict, now: datetime) -> dict:
    o = dict(o)
    text = (o["title"] + " " + o["description"]).lower()
    sa, code = setaside(o), o["naics"]
    early = o["type"].lower() in {"sources sought", "presolicitation", "pre-solicitation"}
    wex = has(text, "wexmac") or (has(text, "titus") and "NAVY" in o["agency"].upper())
    va = "VETERANS AFFAIRS" in o["agency"].upper()
    matches = {name: [t for t in spec[0] if has(text, t)] for name, spec in FAMILIES.items()}
    matches = {name: terms for name, terms in matches.items() if terms}
    fam = max(matches, key=lambda k: len(matches[k])) if matches else CODE_FAMILY.get(code, "unverified specialty")
    reasons, risks, blocked = [], [], []
    if code in REGISTERED:
        fit = 35
        reasons.append("E2 Federal SAM-derived NAICS match: " + code)
    elif cfg["include_adjacent_naics"] and code in ADJACENT:
        fit = 30
        reasons.append("Strategic adjacent NAICS (not verified E2 Federal registration): " + code)
    else:
        fit = 8 if matches else 0
    fit = min(50, fit + (15 if matches else 0))
    if matches:
        reasons.append("Scope signals: " + ", ".join(t for ts in matches.values() for t in ts)[:240])
    if sa.startswith("SDVOSB"):
        route, lane = 20, "SDVOSB prime candidates"
    elif early and va:
        route, lane = 14, "Early-stage / market shaping"
    elif sa.startswith("VOSB") or sa in {"Small business", "Partial small business"}:
        route, lane = 12, "Secondary teaming candidates"
    else:
        route, lane = 5, "Secondary teaming candidates"
    if early:
        lane = "Early-stage / market shaping"
    if wex:
        lane = "WEXMAC public-notice watch"
        risks.append("WEXMAC: verify Weston's specific award/region/task-order access. This public scan cannot see holder-only orders; TITUS access is not assumed.")
    if sa.startswith(("8(a)", "WOSB", "EDWOSB", "Indian", "Buy Indian")):
        blocked.append("Required certification not established for Weston: " + sa)
    if sa.startswith("HUBZone") and not cfg["hubzone_certified"]:
        blocked.append("HUBZone is a prospective pathway, not a confirmed certification")
    if sa.startswith("Unknown") or sa == "Local area":
        risks.append("Set-aside eligibility requires manual verification: " + sa)
    if "sole source" in sa.lower() or has(text, "intent to sole source") or has(text, "intent to award sole source"):
        lane = "Market intelligence / sole-source watch"
        risks.append("Not treated as an open competition; review any capability-response avenue")
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
    # A team can add staff, partners and resources. No prime-only capacity proxy.
    for risk, terms in RISK_TERMS.items():
        if any(has(text, t) for t in terms):
            risks.append(risk)
    if code.startswith(("236", "237", "238")):
        risks.append("Construction: develop prime licensing, bonding, safety and workshare arrangements")
    if code == "541330":
        risks.append("Confirm whether this is qualifications-based A-E procurement and address prime licensing/experience requirements in the team structure")
    if any(has(text, t) for t in ["clinical staffing", "nursing services", "physician services", "medical residency", "registered nurse", "anesthesiology"]):
        risks.append("Clinical/specialist delivery needs a qualified team; capability is not established by this scan. Retained for review, not excluded.")
    agency = 10 if va else 7 if any(k in o["agency"].upper() for k in ["ENERGY", "NAVY", "CORPS OF ENGINEERS", "ENVIRONMENTAL PROTECTION"]) else 3
    geo = 5 if set(o["states"]) & set(cfg["preferred_states"]) else 3 if o["states"] else 1
    parts = {"team_scope_fit_50": fit, "contracting_route_20": route,
             "response_time_15": timing, "agency_fit_10": agency, "location_5": geo}
    total = sum(parts.values())
    if fam == "unverified specialty" and not wex:
        risks.append("Specialty team structure requires review; lack of a configured discipline does not exclude this opportunity")
    if not o["description"] or o["description_status"].startswith("cached"):
        risks.append("Description unavailable/not fetched: title-only assessment; attachments not reviewed")
        total = min(total, 64)
    if not due or o["active"] not in {"yes", "true", "1"} or o["refresh"] == "unavailable":
        total = min(total, 49)
    if code not in REGISTERED and code not in ADJACENT and not matches and not wex:
        risks.append("Scope alignment not established by current metadata; retained for team review")
    if o["type"].lower() not in {"sources sought", "presolicitation", "pre-solicitation", "solicitation", "combined synopsis/solicitation"}:
        if not wex:
            blocked.append("Not an actionable solicitation / market-research notice")
        else:
            lane = "WEXMAC public-notice watch"
    if blocked:
        total, lane = 0, "Excluded / blocked"
    rating = "Priority review" if total >= 75 else "Qualify" if total >= 55 else "Watch / verify"
    if early and not blocked:
        rating = "Shape requirement - not a bid"
    if blocked:
        rating = "Do not pursue as currently classified"
    risks.append("Define staffing, specialist partners, workshare and prime control with Weston/E2; these are planning items, not capacity-based rejection reasons. Check requirements at the applicable proposal, award and performance stages.")
    risks.append("Confirm solicitation permits proposed subcontractor experience; E2/JV past performance is not automatically Weston's")
    o.update(score=total, rating=rating, lane=lane, family=fam, setaside=sa,
             components=parts, why=reasons, risks=risks, blockers=blocked,
             workshare=workshare(code), roles=FAMILIES.get(fam, ([], "Weston/E2: identify the necessary personnel, specialist partners and compliant prime/sub work split."))[1],
             next_step="Review solicitation/attachments and eligibility; assess the combined team and additional partners, obtain E2 scope/pricing, and develop the delivery and workshare structure. Do not require Weston to perform the whole scope alone.")
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
    today = now.date()
    codes = sorted(set(REGISTERED) | (set(ADJACENT) if cfg["include_adjacent_naics"] else set()))
    seen = {}
    first = not previous.get("last_success")
    for i, code in enumerate(codes):
        days = 364 if i % 7 == today.weekday() else int(cfg["initial_days"] if first else cfg["discovery_days"])
        if code not in previous.get("completed_backfills", []):
            days = max(days, DISCOVERY_BACKFILLS.get(code, 0))
        for raw in client.search({**bounds(today - timedelta(days=days), today), "ncode": code}):
            o = normalize(raw)
            seen[o["id"]] = o
    for term in ["WEXMAC", "TITUS"]:
        for raw in client.search({**bounds(today - timedelta(days=90 if first else 7), today), "title": term}):
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


def choose(rows: list[dict], cfg: dict) -> list[dict]:
    chosen, counts = [], {}
    for o in sorted(rows, key=lambda x: (-x["score"], x["deadline"] or "9999")):
        lane = o["lane"]
        if lane == "Excluded / blocked":
            continue
        # Headline limits control email length, not opportunity retention.
        # No minimum score: remaining candidates appear in the full email index.
        if counts.get(lane, 0) >= int(cfg["top_per_lane"]):
            continue
        chosen.append(o)
        counts[lane] = counts.get(lane, 0) + 1
        if len(chosen) >= int(cfg["max_highlights"]):
            break
    return chosen


def csv_safe(v: Any) -> str:
    text = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v if v is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")) else text


def write_report(rows: list[dict], selected: list[dict], cfg: dict, now: datetime, out: Path, demo: bool) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    tag = "DEMO - SYNTHETIC DATA - " if demo else ""
    headline = tag + "Weston prime + E2 technical partner | Daily capture report"
    intro = ("Scores rank potential TEAM opportunity fit, NOT Weston's standalone capacity, win probability or bid approval. "
             "No capacity, staffing, workshare, contract-size, complexity, licensing, bonding or clearance assumption causes exclusion or a score penalty. "
             "These are review notes; the team and delivery structure are to be developed. "
             "Weston is the proposed SDVOSB prime; E2 is a non-similarly-situated technical subcontractor unless established otherwise. "
             "No JV, HUBZone approval, bonding, clearance or transferable past performance is assumed. "
             "Contract value, profit and incumbent are unknown unless separately verified. Attachments are linked, not parsed. "
             "Saved notices are refreshed before old deadlines are applied. Public SAM does not expose all WEXMAC holder-only task orders.")
    coverage = (f"Generated {now.astimezone(EASTERN).isoformat()}. {len(rows)} records evaluated; {len(selected)} highlighted. "
                "Every non-blocked record is shown below or in the additional ranked index, with all records in the CSV/JSON archive. "
                "Only detailed highlights and previously tracked records enter the persistent watchlist. "
                f"Discovery: {cfg['discovery_days']}-day rolling window; {cfg['initial_days']}-day initial window; "
                "one-year backfill rotates across codes weekly. This is a bounded search, not an exhaustive universe of all procurement notices. "
                "E2 Federal: RRM2YJMNTPX1 / 14TE2; 17 corroborated SAM-derived codes, direct entity export pending.")
    lines = [headline, "", coverage, "", intro, ""]
    panels = [f"<h1>{html.escape(headline)}</h1><p>{html.escape(coverage)}</p><p>{html.escape(intro)}</p>"]
    lanes = ["SDVOSB prime candidates", "Early-stage / market shaping", "Secondary teaming candidates",
             "WEXMAC public-notice watch", "Market intelligence / sole-source watch", "Unverified saved notices"]
    for lane in lanes:
        entries = [o for o in selected if o["lane"] == lane]
        if not entries:
            continue
        lines.append(lane.upper())
        panels.append(f"<h2>{html.escape(lane)}</h2>")
        for o in entries:
            urgency = "DUE WITHIN 72 HOURS | " if o["days_left"] is not None and 0 <= o["days_left"] <= 3 else ""
            title = f"{o['score']}/100 | {o['rating']} | {o['change']} | {urgency}{o['title']}"
            body = [f"{o['agency']} | {o['location']}",
                    f"{o['type']} | {o['setaside']} | NAICS {o['naics']} | Solicitation {o['solicitation'] or 'not supplied'}",
                    f"Deadline: {o['deadline'] or 'not supplied'} | Days remaining: {o['days_left']}",
                    "Why: " + "; ".join(o["why"]),
                    "Score breakdown: " + json.dumps(o["components"]),
                    "Notice excerpt (" + o["description_status"] + "): " + (o["description"][:550] or "Description unavailable - verify source"),
                    "Possible roles: " + o["roles"], "Workshare review: " + o["workshare"],
                    "Review / structuring notes: " + "; ".join(o["risks"]), "Next action: " + o["next_step"],
                    "Source: " + o["url"]]
            lines += [title, *body, ""]
            panels.append('<article><h3>' + html.escape(title) + '</h3>' +
                          ''.join('<p>' + html.escape(x) + '</p>' for x in body[:-1]) +
                          (f'<p><a href="{html.escape(o["url"], quote=True)}">Open SAM.gov notice</a></p>' if o["url"] else '') + '</article>')
    if not selected:
        msg = "No current candidate notices were available for highlights in this successful scan. No filler recommendations were created."
        lines.append(msg)
        panels.append("<p>" + msg + "</p>")
    selected_ids = {o["id"] for o in selected}
    additional = sorted((o for o in rows if o["id"] not in selected_ids and o["lane"] != "Excluded / blocked"),
                        key=lambda x: (-x["score"], x["deadline"] or "9999"))
    if additional:
        lines += ["", "ADDITIONAL RANKED OPPORTUNITIES - NOT EXCLUDED",
                  "These remain in the candidate pool. Headline space is limited; a low score is not a no-bid decision."]
        panels.append("<h2>Additional ranked opportunities - not excluded</h2><p>All other candidates, including lower-scoring and verification-needed records. Headline space is limited; a low score is not a no-bid decision.</p>")
        panels.append("<table style='width:100%;border-collapse:collapse'><thead><tr><th>Score</th><th>Opportunity</th><th>Deadline / review notes</th></tr></thead><tbody>")
        for o in additional:
            review = "; ".join(o["risks"])
            lines += [f"{o['score']}/100 | {o['lane']} | {o['title']}",
                      f"{o['agency']} | NAICS {o['naics']} | {o['setaside']} | Deadline: {o['deadline'] or 'not supplied'}",
                      "Review: " + review, "Source: " + o["url"], ""]
            label = html.escape(o["title"])
            if o["url"]:
                label = f'<a href="{html.escape(o["url"], quote=True)}">{label}</a>'
            panels.append("<tr><td style='vertical-align:top;padding:8px'>" + str(o["score"]) +
                          "</td><td style='vertical-align:top;padding:8px'>" + label + "<br>" +
                          html.escape(o["lane"] + " | " + o["agency"] + " | " + o["setaside"]) +
                          "</td><td style='vertical-align:top;padding:8px'>" +
                          html.escape(o["deadline"] or "Deadline not supplied") + "<br>" + html.escape(review) + "</td></tr>")
        panels.append("</tbody></table>")
    blocked_count = sum(o["lane"] == "Excluded / blocked" for o in rows)
    if blocked_count:
        note = (f"{blocked_count} records are separated from the candidate list because of notice status/type "
                "or an unestablished set-aside certification, not assumed delivery capacity. Their exact reasons remain in the full CSV/JSON archive.")
        lines.append(note)
        panels.append("<p>" + html.escape(note) + "</p>")
    tracked_missing = [o for o in rows if o["refresh"] == "unavailable"]
    if tracked_missing:
        warning = "UNVERIFIED SAVED NOTICES: " + "; ".join(o["id"] + " " + o["title"] for o in tracked_missing)
        lines += [warning]
        panels.append("<p><strong>" + html.escape(warning) + "</strong></p>")
    footer = ("Opportunity discovery does not decide the final team or work allocation. Staffing, partners and workshare are review items, not automatic no-bid decisions. "
              "Check SBA certification, size, licensing, bonding, experience and control requirements at the applicable proposal, award and performance stages. "
              "Resolve owner employment/conflict-of-interest issues with counsel. No proposals or outreach are sent by this scanner.")
    sources = ["https://www.acquisition.gov/far/52.219-14",
               "https://www.ecfr.gov/current/title-13/chapter-I/part-121/section-121.103",
               "https://open.gsa.gov/api/get-opportunities-public-api/",
               "https://e2.com/services/federal-services/"]
    lines += [footer, "Sources / rules: " + " | ".join(sources)]
    panels += ["<p>" + html.escape(footer) + "</p>", "<p>Sources: " + " | ".join(f'<a href="{s}">{html.escape(s)}</a>' for s in sources) + "</p>"]
    paths = [out / "email_draft.txt", out / "email_draft.html", out / "opportunities.csv", out / "opportunities.json"]
    paths[0].write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths[1].write_text('<!doctype html><html><head><meta charset="utf-8"><style>body{font:15px Arial,sans-serif;max-width:1050px;margin:auto;padding:24px;line-height:1.5;color:#172b4d}h1{font-size:26px}h2{border-bottom:2px solid #246b75;padding-top:18px}article{border:1px solid #ccd5df;border-left:5px solid #246b75;padding:15px;margin:16px 0}p{margin:8px 0}a{color:#125f92}</style></head><body>' + "".join(panels) + '</body></html>', encoding="utf-8")
    fields = ["score", "rating", "lane", "change", "title", "agency", "location", "type", "setaside", "naics", "deadline", "days_left", "solicitation", "url", "why", "risks", "blockers", "workshare", "roles", "components", "description_status", "refresh"]
    with paths[2].open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: csv_safe(o.get(k, "")) for k in fields} for o in sorted(rows, key=lambda x: -x["score"]))
    paths[3].write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths


def email_report(paths: list[Path], cfg: dict, now: datetime, send: bool, demo: bool) -> None:
    recipients = [a for _, a in getaddresses([os.getenv("REPORT_TO") or os.getenv("EMAIL_TO") or cfg["email_to"]])]
    if not recipients or any("@" not in a or "\n" in a or "\r" in a for a in recipients):
        raise RuntimeError("Invalid report recipient")
    msg = EmailMessage()
    msg["Subject"] = ("DEMO - " if demo else "") + "Weston + E2 | SDVOSB team opportunity fit | " + now.astimezone(EASTERN).strftime("%Y-%m-%d")
    sender = os.getenv("FROM_EMAIL") or os.getenv("SMTP_USER") or cfg["email_to"]
    msg["From"], msg["To"] = sender, ", ".join(recipients)
    msg.set_content(paths[0].read_text(encoding="utf-8"))
    msg.add_alternative(paths[1].read_text(encoding="utf-8"), subtype="html")
    msg.add_attachment(paths[2].read_bytes(), maintype="text", subtype="csv", filename="e2_sdvosb_opportunities.csv")
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
            eligible = [o for o in preliminary if not o["blockers"] and o["refresh"] == "current"]
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
        email_report(paths, cfg, now, send=os.getenv("SEND_EMAIL", "0") == "1" and not args.demo, demo=args.demo)
        if not args.demo:
            tracked = set(previous["notices"]) | {o["id"] for o in selected}
            retained = {o["id"]: o for o in rows if o["id"] in tracked or any(i in tracked for i in o.get("prior_ids", []))}
            retained = {nid: o for nid, o in retained.items() if o["refresh"] == "unavailable" or not any(
                b in {"Notice inactive, archived or cancelled", "Response deadline passed on refreshed notice"} for b in o["blockers"])}
            state = {"version": STATE_VERSION, "last_success": now.isoformat(), "notices": retained,
                     "completed_backfills": sorted(set(previous.get("completed_backfills", [])) |
                         {code for code in DISCOVERY_BACKFILLS if code in REGISTERED or
                          (cfg["include_adjacent_naics"] and code in ADJACENT)})}
            args.state.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.state.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            tmp.replace(args.state)
        success = True
        print(f"E2 SDVOSB report complete: {len(rows)} evaluated, {len(selected)} highlighted; email={'sent' if os.getenv('SEND_EMAIL') == '1' and not args.demo else 'draft only'}")
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
