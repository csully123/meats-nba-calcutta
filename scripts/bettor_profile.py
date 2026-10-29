#!/usr/bin/env python3
"""Per-player betting profile from the nightly wagers backup, for the morning task's strategy write-ups.

Uses settled bets only (win, loss, push, void), so nobody's open bets are revealed before tip-off.
Prints JSON: {player: {...numbers...}}. Read-only; writes nothing.

Sources: data/backups/wagers-latest.json (bets), data/rosters.json (ESPN positions, for guards vs wings vs bigs),
data/book-insights.json (Claude's picks of the day, to spot who follows them), data/odds/*.json (main lines, to
tell an alt line from the main number).
"""
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYERS = ["Kev", "Beekie", "Mio", "Sulliver"]
SETTLED = ("win", "loss", "push", "void")
STAT_WORDS = re.compile(r" (Points|Rebounds|Assists|3-pointers made|Pts \+ Reb \+ Ast|Pts \+ Reb|Pts \+ Ast|Reb \+ Ast|Steals|Blocks|"
                        r"Turnovers|Blk \+ Stl|Double-double|Triple-double|First basket)\b.*$")
STAT_NAMES = {"points": "points", "rebounds": "rebounds", "assists": "assists", "threePointersMade": "threes",
              "points+rebounds+assists": "PRA combo", "points+rebounds": "combo", "points+assists": "combo",
              "rebounds+assists": "combo", "steals": "steals", "blocks": "blocks", "turnovers": "turnovers",
              "blocks+steals": "combo", "doubleDouble": "double-double", "tripleDouble": "triple-double", "firstBasket": "first basket"}


ROSTER_BY_NORM = {}


def pretty_name(text: str) -> str:
    """Raw feed ids in a leg label (ZACH_LAVINE_1_NBA Points) become the ESPN roster spelling."""
    def fix(m):
        guess = " ".join(w.capitalize() for w in m.group(0).rsplit("_", 2)[0].split("_") if w)
        return ROSTER_BY_NORM.get(norm(guess), guess)
    return re.sub(r"\b[A-Z][A-Z0-9']*(?:_[A-Z0-9']+)*_\d+_NBA\b", fix, text or "")


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s.replace(" jr", "").replace(" sr", "").replace(" iii", "").replace(" ii", "")).strip()


def dec(a) -> float:
    a = float(a)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def amer(d: float):
    if not d or d <= 1:
        return None
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def rec(ws) -> str:
    w = sum(1 for x in ws if x.get("status") == "win")
    l = sum(1 for x in ws if x.get("status") == "loss")
    return f"{w}-{l}"


def kind_of(leg) -> str:
    if leg.get("player"):
        return "player prop"
    if leg.get("period") == "1h":
        return "first-half line"
    return {"sp": "spread", "ml": "moneyline", "ou": "total"}.get(leg.get("betType"), "other")


def price_band(a) -> str:
    if a is None:
        return "unknown"
    if a <= -200: return "heavy favorite (-200 or shorter)"
    if a < -130: return "favorite (-199 to -131)"
    if a <= 130: return "near even (-130 to +130)"
    if a <= 300: return "underdog (+131 to +300)"
    return "long shot (+301 or longer)"


def pos_group(pos):
    """ESPN lists positions as G, F or C (sometimes PG, SG, SF, PF, G-F, F-C): group into guard, forward, center."""
    if not pos:
        return None
    p = pos.upper()
    if p in ("PG", "SG", "G", "G-F"):
        return "guard"
    if p in ("SF", "PF", "F", "F-G"):
        return "forward"
    if p in ("C", "F-C", "C-F"):
        return "center"
    return None


def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def main():
    wagers = list(load(ROOT / "data" / "backups" / "wagers-latest.json", {}).get("wagers", {}).values())
    rosters = {norm(k): v for k, v in load(ROOT / "data" / "rosters.json", {}).get("players", {}).items()}
    for k in load(ROOT / "data" / "rosters.json", {}).get("players", {}):
        ROSTER_BY_NORM.setdefault(norm(k), k)
    insights = load(ROOT / "data" / "book-insights.json", {})
    # Claude's picks: (eventID, oddID) pairs for singles, and each parlay's leg set
    claude_singles, claude_parlays = set(), []
    for day in (insights.get("days") or {}).values():
        s = day.get("single") or {}
        if s.get("eventID"):
            claude_singles.add((s["eventID"], s.get("oddID")))
        p = day.get("parlay") or {}
        if p.get("eventID"):
            claude_parlays.append((p["eventID"], {l.get("oddID") for l in p.get("legs") or []}))
    # main lines on file, to tell alt numbers from mains
    mains = {}
    for f in sorted((ROOT / "data" / "odds").glob("????-??-??.json")):
        for eid, g in (load(f, {}).get("games") or {}).items():
            for m in g.get("markets") or []:
                mains[(eid, m.get("oddID"))] = (m.get("line"), m.get("odds"))
    games_home = {}
    for f in sorted((ROOT / "data" / "odds").glob("????-??-??.json")):
        for eid, g in (load(f, {}).get("games") or {}).items():
            games_home[eid] = (g.get("home"), g.get("away"))

    out = {}
    for p in PLAYERS:
        mine = sorted([w for w in wagers if w.get("player") == p and w.get("status") in SETTLED], key=lambda w: w.get("placedAt") or "")
        graded = [w for w in mine if w.get("status") in ("win", "loss")]
        singles = [w for w in mine if len(w.get("legs", [])) == 1]
        parlays = [w for w in mine if len(w.get("legs", [])) > 1]
        legs = [(w, l) for w in mine for l in w.get("legs", [])]

        # whole-bet price
        prices = {}
        for w in mine:
            d = 1.0
            for l in w.get("legs", []):
                d *= dec(l.get("odds", -110))
            prices[id(w)] = amer(d)
        band = defaultdict(list)
        for w in mine:
            band[price_band(prices[id(w)])].append(w)

        # sides: favorites vs underdogs, home vs away
        side_legs = [(w, l) for w, l in legs if l.get("betType") in ("sp", "ml") and not l.get("player")]
        fav = dog = 0
        home = away = 0
        for w, l in side_legs:
            if l.get("betType") == "sp" and l.get("line") is not None:
                fav, dog = (fav + 1, dog) if float(l["line"]) < 0 else (fav, dog + 1)
            elif l.get("betType") == "ml":
                fav, dog = (fav + 1, dog) if float(l.get("odds", 0)) < 0 else (fav, dog + 1)
            hp = games_home.get(w.get("eventID"))
            if l.get("entity") == "home" or (hp and l.get("team") == hp[0]):
                home += 1
            elif l.get("entity") == "away" or (hp and l.get("team") == hp[1]):
                away += 1

        # props: who, what stat, positions, over/under
        prop_legs = [(w, l) for w, l in legs if l.get("player")]
        prop_names = Counter(STAT_WORDS.sub("", pretty_name(l.get("short", ""))).strip() for _, l in prop_legs)
        prop_stats = Counter(STAT_NAMES.get(l.get("stat"), l.get("stat") or "other") for _, l in prop_legs)
        pos = Counter()
        unknown_pos = []
        for _, l in prop_legs:
            name = STAT_WORDS.sub("", l.get("short", "")).strip()
            g = pos_group((rosters.get(norm(name)) or {}).get("pos"))
            if g:
                pos[g] += 1
            else:
                unknown_pos.append(name)
        prop_dirs = Counter((l.get("side") or "") for _, l in prop_legs if l.get("betType") in ("ou", "yn"))
        total_dirs = Counter((l.get("side") or "") for _, l in legs if l.get("betType") == "ou" and not l.get("player"))

        # teams backed (sides only) and teams involved at all
        teams_backed = Counter(l.get("team") for _, l in side_legs if l.get("team"))
        games_bet = Counter(w.get("game") for w in mine if w.get("game"))

        # alt lines ("teasing"): direction from price vs the main number
        alt = [(w, l) for w, l in legs if l.get("alt")]
        bought = sold = 0
        for w, l in alt:
            main = mains.get((w.get("eventID"), l.get("oddID")))
            o = float(l.get("odds", 0))
            mo = float(main[1]) if main and main[1] is not None else -110.0
            if dec(o) < dec(mo):
                bought += 1  # shorter price than the main line: bought points or a safer number
            else:
                sold += 1    # longer price: moved the number for a bigger payout

        # boosts
        boosted = [w for w in mine if w.get("boost")]
        boost_kinds = Counter(((w.get("boost") or {}).get("id") or "").split(":")[0] for w in boosted)
        boost_on = Counter("parlay" if len(w.get("legs", [])) > 1 else kind_of(w["legs"][0]) for w in boosted)

        # timing: hours before tip
        leads = []
        for w in mine:
            try:
                t0 = datetime.fromisoformat(str(w.get("placedAt")).replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(str(w.get("gameStart")).replace("Z", "+00:00"))
                leads.append((t1 - t0).total_seconds() / 3600)
            except (TypeError, ValueError):
                pass

        # Claude's picks followed
        followed = 0
        for w in mine:
            ls = w.get("legs", [])
            if len(ls) == 1 and (w.get("eventID"), ls[0].get("oddID")) in claude_singles:
                followed += 1
            elif len(ls) > 1 and any(w.get("eventID") == e and {l.get("oddID") for l in ls} == s for e, s in claude_parlays):
                followed += 1

        def leg_record(filter_fn, parlays_only=False):
            res = []
            for w in mine:
                ls = w.get("legs", [])
                if parlays_only and len(ls) < 2:
                    continue
                lr = w.get("legResults") or [None] * len(ls)
                res += [r for l, r in zip(ls, lr) if filter_fn(l) and r in ("win", "loss")]
            return f"{res.count('win')}-{res.count('loss')}" if res else None

        out[p] = {
            "settledBets": len(mine),
            "record": rec(graded),
            "net": round(sum(float(w.get("net") or 0) for w in mine), 1),
            "singles": {"count": len(singles), "record": rec([w for w in singles if w in graded])},
            "parlays": {"count": len(parlays), "record": rec([w for w in parlays if w in graded]),
                        "avgLegs": round(sum(len(w["legs"]) for w in parlays) / len(parlays), 1) if parlays else None,
                        "legsThatHit": leg_record(lambda l: True, parlays_only=True) if parlays else None},
            "stake": {"avg": round(sum(float(w.get("stake") or 0) for w in mine) / len(mine), 1) if mine else None,
                      "min": min((w.get("stake") for w in mine), default=None), "max": max((w.get("stake") for w in mine), default=None)},
            "betPrice": {"recordByBand": {b: rec(ws) for b, ws in band.items()},
                         "countByBand": {b: len(ws) for b, ws in band.items()}},
            "legTypes": {k: {"legs": n, "legRecord": leg_record(lambda l, k=k: kind_of(l) == k)} for k, n in Counter(kind_of(l) for _, l in legs).most_common()},
            "sides": {"favorites": fav, "underdogs": dog, "home": home, "away": away,
                      "favRecord": leg_record(lambda l: l.get("betType") in ("sp", "ml") and not l.get("player") and ((l.get("betType") == "sp" and l.get("line") is not None and float(l["line"]) < 0) or (l.get("betType") == "ml" and float(l.get("odds", 0)) < 0))),
                      "dogRecord": leg_record(lambda l: l.get("betType") in ("sp", "ml") and not l.get("player") and ((l.get("betType") == "sp" and l.get("line") is not None and float(l["line"]) > 0) or (l.get("betType") == "ml" and float(l.get("odds", 0)) > 0)))},
            "teamsBacked": teams_backed.most_common(5),
            "gamesBetMost": games_bet.most_common(3),
            "totals": dict(total_dirs),
            "props": {"legs": len(prop_legs), "players": prop_names.most_common(6), "stats": dict(prop_stats.most_common()),
                      "overUnder": dict(prop_dirs), "positions": dict(pos), "positionUnknown": sorted(set(unknown_pos))[:6]},
            "altLines": {"legs": len(alt), "share": round(len(alt) / len(legs), 2) if legs else 0,
                         "boughtSaferNumber": bought, "movedForPayout": sold,
                         "legRecord": leg_record(lambda l: bool(l.get("alt")))},
            "boosts": {"used": len(boosted), "byToken": dict(boost_kinds), "usedOn": dict(boost_on), "record": rec([w for w in boosted if w in graded]),
                       "avgBoostedPrice": amer(sum(dec(prices[id(w)] or -110) for w in boosted) / len(boosted)) if boosted else None},
            "timing": {"avgHoursBeforeTip": round(sum(leads) / len(leads), 1) if leads else None,
                       "within1hOfTip": sum(1 for h in leads if h < 1)},
            "followedClaudePicks": followed,
            "firstBet": mine[0].get("placedAt") if mine else None,
            "lastBet": mine[-1].get("placedAt") if mine else None,
        }
    json.dump(out, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
