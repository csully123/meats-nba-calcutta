#!/usr/bin/env python3
"""Pull NBA odds from SportsGameOdds into data/odds/<YYYY-MM-DD>.json (one file per
New York game date) and data/odds/index.json. Also stores finished games' box score
results so wagers can be graded from the same feed.

Modes (first argument):
  morning   every game today and tomorrow (ET)
  midday    every game today
  pretip    games starting in the next 100 minutes
  results   games that ended in the last 36 hours and are not yet stored as final
Each game costs one object on the free plan, regardless of market count.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "odds"
ET = ZoneInfo("America/New_York")
BASE = "https://api.sportsgameodds.com/v2"
OFFICIAL_BOOK = "fanduel"
FALLBACK_BOOKS = ["draftkings", "betmgm", "caesars", "espnbet", "pointsbet", "unibet", "williamhill", "bovada"]
TEAM_ABBR = {"NY": "NYK", "GS": "GSW", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}

# Markets the book offers. (statID, periodID, betTypeID) -> label. Everything else is ignored.
MARKETS = {
    ("points", "game", "ml"): "Moneyline",
    ("points", "game", "sp"): "Spread",
    ("points", "game", "ou"): "Total",
    ("points", "1h", "ml"): "1st half moneyline",
    ("points", "1h", "sp"): "1st half spread",
    ("points", "1h", "ou"): "1st half total",
}
PLAYER_STATS = {
    "points": "Points", "rebounds": "Rebounds", "assists": "Assists", "threePointersMade": "3-pointers made",
    "points+rebounds+assists": "Pts + Reb + Ast", "points+rebounds": "Pts + Reb", "points+assists": "Pts + Ast",
    "rebounds+assists": "Reb + Ast", "steals": "Steals", "blocks": "Blocks", "turnovers": "Turnovers",
    "blocks+steals": "Blk + Stl", "doubleDouble": "Double-double", "tripleDouble": "Triple-double", "firstBasket": "First basket",
}


def fetch(params: dict) -> list:
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        raise SystemExit("ODDS_API_KEY is not set")
    out, cursor = [], None
    while True:
        q = dict(params)
        q["limit"] = "50"
        q["includeAltLines"] = "true"
        if cursor:
            q["cursor"] = cursor
        req = urllib.request.Request(BASE + "/events/?" + urllib.parse.urlencode(q),
                                     headers={"x-api-key": key, "User-Agent": "meats-nba-calcutta/1.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.load(r)
        out.extend(d.get("data") or [])
        cursor = d.get("nextCursor")
        if not cursor:
            break
    return out


SANE_MIN, SANE_MAX = -2000, 2000  # anything wilder than this is a stale or placeholder price, not a bettable market


def _price(e: dict):
    try:
        p = int(str(e["odds"]).replace("+", ""))
    except (KeyError, ValueError, TypeError):
        return None
    return p if SANE_MIN <= p <= SANE_MAX else None


def _line(e: dict):
    line = e.get("spread") if e.get("spread") is not None else e.get("overUnder")
    return float(line) if line is not None else None


def pick_price(odd: dict):
    """FanDuel's current number if it is there and available, else the first fallback book that is.
    Returns (book, odds, line, alts) where alts is the book's ladder of alternate lines [[line, odds], ...] sorted by line."""
    bb = odd.get("byBookmaker") or {}
    for book in [OFFICIAL_BOOK] + FALLBACK_BOOKS:
        e = bb.get(book)
        if not e or e.get("odds") is None or e.get("available") is False:
            continue
        price = _price(e)
        if price is None:
            continue
        alts = []
        for a in e.get("altLines") or []:
            if a.get("available") is False:
                continue
            ap, al = _price(a), _line(a)
            if ap is not None and al is not None:
                alts.append([al, ap])
        alts.sort()
        return book, price, _line(e), alts
    return None, None, None, []


def shape(ev: dict, players: dict) -> dict:
    st = ev.get("status") or {}
    teams = ev.get("teams") or {}
    home, away = teams.get("home") or {}, teams.get("away") or {}
    hs = (home.get("names") or {}).get("short", "")
    as_ = (away.get("names") or {}).get("short", "")
    start = st.get("startsAt")
    date_et = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%d") if start else None
    markets = []
    for oid, o in (ev.get("odds") or {}).items():
        stat, period, bt, side = o.get("statID"), o.get("periodID"), o.get("betTypeID"), o.get("sideID")
        ent = o.get("statEntityID")
        pid = o.get("playerID")
        if pid:
            if period != "game" or stat not in PLAYER_STATS:
                continue
            p = players.get(pid) or {}
            label = p.get("name") or pid
            team = p.get("teamID")
            team_short = hs if team == home.get("teamID") else as_ if team == away.get("teamID") else ""
            kind = "prop"
            name = f"{label} {PLAYER_STATS[stat]}"
        else:
            if (stat, period, bt) not in MARKETS:
                continue
            kind = "game"
            name = MARKETS[(stat, period, bt)]
            team_short = hs if ent == "home" else as_ if ent == "away" else ""
        book, price, line, alts = pick_price(o)
        if price is None:
            continue
        m = {
            "oddID": oid, "opposing": o.get("opposingOddID"), "kind": kind, "name": name, "stat": stat, "period": period,
            "betType": bt, "side": side, "entity": ent, "team": team_short, "player": pid, "line": line, "odds": price, "book": book,
            "available": bool(o.get("bookOddsAvailable", True)) and not bool(o.get("started")),
        }
        if alts and bt in ("sp", "ou"):
            m["alts"] = alts
        markets.append(m)
    return {
        "eventID": ev.get("eventID"), "date": date_et, "start": start,
        "home": TEAM_ABBR.get(hs, hs), "away": TEAM_ABBR.get(as_, as_),
        "homeName": (home.get("names") or {}).get("long"), "awayName": (away.get("names") or {}).get("long"),
        "homeColor": (home.get("colors") or {}).get("primary"), "awayColor": (away.get("colors") or {}).get("primary"),
        "started": bool(st.get("started")), "ended": bool(st.get("ended")), "finalized": bool(st.get("finalized")),
        "cancelled": bool(st.get("cancelled")), "display": st.get("displayShort"),
        "markets": markets, "pulledAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def results_of(ev: dict) -> dict | None:
    r = ev.get("results") or {}
    if not r.get("game"):
        return None
    game = r["game"]
    out = {"home": game.get("home"), "away": game.get("away"), "players": {k: v for k, v in game.items() if k not in ("home", "away")}}
    if r.get("1h"):
        out["1h"] = r["1h"]
    elif r.get("1q") and r.get("2q"):
        def add(a, b):
            return {k: (a.get(k, 0) or 0) + (b.get(k, 0) or 0) for k in set(a) | set(b) if isinstance(a.get(k, 0), (int, float)) and isinstance(b.get(k, 0), (int, float))}
        out["1h"] = {"home": add(r["1q"].get("home", {}), r["2q"].get("home", {})), "away": add(r["1q"].get("away", {}), r["2q"].get("away", {}))}
    return out


def load_day(date: str) -> dict:
    p = OUT / f"{date}.json"
    return json.loads(p.read_text()) if p.exists() else {"date": date, "games": {}}


def save_day(date: str, d: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{date}.json").write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    now = datetime.now(timezone.utc)
    today = now.astimezone(ET).date()
    if mode == "morning":
        params = {"startsAfter": datetime.combine(today, datetime.min.time(), ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "startsBefore": datetime.combine(today + timedelta(days=2), datetime.min.time(), ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    elif mode == "midday":
        params = {"startsAfter": datetime.combine(today, datetime.min.time(), ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "startsBefore": datetime.combine(today + timedelta(days=1), datetime.min.time(), ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    elif mode == "pretip":
        params = {"startsAfter": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "startsBefore": (now + timedelta(minutes=100)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    elif mode == "results":
        params = {"startsAfter": (now - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ"), "startsBefore": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "ended": "true"}
    else:
        raise SystemExit("mode must be morning, midday, pretip or results")
    params["leagueID"] = "NBA"
    if mode == "results":
        # Skip games we already hold as finalized, to save objects.
        pass
    events = fetch(params)
    pulled = 0
    touched = {}
    for ev in events:
        if (ev.get("type") or "match") != "match":
            continue
        players = ev.get("players") or {}
        g = shape(ev, players)
        if not g["date"]:
            continue
        day = touched.get(g["date"]) or load_day(g["date"])
        prev = day["games"].get(g["eventID"], {})
        if mode == "results":
            if prev.get("finalized"):
                continue
            res = results_of(ev)
            g["markets"] = prev.get("markets", [])  # keep the last pre-game prices on file
            if res:
                g["results"] = res
        else:
            if prev.get("results"):
                g["results"] = prev["results"]
            # Every (line, odds) pair ever offered on each market, main or alt, so the grader can verify a stored price.
            seen_prev = {m.get("oddID"): m.get("seen") or [] for m in prev.get("markets", [])}
            since_prev = {m.get("oddID"): m.get("seenSince") for m in prev.get("markets", [])}
            for m in g["markets"]:
                m["seenSince"] = since_prev.get(m["oddID"]) or g["pulledAt"]  # price history is only complete from here on
                seen = {tuple(x) for x in seen_prev.get(m["oddID"], [])}
                seen.add((m.get("line"), m.get("odds")))
                for al, ap in m.get("alts") or []:
                    seen.add((al, ap))
                m["seen"] = sorted([list(x) for x in seen], key=lambda x: (x[0] is None, x[0] if x[0] is not None else 0, x[1]))
        day["games"][g["eventID"]] = g
        touched[g["date"]] = day
        pulled += 1
    for date, day in touched.items():
        save_day(date, day)
    # index of dates on file
    OUT.mkdir(parents=True, exist_ok=True)
    dates = sorted(p.stem for p in OUT.glob("????-??-??.json"))
    (OUT / "index.json").write_text(json.dumps({"dates": dates, "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": mode, "pulled": pulled}) + "\n")
    print(f"{mode}: {pulled} games pulled, {len(touched)} day files touched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
