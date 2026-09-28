# SAM.gov Agent Engineering Review

This branch integrates the highest-confidence recommendations from independent
Open-Strix and Hermes reviews of the daily SAM.gov scanner fleet.

## Active daily scanners reviewed

- `script.py` — logistics / WEXMAC
- `script_pest.py` — pest / vector
- `script_usace_asia.py` — USACE + South/Southeast Asia
- `script_inspection_oilgas.py` — inspection + oil & gas
- `script_catholic_southeast.py` — Catholic Southeast + full NC sweep

The repository currently has five active scheduled scanners, not four.

## Implemented improvements

### API resilience
All five scanners now route SAM.gov search calls through `sam_common.py`.
The shared helper retries bounded transient failures:

- network exceptions
- HTTP 429
- HTTP 500, 502, 503, and 504

Retries use exponential backoff and honor `Retry-After` when available. Error
messages do not include the API key.

The logistics and pest scanners also now catch per-job API failures and continue
cleanly, matching the behavior already present in the other three scanners.

### Workflow reliability
All five scheduled GitHub Actions workflows now include:

- read-only repository permissions
- per-workflow concurrency protection without cancelling an active scan
- 60-minute job timeout
- pip dependency caching
- shared `requirements.txt`
- unique artifact names using the workflow run number
- 30-day artifact retention
- warning rather than failure if an artifact pattern is empty
- saved text and HTML email drafts in artifacts

The inspection/oil-gas run moves from 11:15 UTC to 11:30 UTC so it no longer
starts at the same time as the Catholic/Southeast scan.

### Data hygiene
The duplicated `S203` PSC entry was removed from the logistics and pest
scanner configuration.

### Offline validation
`test_sam_common.py` validates success, retry-after-429, immediate 400 failure,
and bounded network timeout behavior without calling SAM.gov or sending email.

The validation workflow compiles all five scanners and runs the offline tests on
pull requests.

## Intentionally not changed

This branch does **not** alter search scope, keyword families, geographic rules,
set-aside logic, ranking formulas, or opportunity selection thresholds. Those
changes could materially change which opportunities are surfaced and should be
evaluated separately against real result sets.

## Recommended next improvements

1. Build a historical-results store keyed by SAM notice ID so daily reports can
   label NEW, UPDATED, and PREVIOUSLY SEEN opportunities.
2. Add report-level pursuit fields such as FIT, PURSUIT, WHY, CAPABILITY MATCH,
   GAPS, PARTNER NEED, URGENCY, NEXT ACTION, CONFIDENCE, and MISSED INFORMATION.
3. Add mocked end-to-end tests using saved SAM.gov response fixtures.
4. Consolidate duplicated report/email/rendering code only after fixture tests
   protect each scanner's current behavior.
5. Measure false positives, missed opportunities, and user pursuit decisions
   before modifying ranking weights.


## Runtime monitoring and deadline urgency

The scheduled scanners now have a 60-minute GitHub Actions timeout. Each run
also writes `runtime_metrics.json`, which records:

- total query/report runtime and percentage of the 60-minute threshold
- whether the run reached 90% of the timeout
- API call count and deduplicated candidate count
- duration and result count for each fan-out query

The runtime file is retained with the daily artifacts for 30 days. This gives us
a per-scanner/per-query record to identify which searches regularly consume the
most time and how often runs approach the timeout. A later historical datastore
can ingest these records for longer-term trend reporting.

Response deadlines are marked with `❗` when an opportunity is due within
3 days. The flag appears in email/report titles and in a `deadline_flag`
spreadsheet/CSV field.

### Historical opportunity tracking

The next report enhancement should persist SAM notice IDs and selected notice
metadata across runs so the report can label opportunities as `NEW`,
`UPDATED`, or `SEEN BEFORE`. Once that persistence is implemented, the most
important combined alert should be:

**❗ NEW — SHORT FUSE**

for a newly discovered opportunity whose response deadline is within 3 days.
Until historical state exists, the current `❗` flag indicates a short
deadline but does not claim the opportunity is new.
