#!/usr/bin/env python3
"""Commissioner tool: put voided wagers for one game date back to open so the grader can settle them properly.
Run through the "Reopen voided bets" workflow with the date (YYYY-MM-DD)."""
import json, os, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup import firebase_config, sign_in  # noqa: E402

def main():
    date = sys.argv[1]
    cfg = firebase_config(); token = sign_in(cfg["apiKey"], os.environ["POOL_PASSWORD"])
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    base = f"https://firestore.googleapis.com/v1/projects/{cfg['projectId']}/databases/(default)/documents"
    body = {"structuredQuery": {"from": [{"collectionId": "wagers"}], "where": {"compositeFilter": {"op": "AND", "filters": [
        {"fieldFilter": {"field": {"fieldPath": "status"}, "op": "EQUAL", "value": {"stringValue": "void"}}},
        {"fieldFilter": {"field": {"fieldPath": "gameDate"}, "op": "EQUAL", "value": {"stringValue": date}}}]}}, "limit": 500}}
    req = urllib.request.Request(base + ":runQuery", data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)
    n = 0
    for row in rows:
        doc = row.get("document")
        if not doc:
            continue
        patch = {"fields": {"status": {"stringValue": "open"}, "net": {"nullValue": None}, "payout": {"nullValue": None},
                            "legResults": {"nullValue": None}, "settledAt": {"nullValue": None}}}
        mask = "&".join("updateMask.fieldPaths=" + k for k in patch["fields"])
        req = urllib.request.Request(f"https://firestore.googleapis.com/v1/{doc['name']}?{mask}", data=json.dumps(patch).encode(), headers=headers, method="PATCH")
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        n += 1
        print("reopened", doc["name"].rsplit("/", 1)[-1])
    print(f"reopened {n} voided wagers for {date}")

if __name__ == "__main__":
    main()
