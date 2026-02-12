import os
import json
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from google.oauth2.service_account import Credentials
import gspread

# =========================
# VARIABLES
# =========================

TOKEN = os.environ.get("BOT_TOKEN")
SHEET_NAME = os.environ.get("SPREADSHEET_NAME")

# =========================
# GOOGLE SHEETS
# =========================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds_json = os.environ.get("GOOGLE_CREDENTIALS")
creds_dict = json.loads(creds_json)

credentials = Credentials.from_service_account_info(
    creds_dict,
    scopes=scope
)

client = gspread.authorize(credentials)
sheet = client.open(SHEET_NAME).worksheet("REGISTRO")

# =========================
# TELEGRAM BOT
# =========================

flask_app = Flask(__name__)
application = ApplicationBuilder().token(TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot funcionando 🚀")

application.add_handler(CommandHandler("start", start))

# =========================
# WEBHOOK
# =========================

@flask_app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, application.bot)

    asyncio.run(application.process_update(update))

    return "ok"

@flask_app.route("/")
def home():
    return "Bot activo"

# =========================
# START
# =========================

async def setup():
    await application.initialize()
    await application.bot.set_webhook(
        url=f"https://gestion-dinero-bot.onrender.com/{TOKEN}"
    )
    await application.start()

if __name__ == "__main__":
    asyncio.run(setup())

    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
