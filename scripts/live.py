#!/usr/bin/env python3
"""Live scores and player stat lines for the games in progress, for the progress bars on open bets.

Reads ESPN's scoreboard for today (New York) and, for every game in progress or just finished, its box score, and
writes data/live.json:

  {updated, games: {"<date>|<AWAY> at <HOME>": {espnId, status, period, clock, detail, home, away, homeScore,
                     awayScore, players: {"Name": {pts, reb, ast, threes, stl, blk, to, min}}}}}

The key matches how the page names a game, so odds-feed event ids are not needed. Only games that have tipped
are included; the file is small and is rewritten every few minutes while games are on.
"""
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "live.json"
ET = ZoneInfo("America/New_York")
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}&limit=50"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={id}"
ABBR = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX"}


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "meats-sportsbook/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def code(team: dict) -> str:
    a = (team.get("abbreviation") or "").upper()
    return ABBR.get(a, a)


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s.replace(" jr", "").replace(" sr", "").replace(" iii", "").replace(" ii", "")).strip()


def num(s):
    try:
        return int(str(s).split("-")[0].split(":")[0])
    except Exception:  # noqa: BLE001
        return 0


def players_of(summary: dict) -> dict:
    out = {}
    for side in (summary.get("boxscore") or {}).get("players") or []:
        for block in side.get("statistics") or []:
            keys = block.get("keys") or []
            idx = {k: i for i, k in enumerate(keys)}
            for ath in block.get("athletes") or []:
                a = ath.get("athlete") or {}
                st = ath.get("stats") or []
                if not st or ath.get("didNotPlay"):
                    continue
                def v(key, alt=None):
                    i = idx.get(key, idx.get(alt, -1) if alt else -1)
                    return st[i] if 0 <= i < len(st) else "0"
                threes = v("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "3PT")
                row = {"pts": num(v("points", "PTS")), "reb": num(v("totalRebounds", "REB")), "ast": num(v("assists", "AST")),
                       "threes": num(threes), "stl": num(v("steals", "STL")), "blk": num(v("blocks", "BLK")),
                       "to": num(v("turnovers", "TO")), "min": num(v("minutes", "MIN"))}
                out[a.get("displayName") or a.get("shortName") or ""] = row
    out.pop("", None)
    return out


def main():
    today = datetime.now(ET).strftime("%Y%m%d")
    board = get(SCOREBOARD.format(d=today))
    games = {}
    for ev in board.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        status = (comp.get("status") or {}).get("type") or {}
        state = status.get("state")  # pre, in, post
        if state == "pre":
            continue
        teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        home, away = teams.get("home") or {}, teams.get("away") or {}
        hc, ac = code(home.get("team") or {}), code(away.get("team") or {})
        date = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%d")
        entry = {"espnId": ev.get("id"), "status": "final" if state == "post" else "inprogress",
                 "period": (comp.get("status") or {}).get("period"), "clock": (comp.get("status") or {}).get("displayClock"),
                 "detail": status.get("shortDetail") or status.get("detail"), "home": hc, "away": ac,
                 "homeScore": int(home.get("score") or 0), "awayScore": int(away.get("score") or 0), "players": {}}
        try:
            entry["players"] = players_of(get(SUMMARY.format(id=ev["id"])))
        except Exception as e:  # noqa: BLE001
            print(f"box score for {ac} at {hc} failed: {e}", file=sys.stderr)
        games[f"{date}|{ac} at {hc}"] = entry
    OUT.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "games": games}, indent=1) + "\n")
    print(f"live: {len(games)} games, {sum(len(g['players']) for g in games.values())} player lines")


if __name__ == "__main__":
    main()
