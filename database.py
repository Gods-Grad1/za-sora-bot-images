import os
import json
import time
import csv
import datetime
import requests
import config
from collections import defaultdict

CSV_DATA_CACHE = {}

# ---------------------------------------------------------------------------
# CORE UTILITIES
# ---------------------------------------------------------------------------

def log_error_to_admin(bot, context, exception):
    error_msg = f"⚠️ *BOT ERROR*\n📌 Context: {context}\n💥 `{str(exception)}`"
    print(error_msg)
    try:
        bot.send_message(config.ADMIN_ID, error_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Failed to alert admin: {e}")

def load_json(filepath, default_value):
    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            json.dump(default_value, f, indent=4)
    with open(filepath, "r") as f:
        return json.load(f)

def save_json(bot, filepath, data):
    tmp_file = filepath + ".tmp"
    try:
        with open(tmp_file, "w") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp_file, filepath)
    except Exception as e:
        log_error_to_admin(bot, "Atomic Save Fault", e)

def fetch_csv_cached(bot, url, duration=300):
    now = time.time()
    if url in CSV_DATA_CACHE:
        timestamp, data = CSV_DATA_CACHE[url]
        if now - timestamp < duration:
            return data
    try:
        response = requests.get(url, timeout=10, proxies={})
        response.encoding = 'utf-8'
        lines = response.text.splitlines()
        rows = list(csv.reader(lines))
        CSV_DATA_CACHE[url] = (now, rows)
        return rows
    except Exception as e:
        log_error_to_admin(bot, "CSV Fetch Error", e)
        if url in CSV_DATA_CACHE:
            return CSV_DATA_CACHE[url][1]
        return []

# ---------------------------------------------------------------------------
# DATA MIGRATION: GROUP → GLOBAL
# ---------------------------------------------------------------------------

def migrate_group_to_global(bot):
    """Migrates all user data from group_data.json to user_data.json (global).
    This runs once on startup and is skipped if already done."""
    flag_file = config.MIGRATION_FLAG
    if os.path.exists(flag_file):
        print("✅ Migration already done. Skipping.")
        return

    print("🔄 Starting migration from group_data.json to user_data.json...")
    group_data = load_json(config.GROUP_DATA_FILE, {})
    user_data = load_json(config.USER_DATA_FILE, {})

    # Track which groups exist
    groups_set = set()

    for chat_str, users in group_data.items():
        chat_id = int(chat_str)
        groups_set.add(chat_id)
        for user_str, u in users.items():
            user_id = int(user_str)
            if user_id not in user_data:
                user_data[user_id] = {
                    "username": u.get("username", "Player"),
                    "points": 0,
                    "monthly_points": {},
                    "yearly_points": {},
                    "alltime_points": 0,
                    "streak": 0,
                    "best_streak": 0,
                    "games_played": 0,
                    "correct": 0,
                    "title": None,
                    "title_expires": None,
                    "hint_tokens": 0,
                    "double_xp_until": None,
                    "last_spin": 0,
                    "badges": [],
                    "trivia_correct": 0,
                    "versus_wins": 0,
                    "daily_wins": 0,
                    "powerups": {},
                }
            # Merge data
            for key in ["points", "alltime_points", "streak", "best_streak", "games_played", "correct", "trivia_correct", "versus_wins", "daily_wins", "hint_tokens"]:
                if u.get(key, 0) > user_data[user_id].get(key, 0):
                    user_data[user_id][key] = u.get(key, 0)
            # Merge monthly_points
            for month, pts in u.get("monthly_points", {}).items():
                user_data[user_id]["monthly_points"][month] = user_data[user_id]["monthly_points"].get(month, 0) + pts
            # Merge yearly_points
            for year, pts in u.get("yearly_points", {}).items():
                user_data[user_id]["yearly_points"][year] = user_data[user_id]["yearly_points"].get(year, 0) + pts
            # Merge badges
            for badge in u.get("badges", []):
                if badge not in user_data[user_id]["badges"]:
                    user_data[user_id]["badges"].append(badge)
            # Merge powerups
            for pu_id, count in u.get("powerups", {}).items():
                user_data[user_id]["powerups"][pu_id] = user_data[user_id]["powerups"].get(pu_id, 0) + count
            # Title – keep the latest active title if user has one
            if u.get("title") and not user_data[user_id].get("title"):
                user_data[user_id]["title"] = u.get("title")
                user_data[user_id]["title_expires"] = u.get("title_expires")

    # Save global user data
    save_json(bot, config.USER_DATA_FILE, user_data)

    # Update group_data to only store groups (not user data)
    groups_only = {str(g): {} for g in groups_set}
    save_json(bot, config.GROUP_DATA_FILE, groups_only)

    # Mark migration as done
    with open(flag_file, "w") as f:
        f.write(datetime.datetime.now().isoformat())

    print(f"✅ Migration complete! {len(user_data)} users migrated. Groups: {len(groups_set)}")

# ---------------------------------------------------------------------------
# GROUP TRACKING
# ---------------------------------------------------------------------------

def track_group(chat_id):
    """Ensures a group is tracked."""
    data = load_json(config.GROUP_DATA_FILE, {})
    chat_str = str(chat_id)
    if chat_str not in data:
        data[chat_str] = {}
        save_json(None, config.GROUP_DATA_FILE, data)  # Save without bot instance

def get_all_groups():
    """Returns list of all tracked group IDs."""
    try:
        data = load_json(config.GROUP_DATA_FILE, {})
        return [int(cid) for cid in data.keys()]
    except Exception:
        return []

# ---------------------------------------------------------------------------
# USER HELPERS (GLOBAL)
# ---------------------------------------------------------------------------

def _now_month_key():
    return datetime.datetime.now().strftime("%Y-%m")

def _now_year_key():
    return str(datetime.datetime.now().year)

def get_user(user_id, username=None):
    """Gets or creates a user entry in the global user_data."""
    data = load_json(config.USER_DATA_FILE, {})
    if user_id not in data:
        data[user_id] = {
            "username": username or "Player",
            "points": 0,
            "monthly_points": {},
            "yearly_points": {},
            "alltime_points": 0,
            "streak": 0,
            "best_streak": 0,
            "games_played": 0,
            "correct": 0,
            "title": None,
            "title_expires": None,
            "hint_tokens": 0,
            "double_xp_until": None,
            "last_spin": 0,
            "badges": [],
            "trivia_correct": 0,
            "versus_wins": 0,
            "daily_wins": 0,
            "powerups": {},
        }
    u = data[user_id]
    if username:
        u["username"] = username
    return u

def save_user(bot, user_id, user_data):
    """Saves a single user's data."""
    data = load_json(config.USER_DATA_FILE, {})
    data[user_id] = user_data
    save_json(bot, config.USER_DATA_FILE, data)

def track_member(bot, chat_id, user_id, username):
    """Tracks a member in a group (global stats)."""
    track_group(chat_id)
    user = get_user(user_id, username)
    if username:
        user["username"] = username
    save_user(bot, user_id, user)

def get_all_members(chat_id):
    """Returns list of (user_id, username) for all tracked members in a group.
    This now uses the global user_data and the group tracking list."""
    group_data = load_json(config.GROUP_DATA_FILE, {})
    chat_str = str(chat_id)
    if chat_str not in group_data:
        return []
    # We need to get all users who have interacted with this group
    # Since we don't track per-group user lists separately, we'll use the global user_data
    # and filter based on activity. A simpler approach: maintain a per-group user list in group_data.
    # Let's add a member list to group_data.
    if "members" not in group_data[chat_str]:
        group_data[chat_str]["members"] = []
        save_json(None, config.GROUP_DATA_FILE, group_data)
    members = group_data[chat_str].get("members", [])
    result = []
    for uid, username in members:
        u = get_user(uid)
        result.append((uid, u.get("username", username or "Player")))
    return result

def add_member_to_group(chat_id, user_id, username):
    """Adds a member to the group's member list."""
    data = load_json(config.GROUP_DATA_FILE, {})
    chat_str = str(chat_id)
    if chat_str not in data:
        data[chat_str] = {}
    if "members" not in data[chat_str]:
        data[chat_str]["members"] = []
    if not any(m[0] == user_id for m in data[chat_str]["members"]):
        data[chat_str]["members"].append((user_id, username))
        save_json(None, config.GROUP_DATA_FILE, data)

# ---------------------------------------------------------------------------
# POINTS & STREAKS
# ---------------------------------------------------------------------------

def get_streak_multiplier(streak):
    multiplier = 1.0
    for threshold, mult in sorted(config.STREAK_MULTIPLIERS.items(), reverse=True):
        if streak >= threshold:
            multiplier = mult
            break
    return multiplier

def reward_user(bot, chat_id, user_id, username, amount=50):
    track_group(chat_id)
    add_member_to_group(chat_id, user_id, username)
    user = get_user(user_id, username)

    user["streak"] += 1
    user["correct"] += 1
    if user["streak"] > user["best_streak"]:
        user["best_streak"] = user["streak"]

    multiplier = get_streak_multiplier(user["streak"])
    if user.get("double_xp_until") and time.time() < user["double_xp_until"]:
        multiplier *= 2

    final = int(amount * multiplier)

    month_key = _now_month_key()
    year_key = _now_year_key()
    user["points"] += final
    user["alltime_points"] += final
    user["monthly_points"][month_key] = user["monthly_points"].get(month_key, 0) + final
    user["yearly_points"][year_key] = user["yearly_points"].get(year_key, 0) + final
    user["games_played"] += 1

    save_user(bot, user_id, user)

    # Check achievements
    check_achievements(bot, user_id, username)

    return user["points"], user["streak"], multiplier, final

def penalise_wrong(bot, chat_id, user_id, username):
    track_group(chat_id)
    add_member_to_group(chat_id, user_id, username)
    user = get_user(user_id, username)
    user["streak"] = 0
    user["games_played"] += 1
    save_user(bot, user_id, user)

def deduct_points(bot, chat_id, user_id, username, amount):
    track_group(chat_id)
    add_member_to_group(chat_id, user_id, username)
    user = get_user(user_id, username)
    user["points"] = max(0, user["points"] - amount)
    save_user(bot, user_id, user)
    return user["points"]

# ---------------------------------------------------------------------------
# POWER-UPS (Global)
# ---------------------------------------------------------------------------

def use_powerup(bot, chat_id, user_id, username, powerup_id):
    track_group(chat_id)
    add_member_to_group(chat_id, user_id, username)
    user = get_user(user_id, username)
    if user.get("powerups", {}).get(powerup_id, 0) > 0:
        user["powerups"][powerup_id] -= 1
        save_user(bot, user_id, user)
        return True
    return False

def add_powerup(bot, chat_id, user_id, username, powerup_id, count=1):
    track_group(chat_id)
    add_member_to_group(chat_id, user_id, username)
    user = get_user(user_id, username)
    user.setdefault("powerups", {})
    user["powerups"][powerup_id] = user["powerups"].get(powerup_id, 0) + count
    save_user(bot, user_id, user)

# ---------------------------------------------------------------------------
# ACHIEVEMENTS / BADGES (Global)
# ---------------------------------------------------------------------------

def unlock_badge(bot, user_id, username, badge_id):
    user = get_user(user_id, username)
    if badge_id not in user.get("badges", []):
        user.setdefault("badges", [])
        user["badges"].append(badge_id)
        save_user(bot, user_id, user)
        return True
    return False

def check_achievements(bot, user_id, username):
    user = get_user(user_id, username)
    unlocked = []
    for badge_id, badge_data in config.ACHIEVEMENTS.items():
        if badge_id in user.get("badges", []):
            continue
        condition = badge_data.get("condition", {})
        meets_condition = True
        for key, required in condition.items():
            if user.get(key, 0) < required:
                meets_condition = False
                break
        if meets_condition:
            user.setdefault("badges", [])
            user["badges"].append(badge_id)
            unlocked.append(badge_id)
    if unlocked:
        save_user(bot, user_id, user)
        # Send notification to all groups the user is in
        badge_names = [config.ACHIEVEMENTS[b]["icon"] + " " + config.ACHIEVEMENTS[b]["name"] for b in unlocked]
        groups = get_all_groups()
        for gid in groups:
            try:
                bot.send_message(gid, f"🏅 *ACHIEVEMENT UNLOCKED!*\n\n{username} unlocked: {', '.join(badge_names)}!", parse_mode="Markdown")
            except Exception:
                pass
    return unlocked

# ---------------------------------------------------------------------------
# MUTE MANAGEMENT (Global)
# ---------------------------------------------------------------------------

def load_mutes():
    return load_json(config.MUTE_FILE, {})

def save_mutes(bot, data):
    save_json(bot, config.MUTE_FILE, data)

def mute_user(bot, chat_id, user_id, username, duration_seconds):
    data = load_mutes()
    key = f"{chat_id}_{user_id}"
    data[key] = {
        "username": username,
        "expires": time.time() + duration_seconds,
        "chat_id": chat_id,
        "user_id": user_id,
    }
    save_mutes(bot, data)

def unmute_user(bot, chat_id, user_id):
    data = load_mutes()
    key = f"{chat_id}_{user_id}"
    if key in data:
        del data[key]
        save_mutes(bot, data)
        return True
    return False

def is_muted(chat_id, user_id):
    data = load_mutes()
    key = f"{chat_id}_{user_id}"
    if key not in data:
        return False
    if time.time() > data[key]["expires"]:
        del data[key]
        return False
    return True

def cleanup_expired_mutes(bot):
    data = load_mutes()
    changed = False
    now = time.time()
    for key, value in list(data.items()):
        if now > value["expires"]:
            del data[key]
            changed = True
    if changed:
        save_mutes(bot, data)

# ---------------------------------------------------------------------------
# BROADCAST MANAGEMENT
# ---------------------------------------------------------------------------

def load_broadcasts():
    return load_json(config.BROADCAST_FILE, [])

def save_broadcasts(bot, data):
    save_json(bot, config.BROADCAST_FILE, data)

def add_broadcast(bot, chat_id, message, send_time):
    data = load_broadcasts()
    data.append({
        "chat_id": chat_id,
        "message": message,
        "send_time": send_time,
        "sent": False,
    })
    save_broadcasts(bot, data)
    return len(data) - 1

def get_pending_broadcasts():
    data = load_broadcasts()
    now = time.time()
    pending = [b for b in data if not b.get("sent", False) and b["send_time"] <= now]
    return pending

def mark_broadcast_sent(bot, index):
    data = load_broadcasts()
    if index < len(data):
        data[index]["sent"] = True
        save_broadcasts(bot, data)

# ---------------------------------------------------------------------------
# LEADERBOARD (Global)
# ---------------------------------------------------------------------------

def get_leaderboard(chat_id=None, mode="monthly", top_n=10):
    """
    mode: 'monthly' | 'yearly' | 'alltime'
    Returns list of (rank, username, points, streak, title) sorted by points desc.
    chat_id is now optional – leaderboard is global.
    """
    data = load_json(config.USER_DATA_FILE, {})
    month_key = _now_month_key()
    year_key = _now_year_key()
    results = []

    for user_id, u in data.items():
        if mode == "monthly":
            pts = u.get("monthly_points", {}).get(month_key, 0)
        elif mode == "yearly":
            pts = u.get("yearly_points", {}).get(year_key, 0)
        else:
            pts = u.get("alltime_points", 0)
        results.append({
            "username": u.get("username", "Player"),
            "points": pts,
            "streak": u.get("streak", 0),
            "title": _get_active_title(u),
        })

    results.sort(key=lambda x: x["points"], reverse=True)
    return [(i + 1, r["username"], r["points"], r["streak"], r["title"])
            for i, r in enumerate(results[:top_n])]

def _get_active_title(u):
    title = u.get("title")
    expires = u.get("title_expires")
    if title and expires and time.time() < expires:
        return title
    return None

# ---------------------------------------------------------------------------
# SHOP (Global)
# ---------------------------------------------------------------------------

def purchase_item(bot, chat_id, user_id, username, item_id):
    track_group(chat_id)
    add_member_to_group(chat_id, user_id, username)
    user = get_user(user_id, username)

    if item_id in config.POWERUPS:
        powerup = config.POWERUPS[item_id]
        if user["points"] < powerup["cost"]:
            return False, f"Not enough points. You need {powerup['cost']} but have {user['points']}."
        user["points"] -= powerup["cost"]
        user.setdefault("powerups", {})
        user["powerups"][item_id] = user["powerups"].get(item_id, 0) + 1
        save_user(bot, user_id, user)
        return True, f"✅ Purchased *{powerup['emoji']} {powerup['name']}* for {powerup['cost']} points!"

    item = next((i for i in config.SHOP_TITLES if i["id"] == item_id), None)
    if not item:
        return False, "Item not found."

    if user["points"] < item["cost"]:
        return False, f"Not enough points. You need {item['cost']} but have {user['points']}."

    user["points"] -= item["cost"]

    if item_id == "hint_tokens":
        user["hint_tokens"] = user.get("hint_tokens", 0) + 3
    elif item_id == "double_xp":
        user["double_xp_until"] = time.time() + 3600
    elif item_id == "mystery_box":
        import random
        prize = random.randint(10, 200)
        user["points"] += prize
        save_user(bot, user_id, user)
        return True, f"🎁 Mystery Box opened! You won *{prize} points*!"
    else:
        user["title"] = item["name"]
        user["title_expires"] = time.time() + (config.SHOP_TITLE_DURATION_DAYS * 86400)

    save_user(bot, user_id, user)
    return True, f"✅ Purchased *{item['name']}* for {item['cost']} points!"

def use_hint_token(bot, chat_id, user_id, username):
    track_group(chat_id)
    add_member_to_group(chat_id, user_id, username)
    user = get_user(user_id, username)
    if user.get("hint_tokens", 0) > 0:
        user["hint_tokens"] -= 1
        save_user(bot, user_id, user)
        return True
    return False

# ---------------------------------------------------------------------------
# MONTHLY RESET
# ---------------------------------------------------------------------------

def check_and_run_monthly_reset(bot):
    state = load_json(config.STATE_FILE, {})
    now = datetime.datetime.now()
    last = state.get("last_monthly_reset", "")
    curr = now.strftime("%Y-%m")

    if last == curr:
        return

    data = load_json(config.USER_DATA_FILE, {})
    prev_month = (now.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")

    scores = []
    for user_id, u in data.items():
        pts = u.get("monthly_points", {}).get(prev_month, 0)
        if pts > 0:
            scores.append((u.get("username", "Player"), pts, user_id))
    scores.sort(key=lambda x: x[1], reverse=True)

    if scores:
        winner_name, winner_pts, winner_id = scores[0]
        msg = (
            f"🏆 *Monthly Results — {prev_month}*\n\n"
            f"👑 Champion: *{winner_name}* with *{winner_pts} points*!\n\n"
            f"Top 3:\n"
        )
        for i, (name, pts, _) in enumerate(scores[:3], 1):
            medal = ["🥇", "🥈", "🥉"][i - 1]
            msg += f"{medal} {name} — {pts} pts\n"
        msg += "\nMonthly scores have been reset. New month, new battle! 🔥"

        groups = get_all_groups()
        for gid in groups:
            try:
                bot.send_message(gid, msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Monthly reset announcement failed for {gid}: {e}")

    state["last_monthly_reset"] = curr
    save_json(bot, config.STATE_FILE, state)

def check_and_run_yearly_reset(bot):
    state = load_json(config.STATE_FILE, {})
    now = datetime.datetime.now()
    curr = now.strftime("%Y")
    last = state.get("last_yearly_reset", "")

    if last == curr:
        return

    if now.month != 1 or now.day != 1:
        return

    data = load_json(config.USER_DATA_FILE, {})
    prev_year = str(now.year - 1)

    scores = []
    for user_id, u in data.items():
        pts = u.get("yearly_points", {}).get(prev_year, 0)
        if pts > 0:
            scores.append((u.get("username", "Player"), pts, user_id))
    scores.sort(key=lambda x: x[1], reverse=True)

    if scores:
        winner_name, winner_pts, winner_id = scores[0]
        msg = (
            f"🎊 *Yearly Champion — {prev_year}*\n\n"
            f"👑 *{winner_name}* dominated the year with *{winner_pts} points*!\n\n"
            f"Happy New Year! {now.year} begins now — make it count! 🚀"
        )
        groups = get_all_groups()
        for gid in groups:
            try:
                bot.send_message(gid, msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Yearly reset announcement failed for {gid}: {e}")

    state["last_yearly_reset"] = curr
    save_json(bot, config.STATE_FILE, state)

# ---------------------------------------------------------------------------
# QUOTES
# ---------------------------------------------------------------------------

def load_quotes():
    return load_json(config.QUOTES_FILE, [])

def save_quotes(bot, quotes):
    save_json(bot, config.QUOTES_FILE, quotes)

def add_quote(bot, text, author="CHJN"):
    quotes = load_quotes()
    next_id = max((q["id"] for q in quotes), default=0) + 1
    quotes.append({"id": next_id, "text": text, "author": author})
    save_quotes(bot, quotes)
    return next_id

def delete_quote(bot, quote_id):
    quotes = load_quotes()
    before = len(quotes)
    quotes = [q for q in quotes if q["id"] != quote_id]
    if len(quotes) == before:
        return False
    save_quotes(bot, quotes)
    return True

def edit_quote(bot, quote_id, new_text):
    quotes = load_quotes()
    for q in quotes:
        if q["id"] == quote_id:
            q["text"] = new_text
            save_quotes(bot, quotes)
            return True
    return False

def get_quote(quote_id):
    quotes = load_quotes()
    return next((q for q in quotes if q["id"] == quote_id), None)

def get_random_quote():
    import random
    quotes = load_quotes()
    return random.choice(quotes) if quotes else None
