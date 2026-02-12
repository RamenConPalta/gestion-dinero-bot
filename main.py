import os
import json
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from google.oauth2.service_account import Credentials
import gspread

# =====================================================
# VARIABLES DE ENTORNO
# =====================================================

TOKEN = os.environ.get("BOT_TOKEN")
SHEET_NAME = os.environ.get("SPREADSHEET_NAME")
PORT = int(os.environ.get("PORT", 10000))

# =====================================================
# GOOGLE SHEETS
# =====================================================

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

# =====================================================
# ESTADOS
# =====================================================

TIPO, CATEGORIA, SUB1, SUB2, SUB3, MONTO = range(6)

# =====================================================
# START
# =====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Ingreso", "Gasto"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "¿Es un Ingreso o un Gasto?",
        reply_markup=reply_markup
    )
    return TIPO

# =====================================================
# TIPO
# =====================================================

async def tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tipo"] = update.message.text

    keyboard = [
        ["Personal", "Casa"],
        ["Trabajo"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Selecciona categoría:",
        reply_markup=reply_markup
    )
    return CATEGORIA

# =====================================================
# CATEGORIA
# =====================================================

async def categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["categoria"] = update.message.text

    keyboard = [
        ["Sub1_A", "Sub1_B"],
        ["Sub1_C"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Selecciona Sub1:",
        reply_markup=reply_markup
    )
    return SUB1

# =====================================================
# SUB1
# =====================================================

async def sub1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sub1"] = update.message.text

    keyboard = [
        ["Sub2_A", "Sub2_B"],
        ["Sub2_C"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Selecciona Sub2:",
        reply_markup=reply_markup
    )
    return SUB2

# =====================================================
# SUB2
# =====================================================

async def sub2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sub2"] = update.message.text

    keyboard = [
        ["Sub3_A", "Sub3_B"],
        ["Sub3_C"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Selecciona Sub3:",
        reply_markup=reply_markup
    )
    return SUB3

# =====================================================
# SUB3
# =====================================================

async def sub3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sub3"] = update.message.text

    await update.message.reply_text(
        "Introduce el monto:"
    )
    return MONTO

# =====================================================
# MONTO Y GUARDAR
# =====================================================

async def monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["monto"] = update.message.text

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    sheet.append_row([
        fecha,
        context.user_data.get("tipo"),
        context.user_data.get("categoria"),
        context.user_data.get("sub1"),
        context.user_data.get("sub2"),
        context.user_data.get("sub3"),
        context.user_data.get("monto")
    ])

    await update.message.reply_text("Movimiento guardado ✅")

    return ConversationHandler.END

# =====================================================
# CANCELAR
# =====================================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada ❌")
    return ConversationHandler.END

# =====================================================
# APLICACIÓN
# =====================================================

application = ApplicationBuilder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, tipo)],
        CATEGORIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, categoria)],
        SUB1: [MessageHandler(filters.TEXT & ~filters.COMMAND, sub1)],
        SUB2: [MessageHandler(filters.TEXT & ~filters.COMMAND, sub2)],
        SUB3: [MessageHandler(filters.TEXT & ~filters.COMMAND, sub3)],
        MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, monto)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

application.add_handler(conv_handler)

# =====================================================
# WEBHOOK PARA RENDER
# =====================================================

if __name__ == "__main__":
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"https://gestion-dinero-bot.onrender.com/{TOKEN}",
        url_path=TOKEN,
    )
