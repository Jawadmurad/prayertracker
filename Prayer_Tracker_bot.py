import telebot
from telebot import types
import sqlite3
import pytz
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import os

# ==========================================
# 1. ADD YOUR TELEGRAM BOT TOKEN HERE
# ==========================================
# It is best to use environment variables in Choreo, but you can paste it directly here.
TOKEN = os.getenv("TELEGRAM_TOKEN")

bot = telebot.TeleBot(TOKEN)

# Timezone setup
DAMASCUS_TZ = pytz.timezone('Asia/Damascus')

# Mapping for all Arabic and English accepted inputs
PRAYER_MAP = {
    'fajr': 'Fajr', 'الفجر': 'Fajr', 'فجر': 'Fajr', 'صبح': 'Fajr', 'الصبح': 'Fajr',
    'duhur': 'Duhur', 'ضهر': 'Duhur', 'الضهر': 'Duhur', 'الظهر': 'Duhur', 'ظهر': 'Duhur',
    'asr': 'Asr', 'عصر': 'Asr', 'العصر': 'Asr',
    'maghrib': 'Maghrib', 'mighrib': 'Maghrib', 'مغرب': 'Maghrib', 'المغرب': 'Maghrib',
    'ishaa': 'Ishaa', 'عشاء': 'Ishaa', 'العشاء': 'Ishaa', 'عشا': 'Ishaa', 'العشا': 'Ishaa'
}

# ==========================================
# 2. DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('prayers.db', check_same_thread=False)
    cursor = conn.cursor()
    # Create table for missed prayers. 'made_up' is 0 (no) or 1 (yes)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS missed_prayers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            prayer_name TEXT,
            date_missed TEXT,
            made_up INTEGER DEFAULT 0
        )
    ''')
    # Store user IDs for automated broadcast messages
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()

def log_prayer(user_id, prayer_name):
    conn = sqlite3.connect('prayers.db')
    cursor = conn.cursor()
    date_str = datetime.now(DAMASCUS_TZ).strftime("%Y-%m-%d")
    cursor.execute("INSERT INTO missed_prayers (user_id, prayer_name, date_missed) VALUES (?, ?, ?)", 
                   (user_id, prayer_name, date_str))
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

# ==========================================
# 3. BOT HANDLERS & LOGIC
# ==========================================

# Command: /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    conn = sqlite3.connect('prayers.db')
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton("Fajr")
    btn2 = types.KeyboardButton("Duhur")
    btn3 = types.KeyboardButton("Asr")
    btn4 = types.KeyboardButton("Maghrib")
    btn5 = types.KeyboardButton("Ishaa")
    btn6 = types.KeyboardButton("📊 Get Report")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    
    bot.reply_to(message, "Assalamu Alaikum! Welcome to your Qada Tracker.\n"
                          "You can type the name of the missed prayer (in Arabic or English), "
                          "or use the buttons below. May Allah make it easy for you to maintain your prayers.", 
                 reply_markup=markup)

# Command: /report or Button: 📊 Get Report
@bot.message_handler(commands=['report'])
@bot.message_handler(func=lambda msg: msg.text == "📊 Get Report")
def handle_report(message):
    generate_report(message.chat.id, "Lifetime")

def generate_report(user_id, period, date_prefix=""):
    conn = sqlite3.connect('prayers.db')
    cursor = conn.cursor()
    
    if period == "Lifetime":
        cursor.execute("SELECT prayer_name, COUNT(*) FROM missed_prayers WHERE user_id=? AND made_up=0 GROUP BY prayer_name", (user_id,))
    else:
        cursor.execute("SELECT prayer_name, COUNT(*) FROM missed_prayers WHERE user_id=? AND made_up=0 AND date_missed LIKE ? GROUP BY prayer_name", (user_id, f"{date_prefix}%"))
    
    results = cursor.fetchall()
    conn.close()
    
    if not results:
        bot.send_message(user_id, f"Alhamdulillah! You have no un-made-up missed prayers for this {period.lower()}.")
        return
    
    report = f"📜 *{period} Missed Prayers Report:*\n\n"
    total = 0
    for row in results:
        report += f"🔹 {row[0]}: {row[1]}\n"
        total += row[1]
    
    report += f"\n*Total pending Qada: {total}*\n"
    report += "To mark a prayer as made up, type `/makeup <PrayerName>` (e.g., `/makeup Fajr`)"
    
    bot.send_message(user_id, report, parse_mode="Markdown")

# Command: /makeup (Creative feature to mark prayers as done)
@bot.message_handler(commands=['makeup'])
def make_up_prayer(message):
    try:
        prayer = message.text.split()[1].strip().lower()
        if prayer not in PRAYER_MAP:
            bot.reply_to(message, "Please specify a valid prayer. Example: `/makeup Fajr`", parse_mode="Markdown")
            return
            
        std_prayer = PRAYER_MAP[prayer]
        conn = sqlite3.connect('prayers.db')
        cursor = conn.cursor()
        
        # Find the oldest missed prayer of this type that hasn't been made up yet
        cursor.execute("SELECT id FROM missed_prayers WHERE user_id=? AND prayer_name=? AND made_up=0 ORDER BY date_missed ASC LIMIT 1", (message.chat.id, std_prayer))
        row = cursor.fetchone()
        
        if row:
            cursor.execute("UPDATE missed_prayers SET made_up=1 WHERE id=?", (row[0],))
            conn.commit()
            bot.reply_to(message, f"May Allah accept it! One missed {std_prayer} has been marked as made up. 🤲")
        else:
            bot.reply_to(message, f"You don't have any recorded missed {std_prayer} prayers. Alhamdulillah!")
        conn.close()
    except IndexError:
        bot.reply_to(message, "Please include the prayer name. Example: `/makeup Fajr`", parse_mode="Markdown")

# Catch-all text handler for logging prayers
@bot.message_handler(func=lambda message: True)
def process_text(message):
    text = message.text.strip().lower()
    
    if text in PRAYER_MAP:
        std_prayer = PRAYER_MAP[text]
        log_prayer(message.chat.id, std_prayer)
        
        dua = "May Allah forgive you and help you establish your prayers. 🤲"
        bot.reply_to(message, f"Recorded: Missed **{std_prayer}**.\n{dua}", parse_mode="Markdown")
    else:
        bot.reply_to(message, "I didn't recognize that prayer name. Please try again (e.g., Fajr, ظهر, Maghrib).")

# ==========================================
# 4. AUTOMATED SCHEDULED REPORTS
# ==========================================
def broadcast_reports(period, date_prefix=""):
    conn = sqlite3.connect('prayers.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    for user in users:
        try:
            generate_report(user[0], period, date_prefix)
        except Exception as e:
            print(f"Failed to send to {user[0]}: {e}")

def daily_job():
    today = datetime.now(DAMASCUS_TZ).strftime("%Y-%m-%d")
    broadcast_reports("Daily", today)

def monthly_job():
    month = datetime.now(DAMASCUS_TZ).strftime("%Y-%m")
    broadcast_reports("Monthly", month)

def yearly_job():
    year = datetime.now(DAMASCUS_TZ).strftime("%Y")
    broadcast_reports("Yearly", year)

scheduler = BackgroundScheduler(timezone=DAMASCUS_TZ)
# Daily at 23:50 (11:50 PM)
scheduler.add_job(daily_job, 'cron', hour=23, minute=50)
# Monthly on the 1st day at 23:55
scheduler.add_job(monthly_job, 'cron', day='last', hour=23, minute=55)
# Yearly on Dec 31st at 23:59
scheduler.add_job(yearly_job, 'cron', month=12, day=31, hour=23, minute=59)

scheduler.start()

# ==========================================
# 5. WEBHOOK WEB SERVER & START THE BOT
# ==========================================
from flask import Flask, request
import time
import sys

app = Flask(__name__)
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# This listens for incoming messages from Telegram
@app.route('/', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return "OK"

# This keeps Choreo's health checks happy
@app.route('/', methods=['GET'])
def index():
    return "Bot is alive and running via Webhook!"

if __name__ == "__main__":
    if WEBHOOK_URL:
        try:
            print("Removing old webhook...")
            bot.remove_webhook()
            time.sleep(1)
            
            print(f"Setting new webhook to: {WEBHOOK_URL}")
            bot.set_webhook(url=WEBHOOK_URL)
            print("Webhook set successfully! 🚀")
        except Exception as e:
            print("===================================")
            print(f"❌ FATAL TELEGRAM API ERROR: {e}")
            print("===================================")
    else:
        print("❌ ERROR: WEBHOOK_URL is completely missing from Environment Variables!")

    # Start the Flask web server on port 8080 (this will keep the container alive)
    try:
        print("Starting Flask server on port 8080...")
        app.run(host="0.0.0.0", port=8080)
    except Exception as e:
        print(f"❌ FLASK SERVER CRASHED: {e}")
