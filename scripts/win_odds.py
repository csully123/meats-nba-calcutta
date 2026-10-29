#!/usr/bin/env python3
"""Claude's chance-to-win model for the Meats Sportsbook leaderboard.

Replays every wager in the nightly backup to get each player's bankroll and busts today (open bets count as
pending stakes only; their contents are never used), then simulates the rest of the season many times. Each
simulated player keeps betting the way they actually have: their own mix of prices and parlay sizes, their own
stake size relative to their bankroll and their own volume, paying the book's hold on every leg, with the weekly
1.5x token on the first 20 points of one bet a week, the 25% per-bet cap, the 20-point weekly minimum, bust
reloads and the end-of-season bust penalty. Early in the season, when a player has few settled bets, their
style is blended toward the group's average so one lucky night does not dominate.

Prints JSON {player: percent, ...} plus a few diagnostics. Read-only.
"""
import json
import math
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYERS = ["Kev", "Beekie", "Mio", "Sulliver"]
START, RELOAD = 200.0, 100.0
PEN = [0, .10, .25, .45, .70, .90]
FOUL_OUT = 6
HOLD = 0.045
SEASON_END = date(2027, 6, 20)  # roughly the end of the NBA Finals
SIMS = 4000


def dec(a):
    a = float(a)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def bankroll(player, wagers):
    """Same replay as the page's engine: stakes leave at placement, settle back at settlement, bust at zero with nothing pending."""
    mine = [w for w in wagers if w.get("player") == player]
    tl = []
    for w in mine:
        tl.append((w.get("placedAt") or "", 0, w))
        if w.get("status") not in (None, "open") and w.get("settledAt"):
            tl.append((w["settledAt"], 1, w))
    tl.sort(key=lambda x: (x[0], x[1]))
    stack, pending, busts = START, 0.0, 0
    for _, kind, w in tl:
        s = float(w.get("stake") or 0)
        if kind == 0:
            stack -= s
            pending += s
        else:
            pending -= s
            st = w.get("status")
            if st == "win":
                stack += s + float(w.get("net") or 0)
            elif st in ("push", "void"):
                stack += s
            if stack <= 0.005 and pending <= 0.005:
                busts += 1
                stack = RELOAD
    return stack, pending, busts


def style(player, wagers, weeks_active):
    settled = [w for w in wagers if w.get("player") == player and w.get("status") in ("win", "loss", "push")]
    bets = [w for w in wagers if w.get("player") == player]
    shapes = []
    for w in settled:
        legs = w.get("legs") or []
        d = 1.0
        for l in legs:
            d *= dec(l.get("odds", -110))
        shapes.append((d, max(1, len(legs))))
    stake_frac = [min(.25, float(w.get("stake") or 0) / START) for w in bets] or [0.05]
    per_week = len(bets) / max(1.0, weeks_active)
    return {"shapes": shapes, "stakeFrac": sum(stake_frac) / len(stake_frac), "perWeek": per_week, "n": len(settled)}


def main():
    wagers = list(json.loads((ROOT / "data" / "backups" / "wagers-latest.json").read_text()).get("wagers", {}).values())
    today = datetime.now(timezone.utc).date()
    first = min((w.get("placedAt", "")[:10] for w in wagers if w.get("placedAt")), default=str(today))
    weeks_active = max(1.0, (today - date.fromisoformat(first)).days / 7)
    weeks_left = max(0, (SEASON_END - today).days // 7)

    now = {p: bankroll(p, wagers) for p in PLAYERS}
    st = {p: style(p, wagers, weeks_active) for p in PLAYERS}
    pool = [s for p in PLAYERS for s in st[p]["shapes"]] or [(1.91, 1)]
    avg_frac = sum(st[p]["stakeFrac"] for p in PLAYERS) / len(PLAYERS)
    avg_vol = max(2.0, sum(st[p]["perWeek"] for p in PLAYERS) / len(PLAYERS))

    rng = random.Random(20261028)
    wins = {p: 0.0 for p in PLAYERS}
    finals = {p: [] for p in PLAYERS}
    for _ in range(SIMS):
        res = {}
        for p in PLAYERS:
            stack, pending, busts = now[p]
            stack += pending  # open bets: treat as returning their stake on average, close enough for a season-long view
            s = st[p]
            k = min(1.0, s["n"] / 20)  # trust their own style more as their sample grows
            frac = k * s["stakeFrac"] + (1 - k) * avg_frac
            vol = k * max(1.0, s["perWeek"]) + (1 - k) * avg_vol
            own = s["shapes"] or pool
            for _w in range(weeks_left):
                if busts >= FOUL_OUT:
                    break
                n = max(1, int(vol) + (1 if rng.random() < vol - int(vol) else 0))
                wagered = 0.0
                for i in range(n):
                    if stack < 1:
                        break
                    d, legs = rng.choice(own if rng.random() < k else pool)
                    cap = stack if stack + 0 <= 20 else math.floor(stack * 25) / 100
                    stake = max(1.0, min(cap, round(stack * frac)))
                    if i == n - 1 and wagered + stake < 20:
                        stake = max(stake, min(cap, 20 - wagered))
                    wagered += stake
                    p_win = (1 / d) * (1 - HOLD) ** legs
                    stack -= stake
                    if rng.random() < p_win:
                        boosted = min(stake, 20) if i == 0 else 0  # weekly 1.5x on the first bet
                        stack += stake + math.floor((stake * (d - 1) + boosted * (d - 1) * 0.5) * 100) / 100
                    if stack < 1:
                        busts += 1
                        stack = RELOAD
            if busts >= FOUL_OUT:
                res[p] = None
            else:
                cut = max(stack * PEN[min(busts, 5)], 20 * busts) if busts else 0
                res[p] = max(0.0, stack - cut)
            finals[p].append(res[p] or 0)
        alive = {p: v for p, v in res.items() if v is not None}
        if alive:
            top = max(alive.values())
            leaders = [p for p, v in alive.items() if v == top]
            for p in leaders:
                wins[p] += 1 / len(leaders)
    pct = {p: round(100 * wins[p] / SIMS) for p in PLAYERS}
    # keep the four summing to 100 after rounding
    diff = 100 - sum(pct.values())
    if diff:
        lead = max(PLAYERS, key=lambda p: wins[p])
        pct[lead] += diff
    out = {"odds": pct, "weeksLeft": weeks_left,
           "now": {p: {"stack": round(now[p][0], 1), "pending": round(now[p][1], 1), "busts": now[p][2]} for p in PLAYERS},
           "medianFinal": {p: round(sorted(finals[p])[len(finals[p]) // 2]) for p in PLAYERS}}
    json.dump(out, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
