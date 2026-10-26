#!/usr/bin/env python3
"""Pull NBA schedule, scores and point spreads from ESPN's public scoreboard
feed and merge them into data/games.json.

Runs on a schedule in GitHub Actions. Safe to run repeatedly: it only adds
games in a rolling window, refreshes spreads for games that have not tipped
off, and records scores and status for games that have.
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "data" / "games.json"
CONFIG = ROOT / "data" / "config.json"
ET = ZoneInfo("America/New_York")
FEED = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}&limit=50"

# ESPN uses a few non-standard codes.
ABBR = {"NY": "NYK", "GS": "GSW", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}

DAYS_BACK = 2
DAYS_AHEAD = 7


def fetch(day: str) -> dict:
    req = urllib.request.Request(FEED.format(d=day), headers={"User-Agent": "meats-nba-calcutta/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def status_of(ev: dict) -> str:
    t = ev.get("status", {}).get("type", {})
    name = (t.get("name") or "").upper()
    if t.get("completed") or name == "STATUS_FINAL":
        return "final"
    if name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED"):
        return "postponed"
    if t.get("state") == "in":
        return "inprogress"
    return "scheduled"


def counts(ev: dict) -> bool:
    """Regular season, NBA Cup, play-in and playoffs. The picks board keeps only regular season and Cup; the
    sportsbook runs through the Finals. Preseason (type 1) and all-star events are left out."""
    st = (ev.get("season") or {}).get("type")
    if st in (2, 3, 5):
        return True
    comp = (ev.get("competitions") or [{}])[0]
    notes = " ".join((n.get("headline") or "") for n in comp.get("notes") or [])
    return "cup" in notes.lower()


ROUND_BY_TYPE = {"RD16": "r1", "QTR": "r2", "SEMI": "cf", "FINAL": "finals", "CC": "cupfinal"}


def stage_of(ev: dict) -> str:
    """regular | cup | cupfinal | playin | r1 | r2 | cf | finals, from ESPN's season type, competition type and notes."""
    st = (ev.get("season") or {}).get("type")
    comp = (ev.get("competitions") or [{}])[0]
    abbr = ((comp.get("type") or {}).get("abbreviation") or "").upper()
    notes = " ".join((n.get("headline") or "") for n in comp.get("notes") or []).lower()
    if abbr == "CC" or ("cup" in notes and "championship" in notes):
        return "cupfinal"
    if st == 5 or "play-in" in notes:
        return "playin"
    if st == 3:
        if abbr in ROUND_BY_TYPE:
            return ROUND_BY_TYPE[abbr]
        if "1st round" in notes or "first round" in notes:
            return "r1"
        if "semifinal" in notes:
            return "r2"
        if "nba finals" in notes:
            return "finals"
        if "finals" in notes:
            return "cf"
        return "r1"
    if "cup" in notes:
        return "cup"
    return "regular"


def label_of(ev: dict) -> str | None:
    comp = (ev.get("competitions") or [{}])[0]
    notes = " ".join((n.get("headline") or "") for n in comp.get("notes") or [])
    if "cup" in notes.lower():
        return "NBA Cup Final" if "final" in notes.lower() and "semifinal" not in notes.lower() and "quarterfinal" not in notes.lower() else "NBA Cup"
    return None


def main() -> int:
    games = json.loads(GAMES.read_text()) if GAMES.exists() else {}
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    bonus_dates = cfg.get("bonusDates", {})
    bonus_ids = cfg.get("bonusGameIds", {})
    season_start = cfg.get("seasonStart", "2026-10-01")
    season_end = cfg.get("playoffsEnd") or cfg.get("seasonEnd", "2027-06-30")  # the sportsbook runs through the Finals

    now = datetime.now(timezone.utc)
    today = now.astimezone(ET).date()
    changed = 0
    for off in range(-DAYS_BACK, DAYS_AHEAD + 1):
        day = today + timedelta(days=off)
        dstr = day.strftime("%Y%m%d")
        try:
            feed = fetch(dstr)
        except Exception as e:  # noqa: BLE001
            print(f"fetch failed for {dstr}: {e}", file=sys.stderr)
            continue
        for ev in feed.get("events", []):
            if not counts(ev):
                continue
            comp = (ev.get("competitions") or [{}])[0]
            comps = comp.get("competitors") or []
            home = next((c for c in comps if c.get("homeAway") == "home"), None)
            away = next((c for c in comps if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            start = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            date_et = start.astimezone(ET).strftime("%Y-%m-%d")
            if date_et < season_start or date_et > season_end:
                continue
            gid = str(ev["id"])
            g = games.get(gid, {})
            hcode = ABBR.get(home["team"]["abbreviation"], home["team"]["abbreviation"])
            acode = ABBR.get(away["team"]["abbreviation"], away["team"]["abbreviation"])
            st = status_of(ev)
            stage = stage_of(ev)
            new = dict(g)
            new.update({
                "id": gid,
                "stage": stage,
                "series": "-".join(sorted([hcode, acode])) if stage in ("r1", "r2", "cf", "finals") else None,
                "date": date_et,
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "home": hcode, "away": acode,
                "homeName": home["team"].get("displayName"),
                "awayName": away["team"].get("displayName"),
                "homeLogo": home["team"].get("logo"),
                "awayLogo": away["team"].get("logo"),
                "homeColor": home["team"].get("color"),
                "awayColor": away["team"].get("color"),
                "status": st,
            })
            # Spread: only while the game has not started. ESPN's "spread" is the home team's number.
            tipped = now >= start or st in ("inprogress", "final")
            odds = (comp.get("odds") or [None])[0]
            if not tipped and odds and odds.get("spread") is not None:
                sp = float(odds["spread"])
                if g.get("spreadHome") != sp:
                    new["spreadHome"] = sp
                    new["spreadSource"] = (odds.get("provider") or {}).get("displayName") or "ESPN"
                    new["spreadUpdated"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            new.setdefault("spreadHome", None)
            new.setdefault("spreadSource", None)
            new.setdefault("spreadUpdated", None)
            # Scores.
            if st in ("inprogress", "final"):
                try:
                    new["homeScore"] = int(home.get("score") or 0)
                    new["awayScore"] = int(away.get("score") or 0)
                except ValueError:
                    pass
            else:
                new.setdefault("homeScore", None)
                new.setdefault("awayScore", None)
            # Bonus games.
            label = label_of(ev)
            mult = 1
            if date_et in bonus_dates:
                mult = bonus_dates[date_et].get("multiplier", 2)
                label = bonus_dates[date_et].get("label", label)
            if gid in bonus_ids:
                mult = bonus_ids[gid].get("multiplier", 2)
                label = bonus_ids[gid].get("label", label)
            new["multiplier"] = mult
            new["label"] = label
            if new != g:
                games[gid] = new
                changed += 1

    out = {"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "games": dict(sorted(games.items(), key=lambda kv: kv[1]["start"]))}
    GAMES.write_text(json.dumps(out["games"], indent=1, sort_keys=True) + "\n")
    (ROOT / "data" / "status.json").write_text(json.dumps({"updated": out["updated"], "changed": changed}) + "\n")
    print(f"{len(games)} games on file, {changed} changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
