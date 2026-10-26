#!/usr/bin/env python3
"""One-off check that the Firestore rules accept a wager with boost/stage/series fields and allow
cancelling it while open. Creates a 1-point test wager for a fake game and deletes it straight away."""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup import firebase_config, sign_in  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "probe"


def main() -> int:
    cfg = firebase_config()
    token = sign_in(cfg["apiKey"], os.environ["POOL_PASSWORD"])
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    base = f"https://firestore.googleapis.com/v1/projects/{cfg['projectId']}/databases/(default)/documents/wagers"
    doc = {"fields": {
        "player": {"stringValue": "Kev"}, "stake": {"integerValue": "1"}, "status": {"stringValue": "open"},
        "placedAt": {"stringValue": "2026-01-01T00:00:00Z"}, "eventID": {"stringValue": "rules-check"},
        "game": {"stringValue": "rules check"}, "gameDate": {"stringValue": "2026-01-01"}, "gameStart": {"stringValue": "2026-01-01T00:00:00Z"},
        "stage": {"stringValue": "regular"}, "series": {"nullValue": None},
        "boost": {"mapValue": {"fields": {"id": {"stringValue": "week:2026-01-01"}, "mult": {"doubleValue": 1.5}, "label": {"stringValue": "1.5x weekly"}}}},
        "legs": {"arrayValue": {"values": [{"mapValue": {"fields": {"oddID": {"stringValue": "x"}, "odds": {"integerValue": "-110"}, "short": {"stringValue": "test"}}}}]}},
        "net": {"nullValue": None}, "payout": {"nullValue": None}, "settledAt": {"nullValue": None},
    }}
    lines = []
    try:
        req = urllib.request.Request(base, data=json.dumps(doc).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            created = json.load(r)
        name = created["name"]
        lines.append("CREATE with boost fields: OK")
        req = urllib.request.Request(f"https://firestore.googleapis.com/v1/{name}", headers=headers, method="DELETE")
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        lines.append("DELETE while open: OK")
    except urllib.error.HTTPError as e:
        lines.append(f"FAILED: HTTP {e.code} {e.read().decode()[:300]}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rules-check.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
