#!/usr/bin/env python3
"""Advanced team and player stats for the morning write-ups.

Two sources, written together to data/nba-advanced.json:

  nba    stats.nba.com, the data behind nba.com/stats/teams/advanced and nba.com/stats/players/advanced:
         team advanced (season and last 10), four factors, opponent numbers, home/road splits, player advanced,
         player per-game, player last 5. Those endpoints want browser-like headers and sometimes refuse cloud
         IPs; when the pull fails the section records the error and the house numbers below still land.
  house  the same ideas computed from the box scores already stored in data/odds/<date>.json: possessions,
         offensive and defensive rating, pace, eFG%, turnover rate, offensive-rebound rate, free-throw rate,
         three-point rate, and per-player per-game lines, usage and recent form. Always present.

Read-only against the web; run daily before the morning task.
"""
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "nba-advanced.json"
SEASON = "2026-27"

TEAM_IDS = {1610612737: "ATL", 1610612738: "BOS", 1610612739: "CLE", 1610612740: "NOP", 1610612741: "CHI",
            1610612742: "DAL", 1610612743: "DEN", 1610612744: "GSW", 1610612745: "HOU", 1610612746: "LAC",
            1610612747: "LAL", 1610612748: "MIA", 1610612749: "MIL", 1610612750: "MIN", 1610612751: "BKN",
            1610612752: "NYK", 1610612753: "ORL", 1610612754: "IND", 1610612755: "PHI", 1610612756: "PHX",
            1610612757: "POR", 1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC", 1610612761: "TOR",
            1610612762: "UTA", 1610612763: "MEM", 1610612764: "WAS", 1610612765: "DET", 1610612766: "CHA"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Connection": "keep-alive",
}

BASE_PARAMS = {"LeagueID": "00", "Season": SEASON, "SeasonType": "Regular Season", "PerMode": "PerGame",
               "MeasureType": "Base", "LastNGames": "0", "Month": "0", "OpponentTeamID": "0", "PaceAdjust": "N",
               "Period": "0", "PlusMinus": "N", "Rank": "N", "Outcome": "", "Location": "", "SeasonSegment": "",
               "DateFrom": "", "DateTo": "", "VsConference": "", "VsDivision": "", "GameSegment": "", "Conference": "",
               "Division": "", "GameScope": "", "PlayerExperience": "", "PlayerPosition": "", "StarterBench": "",
               "ShotClockRange": "", "PORound": "0", "TwoWay": "0", "TeamID": "0", "College": "", "Country": "",
               "DraftPick": "", "DraftYear": "", "Height": "", "Weight": "", "ISTRound": ""}


def fetch(endpoint: str, **params):
    q = dict(BASE_PARAMS)
    q.update(params)
    url = f"https://stats.nba.com/stats/{endpoint}?" + urllib.parse.urlencode(q)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
            rs = data["resultSets"][0]
            return [dict(zip(rs["headers"], row)) for row in rs["rowSet"]]
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"{endpoint} {params.get('MeasureType')} {params.get('LastNGames')}: {last}")


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s.replace(" jr", "").replace(" sr", "").replace(" iii", "").replace(" ii", "")).strip()


def pick(row, keys):
    out = {}
    for k in keys:
        if k in row and row[k] is not None:
            v = row[k]
            out[k.lower()] = round(v, 3) if isinstance(v, float) else v
    return out


TEAM_ADV = ["GP", "W", "L", "W_PCT", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE", "AST_PCT", "AST_TO", "AST_RATIO",
            "OREB_PCT", "DREB_PCT", "REB_PCT", "TM_TOV_PCT", "EFG_PCT", "TS_PCT", "PIE"]
TEAM_FF = ["EFG_PCT", "FTA_RATE", "TM_TOV_PCT", "OREB_PCT", "OPP_EFG_PCT", "OPP_FTA_RATE", "OPP_TOV_PCT", "OPP_OREB_PCT"]
TEAM_OPP = ["OPP_PTS", "OPP_FG_PCT", "OPP_FG3M", "OPP_FG3A", "OPP_FG3_PCT", "OPP_FTA", "OPP_REB", "OPP_AST", "OPP_TOV", "OPP_PTS_OFF_TOV"
            , "OPP_PTS_PAINT", "OPP_PTS_FB", "OPP_PTS_2ND_CHANCE"]
TEAM_BASE = ["PTS", "FG3M", "FG3A", "FG3_PCT", "FTA", "REB", "AST", "TOV", "PLUS_MINUS"]
PLAYER_ADV = ["GP", "MIN", "USG_PCT", "TS_PCT", "EFG_PCT", "AST_PCT", "REB_PCT", "OREB_PCT", "DREB_PCT", "PIE", "PACE",
              "OFF_RATING", "DEF_RATING", "NET_RATING"]
PLAYER_BASE = ["GP", "MIN", "PTS", "REB", "AST", "FG3M", "FG3A", "FGA", "FTA", "STL", "BLK", "TOV", "PLUS_MINUS"]


def pull_nba():
    teams = {}
    for row in fetch("leaguedashteamstats", MeasureType="Advanced"):
        ab = TEAM_IDS.get(row["TEAM_ID"])
        if ab:
            teams[ab] = {"name": row["TEAM_NAME"], "advanced": pick(row, TEAM_ADV)}
    for row in fetch("leaguedashteamstats", MeasureType="Advanced", LastNGames="10"):
        ab = TEAM_IDS.get(row["TEAM_ID"])
        if ab in teams:
            teams[ab]["last10"] = pick(row, TEAM_ADV)
    for row in fetch("leaguedashteamstats", MeasureType="Four Factors"):
        ab = TEAM_IDS.get(row["TEAM_ID"])
        if ab in teams:
            teams[ab]["fourFactors"] = pick(row, TEAM_FF)
    for row in fetch("leaguedashteamstats", MeasureType="Opponent"):
        ab = TEAM_IDS.get(row["TEAM_ID"])
        if ab in teams:
            teams[ab]["opponent"] = pick(row, TEAM_OPP)
    for row in fetch("leaguedashteamstats", MeasureType="Base"):
        ab = TEAM_IDS.get(row["TEAM_ID"])
        if ab in teams:
            teams[ab]["perGame"] = pick(row, TEAM_BASE)
    for loc in ("Home", "Road"):
        for row in fetch("leaguedashteamstats", MeasureType="Advanced", Location=loc):
            ab = TEAM_IDS.get(row["TEAM_ID"])
            if ab in teams:
                teams[ab][loc.lower()] = pick(row, ["GP", "W", "L", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE"])

    players = {}
    for row in fetch("leaguedashplayerstats", MeasureType="Base"):
        players[row["PLAYER_NAME"]] = {"team": row.get("TEAM_ABBREVIATION"), "perGame": pick(row, PLAYER_BASE)}
    for row in fetch("leaguedashplayerstats", MeasureType="Advanced"):
        p = players.setdefault(row["PLAYER_NAME"], {"team": row.get("TEAM_ABBREVIATION")})
        p["advanced"] = pick(row, PLAYER_ADV)
    for row in fetch("leaguedashplayerstats", MeasureType="Base", LastNGames="5"):
        p = players.setdefault(row["PLAYER_NAME"], {"team": row.get("TEAM_ABBREVIATION")})
        p["last5"] = pick(row, PLAYER_BASE)
    # rotation players only: the file is read every morning, keep it to people who actually play
    players = {n: p for n, p in players.items() if ((p.get("perGame") or {}).get("min") or 0) >= 12}
    return {"teams": dict(sorted(teams.items())), "players": dict(sorted(players.items()))}


# ----------------------------------------------------------------------------------------------------------------
# House numbers from our own stored box scores


def poss(t, o):
    """Possessions for one team, Dean Oliver style, using the opponent's defensive rebounds."""
    fga, oreb, tov, fta = (float(t.get(k, 0) or 0) for k in ("fieldGoalsAttempted", "offensiveRebounds", "turnovers", "freeThrowsAttempted"))
    odreb = float(o.get("defensiveRebounds", 0) or 0)
    oreb_den = oreb + odreb
    return fga + 0.44 * fta - 1.07 * (oreb / oreb_den if oreb_den else 0) * (fga - float(t.get("fieldGoalsMade", 0) or 0)) + tov


def house():
    team_games = defaultdict(list)
    player_games = defaultdict(list)
    display, pteam = {}, {}
    for f in sorted((ROOT / "data" / "odds").glob("????-??-??.json")):
        for eid, g in (json.loads(f.read_text()).get("games") or {}).items():
            res = g.get("results") or {}
            if not res.get("home") or not res.get("away") or not g.get("ended"):
                continue
            h, a = res["home"], res["away"]
            ph, pa = poss(h, a), poss(a, h)
            p = (ph + pa) / 2 or 1
            for code, own, opp, side in ((g["home"], h, a, "home"), (g["away"], a, h, "away")):
                team_games[code].append({"date": g.get("date"), "side": side, "opp": g["away"] if side == "home" else g["home"],
                                         "pts": float(own.get("points", 0) or 0), "oppPts": float(opp.get("points", 0) or 0),
                                         "poss": p, "own": own, "oppBox": opp})
            # players are keyed by the feed's id (LUKA_DONCIC_1_NBA); display names come from the prop markets
            for m in g.get("markets") or []:
                if m.get("player") and m.get("name") and not m["name"].startswith(m["player"]):
                    first = re.split(r" (?:First basket|Assists|Double-double|Pts|Points|Reb|Rebounds|Steals|Blocks|Blk|3-pointers|Triple-double|Turnovers)\b", m["name"])[0]
                    display.setdefault(m["player"], first.strip())
                    if m.get("team"):
                        pteam.setdefault(m["player"], m["team"])
            for pid, ps in (res.get("players") or {}).items():
                player_games[pid].append({"date": g.get("date"), "eid": eid, "ps": ps, "teamPoss": p, "teams": (g["home"], g["away"])})

    def rate(num, den):
        return round(num / den, 3) if den else None

    teams = {}
    for code, gs in team_games.items():
        gs.sort(key=lambda x: x["date"] or "")
        n = len(gs)
        tp = sum(x["poss"] for x in gs)
        box = defaultdict(float)
        obox = defaultdict(float)
        for x in gs:
            for k, v in x["own"].items():
                if isinstance(v, (int, float)):
                    box[k] += v
            for k, v in x["oppBox"].items():
                if isinstance(v, (int, float)):
                    obox[k] += v
        pts, opts = sum(x["pts"] for x in gs), sum(x["oppPts"] for x in gs)
        ortg, drtg = 100 * pts / tp, 100 * opts / tp
        last3 = gs[-3:]
        tp3 = sum(x["poss"] for x in last3) or 1
        teams[code] = {
            "gp": n, "w": sum(1 for x in gs if x["pts"] > x["oppPts"]), "l": sum(1 for x in gs if x["pts"] < x["oppPts"]),
            "offRtg": round(ortg, 1), "defRtg": round(drtg, 1), "netRtg": round(ortg - drtg, 1), "pace": round(tp / n, 1),
            "ptsFor": round(pts / n, 1), "ptsAgainst": round(opts / n, 1), "avgTotal": round((pts + opts) / n, 1),
            "efg": rate(box["fieldGoalsMade"] + 0.5 * box["threePointersMade"], box["fieldGoalsAttempted"]),
            "oppEfg": rate(obox["fieldGoalsMade"] + 0.5 * obox["threePointersMade"], obox["fieldGoalsAttempted"]),
            "tovPct": rate(box["turnovers"], tp), "oppTovPct": rate(obox["turnovers"], tp),
            "orebPct": rate(box["offensiveRebounds"], box["offensiveRebounds"] + obox["defensiveRebounds"]),
            "drebPct": rate(box["defensiveRebounds"], box["defensiveRebounds"] + obox["offensiveRebounds"]),
            "ftRate": rate(box["freeThrowsAttempted"], box["fieldGoalsAttempted"]),
            "threeRate": rate(box["threePointersAttempted"], box["fieldGoalsAttempted"]),
            "threePct": rate(box["threePointersMade"], box["threePointersAttempted"]),
            "oppThreePct": rate(obox["threePointersMade"], obox["threePointersAttempted"]),
            "oppThreesMade": round(obox["threePointersMade"] / n, 1),
            "oppReb": round(obox["rebounds"] / n, 1), "oppAst": round(obox["assists"] / n, 1),
            "last3": {"offRtg": round(100 * sum(x["pts"] for x in last3) / tp3, 1),
                      "defRtg": round(100 * sum(x["oppPts"] for x in last3) / tp3, 1),
                      "pace": round(tp3 / max(1, len(last3)), 1),
                      "results": [f"{'W' if x['pts'] > x['oppPts'] else 'L'} {'vs' if x['side'] == 'home' else 'at'} {x['opp']} "
                                  f"{int(x['pts'])}-{int(x['oppPts'])}" for x in last3]},
            "home": {"gp": sum(1 for x in gs if x["side"] == "home"),
                     "w": sum(1 for x in gs if x["side"] == "home" and x["pts"] > x["oppPts"])},
            "away": {"gp": sum(1 for x in gs if x["side"] == "away"),
                     "w": sum(1 for x in gs if x["side"] == "away" and x["pts"] > x["oppPts"])},
        }

    rosters = {}
    rp = ROOT / "data" / "rosters.json"
    if rp.exists():
        rosters = json.loads(rp.read_text()).get("players", {})
    rnorm = {norm(n): v for n, v in rosters.items()}
    players = {}
    for pid, gs in player_games.items():
        name = display.get(pid) or " ".join(w.capitalize() for w in pid.replace("_1_NBA", "").split("_"))
        gs.sort(key=lambda x: x["date"] or "")
        played = [x for x in gs if float(x["ps"].get("secondsPlayed", 0) or 0) > 0]
        if len(played) < 1:
            continue
        n = len(played)
        mins = sum(float(x["ps"].get("secondsPlayed", 0) or 0) for x in played) / 60
        if mins / n < 12:
            continue
        ro = rosters.get(name) or rnorm.get(norm(name)) or {}
        team = pteam.get(pid) or ro.get("team")
        team_tot = defaultdict(float)
        usage_num = 0.0
        for x in played:
            ps = x["ps"]
            usage_num += float(ps.get("fieldGoalsAttempted", 0) or 0) + 0.44 * float(ps.get("freeThrowsAttempted", 0) or 0) + float(ps.get("turnovers", 0) or 0)
            for k in ("points", "rebounds", "assists", "threePointersMade", "threePointersAttempted", "fieldGoalsAttempted",
                      "freeThrowsAttempted", "steals", "blocks", "turnovers"):
                team_tot[k] += float(ps.get(k, 0) or 0)
        # usage: share of team possessions used while on the floor, team possessions prorated to his minutes
        team_poss_on = sum(x["teamPoss"] * (float(x["ps"].get("secondsPlayed", 0) or 0) / 60) / 48 for x in played)
        usg = rate(usage_num, team_poss_on)
        last3 = played[-3:]

        def avg(rows, k):
            return round(sum(float(r["ps"].get(k, 0) or 0) for r in rows) / len(rows), 1)

        players[name] = {
            "team": team, "pos": ro.get("pos"), "feedId": pid, "gp": n, "min": round(mins / n, 1),
            "pts": round(team_tot["points"] / n, 1), "reb": round(team_tot["rebounds"] / n, 1), "ast": round(team_tot["assists"] / n, 1),
            "threes": round(team_tot["threePointersMade"] / n, 1), "threesAtt": round(team_tot["threePointersAttempted"] / n, 1),
            "fga": round(team_tot["fieldGoalsAttempted"] / n, 1), "fta": round(team_tot["freeThrowsAttempted"] / n, 1),
            "stl": round(team_tot["steals"] / n, 1), "blk": round(team_tot["blocks"] / n, 1), "tov": round(team_tot["turnovers"] / n, 1),
            "usage": usg,
            "ts": rate(team_tot["points"], 2 * (team_tot["fieldGoalsAttempted"] + 0.44 * team_tot["freeThrowsAttempted"])),
            "last3": {"min": round(sum(float(r["ps"].get("secondsPlayed", 0) or 0) for r in last3) / 60 / len(last3), 1),
                      "pts": avg(last3, "points"), "reb": avg(last3, "rebounds"), "ast": avg(last3, "assists"),
                      "threes": avg(last3, "threePointersMade"),
                      "lines": [f"{x['date']}: {int(float(x['ps'].get('points', 0) or 0))} pts, {int(float(x['ps'].get('rebounds', 0) or 0))} reb, "
                                f"{int(float(x['ps'].get('assists', 0) or 0))} ast, {int(float(x['ps'].get('threePointersMade', 0) or 0))} 3PM, "
                                f"{int(float(x['ps'].get('secondsPlayed', 0) or 0) // 60)} min" for x in last3]},
            "dnp": len(gs) - n,
        }
    return {"teams": dict(sorted(teams.items())), "players": dict(sorted(players.items()))}


def main():
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "season": SEASON,
           "about": {"nba": "stats.nba.com advanced, four factors, opponent, per-game, home/road, player advanced/per-game/last 5",
                     "house": "same ideas computed from our stored box scores (data/odds); pace is possessions per game"}}
    try:
        out["nba"] = pull_nba()
        print(f"nba.com: {len(out['nba']['teams'])} teams, {len(out['nba']['players'])} players")
    except Exception as e:  # noqa: BLE001
        out["nba"] = None
        out["nbaError"] = str(e)[:300]
        print(f"nba.com pull failed: {e}", file=sys.stderr)
    out["house"] = house()
    print(f"house: {len(out['house']['teams'])} teams, {len(out['house']['players'])} players")
    OUT.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
