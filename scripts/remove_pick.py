#!/usr/bin/env python3
"""Commissioner tool: delete one pick from Firestore by its document id
(for example Kev_401909848). Used by the "Remove a pick" GitHub Action.
"""
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup import firebase_config, sign_in  # noqa: E402


def main() -> int:
    pick_id = os.environ.get("PICK_ID", "").strip()
    password = os.environ.get("POOL_PASSWORD", "")
    if not pick_id or not password:
        print("PICK_ID and POOL_PASSWORD are required", file=sys.stderr)
        return 1
    cfg = firebase_config()
    token = sign_in(cfg["apiKey"], password)
    url = (f"https://firestore.googleapis.com/v1/projects/{cfg['projectId']}/databases/(default)/documents/picks/"
           + urllib.parse.quote(pick_id))
    headers = {"Authorization": "Bearer " + token}
    # Show what is about to go, then delete it.
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            print("removing:", r.read().decode()[:600])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"no pick with id {pick_id}; nothing to do")
            return 0
        raise
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    print(f"removed {pick_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
