# WTC + E2 Federal Services: daily SDVOSB team opportunity report

A sixth independent scanner; the other five are unchanged. It pulls **only notices with a structured SDVOSB set-aside** (SAM codes `SDVOSBC` and `SDVOSBS`) and ranks them for the WTC / E2 Federal Services team.

The report is pathway-neutral. **Current state:** WTC (SDVOSB) primes with E2 Federal Services as subcontractor under a teaming agreement. **Future state:** an SBA-approved WTC/E2 Federal mentor-protege joint venture with WTC as managing venturer. Team roles, workshare notes and past-performance notes cover both.

## Entity research - checked October 29, 2026

Legal entity: **E2 Federal Services LLC**. UEI **RRM2YJMNTPX1**. CAGE **14TE2**. Primary NAICS **561210**.

The following 17 codes agree across two public SAM-derived contractor profiles. This is corroborated secondary-source evidence, **not a direct SAM.gov entity extract**. Confirm the current registration with E2 or a SAM export before using it in a proposal. Corporate registrations, past performance, credentials and resources are not automatically interchangeable across E2 entities.

| NAICS | Industry |
| --- | --- |
| 561210 | Facilities Support Services - primary |
| 236220 | Commercial and Institutional Building Construction |
| 238220 | Plumbing, Heating, and Air-Conditioning Contractors |
| 332710 | Machine Shops |
| 541370 | Surveying and Mapping (except Geophysical) Services |
| 541513 | Computer Facilities Management Services |
| 541611 | Administrative Management and General Management Consulting Services |
| 541618 | Other Management Consulting Services |
| 541620 | Environmental Consulting Services |
| 541690 | Other Scientific and Technical Consulting Services |
| 541990 | All Other Professional, Scientific, and Technical Services |
| 561110 | Office Administrative Services |
| 561320 | Temporary Help Services |
| 561730 | Landscaping Services |
| 561790 | Other Services to Buildings and Dwellings |
| 562111 | Solid Waste Collection |
| 562910 | Remediation Services |

Sources:
- https://govtribe.com/vendors/e2-federal-services-llc-14te2
- https://www.sweetspot.so/markets/federal/contractors/e2-federal-services-llc-rrm2yjmntpx1/
- E2's own federal-service capabilities: https://e2.com/services/federal-services/
- Parent entity, distinct from E2 Federal: https://govtribe.com/vendors/e2-consulting-engineers-inc-dot-1sl68

**541330 Engineering Services is not in the subsidiary's corroborated 17-code list.** It is included as an explicitly labeled strategic expansion because it appears in the parent profile and aligns with E2 capabilities. Other enabled expansions are 541350, 541380, 237110 and 237120; these are not represented as verified E2 Federal registrations. Set `include_adjacent_naics` to false to restrict discovery to the 17 listed codes.

## What the daily report does

- Queries SAM.gov by set-aside (`typeOfSetAside=SDVOSBC` and `SDVOSBS`) for solicitations, combined synopses, presolicitations and sources sought. The first run after this change backfills 90 days; later runs use a 7-day rolling window.
- Scores team fit locally against the 17 reported E2 Federal NAICS codes, the labeled adjacent codes, and scope keywords. SDVOSB notices outside that scope go to the attachment only.
- Lanes: competitive SDVOSB set-asides, early-stage SDVOSB (sources sought / presolicitation), and SDVOSB sole source (market intelligence, capped at 54).
- Email format mirrors the USACE and Inspection reports: summary counts, a High Priority table (top 10), Other Strong Matches (next 15), and full ranked CSV + XLSX attachments. There is no saved-notice banner at the top; unrefreshable saved notices are noted in one line at the bottom and listed in the attachment.
- Uses the existing `SAM_API_KEY`, `SMTP_USER`, `SMTP_PASS`, `FROM_EMAIL`, and `EMAIL_TO` secrets. `REPORT_TO` overrides recipients.
- Default schedule is daily at **8:17 a.m. America/New_York**. Manual runs are supported.

## Inclusive team-based opportunity ranking

Scores rank **potential team opportunity fit**, not Weston's standalone capacity, probability of winning, profit or eligibility. Weston, E2 and additional qualified partners can develop the delivery structure. The scanner does not reject or downgrade opportunities because Weston is not assumed to possess the entire workforce, equipment, bonding or specialist capability today.

| Component | Maximum |
| --- | ---: |
| Team scope / NAICS alignment | 50 |
| Contracting route and set-aside fit | 20 |
| Time to respond | 15 |
| Agency alignment, with VA priority | 10 |
| Place-of-performance alignment | 5 |
| Total before data-quality caps | 100 |

**Removed:** the 20-point standalone execution-readiness proxy; penalties for construction, A-E licensing, 24/7 or multi-site work, bonding, specialist controls, clearances and vehicle-access uncertainty; exclusions for clinical delivery or unrecognized specialties; and the minimum score needed to appear in the report. Contract size, staffing and potential workshare never disqualify a notice in this scanner.

**Retained as review notes only:** specialist staffing, additional partners, workshare, independent prime control, licenses, clearances, bonding, past-performance treatment and vehicle access. Lack of proof is not treated as proof that the team cannot deliver. A positive score is not confirmation of access or eligibility. Suggested work splits are possibilities, not prescribed percentages or assertions about current personnel.

75+ means priority review, 55-74 means qualify, and lower scores mean watch/verify. Every non-blocked notice remains visible: up to ten detailed highlights, followed by a full ranked index of remaining candidates, plus the complete CSV/JSON archive. There is no low-score cutoff; a leftover `minimum_report_score` configuration key is ignored. Headline limits affect presentation only. Only detailed highlights and previously tracked records enter the persistent watchlist; the full index and CSV are discovery archives.

Missing or stale descriptions still cap the score at 64. Missing/unparseable deadlines, uncertain active status and unavailable saved IDs cap it at 49. These describe data quality, not capacity, and do not remove a candidate from the email index. Sources sought are marked as requirement-shaping, not bids. Closed/expired notices, non-actionable notice types and set-asides requiring an unestablished certification remain separated from the candidate list, with exact reasons retained in the full CSV/JSON. Generic capability concerns are never such reasons.

## Team pathway notes

These are considerations for the team, not exclusion criteria. **Prime/sub (current):** E2 Federal is treated as a non-similarly-situated subcontractor; typical limitations are 50% for services, 85% for general construction and 75% for specialty trades (excluding materials). Watch the ostensible subcontractor rule on set-asides. **Mentor-protege JV (future):** the JV is the offeror and must meet the limitation as a whole; WTC as protege generally performs at least 40% of the work the JV performs. Agencies must consider each JV member's past performance. The JV pathway requires SBA approval of the mentor-protege agreement first.

The program does not assume HUBZone, 8(a), WOSB or other unestablished eligibility. Structured set-aside fields control classification; a generic mention of SDVOSBs in notice prose does not make a procurement an SDVOSB set-aside. Validate clauses with procurement counsel.

- https://www.acquisition.gov/far/52.219-14
- https://www.acquisition.gov/far/52.219-27
- https://www.ecfr.gov/current/title-13/chapter-I/part-121/section-121.103
- https://www.sba.gov/federal-contracting/contracting-assistance-programs/sba-mentor-protege-program

## Discovery, persistence and limits

Discovery uses seven-day posting windows and a one-time 90-day backfill. Notices posted before the backfill window that were never reported are not guaranteed to be discovered. Public opportunities are not a complete inventory of every agency's available work.

Only detailed highlights and previously tracked records are retained for daily refresh. Every saved ID is refreshed **before** its cached deadline is applied, so extensions can be discovered. Confirmed closed/expired notices leave the watchlist. Unavailable IDs remain explicitly unverified for retry, not falsely described as open. An unambiguous newer notice with the same solicitation and office may inherit tracking. New/updated/still-open labels compare saved notice content; this is not an unlimited archive of every notice ever seen.

Default bounds are 220 total HTTP requests, 40 pages per query and 45 description fetches. Description requests and retries consume the budget. These requests share the same SAM account quota as the other five scanners. SAM's allowance depends on account role; no particular daily allowance is assumed. The public API uses page-index pagination and date bounds of at most one year.

Quota errors, unexpected API schemas, incomplete pagination and email errors fail visibly. A failed scan is not reported as zero opportunities. The watchlist is only committed after report generation and successful email submission, or after an intentionally successful draft-only run. SMTP submission is not proof of inbox delivery. A retry after an ambiguous SMTP outcome can duplicate an email; exactly-once delivery is not guaranteed.

Attachments are linked but not downloaded or interpreted. Scores use structured metadata and fetched description text; descriptions not fetched today are labeled. Human document review is necessary before pursuit decisions.

API documentation: https://open.gsa.gov/api/get-opportunities-public-api/
GitHub scheduling: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

## Run and validate

The scanner has 54 offline tests, including equal-score checks for large/complex work, staffing and workshare flags, retained specialist opportunities, no minimum-score filter, and full email-index inclusion. Repository-wide tests also validate the unchanged legacy scanners.

```bash
python -m pip install -r requirements.txt
python -m unittest test_e2_sdvosb -v
python script_e2_sdvosb.py --demo --output e2_sdvosb_demo_output

# Live search, draft only; requires SAM_API_KEY in the environment.
SEND_EMAIL=0 python script_e2_sdvosb.py

# Live search and email; requires SAM and SMTP environment credentials.
SEND_EMAIL=1 python script_e2_sdvosb.py
```

Demo mode uses clearly labeled synthetic records and never sends email, reads production state or writes production state. It is not a live opportunity report.

Manual GitHub run: **Actions -> SAM.gov - Weston + E2 / SDVOSB -> Run workflow -> main**. Leave demo false for a live scan; turn send_email off to inspect a live draft first. Reports appear in `sam-results-e2-sdvosb-<run>` artifacts. The state artifact is `e2-sdvosb-opportunity-state`, independent of existing scanners.

The workflow runs offline tests without secrets for code changes, and only runs the credentialed scanner on scheduled/manual main-branch events. Report artifacts are retained for 30 days. State artifacts expire after 30 days without a successful run. GitHub can disable scheduled workflows in inactive public repositories; monitor Actions failures and schedule status.
