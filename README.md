# Match Prediction Bot — FULLY AUTOMATED (starting se ending tak)

Bot khud match detect karta hai, khud toss ke baad polls post karta hai,
khud match khatam hone pe winner + score fetch karke score deta hai,
aur leaderboard bhi khud post karta hai.

**Sirf ek manual step hai:** Man of the Match confirm karna (`/mom` command) —
CricketData.org ka free tier ye field reliably nahi deta, isliye admin ek
single command se confirm karta hai, uske baad sab automatic ho jaata hai.

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Environment variables

| Variable | What it is |
|---|---|
| `BOT_TOKEN` | From @BotFather |
| `GROUP_CHAT_ID` | Group/channel chat id |
| `ADMIN_IDS` | Comma-separated Telegram user IDs (for `/mom` command) |
| `CRICKETDATA_API_KEY` | Your CricketData.org API key |
| `CHECK_INTERVAL_MINUTES` | (optional, default 10) how often bot checks for new/ended matches |

## 3. Run

```bash
python bot.py
```

⚠️ Runs continuously — deploy on Railway/Render/VPS, not GitHub Actions cron.

## 4. How the automation flows

1. Every `CHECK_INTERVAL_MINUTES`, bot checks CricketData.org's `currentMatches`
2. When a match's status shows toss has happened, bot fetches the squad and
   auto-posts 3 polls (Winner / Score range / MOM) in your group
3. When the match ends, bot auto-fetches winner + final score, scores everyone
   who predicted correctly, and posts an update — **MOM scoring is held**
4. You run: `/mom <match_id> <player name>` — bot scores MOM predictions and
   posts the final leaderboard automatically

**Check what's waiting on you:** `/pending`
**Check leaderboard anytime:** `/leaderboard`

## Before going live — verify the API schema

CricketData.org's exact JSON field names should be double-checked against
your dashboard/docs before the first real run — the three functions that
talk to their API are isolated at the top of `bot.py`:

- `fetch_matches()` — reads `id`, `status`, `matchType`, `teams`
- `fetch_squad()` — reads `data[].players[].name`
- `fetch_result()` — reads `matchStarted`, `matchEnded`, `matchWinner`, `score[]`

If any field name differs in your account's actual response, only these three
functions need adjusting — the polling/scoring/leaderboard logic stays the same.
Test with one real match_id first before trusting it fully unattended.

## Scoring

| Correct prediction | Points |
|---|---|
| Winner | 10 (automatic) |
| Score range | 15 (automatic) |
| Man of the Match | 20 (after your `/mom` command) |

Test matches are skipped automatically (score-range prediction doesn't fit
a single-innings format well) — only T20 and ODI matches get polls.

## Notes

- No real money involved — points/leaderboard only, keeps this clear of
  betting/gambling regulations.
- `predictions.db` (SQLite) needs to persist across restarts — use a host
  with a persistent volume, or point `DB_PATH` at one.
- CricketData.org free tier = 100 hits/day. Each cycle uses ~1 hit for
  `currentMatches`, plus 1 for squad and 1 for result per match. Adjust
  `CHECK_INTERVAL_MINUTES` upward if you're tracking many matches and hitting
  the limit.
