#!/usr/bin/env python3
"""One-off: confirm the rules accept a wager with a server-side createdAt and allow a prompt cancel."""
import json, os, sys, urllib.error, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup import firebase_config, sign_in  # noqa: E402
OUT = Path(__file__).resolve().parent.parent / "data" / "probe"

def main():
    cfg = firebase_config(); token = sign_in(cfg["apiKey"], os.environ["POOL_PASSWORD"])
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    db = f"projects/{cfg['projectId']}/databases/(default)"
    name = f"{db}/documents/wagers/rules-check-{uuid.uuid4().hex[:8]}"
    fields = {"player": {"stringValue": "Kev"}, "stake": {"integerValue": "1"}, "status": {"stringValue": "open"},
              "placedAt": {"stringValue": "2026-01-01T00:00:00Z"}, "eventID": {"stringValue": "rules-check"}, "game": {"stringValue": "rules check"},
              "gameDate": {"stringValue": "2026-01-01"}, "gameStart": {"stringValue": "2026-01-01T00:00:00Z"}, "stage": {"stringValue": "regular"},
              "boost": {"nullValue": None}, "legs": {"arrayValue": {"values": [{"mapValue": {"fields": {"oddID": {"stringValue": "x"}, "odds": {"integerValue": "-110"}, "short": {"stringValue": "test"}}}}]}},
              "net": {"nullValue": None}, "payout": {"nullValue": None}, "settledAt": {"nullValue": None}}
    lines = []
    try:
        body = {"writes": [{"update": {"name": name, "fields": fields}, "updateTransforms": [{"fieldPath": "createdAt", "setToServerValue": "REQUEST_TIME"}], "currentDocument": {"exists": False}}]}
        req = urllib.request.Request(f"https://firestore.googleapis.com/v1/{db}/documents:commit", data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r: r.read()
        lines.append("CREATE with server createdAt: OK")
        req = urllib.request.Request(f"https://firestore.googleapis.com/v1/{name}", headers=headers, method="DELETE")
        with urllib.request.urlopen(req, timeout=30) as r: r.read()
        lines.append("DELETE within 10 minutes: OK")
        # a create WITHOUT createdAt must now be refused
        try:
            req = urllib.request.Request(f"https://firestore.googleapis.com/v1/{db}/documents/wagers", data=json.dumps({"fields": fields}).encode(), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r: r.read()
            lines.append("CREATE without createdAt: ACCEPTED (rules not enforcing)")
        except urllib.error.HTTPError as e:
            lines.append(f"CREATE without createdAt: refused as expected (HTTP {e.code})")
    except urllib.error.HTTPError as e:
        lines.append(f"FAILED: HTTP {e.code} {e.read().decode()[:300]}")
    OUT.mkdir(parents=True, exist_ok=True); (OUT / "rules-check.txt").write_text("\n".join(lines) + "\n"); print("\n".join(lines))
    return 0

if __name__ == "__main__":
    sys.exit(main())
