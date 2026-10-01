# SAM.gov daily scanners

Five independent GitHub Actions workflows run five opportunity searches. They are **not consolidated into one run**. Each scanner fans out into multiple SAM.gov API queries, combines the results, and sends its own email report. The reports keep the existing search rules and rankings.

| GitHub Actions workflow | File | Scanner | Report focus |
| --- | --- | --- | --- |
| SAM.gov — Logistics / WEXMAC | `run.yml` | `script.py` | Weston Trolley and WEXMAC logistics |
| SAM.gov — Pest / Vector | `run_pest.yml` | `script_pest.py` | Pest and vector control |
| SAM.gov — USACE / South and Southeast Asia | `run_usace_asia.yml` | `script_usace_asia.py` | USACE and South/Southeast Asia |
| SAM.gov — Inspection / Oil and Gas | `run_inspection_oilgas.yml` | `script_inspection_oilgas.py` | Inspection and oil/gas work |
| SAM.gov — Catholic Southeast / Full North Carolina | `run_catholic_southeast.yml` | `script_catholic_southeast.py` | Catholic opportunities in VA/GA/SC/KY/WV/DC, plus full NC sweep |

## Run one report manually

1. Open [Actions](https://github.com/jimleister/sam-gov-agent/actions) in this repository.
2. In the left sidebar, select the workflow named in the table above.
3. Click **Run workflow** on the right, choose branch **main**, then click the green **Run workflow** button.
4. Refresh the workflow page, open the new run, and inspect the `run-script` job. At the bottom of the run, download the uniquely named `sam-results...` artifact for its CSV/XLSX, email draft, and `runtime_metrics.json`.
5. Repeat for each named workflow if you want all five reports. A manual run also sends its email when the repository SMTP secrets are configured; it does not replace the scheduled run.

Runs are independent and may overlap. Each has a 60-minute job timeout. Runtime metrics list the elapsed seconds, API calls, and returned records for every fan-out query. The `near_timeout` field becomes true at 50 minutes; `timeout_threshold_reached` reflects 60 minutes. A job terminated by GitHub at 60 minutes may have no final metrics artifact, so inspect the Actions run status and duration too. Each artifact is retained for 30 days.

Reports mark an opportunity due within 72 hours with ❗. This is based on the response deadline, not whether the notice is newly discovered. Historical NEW/UPDATED/SEEN BEFORE tracking is a separate future step.

All five reports refresh only their **reported/explicit watchlist**: today's Top and Shortlist rows, previously reported records still being tracked, and records marked `explicitly_saved: true` in their scanner's state. Full scored matches stay in the CSV/Excel archive and do not automatically enter daily refresh. A tracked listing remains saved even if it falls out of today's top ranks. Its ID is refreshed before checking the cached deadline so extensions can be discovered; a confirmed closed/expired record is removed. An unavailable ID stays an explicitly unverified review item for retry. API failures still fail visibly.

Each scanner has a separate state artifact with `watchlist_scope: reported-or-explicit-v1`. After restoring an old full-pool state, the workflow rebuilds its watchlist from Top/Shortlist rows in retained successful main-branch report artifacts (up to 30 days), preserves richer cached records and explicit saves, and archives the original pool as `watchlist_migration_archive.json`. Migration uses GitHub requests only, before any SAM API requests. If a nonempty legacy pool cannot be reconciled with any retained report artifacts, migration stops without replacing it. Direct local runs against legacy state also stop until migration is performed. Previously reported records older than retained artifact history require manual recovery or explicit saving.

New normalized records preserve the solicitation number and office code. When an old ID becomes unavailable, an unambiguous newer record already returned by discovery can take over its tracking when solicitation and office match. Legacy records without a solicitation number require the same title/office and at least two identical original attachment URLs. Title alone and ambiguous matches never establish a replacement. Prior notice IDs and explicit-save flags survive the transition. This adds no extra SAM searches.

Daily watchlist updates occur after email submission succeeds (or after a successful intentional SEND_EMAIL=0 run). A failed scan or email does not expand/replace the prior watchlist. The existing 72-hour discovery rules and five separate email schedules remain unchanged. The Catholic/NC report still performs its first-run and Sunday one-year NC backfill.

`runtime_metrics.json` includes one `notice:<ID>` entry per watched opportunity plus discovery jobs. Daily-quota 429 responses with a next-access timestamp fail immediately instead of retrying four times within seconds. Transient throttling and server/network failures retain bounded retries.

The configured discovery fan-outs across all five scanners comprise roughly 456 query jobs before pagination, retries, and saved-ID lookups. Each saved ID adds at least one search call per day; older IDs can require multiple one-year date slices. Actual key usage and the 60-minute workflow runtimes should be checked from the first production runs. The public API's daily allowance depends on the key's account role, so this repository does not assume a fixed 4,000-request quota.

## Development validation

Run `python -m pip install -r requirements.txt`, then `python -m unittest discover -v`. The scanner smoke test uses mocked SAM.gov responses and disables email.

CI also runs `preview_watchlist_migration.py` against main-branch state/report artifacts for all five scanners, publishing before/after counts and migrated snapshots without SAM credentials or email. This read-only replay does not overwrite production artifacts.
