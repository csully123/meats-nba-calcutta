# Meats NBA Calcutta

A season-long NBA against-the-spread picks pool for four friends. Static site on GitHub Pages, picks stored in Firebase Firestore, lines and scores from ESPN's public scoreboard feed.

- `index.html`: the whole site.
- `firebase-config.js`: the Firebase web config (public by design; Firestore rules control access).
- `data/games.json`: every game that counts, with spreads, scores and status. Updated every 30 minutes by the GitHub Action in `.github/workflows/update.yml` running `scripts/update.py`.
- `data/writeups.json`: per-game matchup notes, injury breakdowns and Claude's pick, keyed by ESPN game id.
- `data/config.json`: scoring rules, season dates and bonus games.

Scoring: everyone starts at 30. A regular pick is +1 on a cover and 0 on a miss; a pick marked as a Lock is +2 on a cover and -1 on a miss; each person's one Mega Bonus per season is +5 on a cover and 0 on a miss. Bonus games double the cover payout on regular picks and locks. Pushes are 0. Up to 5 picks per week (Monday to Sunday), no minimum. Picks lock at tip-off and are graded on the spread at the time of the pick.

## Sportsbook (`/book/`)

A second page at `book/index.html` runs the points sportsbook from opening night through the NBA Finals: 200-point stacks, real FanDuel lines from SportsGameOdds (`scripts/odds.py`, scheduled in `.github/workflows/odds.yml`: morning, midday, pre-tip windows, and overnight results), straights and same-game parlays, whole-point stakes with payouts rounded to the nearest point, a 25% max bet that lifts to all-in at 20 points or under, 20 points a week minimum, bust reloads with an escalating end-of-season penalty, and a foul-out at six busts (out of the competition). Wagers live in the Firestore `wagers` collection and are graded by `scripts/grade.py` from the box scores the feed returns. `book/engine.js` holds the odds, bankroll and token math shared by the page.

Boost tokens (profit multipliers, one per bet, chosen on the slip at placement) are defined in `CFG.tokens` in `book/index.html`: a 1.5x token every week, 1.5x for the Cup final, 1.5x per first-round series, 2x per second-round series, 2.5x per conference finals series, 3x for the Finals, and one 5x Mega Bonus per season. Windows come from the `stage` and `series` fields `scripts/update.py` writes into `data/games.json` (ESPN season type and competition type: play-in, RD16, QTR, SEMI, FINAL, CC). A token is spent by any open, won or lost bet carrying it and returned by a push or void. A winning Mega Bonus bet shows a fireworks screen the next time that player opens the book.

Regular-season prize (50 points and an extra 3x Finals token for first, an extra 2x second-round token for second): when the regular season ends, set `CFG.prizes.first` and `CFG.prizes.second` to the player names and add `{player, points: 50, at: <ISO time>, note}` to `CFG.adjustments` in `book/index.html`.

`data/book-insights.json` holds the sportsbook's morning "Game insights" (injuries, Claude's top single and top parlay per game, keyed by the odds feed's eventID), written once per game by the same scheduled Claude task that writes `data/writeups.json`; the page offers an Add-to-slip button for each at the current numbers.

The picks board ignores play-in and playoff games (`stage` other than regular, cup, cupfinal); the sportsbook shows them.
