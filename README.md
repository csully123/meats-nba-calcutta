# Meats NBA Calcutta

The Meats Sportsbook: a points sportsbook for four friends, served from GitHub Pages with wagers in Firebase Firestore. The original against-the-spread picks board is retired; the site root now redirects to `book/`.

- `index.html`: redirect to the sportsbook.
- `firebase-config.js`: the Firebase web config (public by design; Firestore rules control access).
- `data/games.json`: every game that counts, with spreads, scores and status. Updated every 30 minutes by the GitHub Action in `.github/workflows/update.yml` running `scripts/update.py`.
- `data/writeups.json`: per-game matchup notes, injury breakdowns and Claude's pick, keyed by ESPN game id.
- `data/config.json`: scoring rules, season dates and bonus games.

Scoring: everyone starts at 30. A regular pick is +1 on a cover and 0 on a miss; a pick marked as a Lock is +2 on a cover and -1 on a miss; each person's one Mega Bonus per season is +5 on a cover and 0 on a miss. Bonus games double the cover payout on regular picks and locks. Pushes are 0. Up to 5 picks per week (Monday to Sunday), no minimum. Picks lock at tip-off and are graded on the spread at the time of the pick.

## Sportsbook (`/book/`)

A second page at `book/index.html` runs the points sportsbook from opening night through the NBA Finals: 200-point stacks, real FanDuel lines from SportsGameOdds (`scripts/odds.py`, scheduled in `.github/workflows/odds.yml`: morning, midday, pre-tip windows, and overnight results), straights and same-game parlays, whole-point stakes with payouts rounded to the nearest point, a 25% max bet that lifts to all-in at 20 points or under, 20 points a week minimum, bust reloads with an escalating end-of-season penalty, and a foul-out at six busts (out of the competition). Wagers live in the Firestore `wagers` collection and are graded by `scripts/grade.py` from the box scores the feed returns. `book/engine.js` holds the odds, bankroll and token math shared by the page.

Guardrails: 25% of bankroll per bet, 25% per line and 50% per game across open bets (all lifted at 20 points or under); parlays at most 4 legs with conflicting, overlapping or closely related legs refused; profit rounds down; bets cancellable for 10 minutes; `createdAt` is a Firestore server timestamp and the grader voids any bet stamped after tip-off or priced at a number the feed never offered (`scripts/odds.py` keeps every offered price per market under `seen`).

Boost tokens (profit multipliers on the first 20 points of stake, one per bet, chosen on the slip at placement) are defined in `CFG.tokens` in `book/index.html`: a 1.5x token every week, 1.5x for the Cup final, 1.5x for one Christmas Day game, 1.5x per first-round series, 2x per second-round series, 2.5x per conference finals series, 3x for the Finals, and one 5x Mega Bonus per season. Windows come from the `stage` and `series` fields `scripts/update.py` writes into `data/games.json` (ESPN season type and competition type: play-in, RD16, QTR, SEMI, FINAL, CC). A token is spent by any open, won or lost bet carrying it and returned by a push or void. A winning Mega Bonus bet shows a fireworks screen the next time that player opens the book.

Regular-season prize (25 points and an extra 3x Finals token for first, an extra 2x second-round token for second): when the regular season ends, set `CFG.prizes.first` and `CFG.prizes.second` to the player names and add `{player, points: 25, at: <ISO time>, note}` to `CFG.adjustments` in `book/index.html`.

`data/book-insights.json` holds the sportsbook's morning "Game insights": `games` (keyed by the odds feed's eventID: a short game report plus the injury list) and `days` (keyed by New York date: Claude's best single and best parlay across the whole slate). A scheduled Claude task writes it once each morning; the page shows the day's best bets under the day header with Add-to-slip and Go-to-game buttons. The picks board (`index.html`, `data/writeups.json`) is retired and no longer updated.

The picks board ignores play-in and playoff games (`stage` other than regular, cup, cupfinal); the sportsbook shows them.
