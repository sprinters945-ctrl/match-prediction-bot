# Match Prediction Bot — GROUP VERSION (fully automated, CricketData.org)

Bot khud match detect karta hai, khud toss ke baad polls post karta hai,
khud match khatam hone pe winner + score fetch karke score deta hai,
aur leaderboard bhi khud post karta hai. Uses native Telegram polls
(non-anonymous — only works in a group, not a channel).

**Data source: CricketData.org** — free tier is 100 requests/day, which is
generous enough for a 10-minute check interval.

**Sirf ek manual step hai:** Man of the Match confirm karna (`/mom` command) —
free cricket APIs generally don't reliably surface this field.

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Get your CricketData.org API key

1. Sign up at **cricketdata.org** (try a private/incognito window if the
   signup form gave trouble before — check spam folder for a verification email)
2. Log in to your dashboard
3. Copy your API key

## 3. Environment variables

| Variable | What it is |
|---|---|
| `BOT_TOKEN` | From @BotFather |
| `GROUP_CHAT_ID` | Your group's chat id (negative number) |
| `ADMIN_IDS` | Comma-separated Telegram user IDs (for `/mom` command) |
| `CRICKETDATA_API_KEY` | Your CricketData.org API key (step 2) |
| `CHECK_INTERVAL_MINUTES` | (optional, default 10 — safe against a 100/day quota) |

**Finding GROUP_CHAT_ID:** add the bot to your group, send any message,
then forward that message to @userinfobot — it replies with the group's id.

## 4. Run

```bash
python bot.py
```

⚠️ Runs continuously — deploy on Railway/Render/VPS, not GitHub Actions cron.

## 5. How the automation flows

1. Every `CHECK_INTERVAL_MINUTES`, bot checks CricketData.org's `currentMatches`
2. When a match's status shows toss has happened, bot fetches the squad and
   auto-posts 3 native polls (Winner / Score range / MOM) in your group
3. When the match ends, bot auto-fetches winner + final score, scores everyone
   who predicted correctly, and posts an update — MOM scoring is held
4. You run: `/mom <match_id> <player name>` — bot scores MOM predictions and
   posts the final leaderboard automatically

**Check what's waiting on you:** `/pending`
**Check leaderboard anytime:** `/leaderboard`

## Before going live — verify the API schema

CricketData.org's exact JSON field names should be double-checked against
your dashboard/docs before the first real run. The three functions that
talk to their API are isolated at the top of `bot.py`:
- `fetch_matches()` — reads `id`, `status`, `matchType`, `matchStarted`, `teams`
- `fetch_squad()` — reads `data[].players[].name`
- `fetch_result()` — reads `matchStarted`, `matchEnded`, `matchWinner`, `score[]`

If a field name differs in your account's actual response, only these three
functions need adjusting. Test with one real match_id before trusting it
fully unattended.

## Scoring

| Correct prediction | Points |
|---|---|
| Winner | 10 (automatic) |
| Score range | 15 (automatic) |
| Man of the Match | 20 (after your `/mom` command) |

Only T20 and ODI matches get polls (Test skipped).

## Notes

- No real money involved — points/leaderboard only.
- `predictions.db` (SQLite) needs to persist across restarts — use a host
  with a persistent volume, or point `DB_PATH` at one.
- CricketData.org free tier = 100 requests/day. Raise `CHECK_INTERVAL_MINUTES`
  if you're tracking many matches and hitting the limit.
