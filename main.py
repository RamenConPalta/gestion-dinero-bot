import os
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)
from google.oauth2.service_account import Credentials
import gspread

# =========================
# VARIABLES
# =========================

TOKEN = os.environ.get("BOT_TOKEN")
SHEET_NAME = os.environ.get("SPREADSHEET_NAME")
PORT = int(os.environ.get("PORT", 10000))

# =========================
# GOOGLE SHEETS
# =========================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds_json = os.environ.get("GOOGLE_CREDENTIALS")
creds_dict = json.loads(creds_json)

credentials = Credentials.from_service_account_info(
    creds_dict,
    scopes=scope,
)

client = gspread.authorize(credentials)

spreadsheet = client.open(SHEET_NAME)
sheet = spreadsheet.worksheet("REGISTRO")
listas_sheet = spreadsheet.worksheet("LISTAS")

# =========================
# USER STATE
# =========================

user_states = {}

# =========================
# FUNCIONES DATOS
# =========================

def get_tipos():
    data = listas_sheet.get_all_values()[1:]
    tipos = set()

    for row in data:
        if row[0] and row[0] != "—":
            tipos.add(row[0])

    return sorted(tipos)


def get_categorias(tipo_seleccionado):
    data = listas_sheet.get_all_values()[1:]
    categorias = set()

    for row in data:
        tipo = row[0]
        categoria = row[1]

        if (
            tipo == tipo_seleccionado
            and categoria
            and categoria != "—"
        ):
            categorias.add(categoria)

    return sorted(categorias)

def get_sub1(tipo_seleccionado, categoria_seleccionada):
    data = listas_sheet.get_all_values()[1:]
    sub1_set = set()

    for row in data:
        tipo = row[0]
        categoria = row[1]
        sub1 = row[2]

        if (
            tipo == tipo_seleccionado
            and categoria == categoria_seleccionada
            and sub1
            and sub1 != "—"
        ):
            sub1_set.add(sub1)

    return sorted(sub1_set)

# =========================
# TELEGRAM BOT
# =========================

async def start(update, context):
    keyboard = [
        [InlineKeyboardButton("➕ Añadir registro", callback_data="add")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "💰 Sistema de gestión de dinero",
        reply_markup=reply_markup
    )


async def button_handler(update, context):
    query = update.callback_query
    await query.answer()

    # =========================
    # BOTÓN AÑADIR
    # =========================

    if query.data == "add":
        user_id = query.from_user.id
        user_states[user_id] = {}

        tipos = get_tipos()

        keyboard = [
            [InlineKeyboardButton(tipo, callback_data=f"tipo|{tipo}")]
            for tipo in tipos
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "Selecciona TIPO:",
            reply_markup=reply_markup,
        )

    # =========================
    # SELECCIÓN TIPO
    # =========================

    elif query.data.startswith("tipo|"):
        user_id = query.from_user.id
        tipo = query.data.split("|")[1]

        user_states[user_id]["tipo"] = tipo

        categorias = get_categorias(tipo)

        if not categorias:
            await query.edit_message_text(
                f"Tipo seleccionado: {tipo} ✅\n\nNo hay categorías disponibles."
            )
            return

        keyboard = [
            [InlineKeyboardButton(cat, callback_data=f"categoria|{cat}")]
            for cat in categorias
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"Tipo seleccionado: {tipo} ✅\n\nSelecciona CATEGORÍA:",
            reply_markup=reply_markup,
        )

    # =========================
    # SELECCIÓN CATEGORÍA
    # =========================

    elif query.data.startswith("categoria|"):
    user_id = query.from_user.id
    categoria = query.data.split("|")[1]

    user_states[user_id]["categoria"] = categoria

    tipo = user_states[user_id]["tipo"]

    sub1_list = get_sub1(tipo, categoria)

        if not sub1_list:
            await query.edit_message_text(
                f"Tipo: {tipo} ✅\n"
                f"Categoría: {categoria} ✅\n\n"
                "No hay SUB1 disponibles."
            )
            return
    
        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"sub1|{s}")]
            for s in sub1_list
        ]
    
        reply_markup = InlineKeyboardMarkup(keyboard)
    
        await query.edit_message_text(
            f"Tipo: {tipo} ✅\n"
            f"Categoría: {categoria} ✅\n\n"
            "Selecciona SUB1:",
            reply_markup=reply_markup,
        )

    elif query.data.startswith("sub1|"):
        user_id = query.from_user.id
        sub1 = query.data.split("|")[1]
    
        user_states[user_id]["sub1"] = sub1
    
        await query.edit_message_text(
            f"Tipo: {user_states[user_id]['tipo']} ✅\n"
            f"Categoría: {user_states[user_id]['categoria']} ✅\n"
            f"SUB1: {sub1} ✅\n\n"
            "🔜 Próximo paso: SUB2"
        )


# =========================
# START APP
# =========================

application = ApplicationBuilder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))

# =========================
# START WEBHOOK
# =========================

if __name__ == "__main__":
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"https://gestion-dinero-bot.onrender.com/{TOKEN}",
        url_path=TOKEN,
    )
