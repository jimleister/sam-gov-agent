from __future__ import annotations

import time
from typing import Any, Dict

import requests

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def sam_search_with_retry(
    url: str,
    api_key: str,
    params: Dict[str, Any],
    *,
    timeout: int = 60,
    max_attempts: int = 4,
    backoff_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Call the SAM.gov opportunities endpoint with bounded retries.

    Retries network failures plus 429/5xx responses. Error messages never include
    the API key.
    """
    query = dict(params)
    query["api_key"] = api_key
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, params=query, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            if attempt == max_attempts:
                break
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise RuntimeError("SAM API returned invalid JSON") from exc

            snippet = (response.text or "")[:500].replace("\n", " ")
            if response.status_code not in RETRYABLE_STATUS:
                raise RuntimeError(f"SAM API error {response.status_code}: {snippet}")

            last_error = RuntimeError(
                f"SAM API retryable error {response.status_code}: {snippet}"
            )
            if attempt == max_attempts:
                break

            retry_after = response.headers.get("Retry-After")
            try:
                delay = (
                    float(retry_after)
                    if retry_after
                    else backoff_seconds * (2 ** (attempt - 1))
                )
            except (TypeError, ValueError):
                delay = backoff_seconds * (2 ** (attempt - 1))
            time.sleep(min(max(delay, 0.0), 60.0))
            continue

        time.sleep(min(backoff_seconds * (2 ** (attempt - 1)), 60.0))

    raise RuntimeError(
        f"SAM API request failed after {max_attempts} attempts"
    ) from last_error


def deadline_urgency_flag(deadline: Any, as_of: Any = None, urgent_days: int = 3) -> str:
    """Return an exclamation flag when a response deadline is very close."""
    if not deadline:
        return ""
    from datetime import datetime, timezone

    try:
        due = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""

    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)

    if as_of is None:
        now = datetime.now(timezone.utc)
    elif getattr(as_of, "tzinfo", None) is None:
        now = as_of.replace(tzinfo=timezone.utc)
    else:
        now = as_of.astimezone(timezone.utc)

    seconds_left = (due.astimezone(timezone.utc) - now).total_seconds()
    return "❗" if 0 <= seconds_left <= urgent_days * 86400 else ""


def write_runtime_metrics(
    job_elapsed_seconds: Dict[str, float],
    job_result_counts: Dict[str, int],
    total_elapsed_seconds: float,
    *,
    timeout_minutes: int = 60,
    path: str = "runtime_metrics.json",
) -> str:
    """Write per-query and total runtime telemetry for later historical analysis."""
    import json

    threshold_seconds = timeout_minutes * 60
    jobs = []
    for name in sorted(job_elapsed_seconds):
        elapsed = round(float(job_elapsed_seconds[name]), 3)
        jobs.append(
            {
                "query": name,
                "elapsed_seconds": elapsed,
                "result_count": int(job_result_counts.get(name, 0)),
                "threshold_pct": round((elapsed / threshold_seconds) * 100, 2),
                "near_timeout": elapsed >= threshold_seconds * 0.8,
            }
        )

    payload = {
        "timeout_minutes": timeout_minutes,
        "total_elapsed_seconds": round(float(total_elapsed_seconds), 3),
        "total_threshold_pct": round(
            (float(total_elapsed_seconds) / threshold_seconds) * 100, 2
        ),
        "near_timeout": float(total_elapsed_seconds) >= threshold_seconds * 0.8,
        "jobs": jobs,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return path
