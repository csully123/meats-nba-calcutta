#!/usr/bin/env python3
"""Situational context for every game on the board: rest, travel, schedule density, altitude, look-ahead.

Reads data/games.json (the running season schedule with results) and writes data/schedule-context.json:

  {updated, days: {date: {eventID: {away: {...}, home: {...}, notes: [...]}}}}

For each team in each game today and tomorrow (ET): days of rest, back-to-back (with the estimated local landing
time when the team flew in overnight), three games in four nights, four in six, games in the last seven days,
road-trip or homestand length and position, time-zone change since the last game, altitude, the last game's
result and whether it went to overtime, and the next game. notes is a short human-readable list of the things that
matter for betting, with the rest edge spelled out. The flight math is an estimate: final buzzer about 2h25m after
tip, wheels up about two hours later, cruise around 480 mph plus 55 minutes of taxi, climb and descent. Real
flights run later than that often enough (weather, mechanical holds) that the morning task should check the news.
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "data" / "games.json"
OUT = ROOT / "data" / "schedule-context.json"
ET = ZoneInfo("America/New_York")

# arena latitude, longitude, time zone, altitude in feet
ARENAS = {
    "ATL": (33.757, -84.396, "America/New_York", 1050), "BOS": (42.366, -71.062, "America/New_York", 20),
    "BKN": (40.683, -73.975, "America/New_York", 30), "CHA": (35.225, -80.839, "America/New_York", 750),
    "CHI": (41.881, -87.674, "America/Chicago", 600), "CLE": (41.496, -81.688, "America/New_York", 650),
    "DAL": (32.790, -96.810, "America/Chicago", 430), "DEN": (39.749, -105.008, "America/Denver", 5280),
    "DET": (42.341, -83.055, "America/Detroit", 600), "GSW": (37.768, -122.388, "America/Los_Angeles", 10),
    "HOU": (29.751, -95.362, "America/Chicago", 50), "IND": (39.764, -86.156, "America/Indiana/Indianapolis", 715),
    "LAC": (33.945, -118.342, "America/Los_Angeles", 70), "LAL": (34.043, -118.267, "America/Los_Angeles", 270),
    "MEM": (35.138, -90.051, "America/Chicago", 260), "MIA": (25.781, -80.187, "America/New_York", 10),
    "MIL": (43.045, -87.917, "America/Chicago", 620), "MIN": (44.979, -93.276, "America/Chicago", 830),
    "NOP": (29.949, -90.082, "America/Chicago", 5), "NYK": (40.751, -73.994, "America/New_York", 30),
    "OKC": (35.463, -97.515, "America/Chicago", 1200), "ORL": (28.539, -81.384, "America/New_York", 100),
    "PHI": (39.901, -75.172, "America/New_York", 20), "PHX": (33.446, -112.071, "America/Phoenix", 1090),
    "POR": (45.532, -122.667, "America/Los_Angeles", 50), "SAC": (38.580, -121.500, "America/Los_Angeles", 30),
    "SAS": (29.427, -98.438, "America/Chicago", 650), "TOR": (43.643, -79.379, "America/Toronto", 250),
    "UTA": (40.768, -111.901, "America/Denver", 4226), "WAS": (38.898, -77.021, "America/New_York", 30),
}
CITY = {"ATL": "Atlanta", "BOS": "Boston", "BKN": "Brooklyn", "CHA": "Charlotte", "CHI": "Chicago", "CLE": "Cleveland",
        "DAL": "Dallas", "DEN": "Denver", "DET": "Detroit", "GSW": "San Francisco", "HOU": "Houston", "IND": "Indianapolis",
        "LAC": "Los Angeles", "LAL": "Los Angeles", "MEM": "Memphis", "MIA": "Miami", "MIL": "Milwaukee", "MIN": "Minneapolis",
        "NOP": "New Orleans", "NYK": "New York", "OKC": "Oklahoma City", "ORL": "Orlando", "PHI": "Philadelphia", "PHX": "Phoenix",
        "POR": "Portland", "SAC": "Sacramento", "SAS": "San Antonio", "TOR": "Toronto", "UTA": "Salt Lake City", "WAS": "Washington"}


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (ARENAS[a][0], ARENAS[a][1], ARENAS[b][0], ARENAS[b][1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))


def utc(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def clock(dt, tz):
    return dt.astimezone(ZoneInfo(tz)).strftime("%-I:%M %p").lower()


def tz_offset_hours(tz, when):
    return ZoneInfo(tz).utcoffset(when).total_seconds() / 3600


def overtime(game):
    """True when the stored box score shows more than 48 team minutes."""
    res = game.get("_results") or {}
    secs = sum(float((p or {}).get("secondsPlayed", 0) or 0) for p in (res.get("players") or {}).values())
    return secs > 2 * 5 * 48 * 60 + 60 if secs else None


def team_schedule(games, code):
    return sorted((g for g in games if code in (g["home"], g["away"])), key=lambda g: g["start"])


def context(games, g, code, idx_by_id):
    sched = team_schedule(games, code)
    i = next(k for k, x in enumerate(sched) if x["id"] == g["id"])
    date = datetime.fromisoformat(g["date"]).date()
    site = g["home"]  # the arena the game is played in
    is_home = g["home"] == code
    out = {"team": code, "site": "home" if is_home else "away", "tipLocal": clock(utc(g["start"]), ARENAS[site][2]),
           "altitude": ARENAS[site][3] if ARENAS[site][3] >= 4000 and not is_home else None}
    notes = []
    prev = sched[i - 1] if i > 0 else None
    nxt = sched[i + 1] if i + 1 < len(sched) else None

    # density over the trailing window, counting only games already in the file
    played_dates = [datetime.fromisoformat(x["date"]).date() for x in sched[: i + 1]]
    in_last = lambda n: sum(1 for d in played_dates if 0 <= (date - d).days < n)  # noqa: E731
    out["gamesIn4Nights"], out["gamesIn6Nights"], out["gamesIn7Nights"] = in_last(4), in_last(6), in_last(7)

    if prev:
        pdate = datetime.fromisoformat(prev["date"]).date()
        rest = (date - pdate).days - 1
        out["restDays"] = rest
        psite = prev["home"]
        pres = None
        if prev.get("homeScore") is not None and prev.get("awayScore") is not None:
            own = prev["homeScore"] if prev["home"] == code else prev["awayScore"]
            opp = prev["awayScore"] if prev["home"] == code else prev["homeScore"]
            ot = overtime(prev)
            pres = {"opp": prev["away"] if prev["home"] == code else prev["home"], "where": "home" if prev["home"] == code else "away",
                    "result": ("W" if own > opp else "L") + f" {own}-{opp}", "margin": own - opp, "overtime": ot}
            out["lastGame"] = pres
        out["lastGameDate"] = prev["date"]
        if rest == 0:
            out["backToBack"] = True
            if psite != site and CITY[psite] != CITY[site]:
                dist = miles(psite, site)
                end = utc(prev["start"]) + timedelta(hours=2, minutes=25) + (timedelta(minutes=15) if (pres or {}).get("overtime") else timedelta())
                wheels = end + timedelta(minutes=120)
                land = wheels + timedelta(minutes=55 + dist / 480 * 60)
                hotel = land + timedelta(minutes=45)
                shift = tz_offset_hours(ARENAS[site][2], land) - tz_offset_hours(ARENAS[psite][2], land)
                out["travel"] = {"from": CITY[psite], "to": CITY[site], "miles": round(dist), "estLanding": clock(land, ARENAS[site][2]),
                                 "estHotel": clock(hotel, ARENAS[site][2]), "tzShift": shift}
                late = land.astimezone(ZoneInfo(ARENAS[site][2]))
                hour = late.hour + late.minute / 60
                badness = " (brutal)" if 3 <= hour < 7 else " (late)" if 1.5 <= hour < 3 else ""
                notes.append(f"{code} on a back-to-back: played {'at home' if psite == code else 'in ' + CITY[psite]} last night, "
                             f"flew {round(dist)} miles and landed in {CITY[site]} around {clock(land, ARENAS[site][2])}{badness}"
                             + (f", {abs(shift):.0f} time zone{'s' if abs(shift) != 1 else ''} {'east' if shift > 0 else 'west'}" if shift else "")
                             + "; estimate, check the news for delays")
            else:
                notes.append(f"{code} on a back-to-back with no travel (played {'at home' if psite == code else 'in ' + CITY[psite]} last night)")
        elif rest >= 3:
            notes.append(f"{code} well rested: {rest} days off")
        if pres and pres.get("overtime"):
            notes.append(f"{code} went to overtime last game")
        if pres and rest == 0 and abs(pres["margin"]) >= 20:
            notes.append(f"{code} starters got a light night in a {abs(pres['margin'])}-point {'win' if pres['margin'] > 0 else 'loss'} yesterday")
        if psite != site:
            shift = tz_offset_hours(ARENAS[site][2], utc(g["start"])) - tz_offset_hours(ARENAS[psite][2], utc(g["start"]))
            out["tzShiftSinceLast"] = shift
            if abs(shift) >= 2 and rest <= 1:
                notes.append(f"{code} crossed {abs(shift):.0f} time zones {'eastward' if shift > 0 else 'westward'} since its last game")
    else:
        out["restDays"] = None

    if out["gamesIn4Nights"] >= 3:
        notes.append(f"{code} playing its 3rd game in 4 nights")
    if out["gamesIn6Nights"] >= 4:
        notes.append(f"{code} playing its 4th game in 6 nights")

    # road trip / homestand position
    run = 0
    for x in reversed(sched[: i + 1]):
        if (x["home"] == code) == is_home:
            run += 1
        else:
            break
    ahead = 0
    for x in sched[i + 1:]:
        if (x["home"] == code) == is_home:
            ahead += 1
        else:
            break
    out["streak"] = {"kind": "homestand" if is_home else "roadTrip", "game": run, "of": run + ahead}
    if not is_home and run + ahead >= 3:
        pos = "last game" if ahead == 0 else f"game {run}"
        notes.append(f"{code} {pos} of a {run + ahead}-game road trip")
    if is_home and run == 1 and prev and prev["home"] != code:
        trip = 0
        for x in reversed(sched[:i]):
            if x["home"] != code:
                trip += 1
            else:
                break
        if trip >= 3:
            notes.append(f"{code} first game home after a {trip}-game road trip")
    if out["altitude"]:
        notes.append(f"{code} playing at altitude in {CITY[site]} ({out['altitude']} ft)")

    if nxt:
        ndate = datetime.fromisoformat(nxt["date"]).date()
        out["nextGame"] = {"date": nxt["date"], "opp": nxt["away"] if nxt["home"] == code else nxt["home"],
                           "where": "home" if nxt["home"] == code else "away", "daysUntil": (ndate - date).days}
        if (ndate - date).days == 1:
            notes.append(f"{code} first leg of a back-to-back (plays {'at home' if nxt['home'] == code else 'in ' + CITY[nxt['home']]} tomorrow)")
    out["notes"] = notes
    return out


def load_results(games):
    """Attach stored box scores for overtime detection."""
    by_key = {(g["date"], g["home"], g["away"]): g for g in games.values() if g.get("date")}
    for f in (ROOT / "data" / "odds").glob("????-??-??.json"):
        for g in (json.loads(f.read_text()).get("games") or {}).values():
            tgt = by_key.get((g.get("date"), g.get("home"), g.get("away")))
            if tgt is not None and g.get("results"):
                tgt["_results"] = g["results"]


def main():
    games = json.loads(GAMES.read_text())
    load_results(games)
    gl = [g for g in games.values() if g.get("start") and g["home"] in ARENAS and g["away"] in ARENAS]
    today = datetime.now(ET).date()
    days = {}
    for off in (0, 1):
        d = (today + timedelta(days=off)).isoformat()
        todays = [g for g in gl if g["date"] == d]
        if not todays:
            continue
        day = {}
        for g in sorted(todays, key=lambda x: x["start"]):
            a = context(gl, g, g["away"], None)
            h = context(gl, g, g["home"], None)
            notes = a["notes"] + h["notes"]
            ra, rh = a.get("restDays"), h.get("restDays")
            if ra is not None and rh is not None and ra != rh:
                fresh, tired = (g["home"], g["away"]) if rh > ra else (g["away"], g["home"])
                fr, tr = (rh, ra) if rh > ra else (ra, rh)
                edge = f"Rest edge {fresh}: {fr} day{'s' if fr != 1 else ''} off vs {tr} for {tired}"
                if tr == 0:
                    edge += f" ({tired} on a back-to-back)"
                notes.insert(0, edge)
            elif ra is not None and ra == rh:
                notes.insert(0, f"Even rest: both teams {ra} day{'s' if ra != 1 else ''} off")
            day[g["id"]] = {"matchup": f"{g['away']} at {g['home']}", "tipET": utc(g["start"]).astimezone(ET).strftime("%-I:%M %p ET"),
                            "away": a, "home": h, "notes": notes}
        days[d] = day
    OUT.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": days}, indent=1) + "\n")
    n = sum(len(v) for v in days.values())
    print(f"schedule context for {n} games over {len(days)} days")


if __name__ == "__main__":
    main()
