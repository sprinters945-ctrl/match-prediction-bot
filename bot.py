"""
Sanju Baba - Match Prediction / Fantasy Poll Bot (GROUP VERSION - FULLY AUTOMATED)
--------------------------------------------------------------------------------------
Starting se ending tak automated:
  1. Har few minutes me CricketData.org se live/upcoming matches check karta hai
  2. Jab toss ho jaata hai (status me "Toss" aata hai) -> squad fetch karke
     3 native polls auto-post karta hai (Winner / Score range / MOM) in the group
  3. Jab match "Match ended" ho jaata hai -> winner + score API se auto-fetch
     karke un dono ka scoring kar deta hai automatically
  4. MOM sirf ek cheez hai jo free API reliably nahi deta -> admin ek single
     command se confirm karega: /mom <match_id> <player name>
     Uske turant baad MOM scoring + final leaderboard bhi auto-post ho jaata hai

Uses NATIVE Telegram polls (non-anonymous) - this only works in a GROUP.
Telegram channels only allow anonymous polls, so if you switch to a channel
later, use the button-based version instead (per-user vote tracking needs
either a non-anonymous poll or inline buttons).

DATA SOURCE: CricketData.org (free tier: 100 requests/day - reasonable for
this automation). Sign up at cricketdata.org, grab your API key from the
dashboard, and set it as CRICKETDATA_API_KEY.

Deploy: hamesha-on host chahiye (Railway/Render/VPS). GitHub Actions cron
is NOT suitable - ye bot continuously polls dono Telegram aur CricketData.org.
"""

import os
import logging
import sqlite3
from datetime import datetime, timedelta

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("group-prediction-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROUP_CHAT_ID = int(os.environ["GROUP_CHAT_ID"])
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
CRICKETDATA_API_KEY = os.environ["CRICKETDATA_API_KEY"]

DB_PATH = os.environ.get("DB_PATH", "predictions.db")
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "10"))  # CricketData.org free tier = 100/day, 10 min is safe

POINTS_WINNER = 10
POINTS_SCORE = 15
POINTS_MOM = 20

CRICKETDATA_BASE = "https://api.cricapi.com/v1"

SCORE_BUCKETS = {
    "t20": [140, 160, 180, 200],
    "odi": [220, 260, 300],
}

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cd_match_id TEXT UNIQUE,
            team_a TEXT, team_b TEXT,
            match_type TEXT,
            score_buckets TEXT,
            mom_players TEXT,
            winner_poll_id TEXT,
            score_poll_id TEXT,
            mom_poll_id TEXT,
            polls_posted INTEGER DEFAULT 0,
            resolved INTEGER DEFAULT 0,
            mom_pending INTEGER DEFAULT 0,
            actual_winner TEXT,
            actual_score_bucket TEXT,
            actual_mom TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS poll_votes (
            poll_id TEXT,
            user_id INTEGER,
            username TEXT,
            option_text TEXT,
            PRIMARY KEY (poll_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER,
            username TEXT,
            match_id INTEGER,
            points INTEGER,
            created_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def make_buckets(thresholds):
    nums = sorted(int(x) for x in thresholds)
    buckets = [f"<{nums[0]}"]
    for i in range(len(nums) - 1):
        buckets.append(f"{nums[i]}-{nums[i+1]}")
    buckets.append(f"{nums[-1]}+")
    return buckets


def bucket_for_score(thresholds, actual_score):
    nums = sorted(int(x) for x in thresholds)
    buckets = make_buckets(nums)
    for i, n in enumerate(nums):
        if actual_score < n:
            return buckets[i]
    return buckets[-1]


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ---------------------------------------------------------------------------
# CricketData.org calls
# ---------------------------------------------------------------------------

async def fetch_matches(client: httpx.AsyncClient):
    """
    Uses /matches (not /currentMatches) since /currentMatches only returns
    matches that have already started - /matches also includes upcoming
    (not-yet-started) matches, which we need to catch the moment toss happens.
    """
    r = await client.get(
        f"{CRICKETDATA_BASE}/matches",
        params={"apikey": CRICKETDATA_API_KEY, "offset": 0},
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    matches = []
    for m in data:
        teams = m.get("teams") or []
        if len(teams) != 2:
            continue
        matches.append({
            "id": m.get("id"),
            "status": (m.get("status") or "").lower(),
            "matchType": (m.get("matchType") or "").lower(),
            "matchStarted": bool(m.get("matchStarted")),
            "teams": teams,
        })
    return matches


async def fetch_squad(client: httpx.AsyncClient, cd_match_id: str):
    r = await client.get(
        f"{CRICKETDATA_BASE}/match_squad",
        params={"apikey": CRICKETDATA_API_KEY, "id": cd_match_id},
    )
    r.raise_for_status()
    raw = r.json()
    data = raw.get("data", [])
    players = []
    for team in data:
        for p in team.get("players", []):
            players.append(p.get("name"))
    if len(players) < 2:
        # DEBUG: log the raw response so we can see the actual field names
        log.warning(f"fetch_squad got too few players for match {cd_match_id}. Raw response: {raw}")
    return players[:10] if players else []  # Telegram poll option limit is 10


async def fetch_result(client: httpx.AsyncClient, cd_match_id: str):
    r = await client.get(
        f"{CRICKETDATA_BASE}/match_info",
        params={"apikey": CRICKETDATA_API_KEY, "id": cd_match_id},
    )
    r.raise_for_status()
    info = r.json().get("data", {})
    if info.get("matchStarted") and info.get("matchEnded"):
        winner = info.get("matchWinner")
        top_score = 0
        for s in info.get("score", []):
            if winner and winner in s.get("inning", ""):
                top_score = max(top_score, s.get("r", 0))
        return winner, top_score
    return None


# ---------------------------------------------------------------------------
# Core automation job - runs every CHECK_INTERVAL_MINUTES
# ---------------------------------------------------------------------------

async def poll_cycle(context: ContextTypes.DEFAULT_TYPE):
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            live_matches = await fetch_matches(client)
        except Exception as e:
            log.error(f"fetch_matches failed: {e}")
            return

        conn = db()

        log.info(f"poll_cycle: fetched {len(live_matches)} matches")

        for m in live_matches:
            cd_id = m.get("id")
            status = (m.get("status") or "").lower()
            match_type = (m.get("matchType") or "").lower()
            teams = m.get("teams") or []
            if len(teams) != 2:
                log.info(f"skip {cd_id}: doesn't have exactly 2 teams ({teams})")
                continue
            team_a, team_b = teams

            existing = conn.execute(
                "SELECT * FROM matches WHERE cd_match_id=?", (cd_id,)
            ).fetchone()

            toss_done = "toss" in status or "elected" in status or m.get("matchStarted")
            log.info(
                f"match {cd_id} ({team_a} vs {team_b}): status='{status}' "
                f"matchType='{match_type}' matchStarted={m.get('matchStarted')} "
                f"toss_done={toss_done} existing={bool(existing)} "
                f"eligible_format={match_type in SCORE_BUCKETS}"
            )
            if not existing and toss_done and match_type in SCORE_BUCKETS:
                try:
                    players = await fetch_squad(client, cd_id)
                except Exception as e:
                    log.error(f"fetch_squad failed for {cd_id}: {e}")
                    players = []
                if len(players) < 2:
                    continue

                thresholds = SCORE_BUCKETS[match_type]
                buckets = make_buckets(thresholds)

                cur = conn.execute(
                    "INSERT INTO matches (cd_match_id, team_a, team_b, match_type, score_buckets, mom_players, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (cd_id, team_a, team_b, match_type, ",".join(str(t) for t in thresholds),
                     ",".join(players), datetime.utcnow().isoformat()),
                )
                match_id = cur.lastrowid
                conn.commit()

                winner_poll = await context.bot.send_poll(
                    chat_id=GROUP_CHAT_ID,
                    question=f"[Match #{match_id}] {team_a} vs {team_b} - Winner kaun banega?",
                    options=[team_a, team_b],
                    is_anonymous=False,
                )
                score_poll = await context.bot.send_poll(
                    chat_id=GROUP_CHAT_ID,
                    question=f"[Match #{match_id}] {team_a} vs {team_b} - Winning team ka score?",
                    options=buckets,
                    is_anonymous=False,
                )
                mom_poll = await context.bot.send_poll(
                    chat_id=GROUP_CHAT_ID,
                    question=f"[Match #{match_id}] {team_a} vs {team_b} - Man of the Match?",
                    options=players,
                    is_anonymous=False,
                )
                conn.execute(
                    "UPDATE matches SET winner_poll_id=?, score_poll_id=?, mom_poll_id=?, polls_posted=1 WHERE match_id=?",
                    (winner_poll.poll.id, score_poll.poll.id, mom_poll.poll.id, match_id),
                )
                conn.commit()
                log.info(f"Posted polls for match #{match_id} ({team_a} vs {team_b})")
                continue

            if existing and existing["polls_posted"] and not existing["resolved"]:
                try:
                    result = await fetch_result(client, cd_id)
                except Exception as e:
                    log.error(f"fetch_result failed for {cd_id}: {e}")
                    result = None
                if result:
                    winner, score = result
                    score_bucket = bucket_for_score(existing["score_buckets"].split(","), score)
                    await score_and_report(context, conn, existing, winner, score_bucket)

        conn.close()


async def score_and_report(context, conn, match_row, winner, score_bucket):
    match_id = match_row["match_id"]

    def add_points(poll_id, correct_answer, points, tally):
        votes = conn.execute(
            "SELECT user_id, username, option_text FROM poll_votes WHERE poll_id=?", (poll_id,)
        ).fetchall()
        for v in votes:
            if v["option_text"] == correct_answer:
                entry = tally.setdefault(v["user_id"], [v["username"], 0])
                entry[1] += points

    tally = {}
    add_points(match_row["winner_poll_id"], winner, POINTS_WINNER, tally)
    add_points(match_row["score_poll_id"], score_bucket, POINTS_SCORE, tally)

    now = datetime.utcnow().isoformat()
    for user_id, (username, points) in tally.items():
        conn.execute(
            "INSERT INTO scores (user_id, username, match_id, points, created_at) VALUES (?,?,?,?,?)",
            (user_id, username, match_id, points, now),
        )
    conn.execute(
        "UPDATE matches SET actual_winner=?, actual_score_bucket=?, mom_pending=1 WHERE match_id=?",
        (winner, score_bucket, match_id),
    )
    conn.commit()

    lines = [
        f"Match #{match_id} RESULT: {match_row['team_a']} vs {match_row['team_b']}",
        f"Winner: {winner} | Score: {score_bucket}",
        "",
        "Winner + Score ke points de diye gaye. MOM points admin ke /mom command ke baad add honge.",
    ]
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="\n".join(lines))


# ---------------------------------------------------------------------------
# Manual fallback: MOM only (everything else is automatic)
# ---------------------------------------------------------------------------

async def mom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Sirf admin MOM confirm kar sakta hai.")
        return
    try:
        match_id = int(context.args[0])
        mom_player = " ".join(context.args[1:])
    except (IndexError, ValueError):
        await update.message.reply_text("Use: /mom <match_id> <player name>")
        return

    conn = db()
    match_row = conn.execute("SELECT * FROM matches WHERE match_id=?", (match_id,)).fetchone()
    if not match_row or not match_row["mom_pending"]:
        await update.message.reply_text("Ye match MOM ke liye ready nahi hai (ya already resolved).")
        conn.close()
        return

    votes = conn.execute(
        "SELECT user_id, username, option_text FROM poll_votes WHERE poll_id=?",
        (match_row["mom_poll_id"],),
    ).fetchall()
    now = datetime.utcnow().isoformat()
    for v in votes:
        if v["option_text"] == mom_player:
            conn.execute(
                "INSERT INTO scores (user_id, username, match_id, points, created_at) VALUES (?,?,?,?,?)",
                (v["user_id"], v["username"], match_id, POINTS_MOM, now),
            )
    conn.execute(
        "UPDATE matches SET actual_mom=?, mom_pending=0, resolved=1 WHERE match_id=?",
        (mom_player, match_id),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(f"MOM confirmed: {mom_player}. Final leaderboard bhej raha hoon.")
    await send_leaderboard(context)


async def send_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    all_time = conn.execute(
        "SELECT username, SUM(points) as total FROM scores GROUP BY user_id ORDER BY total DESC LIMIT 10"
    ).fetchall()
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    weekly = conn.execute(
        "SELECT username, SUM(points) as total FROM scores WHERE created_at >= ? GROUP BY user_id ORDER BY total DESC LIMIT 10",
        (week_ago,),
    ).fetchall()
    conn.close()

    lines = ["LEADERBOARD", "", "This Week:"]
    lines += [f"  {i}. @{r['username']} - {r['total']} pts" for i, r in enumerate(weekly, 1)] or ["  Abhi koi points nahi."]
    lines.append("")
    lines.append("All-Time:")
    lines += [f"  {i}. @{r['username']} - {r['total']} pts" for i, r in enumerate(all_time, 1)] or ["  Abhi koi points nahi."]

    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="\n".join(lines))


async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_leaderboard(context)


async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    rows = conn.execute(
        "SELECT match_id, team_a, team_b FROM matches WHERE mom_pending=1"
    ).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Koi match MOM ke wait me nahi hai.")
        return
    lines = ["MOM pending for:"]
    for r in rows:
        lines.append(f"  #{r['match_id']}: {r['team_a']} vs {r['team_b']} -> /mom {r['match_id']} <player>")
    await update.message.reply_text("\n".join(lines))


async def poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    if not ans.option_ids:
        return

    conn = db()
    row = conn.execute(
        "SELECT match_id, team_a, team_b, score_buckets, mom_players, "
        "winner_poll_id, score_poll_id, mom_poll_id FROM matches "
        "WHERE winner_poll_id=? OR score_poll_id=? OR mom_poll_id=?",
        (ans.poll_id, ans.poll_id, ans.poll_id),
    ).fetchone()
    if not row:
        conn.close()
        return

    if ans.poll_id == row["winner_poll_id"]:
        options = [row["team_a"], row["team_b"]]
    elif ans.poll_id == row["score_poll_id"]:
        options = make_buckets(row["score_buckets"].split(","))
    else:
        options = row["mom_players"].split(",")

    chosen = options[ans.option_ids[0]]
    username = ans.user.username or ans.user.first_name

    conn.execute(
        "INSERT OR REPLACE INTO poll_votes (poll_id, user_id, username, option_text) VALUES (?,?,?,?)",
        (ans.poll_id, ans.user.id, username, chosen),
    )
    conn.commit()
    conn.close()


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("mom", mom_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(PollAnswerHandler(poll_answer))

    app.job_queue.run_repeating(poll_cycle, interval=CHECK_INTERVAL_MINUTES * 60, first=10)

    log.info("Group bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
