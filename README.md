# Meats NBA Calcutta

A season-long NBA against-the-spread picks pool for four friends. Static site on GitHub Pages, picks stored in Firebase Firestore, lines and scores from ESPN's public scoreboard feed.

- `index.html`: the whole site.
- `firebase-config.js`: the Firebase web config (public by design; Firestore rules control access).
- `data/games.json`: every game that counts, with spreads, scores and status. Updated every 30 minutes by the GitHub Action in `.github/workflows/update.yml` running `scripts/update.py`.
- `data/writeups.json`: per-game matchup notes, injury breakdowns and Claude's pick, keyed by ESPN game id.
- `data/config.json`: scoring rules, season dates and bonus games.

Scoring: everyone starts at 30. A regular pick is +1 on a cover and 0 on a miss; a pick marked as a Lock is +2 on a cover and -1 on a miss; each person's one Mega Bonus per season is +5 on a cover and 0 on a miss. Bonus games double the cover payout on regular picks and locks. Pushes are 0. Up to 5 picks per week (Monday to Sunday), no minimum. Picks lock at tip-off and are graded on the spread at the time of the pick.

## Sportsbook (`/book/`)

A second page at `book/index.html` runs the points sportsbook: 100-point stacks, real FanDuel lines from SportsGameOdds (`scripts/odds.py`, scheduled in `.github/workflows/odds.yml`: morning, midday, pre-tip windows, and overnight results), straights and same-game parlays, a 25% max bet, 20 points a week minimum, and bust reloads with a proportional end-of-season penalty. Wagers live in the Firestore `wagers` collection and are graded by `scripts/grade.py` from the box scores the feed returns. `book/engine.js` holds the odds and bankroll math shared by the page.
