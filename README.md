# Meats NBA Calcutta

A season-long NBA against-the-spread picks pool for four friends. Static site on GitHub Pages, picks stored in Firebase Firestore, lines and scores from ESPN's public scoreboard feed.

- `index.html`: the whole site.
- `firebase-config.js`: the Firebase web config (public by design; Firestore rules control access).
- `data/games.json`: every game that counts, with spreads, scores and status. Updated every 30 minutes by the GitHub Action in `.github/workflows/update.yml` running `scripts/update.py`.
- `data/writeups.json`: per-game matchup notes, injury breakdowns and Claude's pick, keyed by ESPN game id.
- `data/config.json`: scoring rules, season dates and bonus games.

Scoring: everyone starts at 30, +2 for a cover (x2 on bonus games), -1 for a miss, 0 for a push. At least 3 picks per week (Monday to Sunday), no maximum. Picks lock at tip-off and are graded on the spread at the time of the pick.
