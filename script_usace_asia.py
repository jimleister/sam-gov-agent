#!/usr/bin/env python3
"""
SAM.gov Daily Scan — USACE + South/Southeast Asia focus.

Third scanner in the Weston scan fleet. Complements script.py (WEXMAC logistics)
and script_pest.py (pest/vector management). This one narrows on geography and
agency rather than on domain.

Scope (hard filter — items outside are dropped, not just deprioritized):
- Nepal carve-out: ANY opportunity with place of performance in Nepal is
  included, regardless of issuing agency or domain. This is a standing
  exception to the rules below.
- USACE-issued opportunities: include only if place of performance is in South
  Asia, Southeast Asia, the United States, or US territories (PR, GU, VI, AS,
  MP) AND the notice text hits a quality control / quality assurance / quality
  surveillance term (see the "Inspection and QA/QC" term list). USACE notices
  with no QC/QS signal are dropped — this scanner is deliberately narrow on
  USACE now, not a general USACE feed.
- Non-USACE opportunities: include only if place of performance is in South
  Asia or Southeast Asia. No domain restriction.
- Everything else (USACE in Europe/Africa/Middle East/Latin America, non-USACE
  in the US, USACE with no QC/QS signal, etc.) is dropped from this scan.
  Those live in the other scanners.

Ranking:
- Domain families (WEXMAC-adjacent) score relevance but do NOT filter.
- USACE-issued gets a strong priority boost.
- Double-hit (USACE + covered Asia POP) gets an additional boost so the
  sweet-spot notices float to the top.
- Set-aside scoring and feasibility feed in as tiebreakers, matching the other
  two scanners.

Improvements over the earlier two scripts:
- Structured placeOfPerformance extraction (country/state/city from the API),
  not just text-scanning the description.
- Word-boundary keyword matching (from the pest script), avoiding false
  positives like "ipm" inside "shipment" or "port" inside "airport".
- Explicit USACE detection via fullParentPathName and district-name text
  (Far East, Japan, Alaska, Honolulu, Pacific Ocean, Transatlantic districts).

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

# South Asia — non-USACE work in these countries is in scope.
SOUTH_ASIA = [
    "Afghanistan", "Bangladesh", "Bhutan", "India", "Maldives",
    "Nepal", "Pakistan", "Sri Lanka",
]

# Southeast Asia — non-USACE work in these countries is in scope. Common name
# variants are included so we catch things like "Burma" vs. "Myanmar".
SOUTHEAST_ASIA = [
    "Brunei", "Brunei Darussalam", "Cambodia", "Indonesia", "Laos",
    "Lao People's Democratic Republic", "Malaysia", "Myanmar", "Burma",
    "Philippines", "Singapore", "Thailand", "Timor-Leste", "East Timor",
    "Timor Leste", "Vietnam", "Viet Nam",
]

# US territories — USACE work here is in scope (part of "US and its territories").
US_TERRITORIES = [
    "Puerto Rico", "US Virgin Islands", "U.S. Virgin Islands", "Virgin Islands",
    "Guam", "American Samoa", "Northern Mariana Islands", "Commonwealth of the Northern Mariana Islands",
]

# Nepal gets a standing carve-out (see include_by_scope): ANY opportunity with
# place of performance in Nepal is included, regardless of issuing agency or
# domain match. This exists because Nepal candidate volume is thin and the
# user wants full visibility there rather than having it filtered out by the
# USACE QC/QS scope rule or by NAICS/PSC fan-out gaps.
NEPAL_NAMES = ["Nepal"]

# All countries considered "target region" for the geographic filter.
TARGET_REGION_COUNTRIES = sorted(set(SOUTH_ASIA + SOUTHEAST_ASIA))

# Full USACE-covered geography (Asia + US + Territories). USACE opportunities
# outside this set are dropped.
USACE_COVERED_COUNTRIES_TEXT = sorted(set(TARGET_REGION_COUNTRIES + US_TERRITORIES + [
    "United States", "USA", "U.S.A.", "US", "U.S.",
]))

# ISO-2 country codes SAM.gov commonly returns for target-region matches. Not
# authoritative — text-name matching is the fallback since SAM.gov's country
# field is inconsistent between structured code and free-text name.
TARGET_REGION_ISO_CODES = {
    # South Asia
    "AF", "BD", "BT", "IN", "MV", "NP", "PK", "LK",
    # Southeast Asia
    "BN", "KH", "ID", "LA", "MY", "MM", "BU", "PH", "SG", "TH", "TL", "VN",
}

# ISO-2 codes for US + territories (USACE-covered only).
US_AND_TERRITORY_ISO_CODES = {"US", "USA", "PR", "VI", "GU", "AS", "MP"}

# ISO-2 states/territories used in the state filter for the US fan-out.
US_STATES_AND_TERRITORIES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR","GU","VI","AS","MP",
]

# States that identify OCONUS US territories (used for scoring separation).
US_TERRITORY_STATE_CODES = {"PR", "GU", "VI", "AS", "MP"}

# -----------------------------
# USACE DETECTION
# -----------------------------

# Text patterns that identify a USACE-issued opportunity. Case-insensitive.
# We match on fullParentPathName and (as a lower-priority signal) title/desc.
USACE_NAME_PATTERNS = [
    "corps of engineers",
    "u.s. army corps of engineers",
    "us army corps of engineers",
    "united states army corps of engineers",
    "usace",
]

# USACE district names — presence in the org path or description confirms USACE
# and hints at which district owns the work.
USACE_DISTRICTS = [
    "Alaska District",
    "Far East District",
    "Honolulu District",
    "Japan District",
    "Los Angeles District",
    "Louisville District",
    "Mobile District",
    "New York District",
    "Pacific Ocean Division",
    "Sacramento District",
    "San Francisco District",
    "Seattle District",
    "Transatlantic Division",
    "Baltimore District",
    "Norfolk District",
    "Charleston District",
    "Fort Worth District",
    "Little Rock District",
    "Vicksburg District",
    "Kansas City District",
    "Omaha District",
    "St. Louis District",
]

# -----------------------------
# BROAD FAN-OUT NAICS / PSC
# -----------------------------
# We do NOT filter on domain, but we still fan out API calls on a reasonable
# NAICS/PSC set to make sure we surface enough candidates. Anything that returns
# from these calls is subject to the geography/agency filter below.
NAICS = [
    # Passenger transport (Weston core)
    "485113","485119","485210","485310","485320","485410","485510","485991","485999","487110",
    # Freight/logistics/warehousing (WEXMAC + USACE support)
    "484110","484121","484122","484220","484230","488320","488390","488410","488490","488510",
    "488991","488999","492110","492210","493110","493190","541614","561210","561320","561599",
    "561920","561990",
    # Rental/lease/maintenance of vehicles and equipment
    "532111","532112","532120","532289","532411","532412","811111","811118","811198","811310",
    # Base ops / life support / facilities
    "221310","236220","238990","541930","561612","561720","561730","561740","561790",
    "562111","562112","562119","562211","562991","562998","721110","721214","722310",
    # Construction / engineering (USACE prime pipeline — visibility even if you sub)
    "237110","237130","237310","237990","541330","541370","541360","541380",
    # Environmental
    "541620","562910",
    # Inspection / QA-QC / testing (welding, coating, quality control)
    "541350",  # Building Inspection Services
    "541380",  # Testing Laboratories (NDT, materials testing, coatings testing)
    "238120",  # Structural Steel and Precast Concrete Contractors (welding trade)
    "238320",  # Painting and Wall Covering (coating trade)
]

PSCS = [
    # Transportation / travel / vehicle operations
    "V003","V112","V119","V122","V129","V212","V222","V225","V226","V227","V229","V999",
    # Logistics / warehousing / support services
    "R405","R408","R499","R602","R604","R605","R606","R706","R799","S216","S205","S206","S208","S209",
    # Rental/lease/maintenance
    "W023","W025","W039","W099","J023","J025","J039","J099",
    # Facilities / base support / food-water-life support
    "M1LZ","S201","S203","S211","S222","S299",
    # USACE construction/A-E work (Y = construction, C = A-E, Z = maintenance)
    "Y1AA","Y1BA","Y1CA","Y1DA","Y1EA","Y1FA","Y1LZ","Y1PA","Y1QA","Y1ZZ",
    "C1AA","C1BA","C1CA","C1DA","C1EA","C1LZ","C1ZZ",
    "Z1AA","Z1BA","Z1CA","Z1DA","Z1LZ","Z1ZZ",
    # Environmental services
    "F999","F998",
    # Quality Control / Testing / Inspection (H-series)
    # H1xx = Q.C. — physical/chemical/mechanical testing
    "H121","H122","H140","H170","H199",
    # H2xx = Equipment/Materials testing (NDT lives here)
    "H221","H222","H231","H271","H299",
    # H3xx = Inspection services
    "H371","H399",
]

# Organization codes (prefix match on fullParentPathCode). USACE lives under DOD/Army.
# We keep the broad DOD prefix so USACE hits reliably; USACE specifically is
# confirmed via USACE_NAME_PATTERNS on fullParentPathName.
ORG_CODES = {
    "DOD": "097",
    "USDA": "012",
    "DOI": "014",
    "DOS": "019",   # State Department (often manages OCONUS project work)
    "DOT": "069",
    "VA": "036",
    "GSA": "047",
}

# -----------------------------
# SCORING WEIGHTS
# -----------------------------

# Priority boosts. USACE dominates because that's the primary target. Double-hit
# (USACE + in South/SE Asia) gets an extra bump so the sweet spot ranks first.
USACE_PRIORITY_BOOST = 40.0
USACE_ASIA_DOUBLE_HIT_BOOST = 20.0
ASIA_REGION_BOOST = 15.0   # non-USACE in target Asia geography
US_TERRITORY_BOOST = 8.0   # PR/GU/VI/AS/MP for USACE work

# Set-aside boosts (matches the existing scripts' pattern).
SDVOSB_SETASIDE_CODES = {"SDVOSBC", "SDVOSBS"}
VOSB_SETASIDE_CODES = {"VSA", "VSS"}
SMALLBIZ_SETASIDE_CODES = {"SBA", "SBP"}
SDVOSB_PRIORITY_BOOST = 20.0
VOSB_PRIORITY_BOOST = 10.0

# WEXMAC-adjacent domain families — used for RANKING (not filtering), so a USACE
# construction notice with no logistics content still surfaces, it just ranks
# below one that has WEXMAC-relevant scope.
DOMAIN_FAMILIES = {
    "Weston core passenger transport": {
        "weight": 20,
        "terms": [
            "trolley","streetcar","shuttle","bus service","charter bus","motor coach",
            "motorcoach","passenger transportation","ground transportation","circulator",
            "visitor transportation","park shuttle","airport transfer","paratransit",
            "microtransit","driver services","vehicle operator","bus operator",
            "fixed route","transit operations",
        ],
    },
    "WEXMAC logistics and transportation": {
        "weight": 24,
        "terms": [
            "cargo truck","cargo van","light duty truck","covered truck","flatbed",
            "stake truck","semi truck","tractor trailer","reefer","refrigerated van",
            "vehicle rental","vehicle leasing","with driver","without driver",
            "personnel logistic movement","personnel logistics movement","plms",
            "logistics support","movement support","loading","unloading",
            "customs clearance","customs duty","bill of lading","freight","drayage",
            "cargo handling","postage","courier","delivery",
        ],
    },
    "Warehousing and supply chain": {
        "weight": 16,
        "terms": [
            "warehouse","warehousing","general warehouse","hazmat warehouse",
            "portable warehouse","storage services","supply chain","inventory",
            "materials management","packing","crating","distribution",
        ],
    },
    "Water transport and port services": {
        "weight": 18,
        "terms": [
            "water taxi","water ferry","ferry","tug","tugboat","tow boat","barge",
            "lighterage","marine cargo","port services","pier","sealift",
            "military sealift","msc","pratique","agricultural cleaning",
        ],
    },
    "Base operations and life support": {
        "weight": 20,
        "terms": [
            "base operations","life support","event support site","event lot",
            "portable sanitary","portable shower","temporary shower","hand wash station",
            "generator","portable generator","heater","air conditioner","cooling",
            "trash removal","dumpster","potable water","non-potable water","laundry",
            "billeting","shelter","custodial","pest","waste management",
            "hazardous waste","medical waste","gray water","black water","sewage",
            "food services","bottled water","rations",
        ],
    },
    "USACE construction and A-E adjacency": {
        "weight": 14,
        "terms": [
            "construction","military construction","milcon","design-build","design build",
            "sabersim","idiq construction","architect-engineer","a-e services","sf330",
            "engineering services","site preparation","earthwork","utilities",
        ],
    },
    "Inspection and QA/QC": {
        # Cross-cutting inspection work — welding, coating, and construction quality
        # control. Heavily used by USACE on construction/repair projects and by other
        # federal agencies on infrastructure and industrial work.
        "weight": 22,
        "terms": [
            # General QA/QC + USACE-specific quality control terminology
            "quality control", "quality assurance", "qa/qc", "quality control plan",
            "quality control program", "qcp", "cqm", "cqm-c",
            "construction quality management", "em 385-1-1", "em385", "em385-1-1",
            "usace qc", "resident management system", "rms3",
            "three phase inspection", "three-phase inspection",
            "inspection test plan", "inspection and test plan", "itp",
            "iso 9001", "ansi n45.2", "quality manager", "quality control manager",
            # Welding inspection
            "welding inspection", "weld inspection", "weld inspector",
            "cwi", "certified welding inspector", "senior certified welding inspector",
            "aws d1", "aws d1.1", "aws d1.5", "aws b31", "api 1104", "asme ix",
            "weld procedure qualification", "wpq", "wps", "weld quality",
            "weld defect", "weld repair",
            # NDT — non-destructive testing (paired with welding and coating)
            "nondestructive testing", "non-destructive testing", "ndt", "nde",
            "radiographic testing", "ultrasonic testing", "phased array ultrasonic",
            "magnetic particle inspection", "magnetic particle testing",
            "dye penetrant", "liquid penetrant", "visual testing",
            "pmi", "positive material identification", "hardness testing",
            # Coating inspection
            "coating inspection", "coating inspector", "coatings inspection",
            "nace", "sspc", "ampp", "sspc-vis", "sspc-pa", "sspc-sp",
            "cathodic protection", "protective coating", "industrial coating",
            "surface preparation", "abrasive blast", "blast profile",
            "dry film thickness", "dft", "wet film thickness", "wft",
            "holiday testing", "holiday detection", "adhesion testing",
            "corrosion protection", "corrosion inspection", "coating repair",
            # Testing labs / general inspection
            "testing laboratory", "materials testing", "concrete testing",
            "soil testing", "field inspection", "field quality control",
            "third-party inspection", "third party inspection",
            "independent inspection", "acceptance testing", "commissioning",
            "punch list inspection",
            # Quality surveillance — government-side QA/surveillance of contractor
            # performance (distinct from contractor CQC above, but the same family).
            "quality surveillance", "surveillance plan", "surveillance schedule",
            "quality assurance surveillance plan", "qasp",
            "performance surveillance", "contract surveillance",
            "government quality assurance", "gqa", "cor surveillance",
            "quality assurance evaluator", "qae", "surveillance officer",
            "cqar", "contractor performance assessment",
        ],
    },
    "Environmental and remediation": {
        "weight": 10,
        "terms": [
            "environmental services","environmental compliance","remediation",
            "wetlands","erosion control","stormwater","habitat","wildlife",
        ],
    },
    "Force protection and communications": {
        "weight": 10,
        "terms": [
            "force protection","security guard","security guards","metal detector",
            "x-ray baggage","explosive detector","guard shack","security trailer",
            "barrier","radio","landline","cellular","sim cards","wifi internet",
            "communications services","internet connection",
        ],
    },
}

# Buyer-fit terms — used for weak ranking, since agency-filtering is already done.
BUYER_FIT_TERMS = {
    "USACE district": [
        "corps of engineers","usace","far east district","japan district",
        "pacific ocean division","transatlantic division","honolulu district",
        "alaska district",
    ],
    "Other DoD": [
        "department of defense","dod","navfac","navy","army","air force","marine corps",
        "u.s. forces korea","u.s. forces japan","indopacom","pacom","paccom",
    ],
    "State Department / diplomatic": [
        "department of state","embassy","consulate","state department","dos",
    ],
    "Development / assistance": [
        "usaid","millennium challenge","peace corps",
    ],
}

SETASIDE_BOOST_TERMS = {
    "VOSB/SDVOSB": ["vosb","veteran-owned","veteran owned","sdvosb","service-disabled","service disabled veteran"],
    "Small business": ["small business","total small business","small business set-aside","sbsa","set-aside","set aside"],
}

# Terms whose presence adds overhead/complexity but does not exclude — most of
# these are inherent to expeditionary/OCONUS work and are expected here.
LOGISTICS_TERMS = [
    "oconus","overseas","remote site","island","ferry","port","customs",
    "bill of lading","hazmat","multi-site","expeditionary","contingency",
]

NEGATIVE_FIT_TERMS = [
    "software development only","strictly it services","cybersecurity certification",
    "research and development grant","university grant",
]

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
EMAIL_SUBJECT_BASE = "SAM.gov USACE (QC/QS) + South/Southeast Asia + Nepal Opportunities"

TOP_MIN, TOP_MAX = 5, 10
SHORTLIST_MIN, SHORTLIST_MAX = 10, 20

MAX_PER_JOB = 2000
MAX_TOTAL_DEDUPED = 8000
SLEEP_SECONDS = 0.12

MAX_RELEVANCE = 10.0

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
    is_usace: bool = False
    usace_district: Optional[str] = None
    region_bucket: Optional[str] = None   # "south_asia", "southeast_asia", "us", "us_territory"
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
    list of objects (multi-site notices). Pick the first non-empty one for the
    canonical POP fields; the full list of countries also lands in why_matched.
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
    """
    Extract (code, name) from a POP sub-object. SAM.gov returns these as either
    {"code": "USA", "name": "UNITED STATES"} objects or bare strings.
    """
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
    Whole-word/phrase match. Avoids substring false positives like 'ipm' matching
    inside 'equipment', or 'port' matching inside 'airport-support'. Multi-word
    phrases still match as phrases with flexible whitespace.
    """
    term = (term or "").strip().lower()
    if not term:
        return False
    escaped = re.escape(term)
    escaped = re.sub(r"\\\s+", r"\\s+", escaped)
    pattern = r"(?<!\w)" + escaped + r"(?!\w)"
    return re.search(pattern, text) is not None


def detect_usace(opp: Opportunity) -> Tuple[bool, Optional[str]]:
    """Detect USACE issuance and (if found) which district owns it."""
    parts = " ".join(filter(None, [
        opp.fullParentPathName or "",
        opp.title or "",
        opp.description_text or "",
    ])).lower()
    is_usace = any(pat in parts for pat in USACE_NAME_PATTERNS)

    district = None
    if is_usace:
        for d in USACE_DISTRICTS:
            if d.lower() in parts:
                district = d
                break
    return is_usace, district


def _country_matches_target_region(name: str) -> Optional[str]:
    """Return 'south_asia' or 'southeast_asia' if the country name matches, else None."""
    if not name:
        return None
    lc = name.lower()
    for c in SOUTH_ASIA:
        if c.lower() == lc or c.lower() in lc:
            return "south_asia"
    for c in SOUTHEAST_ASIA:
        if c.lower() == lc or c.lower() in lc:
            return "southeast_asia"
    return None


def classify_region(opp: Opportunity) -> Optional[str]:
    """
    Classify the opportunity's place-of-performance region as one of:
      'south_asia', 'southeast_asia', 'us', 'us_territory', or None (unknown/other).

    Uses the structured POP fields first, then falls back to text scanning of the
    title/description/agency-path. USACE opportunities lacking any structured POP
    are treated as 'us' by default (CONUS-issued USACE notices very often name
    the OCONUS POP only in the attachments; we don't want to drop them silently).
    """
    # 1) Structured POP country code (most reliable when present).
    code = (opp.pop_country_code or "").strip().upper()
    if code:
        if code in {"US", "USA"}:
            state = (opp.pop_state_code or "").strip().upper()
            if state in US_TERRITORY_STATE_CODES:
                return "us_territory"
            return "us"
        if code in TARGET_REGION_ISO_CODES:
            # Distinguish South vs. SE Asia via name if we have it.
            reg = _country_matches_target_region(opp.pop_country_name or "")
            if reg:
                return reg
            # Fallback: split by ISO code buckets.
            south = {"AF", "BD", "BT", "IN", "MV", "NP", "PK", "LK"}
            return "south_asia" if code in south else "southeast_asia"
        # Any other structured country code = out of scope for this scanner.
        return None

    # 2) Structured POP country name.
    if opp.pop_country_name:
        name_lc = opp.pop_country_name.lower()
        if any(x in name_lc for x in ["united states", "usa", "u.s.a"]):
            state = (opp.pop_state_code or "").strip().upper()
            if state in US_TERRITORY_STATE_CODES:
                return "us_territory"
            return "us"
        for t in US_TERRITORIES:
            if t.lower() in name_lc:
                return "us_territory"
        reg = _country_matches_target_region(opp.pop_country_name)
        if reg:
            return reg
        # Structured name known but out of scope.
        return None

    # 3) Text fallback — scan title + description + agency path.
    blob = " ".join(filter(None, [opp.title, opp.fullParentPathName, opp.description_text])).lower()
    for c in TARGET_REGION_COUNTRIES:
        if term_matches(blob, c):
            return _country_matches_target_region(c)
    for t in US_TERRITORIES:
        if term_matches(blob, t):
            return "us_territory"

    # 4) USACE with no country signal: treat as 'us' so we don't drop CONUS-issued
    # USACE notices whose OCONUS scope only appears in attachments.
    if opp.is_usace:
        return "us"

    # 5) Non-USACE, no country signal, no US state signal: out of scope.
    if opp.office_state and opp.office_state.upper() in {s for s in US_STATES_AND_TERRITORIES}:
        # An opportunity issued from a US office with no explicit country probably is
        # US work — but we only include non-USACE if it's in the Asia scope. So skip.
        return None
    return None


def is_nepal(opp: Opportunity) -> bool:
    """
    True if place of performance is Nepal. Checked via structured POP
    code/name first, then falls back to text-scanning title/agency-path/
    description (word-boundary match, so it won't false-positive on
    substrings). Used for the standing Nepal carve-out in include_by_scope.
    """
    code = (opp.pop_country_code or "").strip().upper()
    if code == "NP":
        return True
    if opp.pop_country_name and "nepal" in opp.pop_country_name.lower():
        return True
    blob = " ".join(filter(None, [opp.title, opp.fullParentPathName, opp.description_text])).lower()
    return term_matches(blob, "nepal")


def include_by_scope(opp: Opportunity) -> Tuple[bool, str]:
    """
    Apply the hard geography/agency/domain filter.

    Include when:
      - Place of performance is Nepal: ALWAYS include — any agency, any
        domain. Standing carve-out (see NEPAL_NAMES above).
      - USACE + POP in {south_asia, southeast_asia, us, us_territory} AND the
        notice text (title/agency-path/description) hits a quality control /
        quality assurance / quality surveillance term from the "Inspection
        and QA/QC" family. USACE notices with no QC/QS signal are dropped.
      - non-USACE + POP in {south_asia, southeast_asia}. No domain filter.

    Anything else is dropped. Returns (include?, reason).
    """
    if is_nepal(opp):
        return True, "Nepal — standing full-coverage carve-out (all agencies/domains)"

    region = opp.region_bucket
    if opp.is_usace:
        if region not in {"south_asia", "southeast_asia", "us", "us_territory"}:
            return False, f"USACE outside covered geography (region={region or 'unknown'})"
        text = " ".join(filter(None, [opp.title, opp.fullParentPathName, opp.description_text])).lower()
        qc_hits = _hits(text, DOMAIN_FAMILIES["Inspection and QA/QC"]["terms"])
        if not qc_hits:
            return False, "USACE dropped — no quality control / quality assurance / surveillance signal"
        opp.keyword_hits = qc_hits[:10]
        return True, f"USACE QC/QS match ({region}): {', '.join(qc_hits[:3])}"
    if region in {"south_asia", "southeast_asia"}:
        return True, f"Non-USACE in target region ({region})"
    return False, f"Non-USACE outside target Asia region (region={region or 'unknown'})"


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
    if opp.fullParentPathCode:
        for name, code in ORG_CODES.items():
            if str(opp.fullParentPathCode).startswith(str(code)):
                opp.why_matched.append(f"Org:{name}({code})")
                break
    if opp.pop_country_name:
        opp.why_matched.append(f"POP-country:{opp.pop_country_name}")
    elif opp.pop_country_code:
        opp.why_matched.append(f"POP-country-code:{opp.pop_country_code}")
    if opp.pop_state_code:
        opp.why_matched.append(f"POP-state:{opp.pop_state_code}")


# -----------------------------
# RATING LOGIC
# -----------------------------
def _hits(text: str, terms: List[str]) -> List[str]:
    out: List[str] = []
    for term in terms:
        if term_matches(text, term):
            out.append(term)
    return list(dict.fromkeys(out))


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

    remote_hits = _hits(text, LOGISTICS_TERMS)
    negative_hits = _hits(text, NEGATIVE_FIT_TERMS)

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
        "Base operations and life support",
        "Water transport and port services",
        "Environmental and remediation",
        "USACE construction and A-E adjacency",
        # Inspection work is technical/specialized but not physically heavy — treat
        # as normal complexity (do not add to this set). This keeps the feasibility
        # ratio favorable for inspection notices, which tend to be lower-overhead
        # sub roles well suited to a small business.
    }
    if any(f in family_scores for f in heavy_families):
        complexity += 1
        overhead += 1
    if opp.region_bucket in {"south_asia", "southeast_asia"} or remote_hits:
        overhead += 1
    if any(w in text for w in ["nationwide", "multi-site", "multiple locations", "24/7", "classified", "secret", "top secret"]):
        complexity += 1
        overhead += 1
    if negative_hits:
        complexity += 1

    complexity = max(1, min(5, complexity))
    overhead = max(1, min(5, overhead))
    profitability = max(1, min(5, profitability))

    evidence: List[str] = []
    if family_scores:
        for fam, pts in sorted(family_scores.items(), key=lambda x: x[1], reverse=True)[:4]:
            evidence.append(f"{fam} fit (+{pts}): {', '.join(family_evidence[fam][:5])}")
    evidence.extend(setaside_evidence)
    evidence.extend(buyer_evidence)
    if opp.is_usace:
        district_tag = f" — {opp.usace_district}" if opp.usace_district else ""
        evidence.insert(0, f"USACE issuance detected{district_tag}")
    if opp.region_bucket:
        evidence.insert(0, f"Region bucket: {opp.region_bucket}")
    if negative_hits:
        evidence.append("Possible off-scope signal: " + ", ".join(negative_hits[:4]))

    opp.ratings = {
        "complexity": complexity,
        "profitability": profitability,
        "overhead": overhead,
        "domain_fit": domain_fit,
        "buyer_fit": buyer_score,
        "setaside_fit": setaside_score,
        "setaside_class": classify_setaside(opp),
        "region_bucket": opp.region_bucket,
        "is_usace": opp.is_usace,
        "usace_district": opp.usace_district,
    }
    opp.evidence = evidence[:8]
    opp.next_step = (
        "Confirm USACE district / buying office, place of performance, sub role vs. prime, "
        "NAICS / PSC alignment, set-aside eligibility, mobilization footprint (visas, theater entry, "
        "customs), and response deadline. Pull attachments from SAM.gov for the full PWS."
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

    # Region + USACE boosts. USACE-in-Asia gets both plus the double-hit bonus.
    region_boost = 0.0
    if opp.region_bucket in {"south_asia", "southeast_asia"}:
        region_boost = ASIA_REGION_BOOST
    elif opp.region_bucket == "us_territory" and opp.is_usace:
        region_boost = US_TERRITORY_BOOST

    usace_boost = USACE_PRIORITY_BOOST if opp.is_usace else 0.0
    double_hit_boost = (
        USACE_ASIA_DOUBLE_HIT_BOOST
        if opp.is_usace and opp.region_bucket in {"south_asia", "southeast_asia"}
        else 0.0
    )

    opp.ratings["region_boost"] = region_boost
    opp.ratings["usace_boost"] = usace_boost
    opp.ratings["double_hit_boost"] = double_hit_boost

    return (
        domain_fit + buyer_fit + setaside_fit
        + (feasibility * 12.0) + (rel * 0.75)
        + setaside_boost + region_boost + usace_boost + double_hit_boost
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
    return "; ".join(items[:max_items]) if items else "Matched USACE/Asia scope"


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
    lines.append(f"Today's SAM.gov scan for USACE (quality control/QA/surveillance only) + South/Southeast Asia + Nepal (all agencies).")
    lines.append(f"Search window: last ~{POSTED_WINDOW_HOURS} hours")
    lines.append(f"Total in scope: {stats.get('in_scope', 0)}")
    lines.append(f"  USACE, QC/QS match only (any covered geography): {stats.get('usace', 0)}")
    lines.append(f"  Non-USACE in South/SE Asia: {stats.get('asia_only', 0)}")
    lines.append(f"  USACE-in-Asia (sweet spot): {stats.get('usace_in_asia', 0)}")
    lines.append(f"  Nepal (all agencies/domains, standing carve-out): {stats.get('nepal', 0)}")
    lines.append(f"  USACE dropped for no QC/QS signal: {stats.get('usace_dropped_no_qc', 0)}")
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
        if opp.is_usace:
            tags.append("USACE")
            if opp.usace_district:
                tags.append(opp.usace_district)
        if opp.region_bucket:
            tags.append(opp.region_bucket.replace("_", " ").title())
        if is_nepal(opp):
            tags.append("Nepal")
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
        tag = "USACE" if opp.is_usace else "Regional"
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
        if opp.is_usace:
            tags.append("USACE")
        if opp.region_bucket:
            tags.append(opp.region_bucket.replace("_", " ").title())
        if is_nepal(opp):
            tags.append("Nepal")
        tag_html = " ".join(
            f"<span style='background:#0B3D91;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-right:4px;'>{esc(t)}</span>"
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
          <strong>{"[USACE] " if opp.is_usace else ""}{esc(opp.title)}</strong><br>
          Score {opp.score:.1f} | {esc(get_location_label(opp))} | {esc(get_setaside_label(opp))} | Due {esc(opp.responseDeadLine or '—')}<br>
          <a href="{esc(opp.uiLink)}">Open in SAM.gov</a>
        </li>
        """
        for opp in shortlist[:15]
    ) or "<li>No shortlist opportunities found for this run.</li>"

    return f"""
    <html>
    <body style="font-family:Arial, Helvetica, sans-serif;color:#222;line-height:1.35;">
      <h2 style="margin-bottom:4px;">USACE (QC/QS) + South/Southeast Asia + Nepal Opportunities</h2>
      <p style="margin-top:0;color:#555;">Generated {as_of:%b %d, %Y %H:%M}. Search window: last ~{POSTED_WINDOW_HOURS} hours.</p>

      <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:12px 0 18px 0;">
        <tr>
          <td style="padding:8px 18px 8px 0;"><strong>In scope</strong><br>{stats.get('in_scope', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>USACE (QC/QS only)</strong><br>{stats.get('usace', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>Non-USACE in Asia</strong><br>{stats.get('asia_only', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>USACE-in-Asia sweet spot</strong><br>{stats.get('usace_in_asia', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>Nepal (all agencies)</strong><br>{stats.get('nepal', 0)}</td>
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

      <p style="margin-top:18px;">Full ranked results are attached (CSV + XLSX) with USACE flag, district, and region bucket per row.</p>
    </body>
    </html>
    """


def opp_to_row(opp: Opportunity, rank_group: str = "") -> Dict[str, Any]:
    return {
        "rank_group": rank_group,
        "score": round(float(opp.score or 0), 3),
        "feasibility": round(float(opp.feasibility or 0), 3),
        "is_usace": "Y" if opp.is_usace else "",
        "usace_district": opp.usace_district or "",
        "region_bucket": opp.region_bucket or "",
        "is_nepal": "Y" if is_nepal(opp) else "",
        "pop_country": opp.pop_country_name or opp.pop_country_code or "",
        "pop_state": opp.pop_state_code or "",
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
        "office_state": opp.office_state or "",
        "why_matched": "; ".join(dict.fromkeys(opp.why_matched)),
        "evidence": " | ".join(opp.evidence),
        "next_step": opp.next_step,
        "notice_id": opp.noticeId,
        "sam_link": opp.uiLink,
        "attachment_count": len(opp.resourceLinks or []),
    }


def write_results_csv(scored: List[Opportunity], top_ids: set, shortlist_ids: set, as_of: dt.datetime) -> str:
    filename = f"sam_results_usace_asia_{as_of:%Y-%m-%d}.csv"
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

    filename = f"sam_results_usace_asia_{as_of:%Y-%m-%d}.xlsx"
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
    summary.append(["USACE (QC/QS match only, any covered geography)", stats.get("usace", 0)])
    summary.append(["Non-USACE in South/SE Asia", stats.get("asia_only", 0)])
    summary.append(["USACE-in-Asia (sweet spot)", stats.get("usace_in_asia", 0)])
    summary.append(["Nepal (all agencies/domains, carve-out)", stats.get("nepal", 0)])
    summary.append(["USACE dropped for no QC/QS signal", stats.get("usace_dropped_no_qc", 0)])
    summary.append(["Top opportunities", len(top_ids)])
    summary.append(["Shortlist opportunities", len(shortlist_ids)])
    summary.append(["Search window hours", POSTED_WINDOW_HOURS])
    for cell in summary[1]:
        cell.font = Font(bold=True)
    summary.column_dimensions["A"].width = 32
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

    # Fan-out jobs. NAICS/PSC widen the candidate pool; US state calls cover
    # domestic USACE notices; the geography filter downstream trims aggressively.
    jobs: List[Tuple[str, Dict[str, Any]]] = []
    for st in US_STATES_AND_TERRITORIES:
        jobs.append((f"state:{st}", {**base, "state": st}))
    for code in NAICS:
        jobs.append((f"naics:{code}", {**base, "ncode": code}))
    for code in PSCS:
        jobs.append((f"psc:{code}", {**base, "ccode": code}))

    # Unrestricted sweep — no NAICS/PSC/state filter. SAM.gov's search API has
    # no place-of-performance-country parameter, so a notice posted with an
    # unusual NAICS/PSC code (or POP in Nepal specifically) can otherwise slip
    # through every fanned-out job above. This job exists mainly to guarantee
    # full candidate coverage for the Nepal carve-out and for Asia POP notices
    # generally; the geography/agency/domain filter downstream still applies
    # to everything it turns up except Nepal.
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
    stats = {
        "in_scope": 0, "usace": 0, "asia_only": 0, "usace_in_asia": 0,
        "nepal": 0, "usace_dropped_no_qc": 0, "dropped_out_of_scope": 0,
    }

    for opp in seen.values():
        if not hard_filters_ok(opp, today=today, due_max=due_max):
            continue

        # Description fetch (best-effort; needed for USACE detection + region text fallback).
        opp.description_text = sam_fetch_description(opp.description_url)

        opp.is_usace, opp.usace_district = detect_usace(opp)
        opp.region_bucket = classify_region(opp)

        keep, reason = include_by_scope(opp)
        if not keep:
            stats["dropped_out_of_scope"] += 1
            if reason.startswith("USACE dropped"):
                stats["usace_dropped_no_qc"] += 1
            continue

        add_structural_reasons(opp)
        opp.why_matched.append(f"scope:{reason}")

        estimate_ratings(opp)
        opp.score = compute_score(opp)
        scored.append(opp)

        stats["in_scope"] += 1
        if opp.is_usace:
            stats["usace"] += 1
        if opp.region_bucket in {"south_asia", "southeast_asia"} and not opp.is_usace:
            stats["asia_only"] += 1
        if opp.is_usace and opp.region_bucket in {"south_asia", "southeast_asia"}:
            stats["usace_in_asia"] += 1
        if is_nepal(opp):
            stats["nepal"] += 1

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
        f"USACE (QC/QS) + S/SE Asia + Nepal Opportunities "
        f"({stats['in_scope']} in scope | {stats['usace_in_asia']} sweet-spot | {stats['nepal']} Nepal) — {now:%b %d, %Y}"
    )
    attachments = [p for p in [xlsx_path, csv_path] if p]
    send_email(subject, email_text, html_body=email_html, attachments=attachments)

    print(f"[INFO] Wrote spreadsheet files: {', '.join(attachments)}", file=sys.stderr)
    print(
        f"\n[INFO] API calls: {total_calls} | Deduped candidates: {len(seen)} | "
        f"In scope: {stats['in_scope']} | USACE (QC/QS): {stats['usace']} | Asia-only: {stats['asia_only']} | "
        f"Sweet spot: {stats['usace_in_asia']} | Nepal: {stats['nepal']} | "
        f"USACE dropped (no QC/QS): {stats['usace_dropped_no_qc']} | Dropped: {stats['dropped_out_of_scope']} | "
        f"Top: {len(top)} | Shortlist: {len(shortlist)} | SEND_EMAIL={int(SEND_EMAIL)}",
        file=sys.stderr,
    )
    for k in sorted(job_counts, key=lambda x: (-job_counts[x], x))[:20]:
        print(f"[JOB] {k}: {job_counts[k]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
