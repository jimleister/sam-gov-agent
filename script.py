#!/usr/bin/env python3
"""
SAM.gov Daily Scan (Get Opportunities Public API v2)

Goals (updated)
- Pull opportunities posted in the last 72 hours, Active only, for notice types:
  Sources Sought, Presolicitation, Solicitation, Combined Synopsis/Solicitation
- Use OR-logic across structured “signal families” (state, NAICS, PSC):
  run multiple API searches -> union -> dedupe by noticeId
- Match keywords LOCALLY (title + description). No API q= keyword searches.
- Rank Top opportunities by a FEASIBILITY ratio derived from:
    Profitability (higher is better) vs (Complexity + Overhead) (lower is better)
  Relevance (number of matched signals) is a light tiebreaker.
- Top 5–10 should be drawn from *all* matches (keywords/NAICS/PSC/state/org/etc),
  with no “core keyword” gating/boosting.
- Shortlist 10–20: next-best items (including state-only matches).

Email output
- Writes ./email_draft.txt and prints to stdout.
- Includes To and Cc headers (configurable).
- Does NOT include any API keys.
- Optional: can send via Gmail SMTP if you set SEND_EMAIL=1 and SMTP env vars (see below).

Secrets
- Requires SAM_API_KEY in environment.

Optional SMTP sending (Gmail)
- Set these env vars (recommended in ~/.zprofile), and set SEND_EMAIL=1:
  SMTP_HOST="smtp.gmail.com"
  SMTP_PORT="587"
  SMTP_USER="westontrolley@gmail.com"
  SMTP_PASS="<Gmail App Password>"   # NOT your normal password
  FROM_EMAIL="westontrolley@gmail.com"
"""

from __future__ import annotations

import os
import sys
import json
import time
import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Optional

import requests

# Optional SMTP (only used if SEND_EMAIL=1)
import smtplib
from email.message import EmailMessage


# -----------------------------
# CONFIG
# -----------------------------

SAM_SEARCH_URL = "https://api.sam.gov/prod/opportunities/v2/search"

NOTICE_TYPES = ["r", "p", "o", "k"]  # Sources Sought, Presolicitation, Solicitation, Combined Synopsis/Solicitation
POSTED_WINDOW_HOURS = 72
ACTIVE_ONLY = True

# LOCAL keyword filtering only (no API q=)
# Weston Trolley target universe: passenger transportation, trolley/shuttle/circulator
# operations, visitor transport, fleet maintenance, paratransit/microtransit, and
# event/concession transportation. VOSB/small-business language is handled below
# as set-aside signals and scoring boosters.
KEYWORDS = [
    # core trolley / shuttle / bus operations
    "trolley", "trolley service", "historic trolley", "streetcar",
    "shuttle", "shuttle service", "bus shuttle", "courtesy shuttle",
    "circulator", "downtown circulator", "visitor shuttle", "park shuttle",
    "transit operations", "transportation services", "passenger transportation",
    "ground transportation", "surface transportation", "fixed route",
    "bus service", "motor coach", "motorcoach", "charter bus", "coach bus",

    # municipal / campus / event / tourism use cases
    "event transportation", "special event transportation", "festival shuttle",
    "campus shuttle", "employee shuttle", "commuter shuttle",
    "tour transportation", "sightseeing", "visitor transportation",
    "concessionaire", "concession", "recreation area", "national park",
    "theme park", "fairgrounds", "parking shuttle", "lot shuttle",

    # accessibility / community transport
    "paratransit", "microtransit", "demand response", "non-emergency transportation",
    "mobility services", "senior transportation", "ada transportation",

    # fleet, drivers, dispatch, maintenance
    "vehicle operator", "driver services", "bus operator", "dispatch",
    "fleet maintenance", "vehicle maintenance", "preventive maintenance",
    "bus maintenance", "transit vehicle", "vehicle leasing", "vehicle rental",

    # agency/market signals
    "department of transportation", "dot", "transit authority", "municipal transportation",
    "public transportation", "mass transit", "airport shuttle", "base shuttle",
    "department of veterans affairs", "veterans affairs", "va medical center",
    "department of the interior", "national park service", "nps", "forest service",
    "department of defense", "dod", "installation shuttle", "base transportation",
]

# PSC / classificationCode (signals)
# V-codes generally represent transportation/travel-type services; J/W codes catch
# maintenance/lease/rental-related opportunities that may support vehicle fleet work.
PSCS = [
    "V212", "V222", "V225", "V226", "V227", "V229",
    "V999", "R706", "R799", "M1LZ", "S216",
    "J023", "J025", "J099", "W023", "W025",
]

# NAICS (signals) — Weston Trolley / ground passenger transportation universe
NAICS = [
    "485113",  # Bus and Other Motor Vehicle Transit Systems
    "485119",  # Other Urban Transit Systems
    "485210",  # Interurban and Rural Bus Transportation
    "485310",  # Taxi and Ridesharing Services
    "485320",  # Limousine Service
    "485410",  # School and Employee Bus Transportation
    "485510",  # Charter Bus Industry
    "485991",  # Special Needs Transportation
    "485999",  # Other Transit and Ground Passenger Transportation
    "487110",  # Scenic and Sightseeing Transportation, Land
    "488490",  # Other Support Activities for Road Transportation
    "532111",  # Passenger Car Rental
    "532112",  # Passenger Car Leasing
    "532120",  # Truck, Utility Trailer, and RV Rental and Leasing
    "541614",  # Process/Logistics Consulting Services
    "561210",  # Facilities Support Services
    "561320",  # Temporary Help Services (drivers/operators when bundled)
    "561599",  # All Other Travel Arrangement and Reservation Services
    "561920",  # Convention and Trade Show Organizers
    "721214",  # Recreational and Vacation Camps
    "811111",  # General Automotive Repair
    "811118",  # Other Automotive Mechanical/Electrical Repair
    "811198",  # All Other Automotive Repair and Maintenance
    "811310",  # Commercial/Industrial Machinery Repair and Maintenance
]

# Organization codes as LOCAL signals (prefix match on fullParentPathCode)
# Kept broad because Weston Trolley opportunities may come from transportation,
# installation/base support, parks/visitor services, VA, and municipal-adjacent agencies.
ORG_CODES = {
    "DOT": "069",
    "VA": "036",
    "DOI": "014",
    "NPS": "014103",
    "USDA": "012",
    "DOD": "097",
    "GSA": "047",
}

# Place of performance: US states/territories (signals)
# Preserves the existing script regions and adds the previously discussed upper-midwest / mountain states.
POP_STATES = sorted(set([
    "NC", "SC", "VA", "CO", "PA", "PR", "GU",
    "MN", "ND", "SD", "WI",
]))

# International PoP targets (signals)
# South Asia, South America, Central America, and Caribbean coverage. Country names
# are matched locally in title/description/agency text after structured searches return.
POP_COUNTRIES = sorted(set([
    # South Asia
    "Afghanistan", "Bangladesh", "Bhutan", "India", "Maldives",
    "Nepal", "Pakistan", "Sri Lanka",

    # South America
    "Argentina", "Bolivia", "Brazil", "Chile", "Colombia", "Ecuador",
    "Guyana", "Paraguay", "Peru", "Suriname", "Uruguay", "Venezuela",

    # Central America
    "Belize", "Costa Rica", "El Salvador", "Guatemala", "Honduras",
    "Nicaragua", "Panama",

    # Caribbean
    "Anguilla", "Antigua", "Antigua and Barbuda", "Aruba", "Bahamas",
    "Barbados", "Bermuda", "Bonaire", "British Virgin Islands",
    "Cayman Islands", "Cuba", "Curacao", "Dominica", "Dominican Republic",
    "Grenada", "Guadeloupe", "Haiti", "Jamaica", "Martinique",
    "Montserrat", "Puerto Rico", "Saint Barthelemy", "Saint Kitts",
    "Saint Kitts and Nevis", "Saint Lucia", "Saint Martin",
    "Saint Vincent", "Saint Vincent and the Grenadines", "Sint Maarten",
    "Trinidad", "Trinidad and Tobago", "Turks and Caicos",
    "U.S. Virgin Islands", "US Virgin Islands", "Virgin Islands",
]))

# Set-aside signals inferred locally from title/description. Weston qualifies for
# Veteran-Owned Small Business and Small Business set-asides.
SETASIDE_KEYWORDS = [
    "VOSB", "Veteran-Owned", "Veteran Owned", "Veteran-Owned Small Business",
    "Veteran Owned Small Business", "SDVOSB", "Service-Disabled",
    "Service Disabled Veteran Owned", "Service-Disabled Veteran-Owned",
    "Small Business", "Total Small Business", "Small Business Set-Aside",
    "SBSA", "set-aside", "set aside",
]

# Logistics-only terms: overhead bump but NOT automatically an international advantage.
LOGISTICS_TERMS = [
    "guam", "puerto rico", "u.s. virgin islands", "us virgin islands",
    "oconus", "overseas", "remote site", "island", "ferry",
]

# Email recipients (prefer env vars so you don't edit code)
EMAIL_TO = os.getenv("REPORT_TO", "jleister@westontrolley.com")
EMAIL_CC = os.getenv("REPORT_CC", "pgurung@westontrolley.com, manish@zenjatra.com")
EMAIL_SUBJECT_BASE = "SAM.gov Opportunities – last 72 hours (Feasibility Ranked)"

TOP_MIN, TOP_MAX = 5, 10
SHORTLIST_MIN, SHORTLIST_MAX = 10, 20

# Performance caps
MAX_PER_JOB = 2000        # max records to pull per query job
MAX_TOTAL_DEDUPED = 6000  # stop early once enough deduped candidates exist
SLEEP_SECONDS = 0.12

# Feasibility scoring weights
# Score = (Profitability / (Complexity + Overhead)) * 10  +  0.15 * RelevanceSignals
FEASIBILITY_MULT = 10.0
RELEVANCE_WEIGHT = 0.15
MAX_RELEVANCE = 10.0


# -----------------------------
# OPTIONAL SMTP CONFIG (send only if SEND_EMAIL=1)
# -----------------------------
SEND_EMAIL = os.getenv("SEND_EMAIL", "0").strip() == "1"
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)


# -----------------------------
# DATA MODEL
# -----------------------------
@dataclass
class Opportunity:
    noticeId: str
    title: str
    uiLink: str
    postedDate: Optional[str] = None
    responseDeadLine: Optional[str] = None
    type: Optional[str] = None
    baseType: Optional[str] = None
    fullParentPathName: Optional[str] = None
    fullParentPathCode: Optional[str] = None
    naicsCodes: List[str] = field(default_factory=list)
    classificationCode: Optional[str] = None
    active: Optional[str] = None
    office_state: Optional[str] = None
    description_url: Optional[str] = None
    resourceLinks: List[str] = field(default_factory=list)

    # derived
    why_matched: List[str] = field(default_factory=list)
    description_text: str = ""
    keyword_hits: List[str] = field(default_factory=list)

    ratings: Dict[str, Any] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    next_step: str = ""
    score: float = 0.0
    feasibility: float = 0.0


# -----------------------------
# HELPERS
# -----------------------------
def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def mmddyyyy(d: dt.date) -> str:
    return d.strftime("%m/%d/%Y")


def parse_iso_date(iso_dt: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
    except Exception:
        return None


def sam_search(api_key: str, params: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    q = dict(params)
    q["api_key"] = api_key
    r = requests.get(SAM_SEARCH_URL, params=q, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"SAM API error {r.status_code}: {r.text[:800]}")
    return r.json()


def sam_fetch_description(desc_url: str, timeout: int = 60) -> str:
    """
    desc_url often is a v1 noticedesc endpoint; public but can be flaky.
    Best-effort pull.
    """
    if not desc_url:
        return ""
    try:
        r = requests.get(desc_url, timeout=timeout)
        if r.status_code != 200:
            return ""
        ctype = r.headers.get("content-type", "")
        if "application/json" in ctype:
            data = r.json()
            for k in ("description", "noticeDesc", "data"):
                if isinstance(data.get(k), str):
                    return data[k][:20000]
            return json.dumps(data)[:20000]
        return r.text[:20000]
    except Exception:
        return ""


def normalize(item: Dict[str, Any]) -> Opportunity:
    office = item.get("officeAddress") or {}
    return Opportunity(
        noticeId=item.get("noticeId") or "",
        title=item.get("title") or "",
        uiLink=item.get("uiLink") or "",
        postedDate=item.get("postedDate"),
        responseDeadLine=item.get("responseDeadLine") or item.get("responseDeadline"),
        type=item.get("type"),
        baseType=item.get("baseType"),
        fullParentPathName=item.get("fullParentPathName"),
        fullParentPathCode=item.get("fullParentPathCode"),
        naicsCodes=item.get("naicsCodes") or ([item["naicsCode"]] if item.get("naicsCode") else []),
        classificationCode=item.get("classificationCode"),
        active=item.get("active"),
        office_state=office.get("state"),
        description_url=item.get("description"),
        resourceLinks=item.get("resourceLinks") or [],
    )


def hard_filters_ok(opp: Opportunity, today: dt.date, due_max: dt.date) -> bool:
    if ACTIVE_ONLY and (opp.active or "").lower() != "yes":
        return False

    # due within next year (best-effort)
    if opp.responseDeadLine:
        due_dt = parse_iso_date(opp.responseDeadLine)
        if due_dt and not (today <= due_dt.date() <= due_max):
            return False

    return True


def keyword_hits_local(text: str) -> List[str]:
    t = (text or "").lower()
    hits = []
    for kw in KEYWORDS:
        k = kw.lower()
        if k and k in t:
            hits.append(kw)
    # de-dupe but keep order
    out: List[str] = []
    seen = set()
    for h in hits:
        if h not in seen:
            out.append(h)
            seen.add(h)
    return out


def add_job_tag(opp: Opportunity, job_tag: str) -> None:
    tag = f"signal:{job_tag}"
    if tag not in opp.why_matched:
        opp.why_matched.append(tag)


def add_structural_reasons(opp: Opportunity) -> None:
    # PSC
    if opp.classificationCode and opp.classificationCode.upper() in {p.upper() for p in PSCS}:
        opp.why_matched.append(f"PSC:{opp.classificationCode}")

    # NAICS
    naics_hit = sorted(set(opp.naicsCodes).intersection(NAICS))
    if naics_hit:
        opp.why_matched.append("NAICS:" + ",".join(naics_hit))

    # Org codes (prefix match on fullParentPathCode)
    if opp.fullParentPathCode:
        for name, code in ORG_CODES.items():
            if str(opp.fullParentPathCode).startswith(str(code)):
                opp.why_matched.append(f"Org:{name}({code})")
                break

    # Office state weak signal
    if opp.office_state and opp.office_state.upper() in set(POP_STATES):
        opp.why_matched.append(f"OfficeState:{opp.office_state.upper()}")


# -----------------------------
# RATING LOGIC
# -----------------------------
def estimate_ratings(opp: Opportunity) -> None:
    """
    Ratings:
    - Complexity (1–5): execution difficulty (security, compliance, integration, uncertainty)
    - Profitability (1–5): margin potential (specialization, barriers, your advantage)
    - Overhead (1–5): bid/admin/mobilization burden (clearances, construction admin, travel/logistics)

    International advantage: ONLY explicit target countries
    Guam/OCONUS/Overseas: overhead bump only (not treated as international advantage)
    """
    text = f"{opp.title}\n{opp.type}\n{opp.baseType}\n{opp.fullParentPathName}\n{opp.description_text}".lower()

    complexity = 3
    profitability = 3
    overhead = 3
    evidence: List[str] = []

    # Lower complexity / overhead: routine passenger transportation and vehicle service work
    if any(w in text for w in [
        "shuttle", "trolley", "bus service", "driver services", "vehicle operator",
        "dispatch", "fixed route", "preventive maintenance", "vehicle maintenance",
        "fleet maintenance", "repair"
    ]):
        complexity = max(1, complexity - 1)
        overhead = max(1, overhead - 1)
        evidence.append("Routine passenger transportation/fleet service indicators detected (lower execution complexity/admin burden).")

    # Higher complexity/overhead: heavy compliance, construction, technology integration, or multi-site operations
    if any(w in text for w in [
        "sf330", "a-e", "architect", "engineer", "davis-bacon", "bonding", "construction",
        "software integration", "fare collection", "multi-site", "nationwide", "24/7", "twenty four seven"
    ]):
        complexity = min(5, complexity + 1)
        overhead = min(5, overhead + 1)
        evidence.append("Complex compliance/integration/multi-site indicators detected (heavier coordination/proposal burden).")

    # Security/clearances
    if any(w in text for w in ["classified", "sipr", "secret", "top secret"]):
        complexity = min(5, complexity + 2)
        overhead = min(5, overhead + 2)
        evidence.append("Security/clearance language detected (raises complexity and overhead).")

    # International advantage: ONLY explicit countries
    if any(ct.lower() in text for ct in [c.lower() for c in POP_COUNTRIES]):
        overhead = min(5, overhead + 1)
        profitability = min(5, profitability + 1)
        evidence.append("International country signal detected (logistics overhead exists, but also a competitive advantage).")

    # Logistics-only terms (no profitability boost)
    if any(term in text for term in LOGISTICS_TERMS):
        overhead = min(5, overhead + 1)
        evidence.append("Remote/OCONUS logistics indicator detected (overhead higher; not treated as international advantage).")

    # Profitability boosters: barriers
    if any(w in text for w in ["oem", "authorized", "brand name", "sole source"]):
        profitability = min(5, profitability + 1)
        evidence.append("Barrier-to-entry indicator (OEM/authorized/sole-source cues) may reduce competition.")

    # Profitability boosters: specialization / fit to Weston Trolley
    if any(w in text for w in [
        "trolley", "historic trolley", "streetcar", "shuttle", "circulator",
        "visitor transportation", "park shuttle", "event transportation",
        "charter bus", "motor coach", "motorcoach", "paratransit", "microtransit"
    ]):
        profitability = min(5, profitability + 1)
        evidence.append("Strong Weston Trolley domain fit (trolley/shuttle/passenger transport) may support stronger margin and proposal credibility.")

    # Set-aside signal
    if any(s.lower() in text for s in [x.lower() for x in SETASIDE_KEYWORDS]):
        profitability = min(5, profitability + 1)
        evidence.append("VOSB/small-business set-aside language detected (eligibility/competition advantage).")

    opp.ratings = {"complexity": complexity, "profitability": profitability, "overhead": overhead}
    opp.evidence = evidence[:5]
    opp.next_step = (
        "Open the SAM notice and download attachments; confirm route scope, vehicle requirements, driver/insurance/licensing, "
        "set-aside eligibility, mobilization location, and decide prime vs. teaming."
    )


def compute_score(opp: Opportunity) -> float:
    """
    Feasibility-driven ranking (no “core keyword” gating/boosting):
      feasibility = Profitability / (Complexity + Overhead)
      score = feasibility * 10 + 0.15 * relevance_signals
    """
    rel = min(MAX_RELEVANCE, float(len(set(opp.why_matched))))

    c = float(opp.ratings.get("complexity", 3))
    o = float(opp.ratings.get("overhead", 3))
    p = float(opp.ratings.get("profitability", 3))

    denom = max(1.0, c + o)
    feasibility = p / denom
    opp.feasibility = feasibility

    return feasibility * FEASIBILITY_MULT + rel * RELEVANCE_WEIGHT


def build_email(top: List[Opportunity], shortlist: List[Opportunity], as_of: dt.datetime) -> str:
    lines: List[str] = []
    lines.append(f"To: {EMAIL_TO}")
    if EMAIL_CC.strip():
        lines.append(f"Cc: {EMAIL_CC}")
    lines.append(f"Subject: {EMAIL_SUBJECT_BASE} — {as_of:%b %d, %Y}")
    lines.append("")
    lines.append(f"Daily SAM.gov scan (posted last ~{POSTED_WINDOW_HOURS} hours). Ranked by feasibility = Profitability / (Complexity + Overhead).")
    lines.append("")

    lines.append(f"TOP OPPORTUNITIES ({len(top)})")
    lines.append("=" * 72)
    for i, opp in enumerate(top, 1):
        c = opp.ratings["complexity"]
        p = opp.ratings["profitability"]
        o = opp.ratings["overhead"]
        feas = opp.feasibility

        lines.append(f"{i}) {opp.title}")
        lines.append(f"   - Notice Type: {opp.type} | Posted: {opp.postedDate or '—'} | Due: {opp.responseDeadLine or '—'}")
        lines.append(f"   - Agency/Office: {opp.fullParentPathName or '—'}")
        lines.append(f"   - NAICS: {', '.join(opp.naicsCodes) if opp.naicsCodes else '—'} | PSC: {opp.classificationCode or '—'}")
        if opp.keyword_hits:
            lines.append(f"   - Keyword hits: {', '.join(opp.keyword_hits[:6])}")
        lines.append(f"   - Feasibility: {feas:.2f}  (P/(C+O) = {p}/({c}+{o}))")
        lines.append(f"   - Ratings: Complexity {c}/5 | Profitability {p}/5 | Overhead {o}/5")
        lines.append(f"   - Why it matched: {', '.join(dict.fromkeys(opp.why_matched)) if opp.why_matched else '—'}")
        if opp.evidence:
            lines.append("   - Evidence:")
            for ev in opp.evidence:
                lines.append(f"     • {ev}")
        lines.append(f"   - Recommended next step: {opp.next_step}")
        lines.append(f"   - SAM link: {opp.uiLink}")
        if opp.resourceLinks:
            lines.append(f"   - Attachments: {len(opp.resourceLinks)} file(s)")
        lines.append("")

    lines.append(f"NEXT-BEST SHORTLIST ({len(shortlist)})")
    lines.append("=" * 72)
    for opp in shortlist:
        c = opp.ratings.get("complexity", 3)
        p = opp.ratings.get("profitability", 3)
        o = opp.ratings.get("overhead", 3)
        feas = opp.feasibility
        reason = ", ".join(list(dict.fromkeys(opp.why_matched))[:2]) if opp.why_matched else "signal match"
        lines.append(f"- {opp.title} (Feas={feas:.2f}, C={c}/5, P={p}/5, O={o}/5) — {reason}")
        lines.append(f"  {opp.uiLink}")

    lines.append("")
    return "\n".join(lines)


def send_email(subject: str, body: str) -> None:
    if not SEND_EMAIL:
        return
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SEND_EMAIL=1 but SMTP_USER/SMTP_PASS not set.")

    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = EMAIL_TO
    if EMAIL_CC.strip():
        msg["Cc"] = EMAIL_CC
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


# -----------------------------
# MAIN
# -----------------------------
def run() -> int:
    api_key = require_env("SAM_API_KEY")

    now = dt.datetime.now()
    today = now.date()
    posted_from = (now - dt.timedelta(hours=POSTED_WINDOW_HOURS)).date()
    posted_to = today
    due_max = today + dt.timedelta(days=365)

    base = {
        "postedFrom": mmddyyyy(posted_from),
        "postedTo": mmddyyyy(posted_to),
        "ptype": ",".join(NOTICE_TYPES),
        "active": "Yes" if ACTIVE_ONLY else "No",
        "limit": 1000,
    }

    # Jobs: structured filters only (no q=)
    jobs: List[Tuple[str, Dict[str, Any]]] = []

    # PoP states
    for st in POP_STATES:
        jobs.append((f"state:{st}", {**base, "state": st}))

    # NAICS: single-code calls
    for code in NAICS:
        jobs.append((f"naics:{code}", {**base, "ncode": code}))

    # PSC: single-code calls
    for code in PSCS:
        jobs.append((f"psc:{code}", {**base, "ccode": code}))

    seen: Dict[str, Opportunity] = {}
    total_calls = 0
    job_counts: Dict[str, int] = {}

    for job_name, params in jobs:
        offset = 0
        while True:
            p = dict(params)
            p["offset"] = offset
            data = sam_search(api_key, p)
            total_calls += 1

            items = data.get("opportunitiesData") or []
            job_counts[job_name] = job_counts.get(job_name, 0) + len(items)

            if not items:
                break

            for item in items:
                opp = normalize(item)
                if not opp.noticeId:
                    continue
                if opp.noticeId not in seen:
                    seen[opp.noticeId] = opp
                add_job_tag(seen[opp.noticeId], job_name)

            if len(items) < int(p["limit"]):
                break

            offset += int(p["limit"])
            if offset > 10000:
                break
            if offset >= MAX_PER_JOB:
                break
            if len(seen) >= MAX_TOTAL_DEDUPED:
                break

            time.sleep(SLEEP_SECONDS)

        if len(seen) >= MAX_TOTAL_DEDUPED:
            break

    scored: List[Opportunity] = []
    for opp in seen.values():
        if not hard_filters_ok(opp, today=today, due_max=due_max):
            continue

        add_structural_reasons(opp)

        # Description (best-effort)
        opp.description_text = sam_fetch_description(opp.description_url)
        text_lower = (opp.description_text or "").lower()

        # Local keyword hits
        opp.keyword_hits = keyword_hits_local(f"{opp.title} {opp.fullParentPathName or ''} {opp.description_text}")
        if opp.keyword_hits:
            opp.why_matched.append("keyword:text " + ", ".join(opp.keyword_hits[:4]))

        # International country mentions (signals)
        for ctry in POP_COUNTRIES:
            if ctry.lower() in text_lower:
                opp.why_matched.append(f"POP:{ctry}")

        # Set-aside mentions (signals)
        if any(s.lower() in text_lower for s in [x.lower() for x in SETASIDE_KEYWORDS]):
            opp.why_matched.append("set-aside:text veteran")

        estimate_ratings(opp)
        opp.score = compute_score(opp)
        scored.append(opp)

    scored.sort(key=lambda x: x.score, reverse=True)

    top = scored[:TOP_MAX]
    if len(top) < TOP_MIN:
        top = scored[:max(TOP_MIN, len(scored))]

    top_ids = {o.noticeId for o in top}
    remaining = [o for o in scored if o.noticeId not in top_ids]

    shortlist = remaining[:SHORTLIST_MAX]
    if len(shortlist) < SHORTLIST_MIN:
        shortlist = remaining[:max(SHORTLIST_MIN, len(remaining))]

    email_text = build_email(top, shortlist, now)

    with open("email_draft.txt", "w", encoding="utf-8") as f:
        f.write(email_text)

    print(email_text)

    subject = f"{EMAIL_SUBJECT_BASE} — {now:%b %d, %Y}"
    send_email(subject, email_text)

    print(
        f"\n[INFO] API calls: {total_calls} | Deduped candidates: {len(seen)} | Scored candidates: {len(scored)} | Top: {len(top)} | Shortlist: {len(shortlist)} | SEND_EMAIL={int(SEND_EMAIL)}",
        file=sys.stderr
    )
    for k in sorted(job_counts, key=lambda x: (-job_counts[x], x)):
        print(f"[JOB] {k}: {job_counts[k]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
