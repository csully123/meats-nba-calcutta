#!/usr/bin/env python3
"""Apply the weekly minimum: wager at least 20 points every week (Monday through Sunday, New York), or your whole
stack if you have less than 20; miss it and 20 points (or what is left of the stack) come off at the end of that week.

Runs every Monday morning after the nightly backup. For the week that just ended it replays each player's bankroll
from data/backups/wagers-latest.json plus the adjustments already on file, adds up what they wagered that week, and
appends a penalty to data/adjustments.json for anyone short. Idempotent: each penalty has the id min:<player>:<week>
and is never written twice. Players who have fouled out (six busts) are left alone. --week YYYY-MM-DD (a Monday)
checks that week instead of the last completed one; --dry-run prints without writing.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ADJ = ROOT / "data" / "adjustments.json"
ET = ZoneInfo("America/New_York")
START, RELOAD, MIN_WEEKLY, FOUL_OUT = 200.0, 100.0, 20.0, 6
FIRST_WEEK = "2026-10-26"  # the first full week of the book


def week_key(iso: str) -> str:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y-%m-%d")


def week_end_utc(week: str) -> datetime:
    """Sunday 11:59 PM New York of that week, as UTC."""
    mon = datetime.strptime(week, "%Y-%m-%d").replace(tzinfo=ET)
    return (mon + timedelta(days=6, hours=23, minutes=59)).astimezone(timezone.utc)


def replay(player: str, wagers: list, adjustments: list, until: datetime):
    """Stack, pending, busts and points wagered per week for one player as of `until` (same rules as the page)."""
    cutoff = until.strftime("%Y-%m-%dT%H:%M:%SZ")
    tl = []
    for w in wagers:
        if w.get("player") != player or not w.get("placedAt") or w["placedAt"] > cutoff:
            continue
        tl.append((w["placedAt"], 0, w))
        if w.get("status") not in (None, "open") and w.get("settledAt") and w["settledAt"] <= cutoff:
            tl.append((w["settledAt"], 1, w))
    for a in adjustments:
        if a.get("player") == player and a.get("at") and a["at"] <= cutoff:
            tl.append((a["at"], 2, a))
    tl.sort(key=lambda x: (x[0], x[1]))
    stack, pending, busts, by_week = START, 0.0, 0, {}
    for t, kind, x in tl:
        if kind == 2:
            stack += float(x.get("points") or 0)
        elif kind == 0:
            s = float(x.get("stake") or 0)
            stack -= s
            pending += s
            wk = week_key(x["placedAt"])
            by_week[wk] = by_week.get(wk, 0.0) + s
        else:
            s = float(x.get("stake") or 0)
            pending -= s
            st = x.get("status")
            if st == "win":
                stack += s + float(x.get("net") or 0)
            elif st in ("push", "void"):
                stack += s
        if stack <= 0.005 and pending <= 0.005:
            busts += 1
            stack = RELOAD
    return round(stack, 2), round(pending, 2), busts, by_week


def main(argv):
    dry = "--dry-run" in argv
    if "--week" in argv:
        week = argv[argv.index("--week") + 1]
    else:
        now_et = datetime.now(ET)
        this_monday = (now_et - timedelta(days=now_et.weekday())).strftime("%Y-%m-%d")
        week = (datetime.strptime(this_monday, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    if week < FIRST_WEEK:
        print(f"week of {week} is before the book started; nothing to do")
        return 0
    end = week_end_utc(week)
    if end > datetime.now(timezone.utc):
        print(f"week of {week} has not ended yet")
        return 0
    data = json.loads(ADJ.read_text()) if ADJ.exists() else {"adjustments": []}
    adjustments = data.setdefault("adjustments", [])
    have = {a.get("id") for a in adjustments}
    cfg = json.loads((ROOT / "data" / "config.json").read_text())
    wagers = list(json.loads((ROOT / "data" / "backups" / "wagers-latest.json").read_text()).get("wagers", {}).values())
    added = 0
    for player in cfg["players"]:
        pid = f"min:{player}:{week}"
        stack, pending, busts, by_week = replay(player, wagers, adjustments, end)
        wagered = round(by_week.get(week, 0.0), 2)
        if busts >= FOUL_OUT:
            print(f"{player}: fouled out, no minimum")
            continue
        required = min(MIN_WEEKLY, round(stack + pending + wagered, 2))
        if wagered + 0.005 >= required:
            print(f"{player}: wagered {wagered} of {required} in the week of {week}, fine")
            continue
        if pid in have:
            print(f"{player}: short ({wagered} of {required}) but already penalized")
            continue
        penalty = round(min(MIN_WEEKLY, max(0.0, stack)), 2)
        if penalty <= 0:
            print(f"{player}: short but nothing left to take")
            continue
        label = datetime.strptime(week, "%Y-%m-%d").strftime("%b %-d")
        adjustments.append({"id": pid, "player": player, "points": -penalty, "at": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "note": f"Missed the 20-point weekly minimum, week of {label} (wagered {wagered:g})"})
        added += 1
        print(f"{player}: wagered {wagered} of {required} in the week of {week}, penalty {penalty}")
    if added and not dry:
        adjustments.sort(key=lambda a: a.get("at", ""))
        ADJ.write_text(json.dumps(data, indent=2) + "\n")
    print(f"{added} penalt{'y' if added == 1 else 'ies'} {'would be ' if dry else ''}added for the week of {week}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
