import os
import sys
import threading
import time

# Disable proxies
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['NO_PROXY'] = '*'

from telebot import apihelper
apihelper.proxy = None

# Import your bot
import bot
import profile_banner  # <-- NEW

# Delete any existing webhook to avoid conflict
bot.bot.delete_webhook()
time.sleep(2)  # Let Telegram process

# ------------------------------------------------------------
# 1. Start the bot polling thread
# ------------------------------------------------------------
def run_bot():
    bot.bot.infinity_polling()

thread = threading.Thread(target=run_bot, daemon=True)
thread.start()

# ------------------------------------------------------------
# 2. Start the scheduler and broadcast checker threads
# ------------------------------------------------------------
def start_scheduler():
    bot.start_scheduler()

def start_broadcast_checker():
    bot.start_broadcast_checker()

# Start both as daemon threads so they run alongside Gunicorn
start_scheduler()
start_broadcast_checker()

print("🚀 Scheduler and broadcast checker threads started.")

# ------------------------------------------------------------
# 3. NEW: Pre-generate profile banners for all users in background
# ------------------------------------------------------------
def pre_generate_banners():
    # Small delay to let the bot fully initialize
    time.sleep(5)
    profile_banner.pre_generate_all_banners(bot.bot)

banner_thread = threading.Thread(target=pre_generate_banners, daemon=True)
banner_thread.start()
print("🖼️ Background banner pre-generation started.")

# ------------------------------------------------------------
# 4. Flask app for Render's health checks
# ------------------------------------------------------------
from flask import Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Za Sora Bot is running! 🚀"
