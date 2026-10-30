#!/usr/bin/env python3
"""Running history of each player's chance to win, for the trend chart under the leaderboard.

data/win-odds-history.json: {"players": [...], "points": [{"t": ISO UTC, "odds": {name: percent}}, ...]}

Default run (nightly, after the backup and the overnight grading): simulate from data/backups/wagers-latest.json
and append one point stamped now. --backfill rebuilds the file from every dated backup in data/backups, one point
per day stamped at that backup's time, so the chart starts at opening night. --asof YYYY-MM-DD adds a single point
for that day's backup. Points are kept in time order and a new point within 20 minutes of the last one replaces it.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from win_odds import PLAYERS, simulate  # noqa: E402

OUT = ROOT / "data" / "win-odds-history.json"
BACKUPS = ROOT / "data" / "backups"


def load():
    if OUT.exists():
        try:
            return json.loads(OUT.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"players": PLAYERS, "points": []}


def point_from(path: Path, stamp: datetime):
    data = json.loads(path.read_text())
    wagers = list((data.get("wagers") or {}).values())
    out = simulate(wagers, stamp.date())
    return {"t": stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "odds": out["odds"],
            "stacks": {p: out["now"][p]["stack"] for p in PLAYERS}}


def add(hist, pt):
    pts = [p for p in hist["points"] if abs((datetime.fromisoformat(p["t"].replace("Z", "+00:00")) - datetime.fromisoformat(pt["t"].replace("Z", "+00:00"))).total_seconds()) > 1200]
    pts.append(pt)
    pts.sort(key=lambda p: p["t"])
    hist["points"] = pts


def backup_stamp(path: Path):
    try:
        s = json.loads(path.read_text()).get("backedUpAt")
        if s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        pass
    d = path.stem.split("-", 1)[1]
    return datetime.fromisoformat(d + "T08:10:00+00:00")


def main(argv):
    hist = load()
    if "--backfill" in argv:
        hist["points"] = []
        for f in sorted(BACKUPS.glob("wagers-????-??-??.json")):
            add(hist, point_from(f, backup_stamp(f)))
            print(f"{f.name}: {hist['points'][-1]['odds']}")
    elif "--asof" in argv:
        d = argv[argv.index("--asof") + 1]
        f = BACKUPS / f"wagers-{d}.json"
        add(hist, point_from(f, backup_stamp(f)))
    else:
        add(hist, point_from(BACKUPS / "wagers-latest.json", datetime.now(timezone.utc)))
    hist["players"] = PLAYERS
    hist["updated"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    OUT.write_text(json.dumps(hist, indent=1) + "\n")
    print(f"{len(hist['points'])} points, latest {hist['points'][-1]['t']} {hist['points'][-1]['odds']}")


if __name__ == "__main__":
    main(sys.argv[1:])
