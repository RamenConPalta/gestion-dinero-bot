import logging
import os
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
import threading

# ===== CONFIG =====
TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")

# ===== GOOGLE SHEETS AUTH =====
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

import json

google_credentials = os.getenv("GOOGLE_CREDENTIALS")
creds_dict = json.loads(google_credentials)

creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=scope
)

client = gspread.authorize(creds)
spreadsheet = client.open(SPREADSHEET_NAME)
registro_sheet = spreadsheet.worksheet("REGISTRO")

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["➕ Añadir registro"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "💰 Bienvenido al sistema de gestión de dinero",
        reply_markup=reply_markup
    )

# ===== MENSAJES =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "➕ Añadir registro":
        registro_sheet.append_row(["Prueba desde Telegram"])
        await update.message.reply_text("Registro añadido correctamente ✅")

# ===== MAIN =====
def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot funcionando...")
    application.run_polling()


if __name__ == "__main__":
    # Iniciar bot en hilo separado
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()

    # Crear servidor web para Render
    app = Flask(__name__)

    @app.route("/")
    def home():
        return "Bot activo"

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
