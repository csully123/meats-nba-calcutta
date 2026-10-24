#!/usr/bin/env python3
"""Nightly backup of every pick from Firestore into data/backups/.

Signs in as the pool user (email + password from the environment), reads the
`picks` collection through the Firestore REST API, and writes two files:
data/backups/picks-latest.json and data/backups/picks-YYYY-MM-DD.json.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG_JS = ROOT / "firebase-config.js"
OUT = ROOT / "data" / "backups"
POOL_EMAIL = "pool@meats-calcutta-picks.firebaseapp.com"


def firebase_config() -> dict:
    text = CONFIG_JS.read_text()
    key = re.search(r'apiKey:\s*"([^"]+)"', text)
    pid = re.search(r'projectId:\s*"([^"]+)"', text)
    if not key or not pid:
        raise SystemExit("firebase-config.js is missing apiKey or projectId")
    return {"apiKey": key.group(1), "projectId": pid.group(1)}


def post_json(url: str, body: dict, headers: dict | None = None) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def sign_in(api_key: str, password: str) -> str:
    url = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + urllib.parse.quote(api_key)
    res = post_json(url, {"email": POOL_EMAIL, "password": password, "returnSecureToken": True})
    return res["idToken"]


def unwrap(v: dict):
    """Firestore REST value -> plain Python."""
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "booleanValue" in v:
        return v["booleanValue"]
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "mapValue" in v:
        return {k: unwrap(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in v:
        return [unwrap(x) for x in (v["arrayValue"].get("values") or [])]
    return v


def main() -> int:
    password = os.environ.get("POOL_PASSWORD", "")
    if not password:
        print("POOL_PASSWORD is not set; add it as a repository secret.", file=sys.stderr)
        return 1
    cfg = firebase_config()
    token = sign_in(cfg["apiKey"], password)
    headers = {"Authorization": "Bearer " + token}

    def dump(collection: str) -> dict:
        base = f"https://firestore.googleapis.com/v1/projects/{cfg['projectId']}/databases/(default)/documents/{collection}"
        out, page = {}, None
        while True:
            url = base + "?pageSize=1000" + (f"&pageToken={urllib.parse.quote(page)}" if page else "")
            res = get_json(url, headers)
            for doc in res.get("documents", []):
                doc_id = doc["name"].rsplit("/", 1)[-1]
                out[doc_id] = {k: unwrap(v) for k, v in (doc.get("fields") or {}).items()}
                out[doc_id]["_updated"] = doc.get("updateTime")
            page = res.get("nextPageToken")
            if not page:
                break
        return out

    picks = dump("picks")
    wagers = dump("wagers")
    now = datetime.now(timezone.utc)
    stamp = now.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    OUT.mkdir(parents=True, exist_ok=True)
    body = {"backedUpAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(picks), "picks": dict(sorted(picks.items()))}
    text = json.dumps(body, indent=1, sort_keys=True) + "\n"
    (OUT / "picks-latest.json").write_text(text)
    (OUT / f"picks-{stamp}.json").write_text(text)
    wbody = {"backedUpAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(wagers), "wagers": dict(sorted(wagers.items()))}
    wtext = json.dumps(wbody, indent=1, sort_keys=True) + "\n"
    (OUT / "wagers-latest.json").write_text(wtext)
    (OUT / f"wagers-{stamp}.json").write_text(wtext)
    print(f"backed up {len(picks)} picks and {len(wagers)} wagers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
