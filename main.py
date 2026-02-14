import os
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)
from telegram.ext import MessageHandler, filters
from datetime import datetime, timedelta
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

def get_personas_gasto():
    valores = listas_sheet.col_values(19)[1:4]  # Columna S (19)
    return [v for v in valores if v and v != "—"]


def get_quien_paga():
    valores = listas_sheet.col_values(20)[1:4]  # Columna T (20)
    return [v for v in valores if v and v != "—"]


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

async def recibir_texto(update, context):
    user_id = update.effective_user.id

    if user_id not in user_states:
        return

    texto = update.message.text.strip()

    # =========================
    # FECHA MANUAL
    # =========================

    if user_states[user_id].get("esperando_fecha_manual"):
        try:
            fecha = datetime.strptime(texto, "%d/%m/%Y")
            user_states[user_id]["fecha"] = fecha.strftime("%d/%m/%Y")
            user_states[user_id]["esperando_fecha_manual"] = False
        except:
            await update.message.reply_text("Formato incorrecto. Usa DD/MM/YYYY")
            return

        personas = get_personas_gasto()

        keyboard = [
            [InlineKeyboardButton(p, callback_data=f"persona|{p}")]
            for p in personas
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Fecha: {user_states[user_id]['fecha']} ✅\n\n¿De quién es el gasto?",
            reply_markup=reply_markup
        )
        return

    # =========================
    # IMPORTE
    # =========================

    if user_states[user_id].get("esperando_importe"):
        try:
            importe = float(texto.replace(",", "."))
        except:
            await update.message.reply_text("Escribe un número válido 💰")
            return

        data = user_states[user_id]

        sheet.append_row([
            data.get("fecha", ""),
            data.get("persona", ""),
            data.get("pagador", ""),
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
    user_id = update.effective_user.id
    user_states[user_id] = {}

    keyboard = [
        [
            InlineKeyboardButton("Hoy", callback_data="fecha|hoy"),
            InlineKeyboardButton("Ayer", callback_data="fecha|ayer"),
        ],
        [
            InlineKeyboardButton("Otra", callback_data="fecha|otra")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📅 Selecciona la fecha:",
        reply_markup=reply_markup
    )


async def button_handler(update, context):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # =========================
    # FECHA
    # =========================

    if data.startswith("fecha|"):
        opcion = data.split("|")[1]

        if opcion == "hoy":
            fecha = datetime.now().strftime("%d/%m/%Y")
        elif opcion == "ayer":
            fecha = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y")
        else:
            user_states[user_id]["esperando_fecha_manual"] = True
            await query.edit_message_text(
                "✍️ Escribe la fecha en formato DD/MM/YYYY:"
            )
            return

        user_states[user_id]["fecha"] = fecha

        personas = get_personas_gasto()

        keyboard = [
            [InlineKeyboardButton(p, callback_data=f"persona|{p}")]
            for p in personas
        ]

        await query.edit_message_text(
            f"Fecha: {fecha} ✅\n\n¿De quién es el gasto?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # =========================
    # PERSONA
    # =========================

    elif data.startswith("persona|"):
        persona = data.split("|")[1]
        user_states[user_id]["persona"] = persona

        pagadores = get_quien_paga()

        keyboard = [
            [InlineKeyboardButton(p, callback_data=f"pagador|{p}")]
            for p in pagadores
        ]

        await query.edit_message_text(
            f"Fecha: {user_states[user_id]['fecha']} ✅\n"
            f"Gasto de: {persona} ✅\n\n"
            "¿Quién paga?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # =========================
    # PAGADOR
    # =========================

    elif data.startswith("pagador|"):
        pagador = data.split("|")[1]
        user_states[user_id]["pagador"] = pagador

        tipos = get_tipos()

        keyboard = [
            [InlineKeyboardButton(t, callback_data=f"tipo|{t}")]
            for t in tipos
        ]

        await query.edit_message_text(
            f"Fecha: {user_states[user_id]['fecha']} ✅\n"
            f"Gasto de: {user_states[user_id]['persona']} ✅\n"
            f"Paga: {pagador} ✅\n\n"
            "Selecciona TIPO:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # =========================
    # TIPO
    # =========================

    elif data.startswith("tipo|"):
        tipo = data.split("|")[1]
        user_states[user_id]["tipo"] = tipo

        categorias = get_categorias(tipo)

        keyboard = [
            [InlineKeyboardButton(c, callback_data=f"categoria|{c}")]
            for c in categorias
        ]

        await query.edit_message_text(
            f"Tipo: {tipo} ✅\n\nSelecciona CATEGORÍA:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # =========================
    # CATEGORIA
    # =========================

    elif data.startswith("categoria|"):
        categoria = data.split("|")[1]
        user_states[user_id]["categoria"] = categoria

        sub1_list = get_sub1(
            user_states[user_id]["tipo"],
            categoria
        )

        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"sub1|{s}")]
            for s in sub1_list
        ]

        await query.edit_message_text(
            f"Categoría: {categoria} ✅\n\nSelecciona SUB1:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # =========================
    # SUB1
    # =========================

    elif data.startswith("sub1|"):
        sub1 = data.split("|")[1]
        user_states[user_id]["sub1"] = sub1

        sub2_list = get_sub2(
            user_states[user_id]["tipo"],
            user_states[user_id]["categoria"],
            sub1
        )

        if not sub2_list:
            user_states[user_id]["sub2"] = ""
            user_states[user_id]["sub3"] = ""
            user_states[user_id]["esperando_importe"] = True

            await query.edit_message_text(
                "💰 Escribe el importe:"
            )
            return

        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"sub2|{s}")]
            for s in sub2_list
        ]

        await query.edit_message_text(
            "Selecciona SUB2:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # =========================
    # SUB2
    # =========================

    elif data.startswith("sub2|"):
        sub2 = data.split("|")[1]
        user_states[user_id]["sub2"] = sub2

        sub3_list = get_sub3(
            user_states[user_id]["tipo"],
            user_states[user_id]["categoria"],
            user_states[user_id]["sub1"],
            sub2
        )

        if not sub3_list:
            user_states[user_id]["sub3"] = ""
            user_states[user_id]["esperando_importe"] = True

            await query.edit_message_text(
                "💰 Escribe el importe:"
            )
            return

        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"sub3|{s}")]
            for s in sub3_list
        ]

        await query.edit_message_text(
            "Selecciona SUB3:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # =========================
    # SUB3
    # =========================

    elif data.startswith("sub3|"):
        sub3 = data.split("|")[1]
        user_states[user_id]["sub3"] = sub3
        user_states[user_id]["esperando_importe"] = True

        await query.edit_message_text(
            "💰 Escribe el importe:"
        )




# =========================
# START APP
# =========================

application = ApplicationBuilder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto)
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
