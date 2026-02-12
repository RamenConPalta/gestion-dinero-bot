import logging
import os
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ===== CONFIG =====
TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")

# ===== GOOGLE SHEETS AUTH =====
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file(
    "service_account.json",
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
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot funcionando...")
    app.run_polling()
