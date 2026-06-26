import os
import sys
import threading
import time
import fcntl

# Disable proxies
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['NO_PROXY'] = '*'

from telebot import apihelper
apihelper.proxy = None

import bot

# Delete any existing webhook to avoid conflict
bot.bot.delete_webhook()
time.sleep(2)  # Allow Telegram to process the deletion

LOCK_FILE = '/tmp/bot_polling.lock'

def run_bot():
    try:
        with open(LOCK_FILE, 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print("✅ Bot polling started.")
            bot.bot.infinity_polling()
    except (IOError, OSError):
        print("⚠️ Another bot instance is already polling. Skipping.")
        return

thread = threading.Thread(target=run_bot, daemon=True)
thread.start()

from flask import Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Za Sora Bot is running! 🚀"
