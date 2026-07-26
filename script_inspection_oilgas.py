#!/usr/bin/env python3
"""
SAM.gov Daily Scan — Inspection + Oil & Gas focus.

Fourth scanner in the Weston scan fleet. Complements script.py (WEXMAC logistics),
script_pest.py (pest/vector), and script_usace_asia.py (USACE + South/Southeast Asia).
This one narrows on domain (inspection or petroleum) with no geographic filter.

Scope:
- Global. Every federal notice is a candidate, worldwide. No geographic hard filter.
- No agency-level priority boost. Buyer patterns emerge naturally from the data.
- Domain is what drives ranking: inspection (welding, coating, QA/QC) plus
  petroleum operations across upstream, midstream, downstream, fuel infrastructure,
  environmental/remediation, and petroleum testing standards.
- Sweet spot: a notice that hits BOTH the inspection family AND any oil/gas
  family gets a double-hit boost. Those are the highest-fit opportunities.

Ranking:
- Domain families (weighted). Weston-relevant families (fuel systems, inspection,
  midstream, upstream) get the highest weights.
- Sweet-spot double-hit boost (+15) when inspection AND oil/gas both fire.
- SDVOSB / VOSB priority boosts (same as other scanners).
- Home-region tiered boost (NC / SC-VA / broader Southeast) so domestic
  in-region work still ranks well — but NO out-of-region penalty because the
  intended scope is global.

Improvements pulled forward from the earlier scripts:
- Structured placeOfPerformance extraction (country/state/city from the API).
- Word-boundary keyword matching — required here because oil/gas acronyms like
  "AST", "UST", "POL", "API", "MTBE" would false-positive catastrophically
  under substring matching (AST inside "cast", UST inside "just", POL inside
  "policy", API inside "capital").

Email + CSV + XLSX output mirrors the existing scripts.

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

import smtplib
from email.message import EmailMessage


# -----------------------------
# CONFIG
# -----------------------------

SAM_SEARCH_URL = "https://api.sam.gov/prod/opportunities/v2/search"

NOTICE_TYPES = ["r", "p", "o", "k"]  # Sources Sought, Presolicitation, Solicitation, Combined
POSTED_WINDOW_HOURS = 72
ACTIVE_ONLY = True

# -----------------------------
# NAICS — inspection + oil/gas universe
# -----------------------------
NAICS = [
    # Inspection / QA-QC / testing
    "541350",  # Building Inspection Services
    "541380",  # Testing Laboratories (NDT, materials testing, coatings testing)
    "238120",  # Structural Steel and Precast Concrete Contractors (welding trade)
    "238320",  # Painting and Wall Covering (coating trade)

    # Oil & Gas — Upstream & Wells
    "211120",  # Crude Petroleum Extraction
    "211130",  # Natural Gas Extraction
    "213111",  # Drilling Oil and Gas Wells
    "213112",  # Support Activities for Oil and Gas Operations

    # Oil & Gas — Midstream & Pipelines
    "237120",  # Oil and Gas Pipeline and Related Structures Construction
    "486110",  # Pipeline Transportation of Crude Oil
    "486210",  # Pipeline Transportation of Natural Gas
    "486910",  # Pipeline Transportation of Refined Petroleum Products
    "486990",  # All Other Pipeline Transportation
    "424710",  # Petroleum Bulk Stations and Terminals

    # Oil & Gas — Downstream & Refining
    "324110",  # Petroleum Refineries
    "324191",  # Petroleum Lubricating Oil and Grease Manufacturing
    "324199",  # All Other Petroleum and Coal Products Manufacturing

    # Fuel Systems infrastructure / support
    "238910",  # Site Preparation Contractors (tank/pipeline sites)
    "238990",  # Other Specialty Trade Contractors
    "541330",  # Engineering Services (petroleum engineering)
    "541690",  # Other Scientific and Technical Consulting

    # Petroleum Environmental & Remediation
    "541620",  # Environmental Consulting Services
    "562910",  # Remediation Services
    "562211",  # Hazardous Waste Treatment and Disposal
]

# -----------------------------
# PSC — inspection + petroleum
# -----------------------------
PSCS = [
    # Quality Control / Testing / Inspection (H-series)
    "H121", "H122", "H140", "H170", "H199",   # QC — physical/chemical/mechanical
    "H221", "H222", "H231", "H271", "H299",   # NDT / materials testing
    "H371", "H399",                           # Inspection services

    # Petroleum construction (Y — construction of petroleum facilities)
    "Y1EA",  # Construction: Fuel Storage Buildings
    "Y1EB",  # Construction: Fuel Storage Facilities (Non-Building)
    "Y1QA",  # Petroleum Facilities Improvements

    # Petroleum maintenance/repair (Z)
    "Z1EA",  # M/R/A: Fuel Storage Buildings
    "Z1EB",  # M/R/A: Fuel Storage Facilities (Non-Building)

    # Petroleum products & fuel supply (9-series)
    "9130",  # Liquid Propellants and Fuels, Petroleum Base
    "9135",  # Liquid Propellants and Fuels, Chemical Base
    "9140",  # Fuel Oils
    "9150",  # Oils and Greases, Cutting, Lubricating, Hydraulic
    "9160",  # Miscellaneous Waxes, Oils, and Fats

    # Engineering & professional services adjacent
    "R408",  # Support — Program Management/Support Services
    "R699",  # Support — Management: Other
    "R425",  # Engineering & Technical Services

    # Environmental / remediation
    "F108",  # Environmental Systems Protection Support
    "F999",  # Other Environmental Services
]

# -----------------------------
# HOME-REGION TIERS (boost only — NO out-of-region penalty)
# -----------------------------
# Same NC-centric ladder as script.py, but without the -25 penalty for
# out-of-region notices. This scanner is intentionally global, so the tiers
# reward home-region work without excluding distant opportunities.
HOME_REGION_TIERS = {
    18.0: {"NC"},                                     # Tier 1 — home base
    12.0: {"SC", "VA"},                               # Tier 2 — adjacent core
    6.0:  {"MD", "TN", "WV", "KY", "PA", "DC", "GA"}, # Tier 3 — broader region
}

# -----------------------------
# SET-ASIDE (structured codes + text fallback)
# -----------------------------
SDVOSB_SETASIDE_CODES = {"SDVOSBC", "SDVOSBS"}
VOSB_SETASIDE_CODES = {"VSA", "VSS"}
SMALLBIZ_SETASIDE_CODES = {"SBA", "SBP"}
SDVOSB_PRIORITY_BOOST = 25.0
VOSB_PRIORITY_BOOST = 12.0

# -----------------------------
# SWEET-SPOT BOOST — inspection AND oil/gas both fire
# -----------------------------
SWEET_SPOT_BOOST = 15.0

# -----------------------------
# DOMAIN FAMILIES — ranking signals (no filtering)
# -----------------------------
# Weight guidance:
#   Fuel Systems & DoD Petroleum — highest (DoD fuel work is Weston's sweet spot)
#   Inspection and QA/QC         — high (cross-cutting, well-suited to sub role)
#   Oil & Gas Midstream          — high (pipelines/tanks, where inspection fires)
#   Oil & Gas Upstream           — medium-high (drilling/wells, capital-intensive)
#   Petroleum Testing & Standards- medium (API 653/570/1104/510 bridge inspection)
#   Oil & Gas Downstream         — medium (refining, less small-biz)
#   Petroleum Environmental      — medium (spill response, remediation)
DOMAIN_FAMILIES = {
    "Fuel Systems & DoD Petroleum": {
        "weight": 26,
        "terms": [
            # DoD fuel infrastructure
            "pol", "petroleum oil lubricants", "petroleum oils lubricants",
            "dfsp", "defense fuel support point", "defense fuel",
            "defense energy support center", "defense logistics agency energy",
            "dla energy",
            # Hydrant / installation fueling
            "hydrant fueling", "hydrant system", "type iii hydrant", "type iv hydrant",
            "hydrant refueler", "aircraft refueling", "into-plane fueling",
            "into plane fueling", "r-11", "r-9", "fuel bowser",
            # Fuel storage & farm
            "fuel farm", "tank farm", "fuel storage", "petroleum storage",
            "aboveground storage tank", "aboveground storage tanks",
            "underground storage tank", "underground storage tanks",
            # Use the acronym forms only with word boundaries (safe under regex)
            "ast", "asts", "ust", "usts",
            # Tank services
            "tank cleaning", "tank inspection", "tank calibration", "tank certification",
            "tank recertification", "tank strapping", "tank gauging",
            "spill containment", "secondary containment", "oil water separator", "ows",
            # Fuel distribution
            "fuel truck", "fuel tanker", "fuel delivery", "fuel supply",
            "fuel logistics", "fuel movement", "bulk fuel",
        ],
    },
    "Inspection and QA/QC": {
        "weight": 24,
        "terms": [
            # General QA/QC
            "quality control", "quality assurance", "qa/qc", "quality control plan",
            "quality control program", "qcp", "cqm", "cqm-c",
            "construction quality management", "em 385-1-1", "em385", "em385-1-1",
            "usace qc", "resident management system", "rms3",
            "three phase inspection", "three-phase inspection",
            "inspection test plan", "inspection and test plan", "itp",
            "iso 9001", "ansi n45.2", "quality manager", "quality control manager",
            # Welding inspection
            "welding inspection", "weld inspection", "weld inspector",
            "cwi", "scwi", "certified welding inspector",
            "senior certified welding inspector",
            "cwi endorsement", "scwi endorsement", "aws certification",
            # AWS CWI/SCWI code-based endorsements (per AWS.org, 14 total).
            # Code numbers included as bare tokens because solicitations often
            # reference just the number ("per D1.1", "AWS D17.1 endorsement req'd").
            # Word-boundary regex prevents false positives on adjacent digits.
            # Structural Steel (D1.1)
            "d1.1", "aws d1.1", "aws d1", "structural welding code",
            # Structural Aluminum (D1.2)
            "d1.2", "aws d1.2", "aluminum structural welding",
            # Bridge Welding (D1.5)
            "d1.5", "aws d1.5", "bridge welding code",
            # Railroad (D15.1)
            "d15.1", "aws d15.1", "railroad welding",
            # Aerospace (D17.1)
            "d17.1", "aws d17.1", "aerospace welding code",
            # Pipeline (API 1104)
            "api 1104", "api-1104", "pipeline welding code",
            # ASME BPVC Section IX / B31.1 / B31.3
            "asme ix", "asme section ix", "asme bpvc", "asme bpvc section ix",
            "b31.1", "asme b31.1", "b31.3", "asme b31.3",
            "power piping code", "process piping code",
            # ISO Standard endorsement (ISO 3834 welding quality / ISO 14731 coordination)
            "iso 3834", "iso 14731", "iso welding standard",
            # NDT endorsements (MT and PT — specific AWS endorsements distinct
            # from generic NDT scope, so we tag "endorsement" phrasing too)
            "magnetic particle endorsement", "mt endorsement",
            "penetrant testing endorsement", "pt endorsement",
            "penetrant testing",
            # Coordination / QA endorsements (also SCWI-stackable)
            "nondestructive examination coordination", "ndec",
            "welding coordination and qa", "welding coordination",
            # Welder Performance Qualifier (WPQ1) / Welding Procedure Qualifier (WPQ2)
            "welder performance qualifier", "wpq1",
            "welding procedure qualifier", "wpq2",
            "weld procedure qualification", "wpq", "wps", "weld quality",
            "weld defect", "weld repair",
            # NDT
            "nondestructive testing", "non-destructive testing", "ndt",
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
        ],
    },
    "Oil & Gas — Midstream & Pipelines": {
        "weight": 22,
        "terms": [
            # Pipelines
            "pipeline", "pipeline inspection", "pipeline integrity",
            "pipeline construction", "pipeline rehabilitation",
            "crude pipeline", "natural gas pipeline", "product pipeline",
            "gathering system", "transmission pipeline", "distribution pipeline",
            "compressor station", "pump station", "valve station", "meter station",
            "block valve", "check valve",
            # Integrity & inline inspection
            "in-line inspection", "inline inspection", "ili", "smart pig",
            "pig launcher", "pig receiver", "pigging", "pipeline pigging",
            "maop", "mop", "integrity management", "pipeline integrity management",
            "corrosion control", "cathodic protection survey",
            # Terminals & storage
            "product terminal", "tank terminal", "bulk terminal", "loading rack",
            "lact unit", "custody transfer", "custody transfer measurement",
            # Codes and standards specific to midstream
            "api 653", "api 570", "api 510", "api 6d", "api 620", "api 650",
            "api rp 1173",
        ],
    },
    "Oil & Gas — Upstream & Wells": {
        "weight": 20,
        "terms": [
            "oil well", "gas well", "wellhead", "well site",
            "drilling", "drilling rig", "workover", "workover rig",
            "well completion", "well plugging", "plug and abandon",
            "p&a services", "p and a services", "well decommissioning",
            "wellbore", "casing", "tubing", "borehole",
            "wildcat well", "exploration well", "development well",
            "hydraulic fracturing", "fracking", "frac", "frac stimulation",
            "cementing services", "perforation", "well logging",
            "mud logging", "artificial lift", "gas lift", "electric submersible pump",
            "esp", "pump jack", "rod pump", "waterflood", "eor",
            "enhanced oil recovery", "reservoir engineering",
        ],
    },
    "Petroleum Testing & Standards": {
        "weight": 22,
        "terms": [
            # API inspection standards (heavy overlap with inspection but distinct)
            "api 653", "api 570", "api 510", "api 1104", "api 6d",
            "api 620", "api 650", "aboveground storage tank inspection",
            "storage tank inspection", "pressure vessel inspection",
            "piping inspection", "in-service inspection", "out-of-service inspection",
            "tank integrity", "pressure vessel integrity",
            # Standards bodies
            "api", "american petroleum institute", "asme section",
            "nb-23", "national board inspection code",
            # Certifications
            "api 653 inspector", "api 570 inspector", "api 510 inspector",
            "asnt", "asnt level ii", "asnt level iii",
            "asme certified", "asme code",
            # Fuel quality
            "fuel quality", "fuel testing", "fuel sampling",
            "astm d975", "astm d1655", "astm d4814",
        ],
    },
    "Oil & Gas — Downstream & Refining": {
        "weight": 16,
        "terms": [
            "refinery", "refining", "petroleum refinery",
            "crude unit", "fluid catalytic cracker", "fcc unit",
            "hydrocracker", "coker", "delayed coker", "reformer",
            "atmospheric distillation", "vacuum distillation",
            "alkylation", "hydrotreater", "isomerization",
            "sulfur recovery", "sru", "amine treating", "sour water",
            "blender", "blending", "bulk plant",
            # Products
            "gasoline", "diesel", "jet fuel", "jet a", "jet a-1",
            "jp-8", "jp-5", "jp-4", "f-24", "f-76", "kerosene",
            "avgas", "aviation gasoline", "distillate fuel", "residual fuel",
            "marine fuel", "bunker fuel", "biodiesel", "renewable diesel",
        ],
    },
    "Petroleum Environmental & Remediation": {
        "weight": 16,
        "terms": [
            # Spills
            "oil spill", "oil spill response", "spill response",
            "petroleum spill", "spill prevention", "spill containment",
            "spcc plan", "spcc",
            # Contaminated sites
            "lust", "leaking underground storage tank", "petroleum contamination",
            "petroleum-contaminated soil", "contaminated soil",
            "groundwater contamination", "groundwater remediation",
            "soil remediation", "vapor intrusion",
            "lnapl", "dnapl", "free product",
            "benzene", "mtbe", "tph", "total petroleum hydrocarbons",
            # Regulatory
            "rcra", "cercla", "superfund", "corrective action",
            "brownfield", "site assessment", "environmental site assessment",
            "esa phase i", "esa phase ii", "phase i esa", "phase ii esa",
        ],
    },
}

# Family-name sets used for the sweet-spot double-hit check.
INSPECTION_FAMILY_NAMES = {"Inspection and QA/QC"}
OILGAS_FAMILY_NAMES = {
    "Fuel Systems & DoD Petroleum",
    "Oil & Gas — Midstream & Pipelines",
    "Oil & Gas — Upstream & Wells",
    "Petroleum Testing & Standards",
    "Oil & Gas — Downstream & Refining",
    "Petroleum Environmental & Remediation",
}

# Buyer-fit terms (weak ranking — no priority boost per user preference).
BUYER_FIT_TERMS = {
    "DLA Energy / DoD fuel": [
        "dla energy", "defense logistics agency", "defense fuel", "dfsp",
        "military sealift", "msc", "installation fuel", "base fuel",
    ],
    "USACE": [
        "corps of engineers", "usace",
    ],
    "Interior — BLM / BOEM / BSEE": [
        "bureau of land management", "blm",
        "bureau of ocean energy management", "boem",
        "bureau of safety and environmental enforcement", "bsee",
    ],
    "DOE / national labs": [
        "department of energy", "doe", "national laboratory",
        "strategic petroleum reserve", "spr",
    ],
    "EPA / environmental regulators": [
        "environmental protection agency", "epa", "environmental compliance",
    ],
}

SETASIDE_BOOST_TERMS = {
    "VOSB/SDVOSB": ["vosb", "veteran-owned", "veteran owned", "sdvosb", "service-disabled", "service disabled veteran"],
    "Small business": ["small business", "total small business", "small business set-aside", "sbsa", "set-aside", "set aside"],
}

LOGISTICS_TERMS = [
    "oconus", "overseas", "remote site", "island", "customs",
    "bill of lading", "hazmat", "multi-site",
]

NEGATIVE_FIT_TERMS = [
    "software development only", "strictly it services",
    "cybersecurity certification only", "research and development grant",
    "university grant", "medical residency",
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
EMAIL_SUBJECT_BASE = "SAM.gov Inspection + Oil & Gas Opportunities"

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

    pop_country_code: Optional[str] = None
    pop_country_name: Optional[str] = None
    pop_state_code: Optional[str] = None
    pop_state_name: Optional[str] = None
    pop_city_name: Optional[str] = None

    why_matched: List[str] = field(default_factory=list)
    description_text: str = ""
    matched_families: List[str] = field(default_factory=list)

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
    Whole-word/phrase match. Required for this scanner because the term lists
    include acronyms like AST/UST/POL/API/MTBE that would false-positive under
    substring matching (AST inside "cast", UST inside "just", POL inside
    "policy", API inside "capital").
    """
    term = (term or "").strip().lower()
    if not term:
        return False
    escaped = re.escape(term)
    escaped = re.sub(r"\\\s+", r"\\s+", escaped)
    pattern = r"(?<!\w)" + escaped + r"(?!\w)"
    return re.search(pattern, text) is not None


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


def home_region_boost(opp: Opportunity) -> Tuple[float, Optional[str]]:
    """
    In-region tiered boost only. NO out-of-region penalty (unlike the WEXMAC and
    USACE/Asia scanners) so global-scope opportunities remain in play.
    """
    state = opp.pop_state_code.strip().upper() if opp.pop_state_code else (
        opp.office_state.strip().upper() if opp.office_state else None
    )
    if state:
        for boost, states in HOME_REGION_TIERS.items():
            if state in states:
                return boost, state
    return 0.0, state


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

    domain_fit = min(72, sum(family_scores.values()))

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

    # Heavy scope: refining and remediation are capital-intensive; upstream
    # drilling too. Inspection and fuel-system sub work is normal complexity.
    heavy_families = {
        "Oil & Gas — Downstream & Refining",
        "Petroleum Environmental & Remediation",
        "Oil & Gas — Upstream & Wells",
    }
    if any(f in family_scores for f in heavy_families):
        complexity += 1
        overhead += 1
    if remote_hits:
        overhead += 1
    if any(w in text for w in ["nationwide", "multi-site", "24/7", "classified", "secret", "top secret"]):
        complexity += 1
        overhead += 1
    if negative_hits:
        complexity += 1

    complexity = max(1, min(5, complexity))
    overhead = max(1, min(5, overhead))
    profitability = max(1, min(5, profitability))

    evidence: List[str] = []
    if family_scores:
        for fam, pts in sorted(family_scores.items(), key=lambda x: x[1], reverse=True)[:5]:
            evidence.append(f"{fam} fit (+{pts}): {', '.join(family_evidence[fam][:5])}")
    evidence.extend(setaside_evidence)
    evidence.extend(buyer_evidence)
    if negative_hits:
        evidence.append("Possible off-scope signal: " + ", ".join(negative_hits[:4]))

    # Track which family names matched, for the sweet-spot boost.
    opp.matched_families = list(family_scores.keys())

    opp.ratings = {
        "complexity": complexity,
        "profitability": profitability,
        "overhead": overhead,
        "domain_fit": domain_fit,
        "buyer_fit": buyer_score,
        "setaside_fit": setaside_score,
        "setaside_class": classify_setaside(opp),
        "matched_families": opp.matched_families,
        "matched_inspection": any(f in INSPECTION_FAMILY_NAMES for f in opp.matched_families),
        "matched_oilgas": any(f in OILGAS_FAMILY_NAMES for f in opp.matched_families),
    }
    opp.evidence = evidence[:8]
    opp.next_step = (
        "Confirm scope alignment (inspection role, oil/gas discipline), place of "
        "performance, set-aside eligibility, required certifications (CWI, NACE, "
        "API 653/570), mobilization footprint, insurance, and response deadline."
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

    region_boost, region_state = home_region_boost(opp)
    if region_boost != 0.0:
        opp.ratings["home_region_boost"] = region_boost
        opp.ratings["home_region_state"] = region_state

    # Sweet spot: inspection AND any oil/gas family both fire.
    sweet_spot = 0.0
    if opp.ratings.get("matched_inspection") and opp.ratings.get("matched_oilgas"):
        sweet_spot = SWEET_SPOT_BOOST
    opp.ratings["sweet_spot_boost"] = sweet_spot

    return (
        domain_fit + buyer_fit + setaside_fit
        + (feasibility * 12.0) + (rel * 0.75)
        + setaside_boost + region_boost + sweet_spot
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
    return "; ".join(items[:max_items]) if items else "Matched inspection or oil/gas signals"


def get_scope_tag(opp: Opportunity) -> str:
    ins = opp.ratings.get("matched_inspection")
    og = opp.ratings.get("matched_oilgas")
    if ins and og:
        return "SWEET SPOT"
    if ins:
        return "Inspection"
    if og:
        return "Oil & Gas"
    return "Weak match"


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
    lines.append("Today's SAM.gov scan for inspection and oil & gas opportunities (global scope).")
    lines.append(f"Search window: last ~{POSTED_WINDOW_HOURS} hours")
    lines.append(f"Total scored: {stats.get('scored', 0)}")
    lines.append(f"  Inspection matches: {stats.get('inspection', 0)}")
    lines.append(f"  Oil & Gas matches: {stats.get('oilgas', 0)}")
    lines.append(f"  Sweet spot (both): {stats.get('sweet_spot', 0)}")
    lines.append(f"Top opportunities: {len(top)}")
    lines.append(f"Next-best shortlist: {len(shortlist)}")
    lines.append("")

    lines.append("HIGH PRIORITY / TOP OPPORTUNITIES")
    lines.append("=" * 72)
    if not top:
        lines.append("No top opportunities found for this run.")
    for i, opp in enumerate(top, 1):
        lines.append(f"{i}) [{get_scope_tag(opp)}] {opp.title}")
        lines.append(f"   - Score: {opp.score:.1f} | Feasibility: {opp.feasibility:.2f}")
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
        lines.append(
            f"- [{get_scope_tag(opp)}] {opp.title} | Score {opp.score:.1f} | "
            f"{get_location_label(opp)} | {get_setaside_label(opp)} | "
            f"Due {opp.responseDeadLine or '—'}"
        )
        lines.append(f"  {opp.uiLink}")

    lines.append("")
    lines.append("Full ranked results are attached in Excel/CSV.")
    return "\n".join(lines)


def build_html_email(top: List[Opportunity], shortlist: List[Opportunity], as_of: dt.datetime, stats: Dict[str, int]) -> str:
    def esc(x: Any) -> str:
        return html.escape(str(x or ""))

    def tag_pill(text: str, color: str) -> str:
        return (f"<span style='background:{color};color:#fff;padding:2px 8px;"
                f"border-radius:10px;font-size:11px;margin-right:4px;'>{esc(text)}</span>")

    def scope_pill(opp: Opportunity) -> str:
        t = get_scope_tag(opp)
        color = {"SWEET SPOT": "#0B3D91", "Inspection": "#2f8f4d", "Oil & Gas": "#8B4513"}.get(t, "#888")
        return tag_pill(t, color)

    def opportunity_card(i: int, opp: Opportunity) -> str:
        return f"""
        <tr>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;">{i}</td>
          <td style="vertical-align:top;padding:8px;border-bottom:1px solid #ddd;">
            <div style="font-weight:700;font-size:14px;">{esc(opp.title)}</div>
            <div style="margin-top:4px;">{scope_pill(opp)}</div>
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
          {scope_pill(opp)} <strong>{esc(opp.title)}</strong><br>
          Score {opp.score:.1f} | {esc(get_location_label(opp))} | {esc(get_setaside_label(opp))} | Due {esc(opp.responseDeadLine or '—')}<br>
          <a href="{esc(opp.uiLink)}">Open in SAM.gov</a>
        </li>
        """
        for opp in shortlist[:15]
    ) or "<li>No shortlist opportunities found for this run.</li>"

    return f"""
    <html>
    <body style="font-family:Arial, Helvetica, sans-serif;color:#222;line-height:1.35;">
      <h2 style="margin-bottom:4px;">Inspection + Oil &amp; Gas Opportunities</h2>
      <p style="margin-top:0;color:#555;">Generated {as_of:%b %d, %Y %H:%M}. Search window: last ~{POSTED_WINDOW_HOURS} hours. Global scope.</p>

      <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin:12px 0 18px 0;">
        <tr>
          <td style="padding:8px 18px 8px 0;"><strong>Total scored</strong><br>{stats.get('scored', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>Inspection</strong><br>{stats.get('inspection', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>Oil &amp; Gas</strong><br>{stats.get('oilgas', 0)}</td>
          <td style="padding:8px 18px 8px 0;"><strong>Sweet spot</strong><br>{stats.get('sweet_spot', 0)}</td>
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

      <p style="margin-top:18px;">Full ranked results are attached (CSV + XLSX) with per-row scope tag, matched families, and match evidence.</p>
    </body>
    </html>
    """


def opp_to_row(opp: Opportunity, rank_group: str = "") -> Dict[str, Any]:
    return {
        "rank_group": rank_group,
        "score": round(float(opp.score or 0), 3),
        "feasibility": round(float(opp.feasibility or 0), 3),
        "scope_tag": get_scope_tag(opp),
        "matched_inspection": "Y" if opp.ratings.get("matched_inspection") else "",
        "matched_oilgas": "Y" if opp.ratings.get("matched_oilgas") else "",
        "matched_families": " | ".join(opp.matched_families or []),
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
    filename = f"sam_results_inspection_oilgas_{as_of:%Y-%m-%d}.csv"
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

    filename = f"sam_results_inspection_oilgas_{as_of:%Y-%m-%d}.xlsx"
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
    summary.append(["Total scored", stats.get("scored", 0)])
    summary.append(["Inspection matches", stats.get("inspection", 0)])
    summary.append(["Oil & Gas matches", stats.get("oilgas", 0)])
    summary.append(["Sweet spot (both)", stats.get("sweet_spot", 0)])
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

    # Fan-out jobs: NAICS + PSC single-code calls. No state fan-out because the
    # scope is global — a state fan-out would multiply API calls without value.
    jobs: List[Tuple[str, Dict[str, Any]]] = []
    for code in NAICS:
        jobs.append((f"naics:{code}", {**base, "ncode": code}))
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
    stats = {"scored": 0, "inspection": 0, "oilgas": 0, "sweet_spot": 0, "no_match": 0}

    for opp in seen.values():
        if not hard_filters_ok(opp, today=today, due_max=due_max):
            continue

        opp.description_text = sam_fetch_description(opp.description_url)
        add_structural_reasons(opp)
        estimate_ratings(opp)

        # Drop notices that hit no domain family — those slipped in on NAICS/PSC
        # match alone but have no in-body signal. Global scope + no agency boost
        # means we need at least one family match to justify surfacing the notice.
        if not opp.matched_families:
            stats["no_match"] += 1
            continue

        opp.score = compute_score(opp)
        scored.append(opp)

        stats["scored"] += 1
        if opp.ratings.get("matched_inspection"):
            stats["inspection"] += 1
        if opp.ratings.get("matched_oilgas"):
            stats["oilgas"] += 1
        if opp.ratings.get("matched_inspection") and opp.ratings.get("matched_oilgas"):
            stats["sweet_spot"] += 1

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
        f"Inspection + Oil & Gas Opportunities "
        f"({stats['scored']} scored | {stats['sweet_spot']} sweet-spot) — {now:%b %d, %Y}"
    )
    attachments = [p for p in [xlsx_path, csv_path] if p]
    send_email(subject, email_text, html_body=email_html, attachments=attachments)

    print(f"[INFO] Wrote spreadsheet files: {', '.join(attachments)}", file=sys.stderr)
    print(
        f"\n[INFO] API calls: {total_calls} | Deduped candidates: {len(seen)} | "
        f"Scored: {stats['scored']} | Inspection: {stats['inspection']} | Oil&Gas: {stats['oilgas']} | "
        f"Sweet spot: {stats['sweet_spot']} | Dropped (no family match): {stats['no_match']} | "
        f"Top: {len(top)} | Shortlist: {len(shortlist)} | SEND_EMAIL={int(SEND_EMAIL)}",
        file=sys.stderr,
    )
    for k in sorted(job_counts, key=lambda x: (-job_counts[x], x))[:20]:
        print(f"[JOB] {k}: {job_counts[k]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
