# flask_app.py – runs your bot in the background
import os
import threading
import telebot
from telebot import apihelper

# Disable proxies
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
apihelper.proxy = None

# Import your bot (make sure bot.py is in the same directory)
import bot

# Flask app to keep the process alive (required for web app)
from flask import Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

# Start the bot in a background thread
def run_bot():
    # The bot's infinity_polling will run here
    bot.bot.infinity_polling()

# Launch the bot in a daemon thread
thread = threading.Thread(target=run_bot, daemon=True)
thread.start()