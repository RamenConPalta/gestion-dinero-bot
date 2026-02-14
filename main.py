import os
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)
from telegram.ext import MessageHandler, filters
from datetime import datetime
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

def get_sub2(tipo_sel, categoria_sel, sub1_sel):
    data = listas_sheet.get_all_values()[1:]
    sub2_set = set()

    for row in data:
        tipo = row[0]
        categoria = row[1]
        sub1 = row[2]
        sub2 = row[3] if len(row) > 3 else ""

        if (
            tipo == tipo_sel
            and categoria == categoria_sel
            and sub1 == sub1_sel
            and sub2
            and sub2 != "—"
        ):
            sub2_set.add(sub2)

    return sorted(sub2_set)

def get_sub3(tipo_sel, categoria_sel, sub1_sel, sub2_sel):
    data = listas_sheet.get_all_values()[1:]
    sub3_set = set()

    for row in data:
        tipo = row[0]
        categoria = row[1]
        sub1 = row[2]
        sub2 = row[3] if len(row) > 3 else ""
        sub3 = row[4] if len(row) > 4 else ""

        if (
            tipo == tipo_sel
            and categoria == categoria_sel
            and sub1 == sub1_sel
            and sub2 == sub2_sel
            and sub3
            and sub3 != "—"
        ):
            sub3_set.add(sub3)

    return sorted(sub3_set)

async def recibir_importe(update, context):
    user_id = update.effective_user.id

    # Solo actuar si estamos esperando importe
    if user_id not in user_states:
        return

    if not user_states[user_id].get("esperando_importe"):
        return

    texto = update.message.text

    try:
        importe = float(texto.replace(",", "."))
    except:
        await update.message.reply_text("Escribe un número válido 💰")
        return

    fecha = datetime.now().strftime("%Y-%m-%d")
    user = update.effective_user.first_name

    data = user_states[user_id]

    sheet.append_row([
        fecha,
        user,
        data.get("tipo", ""),
        data.get("categoria", ""),
        data.get("sub1", ""),
        data.get("sub2", ""),
        data.get("sub3", ""),
        importe
    ])

    await update.message.reply_text("Movimiento guardado correctamente ✅")

    user_states.pop(user_id)

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
    
        tipo = user_states[user_id]["tipo"]
        categoria = user_states[user_id]["categoria"]
    
        sub2_list = get_sub2(tipo, categoria, sub1)
    
        # Si no hay SUB2 → pasamos directamente a importe
        if not sub2_list:
            user_states[user_id]["sub2"] = ""
            user_states[user_id]["sub3"] = ""
            user_states[user_id]["esperando_importe"] = True

            await query.edit_message_text(
                f"Tipo: {tipo} ✅\n"
                f"Categoría: {categoria} ✅\n"
                f"SUB1: {sub1} ✅\n\n"
                "No hay SUB2.\n\n"
                "💰 Escribe el importe:"
            )
            return
    
        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"sub2|{s}")]
            for s in sub2_list
        ]
    
        reply_markup = InlineKeyboardMarkup(keyboard)
    
        await query.edit_message_text(
            f"Tipo: {tipo} ✅\n"
            f"Categoría: {categoria} ✅\n"
            f"SUB1: {sub1} ✅\n\n"
            "Selecciona SUB2:",
            reply_markup=reply_markup,
        )
        
    elif query.data.startswith("sub2|"):
        user_id = query.from_user.id
        sub2 = query.data.split("|")[1]
    
        user_states[user_id]["sub2"] = sub2
    
        tipo = user_states[user_id]["tipo"]
        categoria = user_states[user_id]["categoria"]
        sub1 = user_states[user_id]["sub1"]
    
        sub3_list = get_sub3(tipo, categoria, sub1, sub2)
    
        # Si no hay SUB3 → pasamos a importe
        if not sub3_list:
            await query.edit_message_text(
                f"Tipo: {tipo} ✅\n"
                f"Categoría: {categoria} ✅\n"
                f"SUB1: {sub1} ✅\n"
                f"SUB2: {sub2} ✅\n\n"
                "No hay SUB3.\n"
                "💰 Escribe el importe:"
            )
            user_states[user_id]["sub3"] = ""
            user_states[user_id]["esperando_importe"] = True
            return
    
        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"sub3|{s}")]
            for s in sub3_list
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
    
        await query.edit_message_text(
            f"Tipo: {tipo} ✅\n"
            f"Categoría: {categoria} ✅\n"
            f"SUB1: {sub1} ✅\n"
            f"SUB2: {sub2} ✅\n\n"
            "Selecciona SUB3:",
            reply_markup=reply_markup,
        )

    elif query.data.startswith("sub3|"):
        user_id = query.from_user.id
        sub3 = query.data.split("|")[1]
    
        user_states[user_id]["sub3"] = sub3
        user_states[user_id]["esperando_importe"] = True
    
        await query.edit_message_text(
            f"Tipo: {user_states[user_id]['tipo']} ✅\n"
            f"Categoría: {user_states[user_id]['categoria']} ✅\n"
            f"SUB1: {user_states[user_id]['sub1']} ✅\n"
            f"SUB2: {user_states[user_id]['sub2']} ✅\n"
            f"SUB3: {sub3} ✅\n\n"
            "💰 Escribe el importe:"
        )




# =========================
# START APP
# =========================

application = ApplicationBuilder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_importe)
)

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
