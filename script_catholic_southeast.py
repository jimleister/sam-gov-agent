#!/usr/bin/env python3
"""
SAM.gov Daily Scan — Catholic institutions (VA/GA/SC/KY/WV/DC) + Full NC Sweep.

Fourth scanner in the Weston scan fleet. Complements script.py (WEXMAC
logistics), script_pest.py (pest/vector management), and
script_usace_asia.py (USACE + South/Southeast Asia). This one narrows on a
keyword theme (Catholic institutions) across a set of Southeast/Mid-Atlantic
states, plus a full, unfiltered sweep of North Carolina.

Scope (hard filter — items outside are dropped, not just deprioritized):
- North Carolina: ANY opportunity with place of performance OR issuing office
  in NC is included — any agency, any domain, any keyword. Full coverage.
  SDVOSB set-asides within this NC feed are tagged/boosted for visibility,
  but they are not a separate filter — they're already part of "all of NC."
- Virginia, Georgia, South Carolina, Kentucky, West Virginia, DC: included
  ONLY if the notice text (title/agency-path/description) hits a Catholic
  institution keyword (diocese, archdiocese, parish, Catholic school, etc.).
  No domain/NAICS restriction — any type of work counts if the keyword hits.
- Everything else (other states, or one of the six above with no Catholic
  keyword match) is dropped from this scan.

Ranking:
- Domain families (Weston-adjacent: passenger transport, logistics,
  facilities/base-ops, construction, security) score relevance but do NOT
  filter.
- NC gets a baseline priority boost so the full sweep doesn't get buried
  under Catholic-keyword hits from the other six states.
- Catholic-keyword matches get their own boost (that's the point of this
  scanner for those six states).
- SDVOSB (and VOSB) set-asides get a strong boost; SDVOSB inside NC gets an
  extra "double-hit" bump so the sweet spot floats to the top.

Candidate discovery:
- One SAM.gov search job per target state using the API's native
  place-of-performance "state" parameter (NC, VA, GA, SC, KY, WV, DC).
- Plus one unrestricted "global-sweep" job (no state/NAICS/PSC filter) as a
  safety net, since SAM.gov's state field is sometimes empty/inconsistent
  and an office based in one of these states can post a notice whose POP
  field doesn't reflect it. Everything the sweep turns up still goes through
  the same hard scope filter above.

Email + CSV + XLSX output mirrors the existing scripts so the workflow file
patterns are identical.

Env vars:
- SAM_API_KEY (required)
- REPORT_TO / EMAIL_TO (recipient; defaults to jleister@westontrolley.com)
- REPORT_CC / EMAIL_CC (optional cc)
- SEND_EMAIL=1 + SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/FROM_EMAIL to send.
"""

from __future__ import annotations

import os
import sys
import re
import json
import time
import csv
import html
import mimetypes
from pathlib import Path
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

# -----------------------------
# GEOGRAPHY
# -----------------------------

# The one state that gets full, unfiltered coverage.
FULL_SWEEP_STATE = "NC"

# States where only Catholic-keyword matches are in scope.
CATHOLIC_ONLY_STATES = ["VA", "GA", "SC", "KY", "WV", "DC"]

# All target states for candidate discovery.
TARGET_STATES = [FULL_SWEEP_STATE] + CATHOLIC_ONLY_STATES

# -----------------------------
# CATHOLIC KEYWORD LIST
# -----------------------------
# Broad list, as requested — covers institutions, clergy/religious life, and
# related terminology. Word-boundary matched (see term_matches), so this
# won't false-positive on things like "Shriners" containing "shrine". Tune
# this list the same way the USACE/Asia scanner's QC/QS list got tuned, if
# it turns out too broad or too narrow in practice.
CATHOLIC_TERMS = [
    "catholic", "roman catholic", "diocese", "diocesan", "archdiocese",
    "parish", "parochial", "rectory", "cathedral", "basilica",
    "catholic charities", "catholic school", "catholic university",
    "catholic hospital", "catholic relief services", "catholic diocese",
    "seminary", "convent", "monastery", "friary", "abbey", "novitiate",
    "shrine", "pilgrimage", "knights of columbus", "usccb",
    "sisters of", "brothers of", "religious order", "eucharistic congress",
    "diocesan school", "archbishop", "bishop's office",
]

# -----------------------------
# BROAD FAN-OUT NAICS / PSC
# -----------------------------
# Not used to restrict candidate discovery (discovery is state-based / global
# sweep, per the "any domain" scope decision). Used only for the informational
# "why_matched" structural tags and to feed the domain-family ranking below.
NAICS = [
    # Passenger transport (Weston core)
    "485113", "485119", "485210", "485310", "485320", "485410", "485510",
    "485991", "485999", "487110",
    # Freight/logistics/warehousing
    "484110", "484121", "484122", "484220", "484230", "488320", "488390",
    "488410", "488490", "488510", "488991", "488999", "492110", "492210",
    "493110", "493190", "541614", "561210", "561320", "561599", "561920",
    "561990",
    # Rental/lease/maintenance of vehicles and equipment
    "532111", "532112", "532120", "532289", "532411", "532412", "811111",
    "811118", "811198", "811310",
    # Facilities / custodial / food service / base ops
    "221310", "236220", "238990", "561612", "561720", "561730", "561740",
    "561790", "562111", "562112", "562119", "722310", "722320", "722410",
    # Construction / renovation / trades
    "236118", "237110", "237130", "237310", "238110", "238120", "238160",
    "238210", "238220", "238290", "238320", "238350", "541330",
    # Security
    "561612", "561621",
]

PSCS = [
    # Transportation / travel / vehicle operations
    "V003", "V112", "V119", "V122", "V129", "V212", "V222", "V225", "V226",
    "V227", "V229", "V999",
    # Logistics / warehousing / support services
    "R405", "R408", "R499", "R602", "R604", "R605", "R606", "R706", "R799",
    "S216", "S205", "S206", "S208", "S209",
    # Rental/lease/maintenance
    "W023", "W025", "W039", "W099", "J023", "J025", "J039", "J099",
    # Facilities / base support / food-water-life support / custodial
    "M1LZ", "S201", "S203", "S211", "S222", "S299", "S208",
    # Construction / renovation (general, non-USACE-specific)
    "Y1AA", "Y1BA", "Y1CA", "Y1DA", "Y1EA", "Y1FA", "Y1LZ", "Y1PA", "Y1QA",
    "Y1ZZ", "Z1AA", "Z1BA", "Z1CA", "Z1DA", "Z1LZ", "Z1ZZ",
    # Security guard services
    "R707", "R799",
]

# -----------------------------
# SCORING WEIGHTS
# -----------------------------

# NC gets a baseline boost so the full sweep isn't buried under Catholic
# keyword hits from the other six states.
NC_BOOST = 12.0
# Catholic-keyword match (the six non-NC states) — the point of this scanner.
CATHOLIC_MATCH_BOOST = 20.0
# NC + SDVOSB double-hit — the sweet spot for this scanner.
NC_SDVOSB_DOUBLE_HIT_BOOST = 15.0

# Set-aside boosts (matches the other scripts' pattern).
SDVOSB_SETASIDE_CODES = {"SDVOSBC", "SDVOSBS"}
VOSB_SETASIDE_CODES = {"VSA", "VSS"}
SMALLBIZ_SETASIDE_CODES = {"SBA", "SBP"}
SDVOSB_PRIORITY_BOOST = 25.0
VOSB_PRIORITY_BOOST = 12.0

# Weston-adjacent domain families — used for RANKING (not filtering), so a
# Catholic-institution HVAC repair with no logistics content still surfaces,
# it just ranks below one that has transport/logistics content.
DOMAIN_FAMILIES = {
    "Weston core passenger transport": {
        "weight": 22,
        "terms": [
            "trolley", "streetcar", "shuttle", "bus service", "charter bus",
            "motor coach", "motorcoach", "passenger transportation",
            "ground transportation", "circulator", "visitor transportation",
            "pilgrimage transportation", "retreat transportation",
            "paratransit", "microtransit", "driver services",
            "vehicle operator", "bus operator", "fixed route",
            "transit operations", "school bus", "student transportation",
            "field trip transportation", "funeral procession",
        ],
    },
    "Logistics and transportation support": {
        "weight": 18,
        "terms": [
            "cargo truck", "cargo van", "light duty truck", "flatbed",
            "vehicle rental", "vehicle leasing", "with driver",
            "without driver", "logistics support", "movement support",
            "loading", "unloading", "freight", "drayage", "cargo handling",
            "courier", "delivery",
        ],
    },
    "Warehousing and supply chain": {
        "weight": 12,
        "terms": [
            "warehouse", "warehousing", "storage services", "supply chain",
            "inventory", "materials management", "packing", "crating",
            "distribution",
        ],
    },
    "Facilities, base ops and life support": {
        "weight": 20,
        "terms": [
            "custodial", "janitorial", "housekeeping", "grounds maintenance",
            "landscaping", "food service", "catering", "cafeteria",
            "trash removal", "waste management", "generator", "hvac",
            "boiler", "plumbing", "electrical repair", "laundry",
            "event support", "portable sanitary", "banquet", "kitchen",
        ],
    },
    "Construction and renovation": {
        "weight": 14,
        "terms": [
            "construction", "renovation", "remodel", "roof repair",
            "roofing", "building repair", "site preparation", "earthwork",
            "design-build", "design build", "architect-engineer",
            "a-e services", "sf330", "engineering services",
        ],
    },
    "Security and force protection": {
        "weight": 10,
        "terms": [
            "security guard", "security guards", "force protection",
            "access control", "surveillance camera", "alarm monitoring",
        ],
    },
}

# Buyer-fit terms — weak ranking signal for likely-relevant buyer types.
BUYER_FIT_TERMS = {
    "Catholic diocese / archdiocese": [
        "diocese", "archdiocese", "parish", "catholic",
    ],
    "Catholic education": [
        "catholic school", "catholic university", "diocesan school",
    ],
    "Federal / DoD chaplaincy": [
        "chaplain", "chapel", "chaplaincy",
    ],
}

SETASIDE_BOOST_TERMS = {
    "VOSB/SDVOSB": [
        "vosb", "veteran-owned", "veteran owned", "sdvosb",
        "service-disabled", "service disabled veteran",
    ],
    "Small business": [
        "small business", "total small business", "small business set-aside",
        "sbsa", "set-aside", "set aside",
    ],
}

MAX_RELEVANCE = 10.0

# -----------------------------
# EMAIL / RUN CONFIG
# -----------------------------

EMAIL_TO = (
    (os.getenv("REPORT_TO") or "").strip()
    or (os.getenv("EMAIL_TO") or "").strip()
    or "jleister@westontrolley.com"
)
EMAIL_CC = (
    (os.getenv("REPORT_CC") or "").strip()
    or (os.getenv("EMAIL_CC") or "").strip()
)
EMAIL_SUBJECT_BASE = "SAM.gov Catholic Institutions (VA/GA/SC/KY/WV/DC) + Full NC Sweep"

TOP_MIN, TOP_MAX = 5, 10
SHORTLIST_MIN, SHORTLIST_MAX = 10, 20

MAX_PER_JOB = 2000
MAX_TOTAL_DEDUPED = 8000
SLEEP_SECONDS = 0.12

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
    typeOfSetAside: Optional[str] = None
    typeOfSetAsideDescription: Optional[str] = None

    # POP (extracted from structured placeOfPerformance)
    pop_country_code: Optional[str] = None
    pop_country_name: Optional[str] = None
    pop_state_code: Optional[str] = None
    pop_state_name: Optional[str] = None
    pop_city_name: Optional[str] = None

    # derived
    state_bucket: Optional[str] = None   # which target state(s) this hit, "NC" or a catholic-only state
    is_nc: bool = False
    catholic_hits: List[str] = field(default_factory=list)
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
    """Best-effort pull of a v1 noticedesc endpoint."""
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


def _pop_first(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    SAM.gov v2 opportunities API returns placeOfPerformance as an object OR a
    list of objects (multi-site notices). Pick the first non-empty one.
    """
    pop = item.get("placeOfPerformance")
    if isinstance(pop, list):
        for x in pop:
            if isinstance(x, dict) and (x.get("country") or x.get("state") or x.get("city")):
                return x
        return {}
    if isinstance(pop, dict):
        return pop
    return {}


def _extract_pop_field(pop_obj: Dict[str, Any], key: str) -> Tuple[Optional[str], Optional[str]]:
    node = pop_obj.get(key)
    if isinstance(node, dict):
        return (node.get("code"), node.get("name"))
    if isinstance(node, str):
        return (None, node)
    return (None, None)


def normalize(item: Dict[str, Any]) -> Opportunity:
    office = item.get("officeAddress") or {}
    pop = _pop_first(item)
    country_code, country_name = _extract_pop_field(pop, "country")
    state_code, state_name = _extract_pop_field(pop, "state")
    _, city_name = _extract_pop_field(pop, "city")

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
        typeOfSetAside=item.get("typeOfSetAside"),
        typeOfSetAsideDescription=item.get("typeOfSetAsideDescription"),
        pop_country_code=country_code,
        pop_country_name=country_name,
        pop_state_code=state_code,
        pop_state_name=state_name,
        pop_city_name=city_name,
    )


def term_matches(text: str, term: str) -> bool:
    """
    Whole-word/phrase match. Avoids substring false positives like 'shrine'
    matching inside 'shriners'. Multi-word phrases match as phrases with
    flexible whitespace.
    """
    term = (term or "").strip().lower()
    if not term:
        return False
    escaped = re.escape(term)
    escaped = re.sub(r"\\\s+", r"\\s+", escaped)
    pattern = r"(?<!\w)" + escaped + r"(?!\w)"
    return re.search(pattern, text) is not None


def _hits(text: str, terms: List[str]) -> List[str]:
    out: List[str] = []
    for term in terms:
        if term_matches(text, term):
            out.append(term)
    return list(dict.fromkeys(out))


def _opp_states(opp: Opportunity) -> set:
    """States this opportunity touches — POP state and/or issuing office state."""
    pop_state = (opp.pop_state_code or "").strip().upper()
    office_state = (opp.office_state or "").strip().upper()
    return {s for s in (pop_state, office_state) if s}


def include_by_scope(opp: Opportunity) -> Tuple[bool, str]:
    """
    Apply the hard geography/keyword filter.

    Include when:
      - NC is among the opportunity's POP state / office state: ALWAYS
        include, any agency, any domain. Full coverage.
      - One of {VA, GA, SC, KY, WV, DC} is among the POP/office state AND the
        notice text (title/agency-path/description) hits a Catholic keyword.
      - Anything else is dropped.

    Returns (include?, reason).
    """
    states_hit = _opp_states(opp)

    if FULL_SWEEP_STATE in states_hit:
        opp.is_nc = True
        return True, "NC — full coverage (all agencies/domains)"

    catholic_states_hit = states_hit & set(CATHOLIC_ONLY_STATES)
    if catholic_states_hit:
        text = " ".join(filter(None, [opp.title, opp.fullParentPathName, opp.description_text])).lower()
        hits = _hits(text, CATHOLIC_TERMS)
        if hits:
            opp.catholic_hits = hits[:10]
            state_label = ",".join(sorted(catholic_states_hit))
            return True, f"Catholic match ({state_label}): {', '.join(hits[:3])}"
        state_label = ",".join(sorted(catholic_states_hit))
        return False, f"{state_label} dropped — no Catholic keyword match"

    pop = opp.pop_state_code or "?"
    office = opp.office_state or "?"
    return False, f"Outside target states (pop={pop}, office={office})"


def hard_filters_ok(opp: Opportunity, today: dt.date, due_max: dt.date) -> bool:
    if ACTIVE_ONLY and (opp.active or "").lower() != "yes":
        return False
    if opp.responseDeadLine:
        due_dt = parse_iso_date(opp.responseDeadLine)
        if due_dt and not (today <= due_dt.date() <= due_max):
            return False
    return True


def add_job_tag(opp: Opportunity, job_tag: str) -> None:
    tag = f"signal:{job_tag}"
    if tag not in opp.why_matched:
        opp.why_matched.append(tag)


def add_structural_reasons(opp: Opportunity) -> None:
    if opp.classificationCode and opp.classificationCode.upper() in {p.upper() for p in PSCS}:
        opp.why_matched.append(f"PSC:{opp.classificationCode}")
    naics_hit = sorted(set(opp.naicsCodes).intersection(NAICS))
    if naics_hit:
        opp.why_matched.append("NAICS:" + ",".join(naics_hit))
    if opp.pop_state_code:
        opp.why_matched.append(f"POP-state:{opp.pop_state_code}")
    if opp.office_state:
        opp.why_matched.append(f"Office-state:{opp.office_state}")
    if opp.pop_country_name:
        opp.why_matched.append(f"POP-country:{opp.pop_country_name}")


# -----------------------------
# RATING LOGIC
# -----------------------------
def _family_scores(text: str) -> Tuple[Dict[str, int], Dict[str, List[str]]]:
    scores: Dict[str, int] = {}
    evidence: Dict[str, List[str]] = {}
    for family, cfg in DOMAIN_FAMILIES.items():
        matches = _hits(text, cfg["terms"])
        if matches:
            scores[family] = int(cfg["weight"]) + min(12, 3 * (len(matches) - 1))
            evidence[family] = matches[:8]
    return scores, evidence


def _buyer_scores(text: str) -> Tuple[int, List[str]]:
    score = 0
    evidence: List[str] = []
    for family, terms in BUYER_FIT_TERMS.items():
        matches = _hits(text, terms)
        if matches:
            score += 6
            evidence.append(f"{family}: {', '.join(matches[:3])}")
    return min(score, 18), evidence[:4]


def classify_setaside(opp: Opportunity) -> Optional[str]:
    code = (opp.typeOfSetAside or "").strip().upper()
    if code in SDVOSB_SETASIDE_CODES:
        return "SDVOSB"
    if code in VOSB_SETASIDE_CODES:
        return "VOSB"
    if code in SMALLBIZ_SETASIDE_CODES:
        return "SmallBiz"
    blob = " ".join([opp.typeOfSetAsideDescription or "", opp.title or "", opp.description_text or ""]).lower()
    if any(t in blob for t in ["sdvosb", "service-disabled veteran", "service disabled veteran"]):
        return "SDVOSB"
    if any(t in blob for t in ["vosb", "veteran-owned", "veteran owned"]):
        return "VOSB"
    if any(t in blob for t in ["small business set-aside", "total small business", "8(a)", "hubzone", "wosb", "edwosb"]):
        return "SmallBiz"
    return None


def _setaside_score(text: str) -> Tuple[int, List[str]]:
    score = 0
    evidence: List[str] = []
    for label, terms in SETASIDE_BOOST_TERMS.items():
        matches = _hits(text, terms)
        if matches:
            score += 10 if "VOSB" in label else 7
            evidence.append(f"{label} signal: {', '.join(matches[:3])}")
    return min(score, 17), evidence


def estimate_ratings(opp: Opportunity) -> None:
    text = f"{opp.title}\n{opp.type}\n{opp.baseType}\n{opp.fullParentPathName}\n{opp.description_text}".lower()

    family_scores, family_evidence = _family_scores(text)
    buyer_score, buyer_evidence = _buyer_scores(text)
    setaside_score, setaside_evidence = _setaside_score(text)

    domain_fit = min(70, sum(family_scores.values()))

    complexity = 3
    overhead = 3
    profitability = 3

    if domain_fit >= 45:
        profitability += 2
    elif domain_fit >= 24:
        profitability += 1
    if setaside_score:
        profitability += 1
    if buyer_score >= 12:
        profitability += 1

    heavy_families = {
        "Facilities, base ops and life support",
        "Construction and renovation",
    }
    if any(f in family_scores for f in heavy_families):
        complexity += 1
        overhead += 1
    if any(w in text for w in ["nationwide", "multi-site", "multiple locations", "24/7", "classified", "secret", "top secret"]):
        complexity += 1
        overhead += 1

    complexity = max(1, min(5, complexity))
    overhead = max(1, min(5, overhead))
    profitability = max(1, min(5, profitability))

    evidence: List[str] = []
    if family_scores:
        for fam, pts in sorted(family_scores.items(), key=lambda x: x[1], reverse=True)[:4]:
            evidence.append(f"{fam} fit (+{pts}): {', '.join(family_evidence[fam][:5])}")
    evidence.extend(setaside_evidence)
    evidence.extend(buyer_evidence)
    if opp.catholic_hits:
        evidence.insert(0, "Catholic keyword match: " + ", ".join(opp.catholic_hits[:5]))
    if opp.is_nc:
        evidence.insert(0, "NC — full coverage")

    opp.ratings = {
        "complexity": complexity,
        "profitability": profitability,
        "overhead": overhead,
        "domain_fit": domain_fit,
        "buyer_fit": buyer_score,
        "setaside_fit": setaside_score,
        "setaside_class": classify_setaside(opp),
        "is_nc": opp.is_nc,
    }
    opp.evidence = evidence[:8]
    opp.next_step = (
        "Confirm buying office, place of performance, sub role vs. prime, NAICS/PSC "
        "alignment, set-aside eligibility, and response deadline. Pull attachments from "
        "SAM.gov for the full PWS/SOW."
    )


def compute_score(opp: Opportunity) -> float:
    c = float(opp.ratings.get("complexity", 3))
    o = float(opp.ratings.get("overhead", 3))
    p = float(opp.ratings.get("profitability", 3))
    feasibility = p / max(1.0, c + o)
    opp.feasibility = feasibility

    domain_fit = float(opp.ratings.get("domain_fit", 0))
    buyer_fit = float(opp.ratings.get("buyer_fit", 0))
    setaside_fit = float(opp.ratings.get("setaside_fit", 0))
    rel = min(MAX_RELEVANCE, float(len(set(opp.why_matched))))

    setaside_class = opp.ratings.get("setaside_class")
    setaside_boost = 0.0
    if setaside_class == "SDVOSB":
        setaside_boost = SDVOSB_PRIORITY_BOOST
    elif setaside_class == "VOSB":
        setaside_boost = VOSB_PRIORITY_BOOST

    nc_boost = NC_BOOST if opp.is_nc else 0.0
    catholic_boost = CATHOLIC_MATCH_BOOST if opp.catholic_hits else 0.0
    double_hit_boost = (
        NC_SDVOSB_DOUBLE_HIT_BOOST
        if opp.is_nc and setaside_class == "SDVOSB"
        else 0.0
    )

    opp.ratings["nc_boost"] = nc_boost
    opp.ratings["catholic_boost"] = catholic_boost
    opp.ratings["double_hit_boost"] = double_hit_boost

    return (
        domain_fit + buyer_fit + setaside_fit
        + (feasibility * 12.0) + (rel * 0.75)
        + setaside_boost + nc_boost + catholic_boost + double_hit_boost
    )


def get_setaside_label(opp: Opportunity) -> str:
    cls = opp.ratings.get("setaside_class") if opp.ratings else None
    if cls == "SDVOSB":
        return "SDVOSB"
    if cls == "VOSB":
        return "VOSB"
    text = " ".join([opp.title or "", opp.typeOfSetAsideDescription or "", opp.description_text or ""]).lower()
    labels: List[str] = []
    if any(t in text for t in ["sdvosb", "service-disabled", "service disabled veteran"]):
        labels.append("SDVOSB")
    elif any(t in text for t in ["vosb", "veteran-owned", "veteran owned"]):
        labels.append("VOSB")
    if any(t in text for t in ["small business", "total small business", "small business set-aside", "sbsa", "set-aside", "set aside"]):
        labels.append("Small Business")
    return ", ".join(labels) if labels else "Not identified"


def get_location_label(opp: Opportunity) -> str:
    pieces: List[str] = []
    if opp.pop_city_name:
        pieces.append(opp.pop_city_name)
    if opp.pop_state_code:
        pieces.append(opp.pop_state_code)
    if opp.pop_country_name:
        pieces.append(opp.pop_country_name)
    elif opp.pop_country_code:
        pieces.append(opp.pop_country_code)
    if not pieces and opp.office_state:
        pieces.append(f"office {opp.office_state}")
    return ", ".join(dict.fromkeys(pieces)) if pieces else "Not specified"


def get_match_summary(opp: Opportunity, max_items: int = 4) -> str:
    items: List[str] = []
    for ev in opp.evidence or []:
        if ev and ev not in items:
            items.append(ev)
    for why in opp.why_matched or []:
        if why and why not in items:
            items.append(why)
    if not items and opp.keyword_hits:
        items = ["keywords: " + ", ".join(opp.keyword_hits[:max_items])]
    return "; ".join(items[:max_items]) if items else "Matched NC/Catholic scope"


# -----------------------------
# OUTPUT (email + CSV + XLSX)
# -----------------------------
def build_email(top: List[Opportunity], shortlist: List[Opportunity], as_of: dt.datetime, stats: Dict[str, int]) -> str:
    lines: List[str] = []
    lines.append(f"To: {EMAIL_TO}")
    if EMAIL_CC.strip():
        lines.append(f"Cc: {EMAIL_CC}")
    lines.append(f"Subject: {EMAIL_SUBJECT_BASE} — {as_of:%b %d, %Y}")
    lines.append("")
    lines.append("Good morning,")
    lines.append("")
    lines.append("Today's SAM.gov scan for Catholic institutions (VA/GA/SC/KY/WV/DC) + full North Carolina coverage.")
    lines.append(f"Search window: last ~{POSTED_WINDOW_HOURS} hours")
    lines.append(f"Total in scope: {stats.get('in_scope', 0)}")
    lines.append(f"  North Carolina (all agencies/domains): {stats.get('nc_total', 0)}")
    lines.append(f"  NC + SDVOSB (sweet spot): {stats.get('nc_sdvosb', 0)}")
    lines.append(f"  Catholic keyword match (VA/GA/SC/KY/WV/DC): {stats.get('catholic_match', 0)}")
    lines.append(f"Top opportunities: {len(top)}")
    lines.append(f"Next-best shortlist: {len(shortlist)}")
    lines.append("")

    lines.append("HIGH PRIORITY / TOP OPPORTUNITIES")
    lines.append("=" * 72)
    if not top:
        lines.append("No top opportunities found for this run.")
    for i, opp in enumerate(top, 1):
        lines.append(f"{i}) {opp.title}")
        lines.append(f"   - Score: {opp.score:.1f} | Feasibility: {opp.feasibility:.2f}")
        tags: List[str] = []
        if opp.is_nc:
            tags.append("NC")
        if opp.catholic_hits:
            tags.append("Catholic match")
        if opp.ratings.get("setaside_class"):
            tags.append(opp.ratings["setaside_class"])
        lines.append(f"   - Tags: {' | '.join(tags) if tags else '—'}")
        lines.append(f"   - Agency/Office: {opp.fullParentPathName or '—'}")
        lines.append(f"   - Location: {get_location_label(opp)}")
        lines.append(f"   - Set-aside: {get_setaside_label(opp)}")
        lines.append(f"   - Posted: {opp.postedDate or '—'} | Due: {opp.responseDeadLine or '—'}")
        lines.append(f"   - NAICS: {', '.join(opp.naicsCodes) if opp.naicsCodes else '—'} | PSC: {opp.classificationCode or '—'}")
        lines.append(f"   - Why it matters: {get_match_summary(opp)}")
        lines.append(f"   - Next step: {opp.next_step}")
        lines.append(f"   - SAM link: {opp.uiLink}")
        lines.append("")

    lines.append("OTHER STRONG MATCHES")
    lines.append("=" * 72)
    if not shortlist:
        lines.append("No shortlist opportunities found for this run.")
    for opp in shortlist:
        tag = "NC" if opp.is_nc else "Catholic"
        lines.append(
            f"- [{tag}] {opp.title} | Score {opp.score:.1f} | {get_location_label(opp)} | "
            f"{get_setaside_label(opp)} | Due {opp.responseDeadLine or '—'}"
        )
        lines.append(f"  {opp.uiLink}")

    lines.append("")
    lines.append("Full ranked results are attached in Excel/CSV.")
    return "\n".join(lines)


def build_html_email(top: List[Opportunity], shortlist: List[Opportunity], as_of: dt.datetime, stats: Dict[str, int]) -> str:
    def esc(x: Any) -> str:
        return html.escape(str(x or ""))

    def opportunity_card(i: int, opp: Opportunity) -> str:
        tags: List[str] = []
        if opp.is_nc:
            tags.append("NC")
        if opp.catholic_hits:
            tags.append("Catholic match")
        if opp.ratings.get("setaside_class"):
            tags.append(opp.ratings["setaside_class"])
        tag_html = " ".join(
            f"<span style='background:#7A1F2B;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-right:4px;'>{esc(t)}</span>"
            for t in tags
        )
        return f"""
        <tr>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;">{i}</td>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;">
            <div style="font-weight:700;font-size:14px;">{esc(opp.title)}</div>
            <div style="margin-top:4px;">{tag_html}</div>
            <div style="margin-top:4px;"><a href="{esc(opp.uiLink)}">Open in SAM.gov</a></div>
            <div style="margin-top:6px;color:#444;"><strong>Why it matters:</strong> {esc(get_match_summary(opp))}</div>
          </td>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;">{esc(opp.fullParentPathName or '—')}</td>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;">{esc(get_location_label(opp))}</td>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;">{esc(get_setaside_label(opp))}</td>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;">{esc(opp.responseDeadLine or '—')}</td>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;text-align:right;">{opp.score:.1f}<br><span style="color:#666;font-size:12px;">Feas {opp.feasibility:.2f}</span></td>
        </tr>
        """

    top_rows = "".join(opportunity_card(i, opp) for i, opp in enumerate(top, 1)) or (
        "<tr><td colspan='7' style='padding:10px;'>No high-priority opportunities found for this run.</td></tr>"
    )

    shortlist_items = "".join(
        f"""
        <li style="margin-bottom:8px;">
          <strong>{"[NC] " if opp.is_nc else "[Catholic] "}{esc(opp.title)}</strong><br>
          Score {opp.score:.1f} | {esc(get_location_label(opp))} | {esc(get_setaside_label(opp))} | Due {esc(opp.responseDeadLine or '—')}<br>
          <a href="{esc(opp.uiLink)}">Open in SAM.gov</a>
        </li>
        """
        for opp in shortlist[:15]
    ) or "<li>No shortlist opportunities found for this run.</li>"

    return f"""
    <html>
    <body style="font-family:Arial, Helvetica, sans-serif;color:#222;line-height:1.35;">
      <h2 style="margin-bottom:4px;">Catholic Institutions (VA/GA/SC/KY/WV/DC) + Full NC Sweep</h2>
      <p style="margin-top:0;color:#555;">Generated {as_of:%b %d, %Y %H:%M}. Search window: last ~{POSTED_WINDOW_HOURS} hours.</p>

      <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:12px 0 18px 0;">
        <tr>
          <td style="padding:8px 18px 8px 0;"><strong>In scope</strong><br>{stats.get('in_scope', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>NC (all agencies)</strong><br>{stats.get('nc_total', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>NC + SDVOSB</strong><br>{stats.get('nc_sdvosb', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>Catholic keyword match</strong><br>{stats.get('catholic_match', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>High priority</strong><br>{len(top)}</td>
        </tr>
      </table>

      <h3 style="margin-bottom:8px;">High Priority / Top Opportunities</h3>
      <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;width:100%;font-size:13px;">
        <thead>
          <tr style="background:#f2f2f2;">
            <th style="text-align:left;padding:8px;border-bottom:2px solid #ccc;">#</th>
            <th style="text-align:left;padding:8px;border-bottom:2px solid #ccc;">Opportunity</th>
            <th style="text-align:left;padding:8px;border-bottom:2px solid #ccc;">Agency / Office</th>
            <th style="text-align:left;padding:8px;border-bottom:2px solid #ccc;">Location</th>
            <th style="text-align:left;padding:8px;border-bottom:2px solid #ccc;">Set-aside</th>
            <th style="text-align:left;padding:8px;border-bottom:2px solid #ccc;">Due</th>
            <th style="text-align:right;padding:8px;border-bottom:2px solid #ccc;">Score</th>
          </tr>
        </thead>
        <tbody>{top_rows}</tbody>
      </table>

      <h3 style="margin-top:22px;">Other Strong Matches</h3>
      <ol>{shortlist_items}</ol>

      <p style="margin-top:18px;">Full ranked results are attached (CSV + XLSX) with NC flag, Catholic-keyword hits, and set-aside class per row.</p>
    </body>
    </html>
    """


def opp_to_row(opp: Opportunity, rank_group: str = "") -> Dict[str, Any]:
    return {
        "rank_group": rank_group,
        "score": round(float(opp.score or 0), 3),
        "feasibility": round(float(opp.feasibility or 0), 3),
        "is_nc": "Y" if opp.is_nc else "",
        "catholic_match": "Y" if opp.catholic_hits else "",
        "catholic_hits": ", ".join(opp.catholic_hits or []),
        "setaside_class": opp.ratings.get("setaside_class", "") or "",
        "pop_state": opp.pop_state_code or "",
        "office_state": opp.office_state or "",
        "pop_country": opp.pop_country_name or opp.pop_country_code or "",
        "pop_city": opp.pop_city_name or "",
        "complexity": opp.ratings.get("complexity", ""),
        "profitability": opp.ratings.get("profitability", ""),
        "overhead": opp.ratings.get("overhead", ""),
        "title": opp.title,
        "notice_type": opp.type,
        "posted_date": opp.postedDate,
        "response_deadline": opp.responseDeadLine,
        "agency_office": opp.fullParentPathName,
        "naics": ", ".join(opp.naicsCodes or []),
        "psc": opp.classificationCode or "",
        "why_matched": "; ".join(dict.fromkeys(opp.why_matched)),
        "evidence": " | ".join(opp.evidence),
        "next_step": opp.next_step,
        "notice_id": opp.noticeId,
        "sam_link": opp.uiLink,
        "attachment_count": len(opp.resourceLinks or []),
    }


def write_results_csv(scored: List[Opportunity], top_ids: set, shortlist_ids: set, as_of: dt.datetime) -> str:
    filename = f"sam_results_catholic_southeast_{as_of:%Y-%m-%d}.csv"
    empty = Opportunity('', '', '')
    fieldnames = list(opp_to_row(scored[0] if scored else empty).keys())
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for opp in scored:
            group = "Top" if opp.noticeId in top_ids else ("Shortlist" if opp.noticeId in shortlist_ids else "All Matches")
            writer.writerow(opp_to_row(opp, group))
    return filename


def write_results_xlsx(scored: List[Opportunity], top_ids: set, shortlist_ids: set, as_of: dt.datetime, stats: Dict[str, int]) -> Optional[str]:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
    except Exception:
        return None

    filename = f"sam_results_catholic_southeast_{as_of:%Y-%m-%d}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "SAM Results"

    rows: List[Dict[str, Any]] = []
    for opp in scored:
        group = "Top" if opp.noticeId in top_ids else ("Shortlist" if opp.noticeId in shortlist_ids else "All Matches")
        rows.append(opp_to_row(opp, group))

    empty = Opportunity('', '', '')
    headers = list(rows[0].keys()) if rows else list(opp_to_row(empty).keys())
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h, "") for h in headers])

    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    summary = wb.create_sheet("Summary")
    summary.append(["Metric", "Value"])
    summary.append(["Generated", as_of.strftime("%Y-%m-%d %H:%M")])
    summary.append(["Total in scope", stats.get("in_scope", 0)])
    summary.append(["North Carolina (all agencies/domains)", stats.get("nc_total", 0)])
    summary.append(["NC + SDVOSB (sweet spot)", stats.get("nc_sdvosb", 0)])
    summary.append(["Catholic keyword match (VA/GA/SC/KY/WV/DC)", stats.get("catholic_match", 0)])
    summary.append(["Top opportunities", len(top_ids)])
    summary.append(["Shortlist opportunities", len(shortlist_ids)])
    summary.append(["Search window hours", POSTED_WINDOW_HOURS])
    for cell in summary[1]:
        cell.font = Font(bold=True)
    summary.column_dimensions["A"].width = 40
    summary.column_dimensions["B"].width = 28

    wb.save(filename)
    return filename


def _parse_addrs(raw: str) -> List[str]:
    if not raw:
        return []
    parts = re.split(r"[;,]", raw)
    return [p.strip() for p in parts if p.strip()]


def send_email(subject: str, body: str, html_body: Optional[str] = None, attachments: Optional[List[str]] = None) -> None:
    if not SEND_EMAIL:
        return
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SEND_EMAIL=1 but SMTP_USER/SMTP_PASS not set.")

    to_addrs = _parse_addrs(EMAIL_TO)
    cc_addrs = _parse_addrs(EMAIL_CC)
    all_recipients = to_addrs + cc_addrs
    if not all_recipients:
        raise RuntimeError("No valid email recipients. Set REPORT_TO.")

    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    for path_str in attachments or []:
        path = Path(path_str)
        if not path.exists():
            continue
        ctype, _ = mimetypes.guess_type(str(path))
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg, from_addr=FROM_EMAIL, to_addrs=all_recipients)


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

    # Fan-out jobs. One per target state via the API's native place-of-
    # performance "state" param, plus an unrestricted global sweep as a
    # safety net (SAM.gov's state field is sometimes empty/inconsistent, and
    # an office based in one of these states can post a notice whose POP
    # field doesn't reflect it). The geography/keyword filter downstream
    # trims aggressively; this stage is purely about not missing candidates.
    jobs: List[Tuple[str, Dict[str, Any]]] = []
    for st in TARGET_STATES:
        jobs.append((f"state:{st}", {**base, "state": st}))
    jobs.append(("global-sweep", dict(base)))

    seen: Dict[str, Opportunity] = {}
    total_calls = 0
    job_counts: Dict[str, int] = {}

    for job_name, params in jobs:
        offset = 0
        while True:
            p = dict(params)
            p["offset"] = offset
            try:
                data = sam_search(api_key, p)
            except Exception as e:
                print(f"[WARN] Job {job_name} failed at offset {offset}: {e}", file=sys.stderr)
                break
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
            if offset > 10000 or offset >= MAX_PER_JOB:
                break
            if len(seen) >= MAX_TOTAL_DEDUPED:
                break
            time.sleep(SLEEP_SECONDS)

        if len(seen) >= MAX_TOTAL_DEDUPED:
            break

    scored: List[Opportunity] = []
    stats = {"in_scope": 0, "nc_total": 0, "nc_sdvosb": 0, "catholic_match": 0, "dropped_out_of_scope": 0}

    for opp in seen.values():
        if not hard_filters_ok(opp, today=today, due_max=due_max):
            continue

        # Description fetch (best-effort; needed for Catholic keyword text fallback).
        opp.description_text = sam_fetch_description(opp.description_url)

        keep, reason = include_by_scope(opp)
        if not keep:
            stats["dropped_out_of_scope"] += 1
            continue

        add_structural_reasons(opp)
        opp.why_matched.append(f"scope:{reason}")

        estimate_ratings(opp)
        opp.score = compute_score(opp)
        scored.append(opp)

        stats["in_scope"] += 1
        if opp.is_nc:
            stats["nc_total"] += 1
            if opp.ratings.get("setaside_class") == "SDVOSB":
                stats["nc_sdvosb"] += 1
        if opp.catholic_hits:
            stats["catholic_match"] += 1

    scored.sort(key=lambda x: x.score, reverse=True)

    top = scored[:TOP_MAX]
    if len(top) < TOP_MIN:
        top = scored[:max(TOP_MIN, len(scored))]
    top_ids = {o.noticeId for o in top}
    remaining = [o for o in scored if o.noticeId not in top_ids]
    shortlist = remaining[:SHORTLIST_MAX]
    if len(shortlist) < SHORTLIST_MIN:
        shortlist = remaining[:max(SHORTLIST_MIN, len(remaining))]
    shortlist_ids = {o.noticeId for o in shortlist}

    csv_path = write_results_csv(scored, top_ids, shortlist_ids, now)
    xlsx_path = write_results_xlsx(scored, top_ids, shortlist_ids, now, stats)

    email_text = build_email(top, shortlist, now, stats)
    email_html = build_html_email(top, shortlist, now, stats)

    with open("email_draft.txt", "w", encoding="utf-8") as f:
        f.write(email_text)
    with open("email_draft.html", "w", encoding="utf-8") as f:
        f.write(email_html)

    print(email_text)

    subject = (
        f"Catholic (VA/GA/SC/KY/WV/DC) + Full NC Opportunities "
        f"({stats['in_scope']} in scope | {stats['nc_total']} NC | {stats['catholic_match']} Catholic) — {now:%b %d, %Y}"
    )
    attachments = [p for p in [xlsx_path, csv_path] if p]
    send_email(subject, email_text, html_body=email_html, attachments=attachments)

    print(f"[INFO] Wrote spreadsheet files: {', '.join(attachments)}", file=sys.stderr)
    print(
        f"\n[INFO] API calls: {total_calls} | Deduped candidates: {len(seen)} | "
        f"In scope: {stats['in_scope']} | NC: {stats['nc_total']} | NC+SDVOSB: {stats['nc_sdvosb']} | "
        f"Catholic match: {stats['catholic_match']} | Dropped: {stats['dropped_out_of_scope']} | "
        f"Top: {len(top)} | Shortlist: {len(shortlist)} | SEND_EMAIL={int(SEND_EMAIL)}",
        file=sys.stderr,
    )
    for k in sorted(job_counts, key=lambda x: (-job_counts[x], x))[:20]:
        print(f"[JOB] {k}: {job_counts[k]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
