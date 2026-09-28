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


## Runtime threshold tracking

The scheduled workflows use a **60-minute job timeout**. Each completed scanner
run now writes `runtime_metrics.json` with:

- total run elapsed time
- elapsed time for each structured SAM.gov query/job
- result count by query/job
- percentage of the 60-minute threshold consumed
- a `near_timeout` flag at 80% of the threshold

The metrics file is retained with the daily workflow artifacts. Historical
tracking should aggregate these records so we can see which query families most
often consume the runtime budget and how frequently a scanner approaches the
60-minute limit. A run that actually reaches GitHub's 60-minute job timeout may
be terminated before the script can write its final metrics file, so GitHub
Actions run status/duration should also be included in that historical record.

## Deadline urgency flag

Report output now prefixes opportunities due within **3 days** with `❗`.
The same urgency marker is included in flattened CSV/XLSX data as
`urgency_flag`.

When historical notice tracking is added, the report should combine status and
urgency so a newly discovered opportunity with an unusually short response
window is especially conspicuous (for example, `❗ NEW`). The current change
does not guess whether an opportunity is new; it only evaluates the actual
response deadline.

## Historical tracking design note

The future persistent history should retain at minimum:

- notice ID
- first-seen timestamp
- most-recent-seen timestamp
- material fields used to detect updates
- prior response deadline
- scanner(s) that surfaced the notice
- runtime metrics by scanner/query and GitHub run duration/status

That supports `NEW`, `UPDATED`, and `SEEN BEFORE` labels without changing
the underlying search coverage.


## Runtime and historical tracking

All five scheduled workflows now use a **60-minute timeout**. Each scanner writes
`runtime_metrics.json` with total elapsed time plus per-query timing, API call
count, and item count. The metrics also mark runs at or above 50 minutes as
`near_timeout` and at or above 60 minutes as `timeout_threshold_reached`.

The runtime file is uploaded with each run's artifacts so we can measure which
scanner/query families are driving long runs. The next historical-tracking phase
should persist these metrics across runs and summarize how often each scanner
approaches the 60-minute threshold.

## Historical opportunity status and deadline urgency

Historical opportunity tracking is still planned rather than inferred from the
current posting window. Once the persistent notice-history store is added,
reports should label opportunities `NEW`, `UPDATED`, and `SEEN BEFORE`.

In the meantime, all five reports now add a **❗** deadline flag to opportunities
whose response deadline is within three days. The report note explicitly says
that NEW/UPDATED labels will be added with historical tracking. This avoids
calling an opportunity "new" until the system can verify that from prior runs.
