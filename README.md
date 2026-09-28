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

The Catholic Southeast / Full NC report discovers recent postings daily and searches up to one year of NC postings on the first run and each Sunday. It saves in-scope notices as a separate GitHub Actions artifact and restores the latest state from the main branch on the next run. **Every saved notice ID is checked against SAM.gov on every run before its deadline is assessed**, so amendments and extensions replace the cached deadline. Notice-ID lookups use the required posted-date bounds, searching one-year slices back to the saved posting date if necessary. A notice stays in the report until its latest response deadline passes. If a saved ID cannot be refreshed or a search fails, the run fails without emailing a partial report. The first run backfills NC notices from the API; a notice posted more than one year before that first run cannot be discovered unless it was already saved. The separate state artifact is retained for 30 days, so a prolonged interruption requires a manual backfill of older notices.

The Logistics/WEXMAC, Pest/Vector, USACE/Asia, and Inspection/Oil and Gas reports now use the same daily notice-ID refresh and exact-deadline retention. Each workflow has its own state artifact, so one report cannot overwrite another's watchlist. On its first run without saved state, a workflow seeds open IDs from its retained result CSV artifacts (up to 30 days of history), then checks each ID against SAM.gov before reporting. Discovery continues using each report's existing state, NAICS, PSC, and global searches. Saved IDs are refreshed before deadlines are assessed; an API error, missing saved ID, or truncated discovery search fails the run rather than emailing a partial report. `runtime_metrics.json` includes one `notice:<ID>` entry per saved opportunity plus the discovery jobs, which makes daily API usage reviewable. Notices never captured in a retained report cannot be reconstructed from those artifacts.

The configured discovery fan-outs across all five scanners comprise roughly 456 query jobs before pagination, retries, and saved-ID lookups. Each saved ID adds at least one search call per day; older IDs can require multiple one-year date slices. Actual key usage and the 60-minute workflow runtimes should be checked from the first production runs. The public API's daily allowance depends on the key's account role, so this repository does not assume a fixed 4,000-request quota.

## Development validation

Run `python -m pip install -r requirements.txt`, then `python -m unittest -v test_sam_common.py test_scanners.py`. The scanner smoke test uses mocked SAM.gov responses and disables email.
