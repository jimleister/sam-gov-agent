#!/usr/bin/env python3
"""Replay all five migrations against main-branch artifacts without SAM or email."""
import io
import json
import os
from pathlib import Path
from urllib.parse import urlencode
import zipfile

import requests
from bootstrap_opportunity_state import api_json, bootstrap

REPORTS = (
    ("run.yml", "sam-results-", "logistics-opportunity-state", "logistics_opportunity_state.json"),
    ("run_pest.yml", "sam-results-pest-", "pest-opportunity-state", "pest_opportunity_state.json"),
    ("run_usace_asia.yml", "sam-results-usace-asia-", "usace-asia-opportunity-state", "usace_asia_opportunity_state.json"),
    ("run_inspection_oilgas.yml", "sam-results-inspection-oilgas-", "inspection-oilgas-opportunity-state", "inspection_oilgas_opportunity_state.json"),
    ("run_catholic_southeast.yml", "sam-results-catholic-southeast-", "catholic-opportunity-state", "catholic_opportunity_state.json"),
)


def main():
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    root = Path("migration-preview").resolve()
    root.mkdir(exist_ok=True)
    summary = []
    for workflow, prefix, artifact_name, state_file in REPORTS:
        folder = root / artifact_name
        folder.mkdir(exist_ok=True)
        url = f"https://api.github.com/repos/{repo}/actions/artifacts?" + urlencode({"name": artifact_name, "per_page": 10})
        artifacts = api_json(url, token).get("artifacts") or []
        usable = [a for a in artifacts if not a["expired"] and a["workflow_run"]["head_branch"] == "main"]
        if not usable:
            raise RuntimeError(f"No retained main state for {artifact_name}")
        latest = max(usable, key=lambda a: a["created_at"])
        response = requests.get(latest["archive_download_url"],
                                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                                timeout=120)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            (folder / state_file).write_bytes(archive.read(state_file))
        before = json.loads((folder / state_file).read_text())
        cwd = Path.cwd()
        try:
            os.chdir(folder)
            after = bootstrap(workflow, prefix, Path(state_file))
        finally:
            os.chdir(cwd)
        result = {"workflow": workflow, "before": len(before["opportunities"]), "after": after,
                  "sam_api_calls": 0, "emails_sent": 0}
        summary.append(result)
        print(json.dumps(result))
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
