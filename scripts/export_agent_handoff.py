#!/usr/bin/env python3
import csv, glob, json, os
from datetime import datetime, timezone

files=sorted(glob.glob("sam_results_weston_wexmac_*.csv"))
if not files:
    raise SystemExit("No Weston/WEXMAC CSV result found")
src=files[-1]
rows=[]
with open(src,newline="",encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r.get("rank_group") in {"Top","Shortlist"}:
            rows.append(r)

handoff={
    "schema_version":"1.0",
    "generated_at":datetime.now(timezone.utc).isoformat(),
    "source_file":os.path.basename(src),
    "experiment":"open-strix-vs-hermes-21-day-pilot",
    "rules":{
        "same_candidate_pool":True,
        "python_score_is_baseline_not_ground_truth":True,
        "external_contact_allowed":False,
        "submission_allowed":False
    },
    "opportunities":rows
}
os.makedirs("agent_handoff",exist_ok=True)
date=os.path.basename(src).removeprefix("sam_results_weston_wexmac_").removesuffix(".csv")
out=f"agent_handoff/sam_agent_handoff_{date}.json"
with open(out,"w",encoding="utf-8") as f:
    json.dump(handoff,f,indent=2,ensure_ascii=False)
print(out)
