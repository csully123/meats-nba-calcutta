#!/usr/bin/env python3
"""Per-player betting profile from the nightly wagers backup, for the morning task's strategy write-ups.

Uses settled bets only (win, loss, push, void), so nobody's open bets are revealed before tip-off.
Prints JSON: {player: {...numbers...}}. Read-only; writes nothing.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYERS = ["Kev", "Beekie", "Mio", "Sulliver"]


def american_to_decimal(a):
    a = float(a)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def kind_of(leg):
    if leg.get("player"):
        return "player prop"
    if leg.get("period") == "1h":
        return "first-half line"
    return {"sp": "spread", "ml": "moneyline", "ou": "total"}.get(leg.get("betType"), "other")


def bucket(odds):
    o = float(odds)
    if o <= -200: return "heavy favorite (-200 or shorter)"
    if o < -130: return "favorite (-199 to -131)"
    if o <= 130: return "near even (-130 to +130)"
    if o <= 300: return "underdog (+131 to +300)"
    return "long shot (+301 or longer)"


def main():
    path = ROOT / "data" / "backups" / "wagers-latest.json"
    wagers = list(json.loads(path.read_text()).get("wagers", {}).values())
    out = {}
    for p in PLAYERS:
        mine = [w for w in wagers if w.get("player") == p and w.get("status") in ("win", "loss", "push", "void")]
        graded = [w for w in mine if w.get("status") in ("win", "loss")]
        singles = [w for w in mine if len(w.get("legs", [])) == 1]
        parlays = [w for w in mine if len(w.get("legs", [])) > 1]
        rec = lambda ws: f"{sum(1 for w in ws if w.get('status') == 'win')}-{sum(1 for w in ws if w.get('status') == 'loss')}"
        legs = [l for w in mine for l in w.get("legs", [])]
        kinds = Counter(kind_of(l) for l in legs)
        teams = Counter(l.get("team") for l in legs if l.get("team") and not l.get("player"))
        stat_words = re.compile(r" (Points|Rebounds|Assists|3-pointers made|Pts \+ Reb \+ Ast|Pts \+ Reb|Pts \+ Ast|Reb \+ Ast|Steals|Blocks|Turnovers|Blk \+ Stl|Double-double|Triple-double|First basket)\b.*$")
        prop_players = Counter(stat_words.sub("", l.get("short", "")) for l in legs if l.get("player"))
        sides = Counter((l.get("side") or "") for l in legs if l.get("betType") == "ou")
        # odds of the whole bet (parlays at their combined price)
        prices = []
        for w in mine:
            d = 1.0
            for l in w.get("legs", []):
                d *= american_to_decimal(l.get("odds", -110))
            prices.append(d)
        avg_dec = sum(prices) / len(prices) if prices else None
        by_bucket = Counter()
        by_bucket_win = Counter()
        for w, d in zip(mine, prices):
            a = (d - 1) * 100 if d >= 2 else -100 / (d - 1)
            b = bucket(a)
            if w.get("status") in ("win", "loss"):
                by_bucket[b] += 1
                by_bucket_win[b] += w.get("status") == "win"
        kind_rec = {}
        for k in kinds:
            ws = [w for w in graded if all(kind_of(l) == k for l in w.get("legs", []))]
            if ws:
                kind_rec[k] = rec(ws)
        out[p] = {
            "settledBets": len(mine),
            "record": rec(graded),
            "net": round(sum(float(w.get("net") or 0) for w in mine), 1),
            "singles": {"count": len(singles), "record": rec([w for w in singles if w in graded])},
            "parlays": {"count": len(parlays), "record": rec([w for w in parlays if w in graded]),
                        "avgLegs": round(sum(len(w["legs"]) for w in parlays) / len(parlays), 1) if parlays else None},
            "avgStake": round(sum(float(w.get("stake") or 0) for w in mine) / len(mine), 1) if mine else None,
            "avgPriceAmerican": (round((avg_dec - 1) * 100) if avg_dec and avg_dec >= 2 else (round(-100 / (avg_dec - 1)) if avg_dec else None)),
            "legTypes": dict(kinds.most_common()),
            "recordByLegType": kind_rec,
            "overUnder": dict(sides),
            "topTeams": teams.most_common(5),
            "topPropPlayers": prop_players.most_common(5),
            "recordByPrice": {b: f"{by_bucket_win[b]}-{by_bucket[b] - by_bucket_win[b]}" for b in by_bucket},
            "boostsUsed": Counter((w.get("boost") or {}).get("id", "").split(":")[0] for w in mine if w.get("boost")).most_common(),
            "firstBet": min((w.get("placedAt") or "" for w in mine), default=None),
        }
    json.dump(out, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
