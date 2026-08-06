# Match Prediction Bot — GROUP VERSION (fully automated, RapidAPI/Cricbuzz)

Bot khud match detect karta hai, khud toss ke baad polls post karta hai,
khud match khatam hone pe winner + score fetch karke score deta hai,
aur leaderboard bhi khud post karta hai. Uses native Telegram polls
(non-anonymous — only works in a group, not a channel).

**Data source: RapidAPI's "Cricbuzz Cricket" API** (switched from CricketData.org).

**Sirf ek manual step hai:** Man of the Match confirm karna (`/mom` command) —
free cricket APIs generally don't reliably surface this field.

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Get your RapidAPI key

1. Go to **rapidapi.com** and sign up (Google/GitHub login works)
2. Search **"Cricbuzz Cricket"** in the marketplace
3. Subscribe to the **free/Basic** plan
4. Copy your **X-RapidAPI-Key** from the dashboard

## 3. Environment variables

| Variable | What it is |
|---|---|
| `BOT_TOKEN` | From @BotFather |
| `GROUP_CHAT_ID` | Your group's chat id (negative number) |
| `ADMIN_IDS` | Comma-separated Telegram user IDs (for `/mom` command) |
| `RAPIDAPI_KEY` | Your RapidAPI key (step 2) |
| `CHECK_INTERVAL_MINUTES` | (optional, default 720 = every 12 hours / 2x a day, to stay within RapidAPI's free-tier limit of 100 requests/month) |

⚠️ **Trade-off:** with only 2x/day checks, polls won't always land ~30 min
after toss — sometimes they'll post several hours after toss (whenever the
next check happens to run), occasionally once the match has already moved
along. If you want tighter timing, either upgrade the RapidAPI plan or
switch back to a data source with a more generous free tier and lower
`CHECK_INTERVAL_MINUTES` back down (10–15 min works well against a
100-requests/day type limit).

**Finding GROUP_CHAT_ID:** add the bot to your group, send any message,
then forward that message to @userinfobot — it replies with the group's id.

## 4. Run

```bash
python bot.py
```

⚠️ Runs continuously — deploy on Railway/Render/VPS, not GitHub Actions cron.

## 5. How the automation flows

1. Every `CHECK_INTERVAL_MINUTES`, bot checks Cricbuzz's live/upcoming matches
2. When a match's status shows toss has happened, bot fetches the squad and
   auto-posts 3 native polls (Winner / Score range / MOM) in your group
3. When the match ends, bot auto-fetches winner + final score, scores everyone
   who predicted correctly, and posts an update — MOM scoring is held
4. You run: `/mom <match_id> <player name>` — bot scores MOM predictions and
   posts the final leaderboard automatically

**Check what's waiting on you:** `/pending`
**Check leaderboard anytime:** `/leaderboard`

## Before going live — verify the API schema

This is an **unofficial** API wrapping Cricbuzz's site. `fetch_matches()` and
`fetch_result()` have been verified against a real response and should work.
`fetch_squad()` is still a best-effort guess (RapidAPI's `matches/get-team`
endpoint likely has a different path/shape than assumed here) — test it via
RapidAPI's Playground with a real `matchId` before relying on it, and adjust
`fetch_squad()`'s field names to match what comes back.

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
- RapidAPI free tiers are typically rate-limited too — raise
  `CHECK_INTERVAL_MINUTES` if you hit limits with many matches tracked.
