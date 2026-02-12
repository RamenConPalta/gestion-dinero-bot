import os
import json
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from google.oauth2.service_account import Credentials
import gspread
import asyncio
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

app = Flask(__name__)
application = ApplicationBuilder().token(TOKEN).build()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot funcionando 🚀")


application.add_handler(CommandHandler("start", start))


@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return "ok"


@app.route("/")
def home():
    return "Bot activo"


# =========================
# START
# =========================

import asyncio

async def main():
    await application.initialize()
    await application.bot.set_webhook(
        url=f"https://gestion-dinero-bot.onrender.com/{TOKEN}"
    )
    await application.start()

if __name__ == "__main__":
    asyncio.run(main())

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
