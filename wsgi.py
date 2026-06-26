# wsgi.py
import os
import sys
import threading

# Disable all proxies (just in case)
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['NO_PROXY'] = '*'

# Disable telebot's proxy
from telebot import apihelper
apihelper.proxy = None

# Import your bot (this runs the bot.py file)
import bot

# Start the bot in a background thread
def run_bot():
    bot.bot.infinity_polling()

thread = threading.Thread(target=run_bot, daemon=True)
thread.start()

# Flask web server to keep Render alive and provide a status page
from flask import Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Za Sora Bot is running! 🚀"

# For Render, the entry point is this Flask app.