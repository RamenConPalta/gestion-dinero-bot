import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)
import gspread
from google.oauth2.service_account import Credentials
import asyncio
# =========================
# VARIABLES DE ENTORNO
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

import json

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot activo ✅")

async def add_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sheet.append_row(["Prueba", "100", "Ingreso"])
    await update.message.reply_text("Fila añadida al Sheet ✅")

application = ApplicationBuilder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("test", add_test))

# =========================
# FLASK SERVER (Render necesita esto)
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot funcionando"

# =========================
# EJECUCIÓN PARA RENDER
# =========================

import asyncio

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application.run_polling()

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    app.run(host="0.0.0.0", port=10000)
