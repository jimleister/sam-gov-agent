# Weston prime + E2 Federal Services: SDVOSB opportunity report

This is a sixth independent scanner. It does not replace or modify the existing five scanners. The commercial model is **Weston as the eligible SDVOSB prime, with E2 as a scoped technical subcontractor/teaming partner**. An SBA mentor-protege agreement or JV is not assumed.

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

- Searches the 17 reported E2 Federal NAICS codes, plus five explicitly labeled adjacent industries when enabled.
- Prioritizes SDVOSB prime opportunities and VA buyers. Other agencies and locations remain eligible; there is no geographic hard exclusion.
- Evaluates the potential Weston/E2 team and additional delivery partners, not whether Weston could perform the entire scope alone.
- Separates competitive SDVOSB prospects, early-stage sources sought/presolicitations, secondary opportunities, WEXMAC public notices, sole-source intelligence, and unavailable saved notices.
- Drafts TXT, HTML and EML reports; sends the HTML/text email with a CSV attachment when enabled. Also saves a complete JSON archive and runtime metrics.
- Uses the existing `SAM_API_KEY`, `SMTP_USER`, `SMTP_PASS`, `FROM_EMAIL`, and `EMAIL_TO` repository secrets. Optional `SMTP_HOST`, `SMTP_PORT`, and `REPORT_TO` environment variables override defaults. No secrets belong in source files or the config.
- Default recipient is `jleister@westontrolley.com` only when `REPORT_TO` and `EMAIL_TO` are unset. No E2 personnel or contracting officers are emailed automatically.
- Default schedule is daily at **8:17 a.m. America/New_York**, subject to GitHub scheduling delays. Scheduled workflows must be on the default branch. Manual runs are supported.

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

## Prime/subcontractor structuring notes

These are considerations for the team, not automated exclusion criteria. The scanner treats E2 as a non-similarly-situated subcontractor unless independently established otherwise. Typical limitations are 50% for services, 85% for general construction and 75% for specialty trades, measured as specified in applicable rules/clauses. Construction limits exclude materials; services should not be simplistically described as a universal 50/50 labor split. Supply/nonmanufacturer requirements need a different review. Validate actual contract clauses and applicable exclusions with procurement counsel.

Weston/E2 can evaluate hiring, similarly situated subcontractors and other lawful structures rather than expecting Weston to perform all work with today's resources. Staffing, work allocation and operating arrangements will be developed by the team; the discovery script does not decide them.

A prime/subcontract arrangement does not automatically gain an approved mentor-protege JV affiliation exception. Weston must maintain independent prime control and address unusual reliance concerns as applicable. A subcontracting percentage alone does not resolve every affiliation/control question. Check obligations at the applicable proposal, award and performance stages rather than assuming all requirements can be deferred until after award. The FAR subcontracting limitation is a performance obligation accepted by offer/contract; actual compliance periods are specified in the clause. Resolve employment/conflict issues and document the agreed structure.

The program does not assume HUBZone, 8(a), WOSB or other unestablished eligibility. Structured set-aside fields control classification; a generic mention of SDVOSBs in notice prose does not make a procurement an SDVOSB set-aside. E2's historical work is not automatically Weston's past performance. SF330/A-E, licensing, bonding, security and vehicle access are review notes, not capability-based rejection criteria.

Authoritative rule references:
- https://www.acquisition.gov/far/52.219-14
- https://www.acquisition.gov/far/52.219-27
- https://www.ecfr.gov/current/title-13/chapter-I/part-121/section-121.103
- https://www.sba.gov/veterans/

## WEXMAC scope

This is a **public-notice watch**, separate from competitive SDVOSB opportunities. It searches WEXMAC and TITUS terms but does not infer that a Weston award grants access to every region, extension or task order. It does not read holder-only portals, ordering emails, attachments requiring authorization, or other nonpublic notices. The existing logistics/WEXMAC scanner remains unchanged.

## Discovery, persistence and limits

Discovery uses seven-day posting windows, a 90-day first-run window, and rotating one-year lookbacks across NAICS codes. The initial run is not a complete historical backfill; every code receives its one-year search over a full seven-day cycle. Notices older than one year that were never reported are not guaranteed to be discovered. Public opportunities are not a complete inventory of every agency's available work.

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
