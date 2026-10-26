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
    profit = float(math.floor(stake * (dec - 1) + 0.5))  # whole points: payouts round to the nearest point (half up)
    return {"status": "win", "net": profit, "payout": stake + profit}


def main() -> int:
    password = os.environ.get("POOL_PASSWORD", "")
    if not password:
        print("POOL_PASSWORD not set", file=sys.stderr)
        return 1
    cfg = firebase_config()
    token = sign_in(cfg["apiKey"], password)
    base = f"https://firestore.googleapis.com/v1/projects/{cfg['projectId']}/databases/(default)/documents"
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
