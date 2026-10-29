#!/usr/bin/env python3
"""What actually happened on every leg of every settled bet, for the Bets tab.

Reads the nightly wagers backup and the box scores stored in data/odds/<date>.json, and writes
data/leg-actuals.json: {wagerId: [{text, margin}, ...]} aligned with each wager's legs. margin is how far the
result landed from the number, signed in the bettor's favor (+4.5 covered by 4.5, -3 missed by 3), or null when
it does not apply (a moneyline, a yes/no prop, a player who did not play). Settled bets only; open bets are left
out so nothing about them shows before tip-off. Run after the nightly backup.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from grade import stat_value  # noqa: E402

STAT_WORD = {"points": "pts", "rebounds": "reb", "assists": "ast", "threePointersMade": "threes", "steals": "stl",
             "blocks": "blk", "turnovers": "TO", "points+rebounds+assists": "PRA", "points+rebounds": "pts+reb",
             "points+assists": "pts+ast", "rebounds+assists": "reb+ast", "blocks+steals": "blk+stl"}


def fmt(x):
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def by(m, word_win, word_loss):
    if m is None:
        return ""
    if m > 0:
        return f" ({word_win} by {fmt(m)})"
    if m < 0:
        return f" ({word_loss} by {fmt(-m)})"
    return " (push)"


def actual(leg: dict, game: dict):
    res = game.get("results") or {}
    if not res:
        return None
    home, away = game.get("home", "HOME"), game.get("away", "AWAY")
    bt, side, line, stat = leg.get("betType"), leg.get("side"), leg.get("line"), leg.get("stat", "points")
    if leg.get("player"):
        ps = (res.get("players") or {}).get(leg["player"])
        if ps is None:
            return {"text": "Did not play", "margin": None}
        v = stat_value(ps, stat)
        if v is None:
            return None
        if bt == "yn":
            parts = [f"{fmt(ps.get(k, 0) or 0)} {w}" for k, w in (("points", "pts"), ("rebounds", "reb"), ("assists", "ast"))]
            got = float(v) >= 1
            return {"text": ("Got it: " if got else "Did not: ") + ", ".join(parts), "margin": None}
        if bt == "ou" and line is not None:
            m = (float(v) - float(line)) * (1 if side == "over" else -1)
            return {"text": f"{fmt(v)} {STAT_WORD.get(stat, stat)}" + by(m, "cleared", "missed"), "margin": m}
        return None
    period = leg.get("period", "game")
    blk = res if period == "game" else res.get(period)
    if not blk:
        return None
    hp = float((blk.get("home") or {}).get("points", 0) or 0)
    ap = float((blk.get("away") or {}).get("points", 0) or 0)
    pre = "1st half " if period == "1h" else "Final "
    score = f"{pre}{away} {fmt(ap)}, {home} {fmt(hp)}"
    if bt == "ml":
        own, opp = (hp, ap) if side == "home" else (ap, hp)
        m = own - opp
        return {"text": score + (f" (won by {fmt(m)})" if m > 0 else f" (lost by {fmt(-m)})" if m < 0 else " (tie)"), "margin": m}
    if bt == "sp" and line is not None:
        own, opp = (hp, ap) if side == "home" else (ap, hp)
        m = own + float(line) - opp
        return {"text": score + by(m, "covered", "missed"), "margin": m}
    if bt == "ou" and line is not None:
        ent = leg.get("entity")
        tot = hp + ap if ent == "all" else hp if ent == "home" else ap
        who = "Total" if ent == "all" else (home if ent == "home" else away) + " scored"
        m = (tot - float(line)) * (1 if side == "over" else -1)
        return {"text": f"{pre.strip()} {who} {fmt(tot)}".replace("Final Total", "Total") + by(m, "cleared", "missed"), "margin": m}
    return None


def main():
    wagers = json.loads((ROOT / "data" / "backups" / "wagers-latest.json").read_text()).get("wagers", {})
    games = {}
    for f in sorted((ROOT / "data" / "odds").glob("????-??-??.json")):
        for eid, g in (json.loads(f.read_text()).get("games") or {}).items():
            games[eid] = g
    out = {}
    for wid, w in wagers.items():
        if w.get("status") in (None, "open"):
            continue
        g = games.get(w.get("eventID"))
        if not g:
            continue
        legs = w.get("legs") or []
        row = [actual(l, g) for l in legs]
        if any(row):
            out[wid] = row
    path = ROOT / "data" / "leg-actuals.json"
    path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(f"leg actuals for {len(out)} settled bets")


if __name__ == "__main__":
    main()
