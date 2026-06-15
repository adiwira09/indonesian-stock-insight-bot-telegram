import time
import json
import requests
import logging
from datetime import date

import schedule
import threading

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import API_URL, BOT_TOKEN, DAILY_TIME

# logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

bot = telebot.TeleBot(BOT_TOKEN) # bot configuration

# load holiday json
with open("market_holiday_2026.json", encoding="utf-8") as f:
    holidays = json.load(f)

# helper functions
def current_date():
    return date.today()

def notification_message():
    holiday, reason = is_holiday()
    
    if holiday:
        return  f"""⚠️ *Hari Libur Pasar ({reason})* ⚠️

Berita dan Insight Saham tidak tersedia saat pasar libur. Silakan cek kembali pada hari bursa berikutnya."""

    return  f"""*🔔 UPDATE ({current_date().strftime('%d/%m/%Y')}) 🔔*

Kami memiliki insight saham terbaru dan berita terkini seputar pasar untuk Anda!

Silakan klik tombol di bawah untuk melihat informasi lebih lengkap.
"""

holiday_count = 0
def is_holiday(check_date=None):
    check_date = check_date or current_date()

    if check_date.weekday() == 5:
        return True, "Sabtu"
    if check_date.weekday() == 6:
        return True, "Minggu"

    reason = holidays.get(check_date.isoformat())    
    if reason:
        return True, reason
    return False, None
    
users_cache = None
def fetch_users():
    global users_cache
    try:
        response = requests.get(f"{API_URL}/user/?is_active=true", timeout=10)
        response.raise_for_status()
        users_cache = response.json()
        logging.info(f"Active users loaded and cached successfully ({len(users_cache)} users)")
    except Exception as e:
        logging.error(f"Error fetching active users: {e}")
        users_cache = []

news_cache = None
ticker_cache = None
def load_news(days_ago=1):
    global news_cache, ticker_cache
    try:
        response = requests.get(f"{API_URL}/news/?days_ago={days_ago}&limit=5", timeout=10)
        response.raise_for_status()
        data = response.json().get("data", [])

        message = (f"*📰 UPDATE BERITA ({current_date().strftime('%d/%m/%Y')}) 📰*\n\n")
        tickers = []
        for news in data:
            message += (
                f"*{news['judul'].upper()}*\n\n"
                f"{news['summary']}\n"
                f"[📚 Baca Selengkapnya]({news['url']})\n\n"
            )
            ticker = news['ticker']
            tickers.extend(ticker)

        news_cache = message
        ticker_cache = list(set(tickers))

        logging.info("News loaded and cached successfully.")

    except Exception as e:
        logging.error(f"Error loading news: {e}")
        return []

# tombol menu utama
def main_menu_button():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📰 Berita Hari Ini", callback_data="berita"),
        InlineKeyboardButton("📊 Insight Saham", callback_data="saham")
    )
    return markup

def ticker_button():
    markup = InlineKeyboardMarkup()
    
    row = []
    row_count = 3

    for i, ticker in enumerate(ticker_cache, start=1):
        row.append(InlineKeyboardButton(ticker, callback_data=f"stock_{ticker.upper()}"))
        if i % row_count == 0:
            markup.row(*row)
            row = []
    if row:  # add remaining buttons if any
        markup.row(*row)
    
    markup.row(InlineKeyboardButton("🏠 Kembali ke Menu", callback_data="menu"))
    return markup

# HANDLER COMMAND
# /start
@bot.message_handler(commands=['start'])
def start(message):
    payload = {
        "id": str(message.from_user.id),
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "last_name": message.from_user.last_name
    }

    try:
        response = requests.post(
            f"{API_URL}/user/upsert",
            json=payload,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()
        state = data.get("state")

        if state == "new_user":
            logging.info(f"New user registered: {payload['id']}")
            text = "Selamat datang! Anda akan menerima notifikasi tentang berita dan insight saham"
        elif state in ("reactivated", "returning_user"):
            logging.info(f"Returning user: {payload['id']}")
            text = "Selamat datang kembali!"
        elif state == "api_error":
            logging.error(f"API error while inserting user: {payload['id']}")
            text = (
                "Server sedang sibuk.\n"
                "Silakan coba lagi nanti."
            )
        
        success = True
        
    except requests.exceptions.Timeout:
        logging.error("API timeout")
        text = "Server timeout. Coba lagi sebentar."

    except requests.exceptions.ConnectionError:
        logging.error("Cannot connect to API server")
        text = "Tidak dapat terhubung ke server."

    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error: {e}")
        text = "Server sedang mengalami gangguan."

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        text = "Terjadi kesalahan saat mendaftar."

    bot.send_message(message.chat.id, text, parse_mode="Markdown")
    if success:
        main_menu(message)

# /stop
@bot.message_handler(commands=['stop'])
def stop(message):
    id = str(message.from_user.id)
    try:
        response = requests.post(
            f"{API_URL}/user/stop/{id}",
            timeout=10
        )
        response.raise_for_status()

        data = response.json()
        state = data.get("state")

        if state == "stopped":
            logging.info(f"User stopped: {id}")
            text = (
                "Anda telah berhenti berlangganan notifikasi.\n"
                "Kalau mau aktif lagi, tinggal /start kapan pun"
            )

        elif state == "already_stopped":
            logging.info(f"User already stopped: {id}")
            text = (
                "Anda sudah berhenti berlangganan notifikasi sebelumnya\n"
                "Kalau mau aktif lagi, tinggal /start kapan pun"
            )

    except requests.exceptions.Timeout:
        logging.error("API timeout during /stop")
        text = "Server timeout. Silakan coba lagi sebentar"

    except requests.exceptions.ConnectionError:
        logging.error("Cannot connect to API server")
        text = "Tidak dapat terhubung ke server"

    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error during /stop: {e}")
        text = "Server sedang mengalami gangguan"

    except Exception as e:
        logging.exception(f"Unexpected error during /stop: {e}")
        text = "Terjadi kesalahan saat memproses permintaan Anda"

    bot.send_message(message.chat.id, text, parse_mode="Markdown")        

# /menu
@bot.message_handler(commands=['menu'])
def main_menu(message):
    bot.send_message(
        message.chat.id, 
        notification_message(), 
        reply_markup=main_menu_button(),
        parse_mode="Markdown"
    )

# CALLBACK HANDLER INLINE BUTTON
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "berita":
        if holiday_count > 0:
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🏠 Kembali ke Menu Utama", callback_data="menu"))

            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Berita tidak tersedia karena hari ini adalah hari libur pasar. Silakan cek kembali pada hari berikutnya.",
                reply_markup=markup,
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)
            return

        # tombol kembali ke menu utama
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🏠 Kembali ke Menu", callback_data="menu"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=news_cache,
            reply_markup=markup,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    elif call.data == "saham":
        if holiday_count > 0:
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🏠 Kembali ke Menu Utama", callback_data="menu"))

            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Insight saham tidak tersedia karena hari ini adalah hari libur pasar. Silakan cek kembali pada hari berikutnya.",
                reply_markup=markup,
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)
            return

        # tombol kembali ke menu utama
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🏠 Kembali ke Menu", callback_data="menu"))

        message = f"*📊 INSIGHT SAHAM ({current_date().strftime('%d/%m/%Y')})*\n\nSilakan pilih kode saham di bawah ini:"
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=message,
            reply_markup=ticker_button(),
            parse_mode="Markdown"
        )
    
    elif call.data.startswith("stock_"):

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔙 Kembali ke Daftar Saham", callback_data="saham"))
        markup.row(InlineKeyboardButton("🏠 Kembali ke Menu Utama", callback_data="menu"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Fitur insight saham sedang dalam pengembangan. Nantikan update selanjutnya!",
            reply_markup=markup
        )

    elif call.data == "menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=notification_message(),
            reply_markup=main_menu_button(),
            parse_mode="Markdown"
        )
    
    bot.answer_callback_query(call.id) # menghilangkan loading indicator

# SCHEDULE TASK
def send_notification_daily():
    global holiday_count

    holiday, reason = is_holiday(current_date())
    if holiday:
        holiday_count += 1
        logging.info(f"Today is a holiday ({reason}). Skipping daily notification.")
        return
        
    load_news(days_ago=holiday_count + 1)
    fetch_users()

    if not users_cache:
        logging.info("No active users found")
        return

    if not news_cache:
        logging.info("No news found")
        return

    logging.info("Sending daily news update...")

    for user in users_cache:
        try:
            bot.send_message(
                chat_id=user["id"],
                text=notification_message(),
                parse_mode="Markdown",
                reply_markup=main_menu_button()
            )
        except Exception as e:
            logging.error(f"Error sending notification to user {user['id']}: {e}")
    
    logging.info("Daily notification task completed")
    logging.info(f"Next scheduled run: {schedule.next_run()}")
    holiday_count = 0 # reset holiday count after sending notification

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

schedule.every().day.at(DAILY_TIME).do(send_notification_daily)

# MAIN
def main():
    # initial holiday check
    global holiday_count
    
    holiday, reason = is_holiday()
    if holiday:
        holiday_count += 1
        logging.info(f"Today is a holiday ({reason}). Bot will start but skip fetching data.")
    else:
        # initial data load
        fetch_users()
        load_news()
        logging.info("Today is not a holiday. Bot will start normally.")

    # start scheduler thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # start bot
    logging.info("Bot started...")
    bot.infinity_polling()

if __name__ == "__main__":
    main()