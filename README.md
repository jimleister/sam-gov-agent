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

## Development validation

Run `python -m pip install -r requirements.txt`, then `python -m unittest -v test_sam_common.py test_scanners.py`. The scanner smoke test uses mocked SAM.gov responses and disables email.
