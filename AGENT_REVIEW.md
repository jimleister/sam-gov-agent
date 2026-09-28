# SAM.gov scanner engineering review

The Open-Strix and Hermes reviews led to changes across all five scheduled scanners: logistics/WEXMAC, pest/vector, USACE/South and Southeast Asia, inspection/oil and gas, and Catholic Southeast/full North Carolina. The scanners remain independent workflows. Search scope, scoring, and ranking are unchanged.

## Delivered

- Bounded retries for transient SAM.gov failures (network, 429, 500, 502, 503, 504), honoring `Retry-After` when available.
- Per-query failures do not cancel the remaining search fan-out. Each report keeps its current scope.
- Read-only Actions permissions, non-cancelling per-workflow concurrency, 60-minute job limits, cached dependencies, and unique 30-day artifacts.
- Staggered inspection/oil-and-gas schedule and duplicate PSC `S203` cleanup.
- One `runtime_metrics.json` per completed run with scanner name, total elapsed time, API calls, every query's duration/calls/result count, and flags for 50 and 60 minutes.
- ❗ for a response deadline within 72 hours in email titles and `urgency_flag` / `deadline_flag` CSV/XLSX fields. The alert does not imply that the notice is new.
- Offline API retry and urgency tests plus a smoke test for each scanner's full empty-result report path.

## Operational limits and next work

A GitHub job killed at 60 minutes cannot be guaranteed to write final metrics; use Actions run status/duration alongside artifacts. Runtime artifacts last 30 days. A persistent history can later aggregate them by scanner and query and retain notice IDs for NEW, UPDATED, and SEEN BEFORE labels. Candidate and pursuit feedback should precede changes to scoring weights.

See README.md for the exact manual Actions steps and workflow names.
