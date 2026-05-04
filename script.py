import requests
import csv
from datetime import datetime

API_KEY = "YOUR_SAM_API_KEY"

url = "https://api.sam.gov/opportunities/v2/search"

params = {
    "api_key": API_KEY,
    "limit": 50,
    "postedFrom": "01/01/2026",
    "state": ["CO", "MN", "ND", "WI", "SD"]
}

response = requests.get(url, params=params)
data = response.json()

opps = data.get("opportunitiesData", [])

filtered = []

keywords = ["inspection", "inspector", "QA", "QC"]

for opp in opps:
    title = opp.get("title", "").lower()
    if any(k.lower() in title for k in keywords):
        filtered.append({
            "title": opp.get("title"),
            "agency": opp.get("department"),
            "date": opp.get("postedDate")
        })

# Save to CSV
filename = f"output_{datetime.now().date()}.csv"

with open(filename, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["title", "agency", "date"])
    writer.writeheader()
    writer.writerows(filtered)

print("Done. Saved:", filename)
