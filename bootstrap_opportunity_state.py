#!/usr/bin/env python3
"""Seed a scanner's watchlist from its still-retained historical CSV artifacts.

Also migrates legacy full-result state to reported/explicit saves. Uses GitHub's
token, never the SAM.gov key. Existing state is preserved if migration fails.
"""
import csv
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from sam_common import WATCHLIST_SCOPE


def api_json(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def artifact_csv_rows(url: str, token: str) -> list[dict]:
    response = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }, timeout=120)
    response.raise_for_status()
    data = response.content
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [name for name in archive.namelist()
                 if name.endswith(".csv") and "sam_results" in name]
        if not names:
            raise ValueError("Result artifact contains no SAM results CSV")
        with archive.open(names[0]) as stream:
            return list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig")))


def open_seed(row: dict, now: datetime) -> dict | None:
    if row.get("rank_group") not in ("Top", "Shortlist") and str(row.get("explicitly_saved", "")).lower() != "true":
        return None
    notice_id = (row.get("notice_id") or "").strip()
    if not notice_id:
        return None
    deadline = (row.get("response_deadline") or "").strip()
    if deadline:
        try:
            due = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Unparseable deadline for {notice_id}") from exc
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due.astimezone(timezone.utc) <= now:
            return None
    return {"noticeId": notice_id, "title": row.get("title") or "",
            "uiLink": row.get("sam_link") or "", "postedDate": row.get("posted_date") or None,
            "responseDeadLine": deadline or None, "active": "Yes",
            "solicitationNumber": row.get("solicitation_number") or None,
            "fullParentPathCode": row.get("agency_office_code") or None,
            "fullParentPathName": row.get("agency_office") or None,
            "explicitly_saved": str(row.get("explicitly_saved", "")).lower() == "true"}


def bootstrap(workflow: str, prefix: str, output: Path) -> int:
    previous = {}
    if output.exists():
        data = json.loads(output.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("opportunities"), list):
            raise ValueError(f"Invalid opportunity state: {output}")
        if data.get("watchlist_scope") == WATCHLIST_SCOPE:
            return len(data["opportunities"])
        previous = {o["noticeId"]: o for o in data["opportunities"]}
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    root = f"https://api.github.com/repos/{repo}/actions"
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    saved: dict[str, dict] = {key: value for key, value in previous.items() if value.get("explicitly_saved") is True}
    observed = set()
    report_artifacts = 0
    page = 1
    while True:
        url = (f"{root}/workflows/{quote(workflow, safe='')}/runs?branch=main"
               f"&status=success&per_page=100&page={page}")
        runs = api_json(url, token).get("workflow_runs") or []
        if not runs:
            break
        for run in runs:
            created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if created < cutoff:
                continue
            artifacts = api_json(f"{root}/runs/{run['id']}/artifacts?per_page=100", token).get("artifacts") or []
            for artifact in artifacts:
                if artifact.get("expired") or not artifact.get("name", "").startswith(prefix):
                    continue
                report_artifacts += 1
                for row in artifact_csv_rows(artifact["archive_download_url"], token):
                    if row.get("rank_group") in ("Top", "Shortlist") or str(row.get("explicitly_saved", "")).lower() == "true":
                        observed.add(row.get("notice_id"))
                    seed = open_seed(row, now)
                    if seed:
                        if seed["noticeId"] not in saved:
                            # Preserve richer cached facts, including unavailable refresh status.
                            saved[seed["noticeId"]] = previous.get(seed["noticeId"], seed)
        if len(runs) < 100 or datetime.fromisoformat(runs[-1]["created_at"].replace("Z", "+00:00")) < cutoff:
            break
        page += 1
    if previous and not report_artifacts:
        raise RuntimeError("Cannot migrate legacy state without retained report artifacts; original state preserved")
    if workflow == "run_catholic_southeast.yml" and not previous and not report_artifacts:
        # Leave first-run detection intact so NC still gets its initial backfill.
        return 0
    if previous:
        # Previously reported missing IDs remain review items even after a cached deadline.
        for key, value in previous.items():
            if key in observed or value.get("explicitly_saved") is True:
                saved[key] = value
        Path("watchlist_migration_archive.json").write_text(output.read_text(encoding="utf-8"), encoding="utf-8")
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps({"version": 1, "watchlist_scope": WATCHLIST_SCOPE,
                                    "opportunities": list(saved.values())}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output)
    print(f"Reported/explicit watchlist: {len(saved)} IDs (legacy pool: {len(previous)}); no SAM calls used")
    return len(saved)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: bootstrap_opportunity_state.py WORKFLOW RESULT_PREFIX STATE_FILE")
    bootstrap(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
