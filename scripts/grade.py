#!/usr/bin/env python3
"""Settle open wagers in Firestore from the results stored in data/odds/<date>.json.

A wager document: {player, stake, placedAt, eventID, legs:[{oddID, name, side, line, odds, stat, period, entity, player, team}],
                   settled: null | {status, net, payout, legs:[...]}, settledAt}
Grading rules: spread and total use the line stored on the leg; props use the player's stat from results.players;
a leg exactly on the line is a push and drops out of a parlay; a lost leg loses the slip; a player with no box score
entry (did not play) voids that leg.
"""
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from backup import firebase_config, sign_in, unwrap  # noqa: E402

ODDS_DIR = ROOT / "data" / "odds"


def decimal(american):
    a = float(american)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def stat_value(stats: dict, stat: str):
    if stat in stats:
        return stats[stat]
    if "+" in stat:
        parts = stat.split("+")
        if all(p in stats for p in parts):
            return sum(float(stats[p]) for p in parts)
    if stat == "doubleDouble" or stat == "tripleDouble":
        cats = [stats.get(k, 0) or 0 for k in ("points", "rebounds", "assists", "steals", "blocks")]
        n = sum(1 for c in cats if float(c) >= 10)
        return 1 if n >= (2 if stat == "doubleDouble" else 3) else 0
    return None


def grade_leg(leg: dict, game: dict):
    res = game.get("results")
    if not res:
        return None
    period = leg.get("period", "game")
    entity = leg.get("entity")
    side = leg.get("side")
    bt = leg.get("betType")
    stat = leg.get("stat", "points")
    line = leg.get("line")
    if leg.get("player"):
        pstats = (res.get("players") or {}).get(leg["player"])
        if pstats is None:
            return "void"
        v = stat_value(pstats, stat)
        if v is None:
            return None
        if bt == "yn":
            hit = float(v) >= 1
            return "win" if (hit and side == "yes") or (not hit and side == "no") else "loss"
        if bt == "ou" and line is not None:
            v = float(v)
            if v == float(line):
                return "push"
            return "win" if (v > float(line)) == (side == "over") else "loss"
        return None
    blk = res if period == "game" else res.get(period)
    if not blk:
        return None
    hp = float((blk.get("home") or {}).get("points", 0) or 0)
    ap = float((blk.get("away") or {}).get("points", 0) or 0)
    if bt == "ml":
        if hp == ap:
            return "push"
        return "win" if (hp > ap) == (side == "home") else "loss"
    if bt == "sp" and line is not None:
        own, opp = (hp, ap) if side == "home" else (ap, hp)
        m = own + float(line) - opp
        return "win" if m > 0 else "loss" if m < 0 else "push"
    if bt == "ou" and line is not None:
        tot = hp + ap if entity == "all" else hp if entity == "home" else ap
        if tot == float(line):
            return "push"
        return "win" if (tot > float(line)) == (side == "over") else "loss"
    return None


def verify(w: dict, g: dict):
    """Honor-system backstop. A bet is voided (stake returned) when its server-stamped placement time is after tip-off,
    or when a leg's stored line and price were never offered on that market by the feed."""
    created = w.get("createdAt")
    start = g.get("start")
    if created and start and str(created) > str(start):
        return f"placed at {created}, after tip-off {start}"
    markets = {m.get("oddID"): m for m in g.get("markets", [])}
    for leg in w.get("legs", []):
        m = markets.get(leg.get("oddID"))
        if not m:
            return f"market {leg.get('oddID')} not on file"
        seen = m.get("seen")
        since = m.get("seenSince")
        if not seen or not created or not since or str(created) < str(since):
            continue  # no price history for the time this bet was placed: nothing to check against
        line = leg.get("line")
        try:
            odds = int(leg.get("odds"))
        except (TypeError, ValueError):
            return f"bad odds on {leg.get('short')}"
        ok = any((x[0] == line or (x[0] is None and line is None) or (x[0] is not None and line is not None and float(x[0]) == float(line))) and int(x[1]) == odds for x in seen)
        if not ok:
            return f"{leg.get('short')} at {odds} was never offered"
    return None


def settle(w: dict, leg_results: list):
    if any(r is None for r in leg_results):
        return None
    if any(r == "loss" for r in leg_results):
        return {"status": "loss", "net": -float(w["stake"]), "payout": 0.0}
    dec, live = 1.0, 0
    for leg, r in zip(w["legs"], leg_results):
        if r == "win":
            dec *= decimal(leg["odds"])
            live += 1
    if live == 0:
        return {"status": "push", "net": 0.0, "payout": float(w["stake"])}
    stake = float(w["stake"])
    boost = w.get("boost") or {}
    try:
        mult = float(boost.get("mult") or 1)  # a boost token multiplies the profit, never the stake
    except (TypeError, ValueError):
        mult = 1.0
    boosted = min(stake, 20.0)  # a token boosts the profit on the first 20 points of stake
    profit = math.floor((stake * (dec - 1) + boosted * (dec - 1) * (mult - 1)) * 100 + 1e-6) / 100  # profit rounds down to the hundredth
    return {"status": "win", "net": profit, "payout": round(stake + profit, 2)}


def repay_wins(base: str, headers: dict) -> None:
    """Points went from whole numbers to two decimals on 2026-10-29. Wins settled before that had their profit rounded
    down to a whole point; recompute every settled win from its stored leg results and patch any whose net differs.
    Idempotent: once every win carries its exact two-decimal profit, this changes nothing."""
    body = {"structuredQuery": {"from": [{"collectionId": "wagers"}], "where": {"fieldFilter": {"field": {"fieldPath": "status"}, "op": "EQUAL", "value": {"stringValue": "win"}}}, "limit": 1000}}
    req = urllib.request.Request(base + ":runQuery", data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)
    fixed = 0
    for row in rows:
        doc = row.get("document")
        if not doc:
            continue
        w = {k: unwrap(v) for k, v in (doc.get("fields") or {}).items()}
        results = w.get("legResults") or []
        if len(results) != len(w.get("legs") or []):
            continue
        s = settle(w, results)
        if not s or s["status"] != "win" or abs(float(w.get("net") or 0) - s["net"]) < 0.005:
            continue
        patch = {"fields": {"net": {"doubleValue": s["net"]}, "payout": {"doubleValue": s["payout"]}}}
        mask = "&".join("updateMask.fieldPaths=" + k for k in patch["fields"])
        req = urllib.request.Request(f"https://firestore.googleapis.com/v1/{doc['name']}?{mask}", data=json.dumps(patch).encode(), headers=headers, method="PATCH")
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        fixed += 1
        print(f"repaid {doc['name'].rsplit('/',1)[-1]}: net {w.get('net')} -> {s['net']}")
    print(f"repaid {fixed} settled wins to two decimals")


def main() -> int:
    password = os.environ.get("POOL_PASSWORD", "")
    if not password:
        print("POOL_PASSWORD not set", file=sys.stderr)
        return 1
    cfg = firebase_config()
    token = sign_in(cfg["apiKey"], password)
    base = f"https://firestore.googleapis.com/v1/projects/{cfg['projectId']}/databases/(default)/documents"
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if "--repay-only" in sys.argv:  # re-pay settled wins to two decimals without grading anything else
        repay_wins(base, headers)
        return 0
    games = {}
    for p in ODDS_DIR.glob("????-??-??.json"):
        for gid, g in json.loads(p.read_text()).get("games", {}).items():
            games[gid] = g
    # Query open wagers
    body = {"structuredQuery": {"from": [{"collectionId": "wagers"}], "where": {"fieldFilter": {"field": {"fieldPath": "status"}, "op": "EQUAL", "value": {"stringValue": "open"}}}, "limit": 1000}}
    req = urllib.request.Request(base + ":runQuery", data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)
    graded = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in rows:
        doc = row.get("document")
        if not doc:
            continue
        w = {k: unwrap(v) for k, v in (doc.get("fields") or {}).items()}
        g = games.get(w.get("eventID"))
        if not g or not g.get("results"):
            continue
        bad = verify(w, g)
        if bad:
            leg_results = ["void"] * len(w.get("legs", []))
            s = {"status": "void", "net": 0.0, "payout": float(w["stake"])}
            print(f"voiding {doc['name'].rsplit('/',1)[-1]}: {bad}")
        else:
            leg_results = [grade_leg(leg, g) for leg in w.get("legs", [])]
            s = settle(w, leg_results)
        if not s:
            continue
        patch = {"fields": {
            "status": {"stringValue": s["status"]},
            "net": {"doubleValue": s["net"]},
            "payout": {"doubleValue": s["payout"]},
            "legResults": {"arrayValue": {"values": [{"stringValue": x} for x in leg_results]}},
            "settledAt": {"stringValue": now},
        }}
        mask = "&".join("updateMask.fieldPaths=" + k for k in patch["fields"])
        req = urllib.request.Request(doc["name"].replace("projects/", base.split("/projects/")[0] + "/projects/", 1) if doc["name"].startswith("projects/") else doc["name"],
                                     data=json.dumps(patch).encode(), headers=headers, method="PATCH")
        url = f"https://firestore.googleapis.com/v1/{doc['name']}?{mask}"
        req = urllib.request.Request(url, data=json.dumps(patch).encode(), headers=headers, method="PATCH")
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        graded += 1
        print(f"settled {doc['name'].rsplit('/',1)[-1]}: {s['status']} net {s['net']}")
    print(f"graded {graded} of {len(rows)} open wagers")
    repay_wins(base, headers)
    grade_claude(games)
    return 0


INSIGHTS = ROOT / "data" / "book-insights.json"


def grade_claude(games: dict) -> None:
    """Grade Claude's daily best single and best parlay (data/book-insights.json, key "days") from the same box
    scores, writing the outcome under key "results" so the site can show a running record. Never touches
    the entries themselves."""
    if not INSIGHTS.exists():
        return
    data = json.loads(INSIGHTS.read_text())
    days = data.get("days") or {}
    results = data.setdefault("results", {})
    changed = 0

    def leg_full(game: dict, leg: dict):
        m = next((x for x in game.get("markets", []) if x.get("oddID") == leg.get("oddID")), None)
        if not m:
            return None
        full = dict(m)
        if leg.get("line") is not None:
            full["line"] = leg["line"]
        return full

    def outcome(game: dict, legs: list):
        rs = []
        for leg in legs:
            full = leg_full(game, leg)
            if not full:
                return None
            r = grade_leg(full, game)
            if r is None:
                return None
            rs.append(r)
        if any(r == "loss" for r in rs):
            return "loss"
        if all(r in ("push", "void") for r in rs):
            return "push"
        return "win"

    for date, day in days.items():
        out = results.setdefault(date, {})
        for kind in ("single", "parlay"):
            pick = day.get(kind)
            if not pick or out.get(kind):
                continue
            game = games.get(pick.get("eventID"))
            if not game or not game.get("results"):
                continue
            legs = [pick] if kind == "single" else (pick.get("legs") or [])
            r = outcome(game, legs)
            if r:
                out[kind] = r
                changed += 1
        # each person's own bet of the day: {name: {eventID, legs: [...]}}
        for name, pick in (day.get("personal") or {}).items():
            per = out.setdefault("personal", {})
            if not pick or per.get(name):
                continue
            game = games.get(pick.get("eventID"))
            if not game or not game.get("results"):
                continue
            r = outcome(game, pick.get("legs") or [])
            if r:
                per[name] = r
                changed += 1
    # each game's own best single and parlay (key "games"): graded into results.games[eventID] with the teams the
    # bet rode on, so the site can keep a record per team
    def teams_of(game: dict, legs: list, fallback: str = ""):
        out = []
        for leg in legs:
            m = next((x for x in game.get("markets", []) if x.get("oddID") == leg.get("oddID")), None)
            t = (m or {}).get("team") or (leg.get("team") if m is None else "")
            if t and t not in out:
                out.append(t)
        if not out and fallback:
            out.append(fallback)
        return out

    gres = results.setdefault("games", {})
    for eid, entry in (data.get("games") or {}).items():
        game = games.get(eid)
        if not game or not game.get("results"):
            continue
        out = gres.setdefault(eid, {})
        for kind in ("single", "parlay"):
            pick = entry.get(kind)
            if not pick or out.get(kind):
                continue
            legs = [pick] if kind == "single" else (pick.get("legs") or [])
            r = outcome(game, legs)
            if r:
                out[kind] = {"r": r, "teams": teams_of(game, legs, pick.get("team", "") if kind == "single" else ""),
                             "date": entry.get("date")}
                changed += 1
        if not out:
            gres.pop(eid, None)
    if changed:
        INSIGHTS.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        print(f"graded {changed} of Claude's picks")


if __name__ == "__main__":
    sys.exit(main())
