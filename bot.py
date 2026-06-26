import os
import time
import datetime
from datetime import timezone
import threading
import telebot
from telebot.types import InputMediaPhoto
import config
import database
import graphics
import games

# Override proxy settings (fix for PythonAnywhere)
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''

bot = telebot.TeleBot(config.API_TOKEN)

# ---------------------------------------------------------------------------
# SCHEDULER STATE
# ---------------------------------------------------------------------------

def load_scheduler():
    return database.load_json(config.SCHEDULER_FILE, {
        "enabled":    False,
        "interval":   60,
        "game_type":  "random",
        "window_start": config.SCHEDULER_WINDOW_START,
        "window_end":   config.SCHEDULER_WINDOW_END,
        "last_game":  0,
        "tagall_last": 0,
    })

def save_scheduler(data):
    database.save_json(bot, config.SCHEDULER_FILE, data)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def is_admin(user_id):
    return user_id == config.ADMIN_ID

def utc_to_local(utc_hour):
    return (utc_hour + 2) % 24

def local_hour():
    return (datetime.datetime.utcnow().hour + 2) % 24

def local_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)

def schedule_delete(chat_id, message_id, delay=config.AUTO_DELETE_DELAY):
    """Schedules a message for deletion after delay seconds."""
    def delete():
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    timer = threading.Timer(delay, delete)
    timer.daemon = True
    timer.start()

# ---------------------------------------------------------------------------
# HELP MENU
# ---------------------------------------------------------------------------

def _build_help_menu():
    import telebot
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🎮 Games", callback_data="help_games"),
        telebot.types.InlineKeyboardButton("🏆 Rankings", callback_data="help_rankings"),
        telebot.types.InlineKeyboardButton("🛒 Shop", callback_data="help_shop"),
        telebot.types.InlineKeyboardButton("💡 Points & Streaks", callback_data="help_points"),
        telebot.types.InlineKeyboardButton("📋 Info", callback_data="help_info"),
    )
    return markup

def _get_help_text(category):
    texts = {
        "games": (
            "🎮 *GAMES*\n\n"
            "/game — Guess the Character\n"
            "/year — Guess the Release Year\n"
            "/trivia — Random trivia question\n"
            "/trivia Gaming — Trivia by category\n"
            "/picture — Scrambled Image Guessing\n"
            "/versus @user — Challenge someone to a duel\n"
            "/forfeit — Concede an active versus match\n"
            "/hint — Get a hint during a game\n"
            "/stop — Stop the current game"
        ),
        "rankings": (
            "🏆 *RANKINGS & STATS*\n\n"
            "/leaderboard — View monthly/yearly/all-time rankings\n"
            "/mystats — View your personal stats\n"
            "/profile @user — View someone's profile card"
        ),
        "shop": (
            "🛒 *SHOP*\n\n"
            "/shop — Spend your points on titles & items\n\n"
            "Titles expire after 30 days.\n"
            "Special items are instant!\n\n"
            "Power-ups:\n"
            "✂️ 50/50 — Removes two wrong trivia answers\n"
            "🧊 Streak Freeze — Protects your streak once\n"
            "⬆️ Double Down — Double points on next correct"
        ),
        "points": (
            "💡 *POINTS & STREAKS*\n\n"
            "Character/Year game: 50 pts\n"
            "Trivia: 75 pts\n"
            "Versus win: 100 pts\n"
            "Daily challenge: 150 pts\n"
            "Wheel of Fortune: Random!\n\n"
            "🔥 Streak multipliers:\n"
            "• 3 in a row → x2\n"
            "• 5 in a row → x3\n"
            "• 10 in a row → x5"
        ),
        "info": (
            "📋 *INFO*\n\n"
            "/categories — View trivia categories\n"
            "/table — League standings\n"
            "/fixtures — Match fixtures\n"
            "/spin — Daily Wheel of Fortune\n"
            "/start — Welcome message & how to play"
        ),
    }
    return texts.get(category, "Unknown category.")

# ---------------------------------------------------------------------------
# LEADERBOARD PAGINATION HELPERS
# ---------------------------------------------------------------------------

def _build_leaderboard_markup(mode, page, total_pages):
    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        telebot.types.InlineKeyboardButton("📅 Monthly", callback_data=f"lb_monthly_1"),
        telebot.types.InlineKeyboardButton("📆 Yearly",  callback_data=f"lb_yearly_1"),
        telebot.types.InlineKeyboardButton("🌟 All Time", callback_data=f"lb_alltime_1"),
    )
    if total_pages > 1:
        nav_btns = []
        if page > 1:
            nav_btns.append(telebot.types.InlineKeyboardButton("⬅️ Prev", callback_data=f"lb_{mode}_{page-1}"))
        nav_btns.append(telebot.types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="lb_nop"))
        if page < total_pages:
            nav_btns.append(telebot.types.InlineKeyboardButton("Next ➡️", callback_data=f"lb_{mode}_{page+1}"))
        markup.row(*nav_btns)
    return markup

# ---------------------------------------------------------------------------
# LEAGUE TABLE & FIXTURES
# ---------------------------------------------------------------------------

def show_league_table(message):
    bot.send_chat_action(message.chat.id, 'upload_photo')
    try:
        img = graphics.generate_table_image(bot)
        if img:
            bot.send_photo(message.chat.id, img, caption="🏆 *ZA SORA ZENITH LEAGUE STANDINGS*", parse_mode="Markdown")
            if hasattr(img, 'close'): img.close()
        else:
            bot.reply_to(message, "❌ Standings unavailable.")
    except Exception as e:
        database.log_error_to_admin(bot, "Table Command", e)

def _build_fixtures_menu_markup(rows):
    home_idx, away_idx, _, _, _ = graphics.detect_fixtures_columns(rows)
    header_offset = 1 if (
        "home" in str(rows[0][home_idx]).lower() or
        rows[0][0].lower() in ["md", "matchday"]
    ) else 0

    teams = set()
    for row in rows[header_offset:]:
        if len(row) > max(home_idx, away_idx):
            h = row[home_idx].strip()
            a = row[away_idx].strip()
            if h and not h.isdigit(): teams.add(h)
            if a and not a.isdigit(): teams.add(a)

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        telebot.types.InlineKeyboardButton("📅  View by Matchday", callback_data="fix_md_menu"),
        telebot.types.InlineKeyboardButton("👤  View by Player", callback_data="fix_pl_menu"),
    )
    return markup, sorted(list(teams))

def show_fixtures_inline(chat_id, message_id=None):
    rows = database.fetch_csv_cached(bot, config.FIXTURES_CSV_URL)
    if not rows or len(rows) <= 1:
        bot.send_message(chat_id, "❌ Fixtures unavailable.")
        return
    markup, _ = _build_fixtures_menu_markup(rows)
    text = "📋 *FIXTURES*\n\nChoose how you want to browse:"
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id,
                                  reply_markup=markup, parse_mode="Markdown")
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

def show_fixtures(message):
    try:
        rows = database.fetch_csv_cached(bot, config.FIXTURES_CSV_URL)
        if not rows or len(rows) <= 1:
            bot.reply_to(message, "❌ Fixtures unavailable.")
            return
        markup, _ = _build_fixtures_menu_markup(rows)
        bot.send_message(
            message.chat.id,
            "📋 *FIXTURES*\n\nChoose how you want to browse:",
            reply_markup=markup, parse_mode="Markdown"
        )
    except Exception as e:
        database.log_error_to_admin(bot, "Fixtures Command", e)
        bot.reply_to(message, "💥 Failed to fetch fixtures.")

# ---------------------------------------------------------------------------
# LEADERBOARD
# ---------------------------------------------------------------------------

def show_leaderboard(message):
    bot.send_chat_action(message.chat.id, 'upload_photo')
    mode = "monthly"
    page = 1
    all_entries = database.get_leaderboard(message.chat.id, mode=mode, top_n=100)
    total_pages = (len(all_entries) + 9) // 10
    img = graphics.build_leaderboard_image(message.chat.id, mode, page)
    if img:
        caption = f"🏆 *Leaderboard — {mode.upper()}* (Page {page}/{total_pages})"
        markup = _build_leaderboard_markup(mode, page, total_pages)
        bot.send_photo(message.chat.id, img, caption=caption,
                       reply_markup=markup, parse_mode="Markdown")
        if hasattr(img, 'close'): img.close()
    else:
        bot.send_message(message.chat.id, "No scores yet!")

# ---------------------------------------------------------------------------
# SHOP
# ---------------------------------------------------------------------------

def show_shop(message):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for item in config.SHOP_TITLES:
        markup.add(telebot.types.InlineKeyboardButton(
            f"{item['name']} — {item['cost']} pts",
            callback_data=f"shop_{item['id']}"
        ))
    bot.send_message(
        message.chat.id,
        "🛒 *POINT SHOP*\n\nTitles expire after 30 days. Special items are instant!",
        reply_markup=markup, parse_mode="Markdown"
    )

# ---------------------------------------------------------------------------
# TAG ALL
# ---------------------------------------------------------------------------

def tag_all_members(message, custom_msg=""):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only.")
        return

    sched = load_scheduler()
    now   = time.time()
    if now - sched.get("tagall_last", 0) < config.TAGALL_COOLDOWN_HOURS * 3600:
        remaining = int((config.TAGALL_COOLDOWN_HOURS * 3600 - (now - sched["tagall_last"])) / 60)
        bot.reply_to(message, f"⏳ Tag all on cooldown. {remaining} minutes remaining.")
        return

    markup = telebot.types.InlineKeyboardMarkup()
    safe_msg = custom_msg[:200].replace('"', "'")
    markup.row(
        telebot.types.InlineKeyboardButton("✅ Confirm Send", callback_data="tagall_confirm"),
        telebot.types.InlineKeyboardButton("❌ Cancel",       callback_data="tagall_cancel")
    )
    sched["tagall_pending_msg"] = custom_msg
    sched["tagall_pending_chat"] = message.chat.id
    save_scheduler(sched)

    bot.reply_to(
        message,
        f"📢 *Tag All Preview:*\n\n{custom_msg}\n\n"
        f"This will tag all {len(database.get_all_members(message.chat.id))} tracked members. Confirm?",
        reply_markup=markup, parse_mode="Markdown"
    )

def _do_tag_all(chat_id, custom_msg):
    members = database.get_all_members(chat_id)
    if not members:
        bot.send_message(chat_id, "❌ No members tracked yet.")
        return

    mentions = " ".join([f"[{name}](tg://user?id={uid})" for uid, name in members])
    full_msg = f"📢 *ANNOUNCEMENT*\n\n{custom_msg}\n\n{mentions}"

    if len(full_msg) > 4096:
        bot.send_message(chat_id, f"📢 *ANNOUNCEMENT*\n\n{custom_msg}", parse_mode="Markdown")
        chunk_size = 30
        for i in range(0, len(members), chunk_size):
            chunk    = members[i:i + chunk_size]
            mentions = " ".join([f"[{name}](tg://user?id={uid})" for uid, name in chunk])
            bot.send_message(chat_id, mentions, parse_mode="Markdown")
    else:
        bot.send_message(chat_id, full_msg, parse_mode="Markdown")

    sched = load_scheduler()
    sched["tagall_last"] = time.time()
    save_scheduler(sched)

# ---------------------------------------------------------------------------
# QUOTE MANAGEMENT (Admin DM only)
# ---------------------------------------------------------------------------

def show_quotes_page(chat_id, page=1):
    quotes   = database.load_quotes()
    per_page = 10
    total    = len(quotes)
    pages    = (total + per_page - 1) // per_page
    page     = max(1, min(page, pages))
    start    = (page - 1) * per_page
    chunk    = quotes[start:start + per_page]

    text = f"📝 *Quotes — Page {page}/{pages}* ({total} total)\n\n"
    for q in chunk:
        preview = q["text"][:60] + "..." if len(q["text"]) > 60 else q["text"]
        text   += f"*#{q['id']}* — {preview}\n"
        text   += f"_— {q['author']}_\n\n"

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    nav    = []
    if page > 1:
        nav.append(telebot.types.InlineKeyboardButton("⬅️ Prev", callback_data=f"qpage_{page-1}"))
    if page < pages:
        nav.append(telebot.types.InlineKeyboardButton("Next ➡️", callback_data=f"qpage_{page+1}"))
    if nav:
        markup.row(*nav)

    return text, markup

# ---------------------------------------------------------------------------
# ADMIN PANEL
# ---------------------------------------------------------------------------

def show_admin_panel(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only.")
        return
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🎮 Start Character Game", callback_data="admin_startchar"),
        telebot.types.InlineKeyboardButton("🎬 Start Year Game",      callback_data="admin_startyear"),
        telebot.types.InlineKeyboardButton("🖼️ Start Picture Game",   callback_data="admin_startpicture"),
        telebot.types.InlineKeyboardButton("❓ Start Trivia",          callback_data="admin_starttrivia"),
        telebot.types.InlineKeyboardButton("📅 Set Schedule",          callback_data="admin_schedule"),
        telebot.types.InlineKeyboardButton("📢 Tag All",               callback_data="admin_tagall"),
        telebot.types.InlineKeyboardButton("🏆 Leaderboard",           callback_data="admin_leaderboard"),
        telebot.types.InlineKeyboardButton("🔄 Rebuild Cache",         callback_data="admin_rebuild"),
        telebot.types.InlineKeyboardButton("📊 Stats",                 callback_data="admin_stats"),
        telebot.types.InlineKeyboardButton("🔇 Mute User",             callback_data="admin_mute"),
        telebot.types.InlineKeyboardButton("📢 Broadcast",             callback_data="admin_broadcast"),
    )
    sched = load_scheduler()
    status_icon = "✅" if sched.get("enabled") else "❌"
    bot.send_message(
        message.chat.id,
        f"⚙️ *ADMIN PANEL*\n\n"
        f"Auto-scheduler: {status_icon} {'ON' if sched.get('enabled') else 'OFF'}\n"
        f"Interval: every {sched.get('interval', 60)} min\n"
        f"Game type: {sched.get('game_type', 'random').title()}\n"
        f"Active window: {sched.get('window_start', 18)}:00 — {sched.get('window_end', 23)}:00",
        reply_markup=markup, parse_mode="Markdown"
    )

def show_schedule_panel(chat_id):
    sched  = load_scheduler()
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    toggle_label = "❌ Disable" if sched.get("enabled") else "✅ Enable"
    markup.add(telebot.types.InlineKeyboardButton(toggle_label, callback_data="sched_toggle"))
    markup.add(*[
        telebot.types.InlineKeyboardButton(f"⏱ {m}min", callback_data=f"sched_interval_{m}")
        for m in config.SCHEDULE_INTERVALS
    ])
    markup.add(*[
        telebot.types.InlineKeyboardButton(f"⏰ {s}s limit", callback_data=f"sched_timelimit_{s}")
        for s in [30, 45, 60, 90, 120]
    ])
    markup.add(
        telebot.types.InlineKeyboardButton("🎮 Character", callback_data="sched_type_character"),
        telebot.types.InlineKeyboardButton("🎬 Year",      callback_data="sched_type_year"),
        telebot.types.InlineKeyboardButton("🖼️ Picture",   callback_data="sched_type_picture"),
        telebot.types.InlineKeyboardButton("❓ Trivia",    callback_data="sched_type_trivia"),
        telebot.types.InlineKeyboardButton("🎲 Random",    callback_data="sched_type_random"),
    )
    markup.add(telebot.types.InlineKeyboardButton("🔙 Back", callback_data="admin_back"))

    status_icon = "✅" if sched.get("enabled") else "❌"
    bot.send_message(
        chat_id,
        f"📅 *SCHEDULE SETTINGS*\n\n"
        f"Status: {status_icon} {'ON' if sched.get('enabled') else 'OFF'}\n"
        f"Interval: every *{sched.get('interval', 60)} min*\n"
        f"Type: *{sched.get('game_type', 'random').title()}*\n"
        f"Window: *{sched.get('window_start',18)}:00 – {sched.get('window_end',23)}:00*\n"
        f"⏰ Answer time limit: *{sched.get('answer_time_limit', 60)}s*",
        reply_markup=markup, parse_mode="Markdown"
    )

def show_stats(chat_id):
    data = database.load_json(config.GROUP_DATA_FILE, {})
    chat_str = str(chat_id)
    if chat_str not in data:
        bot.send_message(chat_id, "📊 No stats yet.")
        return
    users = data[chat_str]
    total_games  = sum(u.get("games_played", 0) for u in users.values())
    total_pts    = sum(u.get("alltime_points", 0) for u in users.values())
    most_active  = max(users.values(), key=lambda u: u.get("games_played", 0), default=None)
    top_scorer   = max(users.values(), key=lambda u: u.get("alltime_points", 0), default=None)
    best_streak  = max(users.values(), key=lambda u: u.get("best_streak", 0), default=None)
    bot.send_message(
        chat_id,
        f"📊 *GROUP STATS*\n\n"
        f"👥 Tracked members: {len(users)}\n"
        f"🎮 Total games played: {total_games}\n"
        f"💰 Total points distributed: {total_pts}\n"
        f"🏃 Most active: {most_active.get('username','?')} ({most_active.get('games_played',0)} games)\n"
        f"🏆 Top scorer: {top_scorer.get('username','?')} ({top_scorer.get('alltime_points',0)} pts)\n"
        f"🔥 Best streak: {best_streak.get('username','?')} ({best_streak.get('best_streak',0)} in a row)",
        parse_mode="Markdown"
    )

# ---------------------------------------------------------------------------
# WEEKLY RECAP
# ---------------------------------------------------------------------------

def send_weekly_recap(bot):
    groups = database.get_all_groups()
    for group_id in groups:
        lb = database.get_leaderboard(group_id, mode="monthly", top_n=3)
        top3 = ""
        if lb:
            medals = ["🥇", "🥈", "🥉"]
            for rank, username, points, streak, title in lb:
                top3 += f"{medals[rank-1]} {username} — {points} pts\n"
        else:
            top3 = "No scores yet this month!\n"
        msg = (
            f"📊 *WEEKLY RECAP*\n\n"
            f"🏆 *Monthly Top 3:*\n{top3}\n"
            f"Keep up the great work, family! 🙏🔥"
        )
        try:
            bot.send_message(group_id, msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Weekly recap failed for {group_id}: {e}")

# ---------------------------------------------------------------------------
# MORNING MESSAGE
# ---------------------------------------------------------------------------

def send_morning_message(bot):
    print("🌅 send_morning_message() called")
    now     = local_now()
    weekday = now.strftime("%A")
    date    = now.strftime("%d %B %Y")
    quote   = database.get_random_quote()
    groups  = database.get_all_groups()
    print(f"📊 Found {len(groups)} groups")

    for group_id in groups:
        lb   = database.get_leaderboard(group_id, mode="monthly", top_n=3)
        top3 = ""
        if lb:
            medals = ["🥇", "🥈", "🥉"]
            for rank, username, points, streak, title in lb:
                top3 += f"{medals[rank-1]} {username} — {points} pts\n"
        else:
            top3 = "No scores yet this month!\n"

        msg = (
            f"☀️ *Good Morning, Family!*\n"
            f"_{weekday}, {date}_\n\n"
        )
        if quote:
            msg += f"💬 *{quote['text']}*\n_— {quote['author']}_\n\n"

        msg += (
            f"🏆 *Monthly Top 3:*\n{top3}\n"
            f"🎮 *Game Commands:*\n"
            f"/game — Guess the Character\n"
            f"/year — Guess the Year\n"
            f"/picture — Scrambled Image\n"
            f"/trivia — Trivia Quiz\n"
            f"/spin — Wheel of Fortune\n"
            f"/leaderboard — Rankings\n"
            f"/shop — Point Shop\n\n"
            f"Let's have a great day! 🙏🔥"
        )
        members = database.get_all_members(group_id)
        if members:
            tag_line = " ".join([f"[{name}](tg://user?id={uid})" for uid, name in members])
            msg += f"\n\n🌱 _Sending love to the whole family_ 🌱\n{tag_line}"
        try:
            bot.send_message(group_id, msg, parse_mode="Markdown")
            print(f"✅ Morning message sent to group {group_id}")
        except Exception as e:
            print(f"❌ Morning message failed for {group_id}: {e}")

# ---------------------------------------------------------------------------
# COMMAND ROUTER
# ---------------------------------------------------------------------------

@bot.message_handler(content_types=['photo'])
def handle_photo_messages(message):
    if message.chat.id == config.ADMIN_ID and message.caption:
        if message.caption.strip().lower().startswith("/saveimage"):
            handle_image_upload(message)

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if message.chat.id != config.ADMIN_ID:
        return
    state = database.load_json("upload_state.json", {})
    if not state.get("pending"):
        return
    # Download the file
    file_info = bot.get_file(message.document.file_id)
    dl_url = f"https://api.telegram.org/file/bot{config.API_TOKEN}/{file_info.file_path}"
    import requests
    try:
        response = requests.get(dl_url, timeout=30)
        response.raise_for_status()
        content = response.content.decode('utf-8')
        filename = message.document.file_name.lower()
        if filename.endswith('.json'):
            new_questions = json.loads(content)
        elif filename.endswith('.csv'):
            import csv
            lines = content.splitlines()
            reader = csv.DictReader(lines)
            new_questions = [{"category": row["category"], "question": row["question"], "options": [row["optionA"], row["optionB"], row["optionC"], row["optionD"]], "answer": row["answer"]} for row in reader]
        else:
            bot.reply_to(message, "❌ Unsupported file format. Use JSON or CSV.")
            return
        trivia = database.load_json(config.TRIVIA_DB, [])
        existing_ids = {q["id"] for q in trivia}
        new_id = max(existing_ids) + 1 if existing_ids else 1
        for q in new_questions:
            q["id"] = new_id
            new_id += 1
            trivia.append(q)
        database.save_json(bot, config.TRIVIA_DB, trivia)
        bot.reply_to(message, f"✅ Added {len(new_questions)} new trivia questions!")
        database.save_json(bot, "upload_state.json", {"pending": False})
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(content_types=['new_chat_members'])
def welcome_new_member(message):
    for member in message.new_chat_members:
        if member.is_bot:
            continue
        username = member.username or member.first_name
        database.track_member(bot, message.chat.id, member.id, username)
        members  = database.get_all_members(message.chat.id)
        tag_line = " ".join([f"[{n}](tg://user?id={uid})" for uid, n in members if uid != member.id])
        welcome  = (
            f"{config.WELCOME_MSG}\n\n"
            f"👋 *Welcome [{username}](tg://user?id={member.id})!* "
            f"Say hi to the family 🌱\n{tag_line}"
        )
        bot.send_message(message.chat.id, welcome, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if not message.text:
        return

    user_id  = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    chat_id  = message.chat.id

    database.track_member(bot, chat_id, user_id, username)

    # Game answer check first
    if games.check_user_answer(bot, message):
        return

    if not message.text.startswith('/'):
        return

    cmd = message.text.split()[0].split('@')[0].lower()
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []

    if cmd == '/start':
        bot.reply_to(message, config.WELCOME_MSG, parse_mode="Markdown")

    elif cmd == '/help':
        show_help(message)

    elif cmd == '/mystats':
        show_my_stats(message)

    elif cmd == '/profile':
        if args and args[0].startswith('@'):
            target_mention = args[0].lstrip('@')
            members = database.get_all_members(chat_id)
            target = next((m for m in members if m[1].lower() == target_mention.lower()), None)
            if not target:
                bot.reply_to(message, "❌ User not found.")
                return
            target_id, target_name = target
            img = graphics.build_profile_card(chat_id, target_id, target_name)
            caption = f"📊 *Profile — {target_name}*"
        else:
            img = graphics.build_profile_card(chat_id, user_id, username)
            caption = f"📊 *Your Profile*"
        if img:
            bot.send_photo(chat_id, img, caption=caption, parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ No data found for this user.")

    elif cmd == '/categories':
        show_categories(message)

    elif cmd == '/table':
        show_league_table(message)

    elif cmd == '/fixtures':
        show_fixtures(message)

    elif cmd in ['/game', '/startgame', '/quiz']:
        games.send_character_category_picker(bot, chat_id)

    elif cmd in ['/year', '/startyear', '/yeargame']:
        games.send_year_category_picker(bot, chat_id)

    elif cmd == '/picture':
        games.send_character_category_picker(bot, chat_id)  # Reuse character categories

    elif cmd == '/trivia':
        games.send_trivia_category_picker(bot, chat_id)

    elif cmd == '/hint':
        games.process_hint(bot, message=message)

    elif cmd == '/stop':
        if chat_id in games.active_games:
            del games.active_games[chat_id]
            bot.reply_to(message, "🛑 Game stopped.")

    elif cmd == '/leaderboard':
        show_leaderboard(message)

    elif cmd == '/shop':
        show_shop(message)

    elif cmd == '/spin':
        # Wheel of Fortune
        if database.is_muted(chat_id, user_id):
            bot.reply_to(message, "🔇 You are muted! Wait until your mute expires.")
            return
        data = database.load_json(config.GROUP_DATA_FILE, {})
        chat_str = str(chat_id)
        user_str = str(user_id)
        u = database.get_user(data, chat_str, user_str, username)
        last_spin = u.get("last_spin", 0)
        if time.time() - last_spin < 86400:
            remaining = int((last_spin + 86400 - time.time()) / 60)
            bot.reply_to(message, f"⏳ You already spun today! Come back in {remaining} minutes.")
            return
        import random
        slots = config.WHEEL_SLOTS
        total_weight = sum(slot["weight"] for slot in slots)
        roll = random.randint(1, total_weight)
        cumulative = 0
        result = None
        for slot in slots:
            cumulative += slot["weight"]
            if roll <= cumulative:
                result = slot
                break
        if not result:
            result = slots[0]
        u["last_spin"] = time.time()
        response = "🎰 *WHEEL OF FORTUNE*\n\n"
        if result.get("points"):
            points = result["points"]
            data = database.load_json(config.GROUP_DATA_FILE, {})
            user_data = database.get_user(data, chat_str, user_str, username)
            user_data["points"] += points
            user_data["alltime_points"] += points
            month_key = database._now_month_key()
            year_key = database._now_year_key()
            user_data["monthly_points"][month_key] = user_data["monthly_points"].get(month_key, 0) + points
            user_data["yearly_points"][year_key] = user_data["yearly_points"].get(year_key, 0) + points
            database.save_json(bot, config.GROUP_DATA_FILE, data)
            response += f"🎉 You won *{points} points*!"
        elif result.get("hint_token"):
            tokens = result["hint_token"]
            u["hint_tokens"] = u.get("hint_tokens", 0) + tokens
            database.save_json(bot, config.GROUP_DATA_FILE, data)
            response += f"💡 You won *{tokens} hint token(s)*!"
        elif result.get("double_xp"):
            duration = result["double_xp"]
            u["double_xp_until"] = time.time() + duration
            database.save_json(bot, config.GROUP_DATA_FILE, data)
            response += f"⚡ You won *Double XP for 1 hour*!"
        elif result.get("bankrupt"):
            u["points"] = max(0, u["points"] - 10)
            database.save_json(bot, config.GROUP_DATA_FILE, data)
            response += f"💸 *BANKRUPT!* You lost 10 points. 😱"
        else:
            response += f"🎁 You won *{result['name']}*!"
        bot.reply_to(message, response, parse_mode="Markdown")

    elif cmd == '/versus':
        if not args:
            bot.reply_to(message, "Usage: /versus @username")
            return
        target_mention = args[0].lstrip('@')
        members = database.get_all_members(chat_id)
        target  = next((m for m in members if m[1].lower() == target_mention.lower()), None)
        if not target:
            bot.reply_to(message, "❌ User not found in tracked members.")
            return
        games.start_versus(bot, chat_id, user_id, username, target[0], target[1])

    elif cmd == '/forfeit':
        games.handle_versus_forfeit(bot, message)

    elif cmd == '/tagall':
        custom_msg = " ".join(args) if args else "Attention everyone!"
        tag_all_members(message, custom_msg)

    elif cmd == '/admin':
        if is_admin(user_id):
            show_admin_panel(message)
        else:
            bot.reply_to(message, "❌ Admin only.")

    elif cmd == '/testmorning':
        if is_admin(user_id):
            send_morning_message(bot)
            bot.reply_to(message, "✅ Morning message sent (test).")
        else:
            bot.reply_to(message, "❌ Admin only.")

    # Mute commands
    elif cmd == '/mute' and is_admin(user_id):
        if len(args) < 2:
            bot.reply_to(message, "Usage: /mute @username 1h  (or 10m, 24h, etc.)")
            return
        target_mention = args[0].lstrip('@')
        duration_str = args[1]
        import re
        match = re.match(r'(\d+)([mh])', duration_str)
        if not match:
            bot.reply_to(message, "❌ Invalid duration. Use like: 10m, 1h, 24h")
            return
        num, unit = int(match.group(1)), match.group(2)
        seconds = num * 60 if unit == 'm' else num * 3600
        if seconds < 60 or seconds > 86400:
            bot.reply_to(message, "❌ Duration must be between 1m and 24h.")
            return
        members = database.get_all_members(chat_id)
        target = next((m for m in members if m[1].lower() == target_mention.lower()), None)
        if not target:
            bot.reply_to(message, "❌ User not found.")
            return
        target_id, target_name = target
        database.mute_user(bot, chat_id, target_id, target_name, seconds)
        bot.reply_to(message, f"✅ Muted {target_name} for {num}{unit}.")

    elif cmd == '/unmute' and is_admin(user_id):
        if not args:
            bot.reply_to(message, "Usage: /unmute @username")
            return
        target_mention = args[0].lstrip('@')
        members = database.get_all_members(chat_id)
        target = next((m for m in members if m[1].lower() == target_mention.lower()), None)
        if not target:
            bot.reply_to(message, "❌ User not found.")
            return
        target_id, target_name = target
        if database.unmute_user(bot, chat_id, target_id):
            bot.reply_to(message, f"✅ Unmuted {target_name}.")
        else:
            bot.reply_to(message, f"❌ {target_name} was not muted.")

    # Upload trivia
    elif cmd == '/uploadtrivia' and is_admin(user_id):
        bot.reply_to(message, "📤 Send me a JSON or CSV file with trivia questions.\n\n"
                              "JSON format: `[{\"category\":\"Gaming\",\"question\":\"...\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"answer\":\"A\"}]`\n"
                              "CSV format: `category,question,optionA,optionB,optionC,optionD,answer`")
        database.save_json(bot, "upload_state.json", {"user_id": user_id, "chat_id": chat_id, "pending": True})
        return

    # Broadcast
    elif cmd == '/broadcast' and is_admin(user_id):
        if len(args) < 2:
            bot.reply_to(message, "Usage: /broadcast [time] [message]\n\n"
                                  "Time format: '2024-12-25 08:00' (UTC+2)\n"
                                  "Example: /broadcast 2024-12-25 08:00 Merry Christmas everyone!")
            return
        # Parse time and message
        time_str = args[0] + " " + args[1]
        try:
            send_time = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M").timestamp()
        except ValueError:
            bot.reply_to(message, "❌ Invalid time format. Use: YYYY-MM-DD HH:MM")
            return
        if send_time < time.time():
            bot.reply_to(message, "❌ Broadcast time must be in the future.")
            return
        message_text = " ".join(args[2:])
        if not message_text:
            bot.reply_to(message, "❌ Please provide a message.")
            return
        database.add_broadcast(bot, chat_id, message_text, send_time)
        bot.reply_to(message, f"✅ Broadcast scheduled for {time_str}.")

    # Quote management
    elif cmd == '/addquote' and chat_id == user_id and is_admin(user_id):
        if not args:
            bot.reply_to(message, "Usage: /addquote [quote text]")
            return
        text    = " ".join(args)
        new_id  = database.add_quote(bot, text)
        bot.reply_to(message, f"✅ Quote #{new_id} added!")

    elif cmd == '/listquotes' and is_admin(user_id):
        text, markup = show_quotes_page(chat_id, 1)
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

    elif cmd == '/deletequote' and is_admin(user_id):
        if not args or not args[0].isdigit():
            bot.reply_to(message, "Usage: /deletequote [id]")
            return
        if database.delete_quote(bot, int(args[0])):
            bot.reply_to(message, f"✅ Quote #{args[0]} deleted.")
        else:
            bot.reply_to(message, f"❌ Quote #{args[0]} not found.")

    elif cmd == '/editquote' and is_admin(user_id):
        if len(args) < 2 or not args[0].isdigit():
            bot.reply_to(message, "Usage: /editquote [id] [new text]")
            return
        new_text = " ".join(args[1:])
        if database.edit_quote(bot, int(args[0]), new_text):
            bot.reply_to(message, f"✅ Quote #{args[0]} updated.")
        else:
            bot.reply_to(message, f"❌ Quote #{args[0]} not found.")

    elif cmd == '/previewquote' and is_admin(user_id):
        if not args or not args[0].isdigit():
            bot.reply_to(message, "Usage: /previewquote [id]")
            return
        q = database.get_quote(int(args[0]))
        if q:
            bot.reply_to(message, f"📖 *Preview — Quote #{q['id']}*\n\n_{q['text']}_\n\n— *{q['author']}*", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ Quote #{args[0]} not found.")

    elif cmd == '/setschedule' and is_admin(user_id):
        show_schedule_panel(chat_id)

# ---------------------------------------------------------------------------
# CALLBACK HANDLER
# ---------------------------------------------------------------------------

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    data    = call.data
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    try:
        # ── Character category picker ─────────────────────────────────────
        if data.startswith("charcat_"):
            cat = data.replace("charcat_", "")
            bot.answer_callback_query(call.id)
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            games.start_character_game(bot, chat_id, category=cat, user_id=user_id)
            return

        # ── Year category picker ──────────────────────────────────────────
        if data.startswith("yearcat_"):
            cat = data.replace("yearcat_", "")
            bot.answer_callback_query(call.id)
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            games.start_year_game(bot, chat_id, category=cat, user_id=user_id)
            return

        # ── Trivia category picker ────────────────────────────────────────
        if data.startswith("triviacat_"):
            cat = data.replace("triviacat_", "")
            bot.answer_callback_query(call.id)
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            games.start_trivia_game(bot, chat_id, category=cat, user_id=user_id)
            return

        # ── Legacy startcat_ support ──────────────────────────────────────
        if data.startswith("startcat_"):
            cat = data.replace("startcat_", "")
            bot.answer_callback_query(call.id)
            games.start_trivia_game(bot, chat_id, category=cat)
            return

        # ── Game callbacks ──────────────────────────────────────────────────
        if any(data.startswith(p) for p in ["trivia_", "year_ans_", "vs_", "vsbet_", "vsans_", "daily_", "hint_", "stopgame_", "nextgame_"]):
            games.handle_game_callback(bot, call)
            return

        # ── Admin force start / cancel ────────────────────────────────────
        if data == "admin_force_start" and is_admin(user_id):
            pending = games.pending_admin_actions.pop(chat_id, None)
            if pending:
                if chat_id in games.active_games:
                    del games.active_games[chat_id]
                if chat_id in games.versus_games:
                    del games.versus_games[chat_id]
                gtype = pending['type']
                cat = pending.get('category')
                if gtype == 'character':
                    games.start_character_game(bot, chat_id, category=cat)
                elif gtype == 'year':
                    games.start_year_game(bot, chat_id, category=cat)
                elif gtype == 'picture':
                    games.start_picture_game(bot, chat_id, category=cat)
                elif gtype == 'trivia':
                    games.start_trivia_game(bot, chat_id, category=cat)
            bot.answer_callback_query(call.id)
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            return

        if data == "admin_cancel_start":
            games.pending_admin_actions.pop(chat_id, None)
            bot.answer_callback_query(call.id, "Cancelled.")
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            return

        # ── Leaderboard pagination ──────────────────────────────────────
        if data.startswith("lb_"):
            if data == "lb_nop":
                bot.answer_callback_query(call.id)
                return
            parts = data.split("_")
            if len(parts) == 3:
                _, mode, page_str = parts
                page = int(page_str)
            else:
                mode = parts[1] if len(parts) > 1 else "monthly"
                page = 1
            all_entries = database.get_leaderboard(chat_id, mode=mode, top_n=100)
            total_pages = (len(all_entries) + 9) // 10
            if page < 1:
                page = 1
            if page > total_pages and total_pages > 0:
                page = total_pages
            img = graphics.build_leaderboard_image(chat_id, mode, page)
            if img:
                caption = f"🏆 *Leaderboard — {mode.upper()}* (Page {page}/{total_pages})"
                markup = _build_leaderboard_markup(mode, page, total_pages)
                bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    media=InputMediaPhoto(img, caption=caption, parse_mode="Markdown"),
                    reply_markup=markup
                )
                if hasattr(img, 'close'): img.close()
            else:
                bot.edit_message_text("No scores yet!", chat_id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return

        # ── Shop ─────────────────────────────────────────────────────────
        if data.startswith("shop_"):
            item_id  = data.replace("shop_", "")
            username = call.from_user.username or call.from_user.first_name
            ok, msg  = database.purchase_item(bot, chat_id, user_id, username, item_id)
            bot.answer_callback_query(call.id, msg, show_alert=True)
            return

        # ── Admin panel ───────────────────────────────────────────────────
        if data.startswith("admin_") and is_admin(user_id):
            action = data.replace("admin_", "")
            if action == "startchar":
                bot.answer_callback_query(call.id)
                games.start_character_game(bot, chat_id)
            elif action == "startyear":
                bot.answer_callback_query(call.id)
                games.start_year_game(bot, chat_id)
            elif action == "startpicture":
                bot.answer_callback_query(call.id)
                games.start_picture_game(bot, chat_id)
            elif action == "starttrivia":
                bot.answer_callback_query(call.id)
                games.start_trivia_game(bot, chat_id)
            elif action == "schedule":
                bot.answer_callback_query(call.id)
                show_schedule_panel(chat_id)
            elif action == "tagall":
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "📢 Use `/tagall Your message here` to tag all members.", parse_mode="Markdown")
            elif action == "leaderboard":
                bot.answer_callback_query(call.id)
                show_leaderboard(call.message)
            elif action == "rebuild":
                bot.answer_callback_query(call.id, "🔄 Rebuilding cache...")
                threading.Thread(target=graphics.clear_and_rebuild_disk_cache, args=(bot,), daemon=True).start()
                bot.send_message(chat_id, "🔄 Cache rebuild started in background.")
            elif action == "stats":
                bot.answer_callback_query(call.id)
                show_stats(chat_id)
            elif action == "mute":
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "🔇 Use `/mute @username 1h` to mute a user.", parse_mode="Markdown")
            elif action == "broadcast":
                bot.answer_callback_query(call.id)
                bot.send_message(chat_id, "📢 Use `/broadcast YYYY-MM-DD HH:MM Your message here`", parse_mode="Markdown")
            elif action == "back":
                bot.answer_callback_query(call.id)
            return

        # ── Scheduler settings ────────────────────────────────────────────
        if data.startswith("sched_") and is_admin(user_id):
            sched  = load_scheduler()
            action = data.replace("sched_", "")
            if action == "toggle":
                sched["enabled"] = not sched.get("enabled", False)
                save_scheduler(sched)
                status = "enabled ✅" if sched["enabled"] else "disabled ❌"
                bot.answer_callback_query(call.id, f"Scheduler {status}", show_alert=True)
            elif action.startswith("interval_"):
                sched["interval"] = int(action.replace("interval_", ""))
                save_scheduler(sched)
                bot.answer_callback_query(call.id, f"Interval set to {sched['interval']} min", show_alert=True)
            elif action.startswith("type_"):
                sched["game_type"] = action.replace("type_", "")
                save_scheduler(sched)
                bot.answer_callback_query(call.id, f"Game type: {sched['game_type'].title()}", show_alert=True)
            elif action.startswith("timelimit_"):
                sched["answer_time_limit"] = int(action.replace("timelimit_", ""))
                save_scheduler(sched)
                bot.answer_callback_query(call.id, f"Time limit set to {sched['answer_time_limit']}s", show_alert=True)
            show_schedule_panel(chat_id)
            return

        # ── Tag all confirm/cancel ────────────────────────────────────────
        if data == "tagall_confirm" and is_admin(user_id):
            sched    = load_scheduler()
            msg      = sched.get("tagall_pending_msg", "")
            send_chat = sched.get("tagall_pending_chat", chat_id)
            bot.answer_callback_query(call.id)
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            _do_tag_all(send_chat, msg)
            return

        if data == "tagall_cancel":
            bot.answer_callback_query(call.id, "Cancelled.")
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            return

        # ── Quote pagination ──────────────────────────────────────────────
        if data.startswith("qpage_") and is_admin(user_id):
            page = int(data.replace("qpage_", ""))
            text, markup = show_quotes_page(chat_id, page)
            bot.edit_message_text(text, chat_id, call.message.message_id,
                                  reply_markup=markup, parse_mode="Markdown")
            bot.answer_callback_query(call.id)
            return

        # ── Help menu ──────────────────────────────────────────────────────
        if data.startswith("help_"):
            category = data.replace("help_", "")
            text = _get_help_text(category)
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🔙 Back", callback_data="help_main"))
            bot.edit_message_text(text, chat_id, call.message.message_id,
                                  reply_markup=markup, parse_mode="Markdown")
            bot.answer_callback_query(call.id)
            return

        if data == "help_main":
            text = "📖 *ZA SORA GAME CLUB — HELP*\n\nChoose a category below:"
            markup = _build_help_menu()
            bot.edit_message_text(text, chat_id, call.message.message_id,
                                  reply_markup=markup, parse_mode="Markdown")
            bot.answer_callback_query(call.id)
            return

        # ── Matchday menu ─────────────────────────────────────────────────
        if data == "fix_back":
            show_fixtures_inline(chat_id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return

        if data == "fix_md_menu":
            rows = database.fetch_csv_cached(bot, config.FIXTURES_CSV_URL)
            if not rows or len(rows) <= 1:
                bot.answer_callback_query(call.id, "No fixtures available.", show_alert=True)
                return

            home_idx, away_idx, _, _, _ = graphics.detect_fixtures_columns(rows)
            header_offset = 1 if (
                "home" in str(rows[0][home_idx]).lower() or
                rows[0][0].lower() in ["md", "matchday"]
            ) else 0

            seen = set()
            matchdays = []
            for row in rows[header_offset:]:
                md = row[0].strip() if row else ""
                if md and md not in seen:
                    seen.add(md)
                    matchdays.append(md)

            if not matchdays:
                bot.answer_callback_query(call.id, "No matchdays found.", show_alert=True)
                return

            import re as _re
            def _sort_md(md):
                nums = _re.findall(r'\d+', md)
                return (0, int(nums[0])) if nums else (1, md.lower())
            matchdays = sorted(matchdays, key=_sort_md)

            markup = telebot.types.InlineKeyboardMarkup(row_width=3)
            markup.add(*[
                telebot.types.InlineKeyboardButton(
                    f"MD {md}" if md.isdigit() else md,
                    callback_data=f"fix_md_{md}"
                )
                for md in matchdays
            ])
            markup.add(telebot.types.InlineKeyboardButton("🔙 Back", callback_data="fix_back"))

            bot.edit_message_text(
                "📅 *SELECT MATCHDAY:*\n\nTap a matchday to see all fixtures:",
                chat_id, call.message.message_id,
                reply_markup=markup, parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)
            return

        if data.startswith("fix_md_") and data != "fix_md_menu":
            matchday = data[len("fix_md_"):]
            rows     = database.fetch_csv_cached(bot, config.FIXTURES_CSV_URL)
            img      = graphics.generate_matchday_image(bot, rows, matchday)
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except Exception:
                pass
            if img:
                bot.send_photo(
                    chat_id, img,
                    caption=f"📅 *Matchday {matchday} — All Fixtures*",
                    parse_mode="Markdown"
                )
                if hasattr(img, 'close'): img.close()
            else:
                bot.send_message(chat_id, f"❌ No fixtures found for Matchday {matchday}.")
            bot.answer_callback_query(call.id)
            return

        # ── Fixtures navigation ───────────────────────────────────────────
        if data == "fix_pl_menu":
            rows = database.fetch_csv_cached(bot, config.FIXTURES_CSV_URL)
            if not rows or len(rows) <= 1:
                bot.answer_callback_query(call.id, "No fixtures available.", show_alert=True)
                return
            _, teams = _build_fixtures_menu_markup(rows)
            markup = telebot.types.InlineKeyboardMarkup(row_width=2)
            markup.add(*[
                telebot.types.InlineKeyboardButton(t, callback_data=f"fix_pl_{t}")
                for t in teams
            ])
            markup.add(telebot.types.InlineKeyboardButton("🔙 Back", callback_data="fix_back"))
            bot.edit_message_text(
                "📋 *SELECT A PLAYER:*\n\nTap a player to view their fixtures:",
                chat_id, call.message.message_id,
                reply_markup=markup, parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)
            return

        if data.startswith("fix_pl_") and data != "fix_pl_menu":
            player = data[len("fix_pl_"):]
            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                telebot.types.InlineKeyboardButton("🏠 Home", callback_data=f"fix_ctx_{player}_home"),
                telebot.types.InlineKeyboardButton("✈️ Away", callback_data=f"fix_ctx_{player}_away"),
                telebot.types.InlineKeyboardButton("🌍 All",  callback_data=f"fix_ctx_{player}_all"),
                telebot.types.InlineKeyboardButton("🔙 Back", callback_data="fix_pl_menu"),
            )
            bot.edit_message_text(f"🏟️ *{player.upper()} — SELECT MATCH TYPE:*",
                                  chat_id, call.message.message_id,
                                  reply_markup=markup, parse_mode="Markdown")
            bot.answer_callback_query(call.id)
            return

        if data.startswith("fix_ctx_"):
            remainder      = data[len("fix_ctx_"):]
            parts          = remainder.rsplit("_", 1)
            player, context = parts[0], parts[1]
            markup = telebot.types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                telebot.types.InlineKeyboardButton("📅 Upcoming",  callback_data=f"fix_v_{player}_{context}_upcoming"),
                telebot.types.InlineKeyboardButton("✅ Completed", callback_data=f"fix_v_{player}_{context}_completed"),
                telebot.types.InlineKeyboardButton("🔙 Back", callback_data=f"fix_pl_{player}"),
            )
            bot.edit_message_text(f"📊 *{player.upper()} — SELECT STATUS:*",
                                  chat_id, call.message.message_id,
                                  reply_markup=markup, parse_mode="Markdown")
            bot.answer_callback_query(call.id)
            return

        if data.startswith("fix_v_"):
            remainder        = data[len("fix_v_"):]
            parts            = remainder.rsplit("_", 2)
            player, context, status = parts[0], parts[1], parts[2]
            _serve_fixtures_page(chat_id, call.message.message_id, player, context, status, 1)
            bot.answer_callback_query(call.id)
            return

        if data.startswith("fix_pg_"):
            remainder            = data[len("fix_pg_"):]
            parts                = remainder.rsplit("_", 3)
            player, context, status, page = parts[0], parts[1], parts[2], int(parts[3])
            _serve_fixtures_page(chat_id, call.message.message_id, player, context, status, page)
            bot.answer_callback_query(call.id)
            return

    except Exception as e:
        print(f"Callback error: {e}")
        database.log_error_to_admin(bot, "Callback Handler", e)

def _serve_fixtures_page(chat_id, message_id, player, context, status, page):
    rows = database.fetch_csv_cached(bot, config.FIXTURES_CSV_URL)
    img  = graphics.generate_fixtures_image(bot, rows, status, player, context, page)
    if not img:
        bot.send_message(chat_id, f"❌ No {status} matches found for {player.upper()} ({context.upper()}).")
        return
    try:
        markup   = telebot.types.InlineKeyboardMarkup()
        nav_btns = []
        prev_img = graphics.generate_fixtures_image(bot, rows, status, player, context, page - 1)
        next_img = graphics.generate_fixtures_image(bot, rows, status, player, context, page + 1)
        if prev_img:
            nav_btns.append(telebot.types.InlineKeyboardButton("⬅️ Prev", callback_data=f"fix_pg_{player}_{context}_{status}_{page-1}"))
            prev_img.close()
        if next_img:
            nav_btns.append(telebot.types.InlineKeyboardButton("Next ➡️", callback_data=f"fix_pg_{player}_{context}_{status}_{page+1}"))
            next_img.close()
        if nav_btns:
            markup.row(*nav_btns)
        caption = f"📋 *{status.upper()} MATCHES*\n👤 {player.upper()} | 🏟️ {context.upper()} | 📄 Page {page}"
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
        bot.send_photo(chat_id, img, caption=caption, reply_markup=markup, parse_mode="Markdown")
    finally:
        if hasattr(img, 'close'):
            img.close()

# ---------------------------------------------------------------------------
# BACKGROUND SCHEDULER THREAD
# ---------------------------------------------------------------------------

def background_scheduler():
    import random
    print("⏰ Scheduler thread started!")
    while True:
        try:
            now   = local_now()
            hour  = now.hour
            minute = now.minute

            sched = load_scheduler()

            # Morning message at 8:00 AM
            if hour == config.MORNING_MSG_HOUR and minute == config.MORNING_MSG_MIN:
                print("🌅 Sending morning message...")
                send_morning_message(bot)
                time.sleep(61)

            # Weekly recap every Monday at 9:00 AM
            if now.weekday() == 0 and hour == 9 and minute == 0:
                send_weekly_recap(bot)
                time.sleep(61)

            # Daily challenge at 2:00 PM
            if hour == config.DAILY_CHALLENGE_HOUR and minute == config.DAILY_CHALLENGE_MIN:
                games.post_daily_challenge(bot)
                time.sleep(61)

            # Sunday cache rebuild at midnight
            if now.weekday() == 6 and hour == 0 and minute == 0:
                graphics.clear_and_rebuild_disk_cache(bot)
                time.sleep(61)

            # Sunday standings broadcast at noon
            if now.weekday() == 6 and hour == 12 and minute == 0:
                groups  = database.get_all_groups()
                img_data = graphics.generate_table_image(bot)
                if img_data:
                    for g_id in groups:
                        try:
                            img_data.seek(0)
                            bot.send_photo(g_id, img_data, caption="📅 *SUNDAY STANDINGS*", parse_mode="Markdown")
                        except Exception:
                            pass
                    if hasattr(img_data, 'close'): img_data.close()
                time.sleep(61)

            # Monthly reset check (run daily at 00:01)
            if hour == 0 and minute == 1:
                database.check_and_run_monthly_reset(bot)
                database.check_and_run_yearly_reset(bot)
                time.sleep(61)

            # Check for pending broadcasts every minute
            pending = database.get_pending_broadcasts()
            for broadcast in pending:
                try:
                    bot.send_message(broadcast["chat_id"], broadcast["message"], parse_mode="Markdown")
                    # Mark as sent
                    index = pending.index(broadcast)
                    database.mark_broadcast_sent(bot, index)
                except Exception as e:
                    print(f"Broadcast failed: {e}")

            # Auto game scheduler
            if sched.get("enabled"):
                window_start = sched.get("window_start", config.SCHEDULER_WINDOW_START)
                window_end   = sched.get("window_end",   config.SCHEDULER_WINDOW_END)
                in_window    = window_start <= hour < window_end
                interval_sec = sched.get("interval", 60) * 60
                last_game    = sched.get("last_game", 0)

                if in_window and (time.time() - last_game) >= interval_sec:
                    game_type = sched.get("game_type", "random")
                    if game_type == "random":
                        game_type = random.choice(["character", "year", "picture", "trivia"])

                    groups = database.get_all_groups()
                    for g_id in groups:
                        if games._is_game_active(g_id) or g_id in games.versus_games:
                            continue
                        if game_type == "character":
                            games.start_character_game(bot, g_id)
                        elif game_type == "year":
                            games.start_year_game(bot, g_id)
                        elif game_type == "picture":
                            games.start_picture_game(bot, g_id)
                        elif game_type == "trivia":
                            games.start_trivia_game(bot, g_id)

                    sched["last_game"] = time.time()
                    save_scheduler(sched)

        except Exception as e:
            print(f"Scheduler error: {e}")

        time.sleep(30)

# ---------------------------------------------------------------------------
# MISSING IMAGES NOTIFICATION
# ---------------------------------------------------------------------------

def notify_missing_images():
    import re

    def to_filename(name):
        return re.sub(r'[^a-zA-Z0-9._-]', '_', name).strip('_')

    def find_local(name, folder):
        for ext in ['.jpg', '.jpeg', '.png', '.webp']:
            if os.path.exists(os.path.join(folder, to_filename(name) + ext)):
                return True
        return False

    char_folder  = config.LOCAL_CHAR_IMAGES_DIR
    media_folder = config.LOCAL_MEDIA_IMAGES_DIR

    char_dbs = {
        "🌸 Anime":   config.CHAR_ANIME_DB,
        "🦸 DC":      config.CHAR_DC_DB,
        "⚡ Marvel":  config.CHAR_MARVEL_DB,
        "🎮 Gaming":  config.CHAR_GAMING_DB,
    }
    media_dbs = {
        "🎬 Movies":       config.MEDIA_DB,
        "📺 Anime Series": config.ANIME_SERIES_DB,
        "🎥 Anime Films":  config.ANIME_FILMS_DB,
        "🎨 Animation":    config.ANIMATION_DB,
    }

    missing_chars = {}
    missing_media = {}

    for cat, path in char_dbs.items():
        data = database.load_json(path, []) if os.path.exists(path) else []
        if isinstance(data, list):
            missing = [c['name'] for c in data if not find_local(c.get('name', ''), char_folder)]
            if missing:
                missing_chars[cat] = missing

    for cat, path in media_dbs.items():
        data = database.load_json(path, []) if os.path.exists(path) else []
        if isinstance(data, list):
            missing = [m['title'] for m in data if not find_local(m.get('title', ''), media_folder)]
            if missing:
                missing_media[cat] = missing

    total = sum(len(v) for v in missing_chars.values()) + sum(len(v) for v in missing_media.values())

    if total == 0:
        try:
            bot.send_message(config.ADMIN_ID,
                "✅ All local images found! No missing files.",
                parse_mode="Markdown")
        except Exception:
            pass
        return

    msg_lines = []
    msg_lines.append(f"📁 Missing Local Images — {total} total")
    msg_lines.append("(Bot will fall back to URLs for these)")
    msg_lines.append("")

    if missing_chars:
        msg_lines.append("CHARACTERS:")
        for cat, names in missing_chars.items():
            msg_lines.append(f"\n{cat} ({len(names)} missing):")
            for name in names:
                msg_lines.append(f"  • {to_filename(name)}.jpg")

    if missing_media:
        msg_lines.append("\nMEDIA:")
        for cat, titles in missing_media.items():
            msg_lines.append(f"\n{cat} ({len(titles)} missing):")
            for title in titles:
                msg_lines.append(f"  • {to_filename(title)}.jpg")

    full_msg = "\n".join(msg_lines)
    chunk_size = 3500
    chunks = []
    lines = full_msg.splitlines(keepends=True)
    current = ""
    for line in lines:
        if len(current) + len(line) > chunk_size:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)

    for i, chunk in enumerate(chunks):
        try:
            prefix = f"(Part {i+1}/{len(chunks)})\n" if len(chunks) > 1 else ""
            bot.send_message(config.ADMIN_ID, prefix + chunk, parse_mode=None)
        except Exception as e:
            print(f"Missing images notification failed for part {i+1}: {e}")

# ---------------------------------------------------------------------------
# IMAGE UPLOAD VIA TELEGRAM (Admin DM only)
# ---------------------------------------------------------------------------

def handle_image_upload(message):
    import re

    if message.chat.id != config.ADMIN_ID:
        return
    if not message.photo:
        bot.reply_to(message, "❌ Please attach a photo with the command as caption.")
        return

    caption = (message.caption or "").strip()
    if not caption.lower().startswith("/saveimage"):
        return

    parts = caption.split()
    if len(parts) < 3:
        bot.reply_to(message,
            "❌ Usage: `/saveimage Name Here characters` or `/saveimage Name Here media`",
            parse_mode="Markdown")
        return

    folder_arg = parts[-1].lower()
    name       = " ".join(parts[1:-1])

    if folder_arg in ("characters", "character", "char"):
        folder = config.LOCAL_CHAR_IMAGES_DIR
        label  = "characters"
    elif folder_arg in ("media", "movie", "anime", "animation"):
        folder = config.LOCAL_MEDIA_IMAGES_DIR
        label  = "media"
    else:
        bot.reply_to(message,
            "❌ Folder must be `characters` or `media`",
            parse_mode="Markdown")
        return

    os.makedirs(folder, exist_ok=True)

    file_id   = message.photo[-1].file_id
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', name).strip('_')
    filename  = f"{safe_name}.jpg"
    filepath  = os.path.join(folder, filename)

    try:
        file_info = bot.get_file(file_id)
        dl_url    = f"https://api.telegram.org/file/bot{config.API_TOKEN}/{file_info.file_path}"
        import requests
        response  = requests.get(dl_url, timeout=15)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(response.content)
        size_kb = len(response.content) // 1024
        bot.reply_to(message,
            f"✅ *Saved!*\n"
            f"📁 `local_images/{label}/{filename}`\n"
            f"📦 {size_kb} KB",
            parse_mode="Markdown")
        print(f"[IMG UPLOAD] Saved: {filepath} ({size_kb}KB)")
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to save image: {e}")
        print(f"[IMG UPLOAD] Error: {e}")

# ---------------------------------------------------------------------------
# REGISTER COMMANDS WITH TELEGRAM
# ---------------------------------------------------------------------------

def register_commands():
    public_commands = [
        telebot.types.BotCommand("start",       "👋 Welcome message & how to play"),
        telebot.types.BotCommand("help",         "📖 Full command list"),
        telebot.types.BotCommand("game",         "👤 Guess the Character"),
        telebot.types.BotCommand("year",         "🎬 Guess the Release Year"),
        telebot.types.BotCommand("picture",      "🖼️ Scrambled Image Guessing"),
        telebot.types.BotCommand("trivia",       "❓ Multiple choice trivia"),
        telebot.types.BotCommand("spin",         "🎰 Wheel of Fortune"),
        telebot.types.BotCommand("versus",       "⚔️ Challenge another player"),
        telebot.types.BotCommand("forfeit",      "🏳️ Forfeit an active versus match"),
        telebot.types.BotCommand("hint",         "💡 Get a hint (costs points)"),
        telebot.types.BotCommand("stop",         "🛑 Stop the current game"),
        telebot.types.BotCommand("leaderboard",  "🏆 View the rankings"),
        telebot.types.BotCommand("mystats",      "📊 View your personal stats"),
        telebot.types.BotCommand("profile",      "👤 View your profile card"),
        telebot.types.BotCommand("shop",         "🛒 Spend your points"),
        telebot.types.BotCommand("categories",   "🗂️ View trivia categories"),
        telebot.types.BotCommand("table",        "📋 League standings"),
        telebot.types.BotCommand("fixtures",     "📅 Match fixtures"),
    ]

    admin_commands = public_commands + [
        telebot.types.BotCommand("admin",        "⚙️ Admin control panel"),
        telebot.types.BotCommand("tagall",       "📢 Tag all members"),
        telebot.types.BotCommand("setschedule",  "🕐 Configure auto-game scheduler"),
        telebot.types.BotCommand("mute",         "🔇 Mute a user"),
        telebot.types.BotCommand("unmute",       "🔊 Unmute a user"),
        telebot.types.BotCommand("broadcast",    "📢 Schedule a broadcast"),
        telebot.types.BotCommand("uploadtrivia", "📤 Upload trivia questions"),
        telebot.types.BotCommand("addquote",     "➕ Add a quote (DM only)"),
        telebot.types.BotCommand("listquotes",   "📝 List all quotes (DM only)"),
        telebot.types.BotCommand("editquote",    "✏️ Edit a quote (DM only)"),
        telebot.types.BotCommand("deletequote",  "🗑️ Delete a quote (DM only)"),
        telebot.types.BotCommand("previewquote", "👁️ Preview a quote (DM only)"),
        telebot.types.BotCommand("testmorning",  "🧪 Test morning message (admin)"),
    ]

    try:
        bot.set_my_commands(public_commands)
        bot.set_my_commands(
            admin_commands,
            scope=telebot.types.BotCommandScopeChat(chat_id=config.ADMIN_ID)
        )
        print("✅ Bot commands registered with Telegram.")
    except Exception as e:
        print(f"⚠️ Failed to register commands: {e}")

# ---------------------------------------------------------------------------
# HELP COMMAND
# ---------------------------------------------------------------------------

def show_help(message):
    chat_id = message.chat.id
    text = "📖 *ZA SORA GAME CLUB — HELP*\n\nChoose a category below:"
    markup = _build_help_menu()
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

# ---------------------------------------------------------------------------
# MY STATS COMMAND
# ---------------------------------------------------------------------------

def show_my_stats(message):
    chat_id  = message.chat.id
    user_id  = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    data     = database.load_json(config.GROUP_DATA_FILE, {})
    chat_str = str(chat_id)
    user_str = str(user_id)

    if chat_str not in data or user_str not in data[chat_str]:
        bot.reply_to(message, "❌ No stats found yet. Play a game first!")
        return

    u         = data[chat_str][user_str]
    month_key = database._now_month_key()
    year_key  = database._now_year_key()

    monthly  = u.get("monthly_points", {}).get(month_key, 0)
    yearly   = u.get("yearly_points",  {}).get(year_key,  0)
    alltime  = u.get("alltime_points", 0)
    streak   = u.get("streak",       0)
    best     = u.get("best_streak",  0)
    played   = u.get("games_played", 0)
    correct  = u.get("correct",      0)
    title    = database._get_active_title(u) or "None"
    hints    = u.get("hint_tokens",  0)
    badges   = u.get("badges", [])
    accuracy = f"{int((correct / played) * 100)}%" if played > 0 else "N/A"

    lb   = database.get_leaderboard(chat_id, mode="monthly", top_n=100)
    rank = next((r for r, name, *_ in lb if name == username), "?")

    double_xp = u.get("double_xp_until")
    xp_status = ""
    if double_xp and time.time() < double_xp:
        mins_left = int((double_xp - time.time()) / 60)
        xp_status = f"\n⚡ *Double XP active:* {mins_left} min remaining"

    badge_icons = " ".join([config.ACHIEVEMENTS.get(b, {}).get("icon", "🏅") for b in badges]) if badges else "None"
    powerups = u.get("powerups", {})
    powerup_str = ", ".join([f"{config.POWERUPS.get(k, {}).get('emoji', k)} {k.replace('_',' ').title()} x{v}" for k, v in powerups.items() if v > 0]) or "None"

    text = (
        f"📊 *{username}'s Stats*\n\n"
        f"🏅 *Title:* {title}\n"
        f"🏆 *Monthly rank:* #{rank}\n\n"
        f"💰 *Points*\n"
        f"This month: {monthly} pts\n"
        f"This year: {yearly} pts\n"
        f"All time: {alltime} pts\n\n"
        f"🎮 *Games*\n"
        f"Played: {played}\n"
        f"Correct: {correct}\n"
        f"Accuracy: {accuracy}\n\n"
        f"🔥 *Streak*\n"
        f"Current: {streak}\n"
        f"Best ever: {best}\n\n"
        f"💡 *Hint tokens:* {hints}\n"
        f"📛 *Badges:* {badge_icons}\n"
        f"⚡ *Power-ups:* {powerup_str}\n"
        f"{xp_status}"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# ---------------------------------------------------------------------------
# CATEGORIES COMMAND
# ---------------------------------------------------------------------------

def show_categories(message):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(*[
        telebot.types.InlineKeyboardButton(f"{cat}", callback_data=f"startcat_{cat}")
        for cat in config.TRIVIA_CATEGORIES
    ])
    bot.send_message(
        message.chat.id,
        "🗂️ *TRIVIA CATEGORIES*\n\nTap a category to start a trivia round:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("🚀 Za Sora Bot starting...")
    register_commands()
    games.precache_assets(bot)
    graphics.clear_and_rebuild_disk_cache(bot)
    database.check_and_run_monthly_reset(bot)
    database.cleanup_expired_mutes(bot)
    threading.Thread(target=background_scheduler, daemon=True).start()
    threading.Thread(target=notify_missing_images, daemon=True).start()
    print("✅ Bot is live!")
    bot.infinity_polling(timeout=20, long_polling_timeout=30)