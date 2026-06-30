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
#    (these were inside if __name__ == "__main__" before)
# ------------------------------------------------------------
def start_scheduler():
    # This function is defined in bot.py as 'background_scheduler'
    bot.background_scheduler()

def start_broadcast_checker():
    # This function is defined in bot.py as 'broadcast_checker'
    bot.broadcast_checker()

# Start both as daemon threads so they run alongside Gunicorn
scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
scheduler_thread.start()

broadcast_thread = threading.Thread(target=start_broadcast_checker, daemon=True)
broadcast_thread.start()

print("🚀 Scheduler and broadcast checker threads started.")

# ------------------------------------------------------------
# 3. Flask app for Render's health checks
# ------------------------------------------------------------
from flask import Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Za Sora Bot is running! 🚀"
