import os
import json
import logging
import time
import re
import unicodedata
from difflib import SequenceMatcher
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
import gspread
from gspread.utils import rowcol_to_a1


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TRABAJO_SPREADSHEETS = {
    "Claudia": "RegistreApostes2026_SeñoraLapa",
    "Ramon": "RegistreApostes2026_SeñorLapa",
}

TRABAJO_PROMOTORES = {
    "Claudia": ["CGP", "RFB", "AFD", "MLC", "RGM"],
    "Ramon": ["RCM", "RCN", "DMC", "TBG", "AAL", "JCM", "JPT", "RGP", "JPC", "JJA"],
}

TRABAJO_GASTOS_COLUMNAS = {
    "Ramon": {
        "RCM": "AS",
        "RCN": "AY",
        "DMC": "BE",
        "TBG": "BK",
        "AAL": "BQ",
        "JCM": "BW",
        "JPT": "CC",
        "RGP": "CI",
        "JPC": "CO",
        "JJA": "CU",
    },
    "Claudia": {
        "CGP": "AV",
        "RFB": "BB",
        "AFD": "BH",
        "MLC": "BN",
        "RGM": "BT",
    },
}

TRABAJO_TIPOS_BONO = [
    "Bono Bienvenida",
    "Casino Bienvenida",
    "Recurrente",
    "Casino Recurrente",
]

TRABAJO_TIPOS_PROMO = [
    "Reembolso",
    "Freebet",
    "Cuota mejorada",
    "Rollover",
    "Bonos superiores",
    "Freespins",
    "Extra depósito",
    "Freebet con condiciones",
    "Error",
    "Blackjack",
    "Dinero real",
    "Ganancia adicional",
    "Surebet",
    "Millas",
    "Supercuota",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# VARIABLES
# =========================

def get_required_env(name):
    value = os.environ.get(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_authorized_users(raw):
    users = set()
    for uid in raw.split(","):
        uid = uid.strip()
        if not uid:
            continue
        try:
            users.add(int(uid))
        except ValueError as e:
            raise RuntimeError(f"Invalid AUTHORIZED_USERS id: {uid}") from e
    return users


TOKEN = get_required_env("BOT_TOKEN")
SHEET_NAME = get_required_env("SPREADSHEET_NAME")
SHEET_NAME_LISTA_COMPRA = get_required_env("SPREADSHEET_NAME_LISTA_COMPRA")
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_BASE_URL = os.environ.get(
    "WEBHOOK_BASE_URL",
    "https://gestion-dinero-bot.onrender.com"
).rstrip("/")

# =========================
# USUARIOS AUTORIZADOS
# =========================

AUTHORIZED_USERS = parse_authorized_users(get_required_env("AUTHORIZED_USERS"))


ADMIN_ID = int(get_required_env("ADMIN_ID"))

# =========================
# GOOGLE SHEETS
# =========================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds_json = get_required_env("GOOGLE_CREDENTIALS")
try:
    creds_dict = json.loads(creds_json)
except json.JSONDecodeError as e:
    raise RuntimeError("GOOGLE_CREDENTIALS is not valid JSON") from e

credentials = Credentials.from_service_account_info(
    creds_dict,
    scopes=scope,
)

client = gspread.authorize(credentials)
spreadsheet = client.open(SHEET_NAME)
sheet = spreadsheet.worksheet("REGISTRO")
listas_sheet = spreadsheet.worksheet("LISTAS")

# =========================
# GOOGLE SHEETS LISTA COMPRA
# =========================

lista_spreadsheet = client.open(SHEET_NAME_LISTA_COMPRA)

sheet_carrefour = lista_spreadsheet.worksheet("Carrefour")
sheet_mercadona = lista_spreadsheet.worksheet("Mercadona")
sheet_sirena = lista_spreadsheet.worksheet("Sirena")
sheet_otros = lista_spreadsheet.worksheet("Otros")

# =========================
# GOOGLE SHEETS TRABAJO
# =========================

trabajo_spreadsheets = {
    persona: client.open(nombre)
    for persona, nombre in TRABAJO_SPREADSHEETS.items()
}

trabajo_promos_sheets = {
    persona: book.worksheet("PromosDone")
    for persona, book in trabajo_spreadsheets.items()
}

trabajo_control_sheets = {
    persona: book.worksheet("ControlDeCases")
    for persona, book in trabajo_spreadsheets.items()
}

trabajo_calculs_sheets = {
    persona: book.worksheet("Calculs")
    for persona, book in trabajo_spreadsheets.items()
}

# =========================
# USER STATE
# =========================

user_states = {}

LISTAS_CACHE_SECONDS = 60
_listas_cache = {
    "data": None,
    "expires_at": 0.0,
}

TRABAJO_CASAS_CACHE_SECONDS = 300
_trabajo_casas_cache = {}


# =========================
# FUNCIONES AUXILIARES
# =========================

def usuario_autorizado(user_id):
    return user_id in AUTHORIZED_USERS
    
def resumen_parcial(data):
    texto = ""
    for campo in ["fecha","persona","pagador","tipo","categoria","sub1","sub2","sub3"]:
        if campo in data:
            texto += f"{campo.capitalize()}: {data[campo]} ✅\n"
    return texto


def botones_navegacion():
    return [
        InlineKeyboardButton("⬅ Volver", callback_data="back"),
        InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
    ]


def teclado_menu_principal():
    return [
        [InlineKeyboardButton("💰 Gestión de dinero", callback_data="menu|gestion")],
        [InlineKeyboardButton("🛒 Lista de la compra", callback_data="menu|lista")],
        [InlineKeyboardButton("💼 Trabajo", callback_data="menu|trabajo")],
    ]


def teclado_menu_gestion():
    return [
        [InlineKeyboardButton("➕ Añadir registro", callback_data="menu|add")],
        [InlineKeyboardButton("📈 Ver resumen", callback_data="menu|resumen")],
        [InlineKeyboardButton("⬅ Volver", callback_data="menu|volver")],
    ]


def teclado_menu_lista():
    return [
        [InlineKeyboardButton("➕ Añadir", callback_data="lista|add")],
        [InlineKeyboardButton("👁️ Ver", callback_data="lista|ver")],
        [InlineKeyboardButton("❌ Borrar", callback_data="lista|borrar")],
        [InlineKeyboardButton("⬅ Volver", callback_data="menu|volver")],
    ]


def teclado_menu_trabajo():
    return [
        [InlineKeyboardButton("Claudia", callback_data="trabajo|Claudia")],
        [InlineKeyboardButton("Ramon", callback_data="trabajo|Ramon")],
        [InlineKeyboardButton("➕ Añadir gasto", callback_data="trabajo_gasto|menu")],
        [InlineKeyboardButton("⬅ Volver", callback_data="menu|volver")],
    ]


async def desplazar_menu_al_final(context, user_id, texto_menu, keyboard):
    estado = user_states.get(user_id, {})
    chat_id = estado.get("ui_chat_id")
    message_id = estado.get("ui_message_id")

    if chat_id and message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except BadRequest:
            pass

    sent_message = await context.bot.send_message(
        chat_id=user_id,
        text=texto_menu,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    user_states.setdefault(user_id, {})["ui_chat_id"] = sent_message.chat_id
    user_states[user_id]["ui_message_id"] = sent_message.message_id


async def desplazar_menu_principal_al_final(context, user_id):
    await desplazar_menu_al_final(
        context,
        user_id,
        "📲 Menú principal",
        teclado_menu_principal(),
    )


def registrar_mensaje_interactivo(user_id, query):
    user_states[user_id]["ui_chat_id"] = query.message.chat_id
    user_states[user_id]["ui_message_id"] = query.message.message_id


async def actualizar_mensaje_flujo(update, context, user_id, texto, reply_markup=None):
    estado = user_states.get(user_id, {})
    chat_id = estado.get("ui_chat_id")
    message_id = estado.get("ui_message_id")

    if chat_id and message_id:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id,
            )
        except BadRequest:
            pass

    sent_message = await update.message.reply_text(texto, reply_markup=reply_markup)
    user_states.setdefault(user_id, {})["ui_chat_id"] = sent_message.chat_id
    user_states[user_id]["ui_message_id"] = sent_message.message_id


async def verificar_autorizacion(update, context):
    user = update.effective_user
    user_id = user.id

    if user_id not in AUTHORIZED_USERS:

        mensaje_alerta = (
            "🚨 INTENTO DE ACCESO NO AUTORIZADO 🚨\n\n"
            f"ID: {user_id}\n"
            f"Nombre: {user.first_name}\n"
            f"Username: @{user.username}"
        )

        # Notificar al admin
        await context.bot.send_message(chat_id=ADMIN_ID, text=mensaje_alerta)

        # Avisar al intruso
        if update.message:
            await update.message.reply_text("⛔ No tienes acceso a este bot.")
        elif update.callback_query:
            await update.callback_query.answer("⛔ No autorizado", show_alert=True)

        return False

    return True

def limpiar_importe(valor):
    valor = str(valor).strip()
    valor = valor.replace("€", "").replace(" ", "")

    # Caso europeo típico: 1.550,00
    if "," in valor and "." in valor:
        valor = valor.replace(".", "")  # quitar separador miles
        valor = valor.replace(",", ".") # decimal correcto

    # Caso solo coma decimal: 150,50
    elif "," in valor:
        valor = valor.replace(",", ".")

    # Quitar cualquier cosa rara
    valor = "".join(c for c in valor if c.isdigit() or c == ".")

    if valor == "":
        return 0

    return float(valor)



def generar_barra(real, objetivo, largo=10):

    if objetivo <= 0:
        return ""

    porcentaje = real / objetivo
    porcentaje_mostrar = round(porcentaje * 100)

    bloques_llenos = int(min(porcentaje, 1) * largo)
    bloques_vacios = largo - bloques_llenos

    barra = "█" * bloques_llenos + "░" * bloques_vacios

    # Colores por porcentaje
    if porcentaje <= 0.8:
        color = "🟢"
    elif porcentaje <= 1:
        color = "🟡"
    else:
        color = "🔴"

    texto = f"{color} {barra} {porcentaje_mostrar}%"

    if porcentaje > 1:
        texto += " ⚠️"

    return texto

def obtener_lista_completa():

    mensaje = "🛒 LISTA ACTUAL COMPLETA\n\n"

    for nombre, hoja in [
        ("Carrefour", sheet_carrefour),
        ("Mercadona", sheet_mercadona),
        ("Sirena", sheet_sirena),
        ("Otros", sheet_otros)
    ]:

        productos = hoja.col_values(1)[1:]

        mensaje += f"📍 {nombre}\n"

        if productos:
            for p in productos:
                mensaje += f"  • {p}\n"
        else:
            mensaje += "  (Vacío)\n"

        mensaje += "\n"

    return mensaje

async def notificar_lista_actualizada(context, mover_menu=False):
    
    mensaje_lista = obtener_lista_completa()

    for user_id_aut in AUTHORIZED_USERS:
        try:
            await context.bot.send_message(
                chat_id=user_id_aut,
                text=mensaje_lista
            )
            if mover_menu:
                await desplazar_menu_principal_al_final(context, user_id_aut)
        except Exception as e:
            print("Error enviando lista a", user_id_aut, e)
# =========================
# FUNCIONES DATOS
# =========================

def get_personas_gasto():
    valores = listas_sheet.col_values(19)[1:4]
    return [v for v in valores if v and v != "—"]

def get_quien_paga():
    valores = listas_sheet.col_values(20)[1:4]
    return [v for v in valores if v and v != "—"]


def get_listas_data():
    now = time.monotonic()
    if _listas_cache["data"] is not None and now < _listas_cache["expires_at"]:
        return _listas_cache["data"]

    data = listas_sheet.get_all_values()[1:]
    _listas_cache["data"] = data
    _listas_cache["expires_at"] = now + LISTAS_CACHE_SECONDS
    return data

def get_tipos():
    data = get_listas_data()
    return sorted(set(row[0] for row in data if row[0] and row[0] != "—"))

def get_categorias(tipo):
    data = get_listas_data()
    return sorted(set(row[1] for row in data
                      if row[0]==tipo and row[1] and row[1]!="—"))

def get_sub1(tipo, categoria):
    data = get_listas_data()
    return sorted(set(row[2] for row in data
                      if row[0]==tipo and row[1]==categoria and row[2]!="—"))

def get_sub2(tipo, categoria, sub1):
    data = get_listas_data()
    sub2_set = set()

    for row in data:
        if len(row) < 4:
            continue

        if (
            row[0].strip() == tipo and
            row[1].strip() == categoria and
            row[2].strip() == sub1 and
            row[3].strip() and
            row[3].strip() != "—"
        ):
            sub2_set.add(row[3].strip())

    return sorted(sub2_set)

def get_sub3(tipo, categoria, sub1, sub2):
    data = get_listas_data()
    sub3_set = set()

    for row in data:
        if len(row) < 5:
            continue

        if (
            row[0].strip() == tipo and
            row[1].strip() == categoria and
            row[2].strip() == sub1 and
            row[3].strip() == sub2 and
            row[4].strip() and
            row[4].strip() != "—"
        ):
            sub3_set.add(row[4].strip())

    return sorted(sub3_set)

def resumen_trabajo_parcial(data):
    campos = [
        ("trabajo_promotores", "Promotores"),
        ("trabajo_promotor", "Promotor"),
        ("trabajo_fecha", "Fecha"),
        ("trabajo_casa", "Casa"),
        ("trabajo_tipo_bono", "Tipo bono"),
        ("trabajo_tipo_promo", "Tipo promo"),
        ("trabajo_observaciones", "Condiciones"),
        ("trabajo_partido", "Partido"),
        ("trabajo_perdida", "Pérdida"),
        ("trabajo_beneficio", "Beneficio"),
        ("trabajo_observaciones_finales", "Observaciones"),
    ]

    texto = ""
    for key, label in campos:
        if key == "trabajo_promotor" and data.get("trabajo_promotores"):
            continue
        if key in data:
            valor = data[key]
            if key == "trabajo_promotores" and isinstance(valor, list):
                valor = ", ".join(valor)
            texto += f"{label}: {valor} ✅\n"
    return texto


def resumen_trabajo_gasto_parcial(data):
    campos = [
        ("trabajo_persona", "Persona"),
        ("trabajo_gasto_usuario", "Usuario"),
        ("trabajo_gasto_info", "Información"),
        ("trabajo_gasto_cantidad", "Cantidad"),
        ("trabajo_gasto_fecha", "Fecha"),
    ]
    texto = ""
    for key, label in campos:
        if key in data and data.get(key) not in [None, ""]:
            texto += f"{label}: {data[key]} ✅\n"
    return texto


def columna_a_indice(columna):
    idx = 0
    for char in columna:
        idx = idx * 26 + (ord(char.upper()) - ord("A") + 1)
    return idx


def primera_fila_libre_columna(hoja, columna_idx):
    valores = hoja.col_values(columna_idx)
    for idx, valor in enumerate(valores, start=1):
        if not str(valor).strip():
            return idx
    return len(valores) + 1


def guardar_gasto_trabajo(data):
    persona = data["trabajo_persona"]
    usuario = data["trabajo_gasto_usuario"]
    columna_cantidad = TRABAJO_GASTOS_COLUMNAS[persona][usuario]

    col_cantidad_idx = columna_a_indice(columna_cantidad)
    col_info_idx = col_cantidad_idx - 1
    col_fecha_idx = col_cantidad_idx + 1

    hoja = trabajo_calculs_sheets[persona]
    fila_destino = primera_fila_libre_columna(hoja, col_cantidad_idx)

    rango_info = rowcol_to_a1(fila_destino, col_info_idx)
    rango_cantidad = rowcol_to_a1(fila_destino, col_cantidad_idx)
    rango_fecha = rowcol_to_a1(fila_destino, col_fecha_idx)

    hoja.update(rango_info, [[data.get("trabajo_gasto_info", "")]], value_input_option="USER_ENTERED")
    hoja.update(
        rango_cantidad,
        [[data.get("trabajo_gasto_cantidad", "")]],
        value_input_option="USER_ENTERED",
    )
    hoja.update(
        rango_fecha,
        [[data.get("trabajo_gasto_fecha", "")]],
        value_input_option="USER_ENTERED",
    )
    hoja.format(
        rango_fecha,
        {
            "numberFormat": {
                "type": "DATE",
                "pattern": "dd/mm/yyyy",
            }
        },
    )


def construir_teclado_promotores(persona, seleccionados):
    seleccionados_set = set(seleccionados)
    keyboard = []

    for promotor in TRABAJO_PROMOTORES[persona]:
        marca = "✅" if promotor in seleccionados_set else "⬜"
        keyboard.append([
            InlineKeyboardButton(
                f"{marca} {promotor}",
                callback_data=f"trabajo_promotor_toggle|{promotor}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton("➡️ Continuar", callback_data="trabajo_promotor_confirmar")
    ])
    keyboard.append(botones_navegacion())
    return keyboard


def normalizar_texto(valor):
    base = unicodedata.normalize("NFKD", valor)
    sin_acentos = "".join(c for c in base if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9]", "", sin_acentos.lower())
    return limpio


def obtener_casas_trabajo(persona):
    now = time.monotonic()
    cache = _trabajo_casas_cache.get(persona)
    if cache and now < cache["expires_at"]:
        return cache["data"]

    sheet_control = trabajo_control_sheets[persona]
    valores = sheet_control.get("A5:A55")
    casas = [row[0].strip() for row in valores if row and row[0].strip()]
    _trabajo_casas_cache[persona] = {
        "data": casas,
        "expires_at": now + TRABAJO_CASAS_CACHE_SECONDS,
    }
    return casas


def score_casa(entrada, casa):
    en = normalizar_texto(entrada)
    ca = normalizar_texto(casa)
    if not en:
        return 0
    if en == ca:
        return 1.0
    if en in ca or ca in en:
        return 0.95
    acronimo = "".join(word[0] for word in casa.split() if word)
    ac = normalizar_texto(acronimo)
    if en == ac or en in ac:
        return 0.93
    return SequenceMatcher(None, en, ca).ratio()


def buscar_casas_parecidas(persona, entrada, limite=6):
    casas = obtener_casas_trabajo(persona)
    ranking = sorted(
        ((score_casa(entrada, casa), casa) for casa in casas),
        key=lambda x: x[0],
        reverse=True,
    )

    sugerencias = [casa for score, casa in ranking if score >= 0.55][:limite]
    if not sugerencias:
        sugerencias = [casa for _, casa in ranking[:limite]]
    return sugerencias


def parse_numero_con_signo(texto):
    valor = str(texto).strip().replace("€", "").replace(" ", "")
    if not valor:
        raise ValueError("vacío")

    if "," in valor and "." in valor:
        valor = valor.replace(".", "")
        valor = valor.replace(",", ".")
    elif "," in valor:
        valor = valor.replace(",", ".")

    if valor in {"+", "-", ".", "+.", "-."}:
        raise ValueError("inválido")

    return float(valor)


def formatear_fecha_para_sheet(fecha_texto):
    valor = str(fecha_texto).strip()
    if not valor:
        return ""

    try:
        fecha = datetime.strptime(valor, "%d/%m/%Y")
        return fecha.strftime("%Y-%m-%d")
    except ValueError:
        return valor


def guardar_registro_trabajo(data):
    persona = data["trabajo_persona"]
    hoja = trabajo_promos_sheets[persona]

    promotores = data.get("trabajo_promotores") or [data.get("trabajo_promotor", "")]
    promotores = [p for p in promotores if p]

    for promotor in promotores:
        fila = [""] * 19
        fila[0] = promotor
        fila[1] = formatear_fecha_para_sheet(data.get("trabajo_fecha", ""))
        fila[2] = data.get("trabajo_casa", "")
        fila[3] = data.get("trabajo_tipo_bono", "")
        fila[4] = data.get("trabajo_tipo_promo", "")
        fila[5] = data.get("trabajo_observaciones", "")
        fila[6] = data.get("trabajo_partido", "")
        fila[15] = data.get("trabajo_perdida", 0)
        fila[16] = data.get("trabajo_beneficio", 0)
        fila[18] = data.get("trabajo_observaciones_finales", "")

        valores_columna_a = hoja.get("A:A")
        fila_destino = len(valores_columna_a) + 1

        for idx, row in enumerate(valores_columna_a, start=1):
            celda = row[0].strip() if row and row[0] else ""
            if not celda:
                fila_destino = idx
                break

        # Importante: nunca tocar la columna R (índice 17), ya que se gestiona fuera del bot.
        hoja.update(
            f"A{fila_destino}:Q{fila_destino}",
            [fila[:17]],
            value_input_option="USER_ENTERED",
        )
        hoja.update(
            f"S{fila_destino}",
            [[fila[18]]],
            value_input_option="USER_ENTERED",
        )

# =========================
# MENU
# =========================

async def mostrar_menu(query):
    await query.edit_message_text(
        "📲 Menú principal",
        reply_markup=InlineKeyboardMarkup(teclado_menu_principal())
    )

async def mostrar_menu_lista(query):
    await query.edit_message_text(
        "🛒 Lista de la compra",
        reply_markup=InlineKeyboardMarkup(teclado_menu_lista())
    )

async def mostrar_selector_meses(query):

    año_actual = datetime.now().year

    meses = [
        "Enero","Febrero","Marzo","Abril","Mayo","Junio",
        "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
    ]

    keyboard = []

    for i, mes in enumerate(meses, start=1):
        callback = f"resumen_mes|{año_actual}|{i}"
        keyboard.append([InlineKeyboardButton(f"{mes} {año_actual}", callback_data=callback)])

    keyboard.append([InlineKeyboardButton(f"📊 Todo {año_actual}", callback_data=f"resumen_año|{año_actual}")])
    keyboard.append([InlineKeyboardButton("⬅ Volver", callback_data="menu|volver")])

    await query.edit_message_text(
        "📅 Selecciona periodo:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start(update, context):

    user_id = update.effective_user.id
    
    if not await verificar_autorizacion(update, context):
        return

    await update.message.reply_text(
        "📲 Menú principal",
        reply_markup=InlineKeyboardMarkup(teclado_menu_principal())    )

# =========================
# RESUMEN
# =========================

async def generar_resumen(query, año, mes, persona):

    print("=== RESUMEN NUEVO ===")
    print("Persona:", persona, "Año:", año, "Mes:", mes)

    # ================= SELECCIÓN DE HOJAS =================

    if persona == "Común":
        hoja_datos = spreadsheet.worksheet(f"Cuenta común: gráficos y datos {año}")
        hoja_objetivos = spreadsheet.worksheet("Cuenta común: gráficos y datos del mes actual")

    elif persona == "Claudia":
        hoja_datos = spreadsheet.worksheet(f"Cuenta Claudia: gráficos y datos {año}")
        hoja_objetivos = spreadsheet.worksheet("Cuenta Claudia: gráficos y datos del mes actual")

    elif persona == "Ramon":
        hoja_datos = spreadsheet.worksheet(f"Cuenta Ramon: gráficos y datos {año}")
        hoja_objetivos = spreadsheet.worksheet("Cuenta Ramon: gráficos y datos del mes actual")

    else:
        await query.edit_message_text("Persona no válida.")
        return

    datos = hoja_datos.get_all_values()[1:]
    objetivos = hoja_objetivos.get_all_values()[1:]

    if mes is None:
        col_index = 13  # Columna N (total)
    else:
        col_index = mes  # Enero=1 → Columna B

    tabla = []

    for row in datos:

        if len(row) <= col_index:
            continue

        categoria = row[0].strip()
        real = limpiar_importe(row[col_index])

        objetivo = 0

        if mes is not None:
            for obj_row in objetivos:
                if obj_row[0].strip().lower() == categoria.lower():
                    objetivo = limpiar_importe(obj_row[2])
                    break

        if real == 0 and objetivo == 0:
            continue

        tabla.append((categoria, objetivo, real))

    if not tabla:
        await query.edit_message_text("No hay datos para este periodo.")
        return

    # ================= CREAR TABLA =================

    mensaje = f"📊 {persona} - {año}"
    if mes:
        mensaje += f" - Mes {mes}"
    else:
        mensaje += " - TOTAL"
    mensaje += "\n\n"

    mensaje += "```\n"
    
    if mes is not None:
        mensaje += f"{'Categoría':20} | {'Objetivo':10} | {'Real':10} | {'Uso':15}\n"
        mensaje += "-"*65 + "\n"
    else:
        mensaje += f"{'Categoría':20} | {'Real':10}\n"
        mensaje += "-"*40 + "\n"

    for categoria, objetivo, real in tabla:

        categoria_txt = categoria[:20]
    
        if mes is not None:
    
            if objetivo > 0:
                uso_txt = generar_barra(real, objetivo)
            else:
                uso_txt = "-"
    
            mensaje += f"{categoria_txt:20} | {round(objetivo,2):10} | {round(real,2):10} | {uso_txt:15}\n"
    
        else:
            mensaje += f"{categoria_txt:20} | {round(real,2):10}\n"
    
    mensaje += "```"
    
    keyboard = [[InlineKeyboardButton("⬅ Volver", callback_data="menu|volver")]]
    
    await query.edit_message_text(
        mensaje,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

    print("=== FIN RESUMEN ===")



def get_objetivos_mes_actual():

    hoja_obj = spreadsheet.worksheet("Cuenta común: gráficos y datos del mes actual")
    filas = hoja_obj.get_all_values()

    objetivos = {}

    for row in filas[1:]:
        try:
            categoria = row[0].strip()
            objetivo = row[2].strip()   # Columna C
            real = row[3].strip()       # Columna D

            if not categoria:
                continue

            objetivo = objetivo.replace("€","").replace(".","").replace(",",".")
            real = real.replace("€","").replace(".","").replace(",",".")
            
            objetivo = float(objetivo) if objetivo else 0
            real = float(real) if real else 0

            objetivos[categoria] = {
                "objetivo": objetivo,
                "real": real
            }

        except (IndexError, ValueError, AttributeError) as e:
            logger.warning("Fila de objetivos inválida y omitida: %s", e)
            continue

    return objetivos



# =========================
# RECIBIR TEXTO
# =========================

async def recibir_texto(update, context):

    user_id = update.effective_user.id

    if not await verificar_autorizacion(update, context):
        return

    if update.message:
        try:
            await update.message.delete()
        except BadRequest:
            pass
    
    if user_id not in user_states:
        return

    texto = update.message.text.strip()
    
    # ================= TRABAJO =================

    if user_states[user_id].get("trabajo_esperando_fecha_manual"):
        try:
            fecha = datetime.strptime(texto, "%d/%m/%Y")
            user_states[user_id]["history"].append(user_states[user_id].copy())
            user_states[user_id]["trabajo_fecha"] = fecha.strftime("%d/%m/%Y")
            user_states[user_id]["trabajo_esperando_fecha_manual"] = False
        except ValueError:
            await update.message.reply_text("❌ Fecha inválida. Usa DD/MM/YYYY")
            return

        user_states[user_id]["trabajo_esperando_casa_input"] = True
        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_trabajo_parcial(user_states[user_id]) + "\nEscribe la casa de apuestas (ej: RETA, WilliamHill, CasinoGranMadrid):",
        )
        return

    if user_states[user_id].get("trabajo_esperando_casa_input"):
        persona = user_states[user_id]["trabajo_persona"]
        sugerencias = buscar_casas_parecidas(persona, texto)
        user_states[user_id]["trabajo_casa_sugerencias"] = sugerencias

        keyboard = [[InlineKeyboardButton(casa, callback_data=f"trabajo_casa_idx|{idx}")]
                    for idx, casa in enumerate(sugerencias)]
        keyboard.append([
            InlineKeyboardButton("✍️ Escribir otra vez", callback_data="trabajo_casa_reintentar")
        ])
        keyboard.append(botones_navegacion())

        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_trabajo_parcial(user_states[user_id]) + "\nSelecciona la casa correcta:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if user_states[user_id].get("trabajo_esperando_observaciones"):
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_observaciones"] = texto
        user_states[user_id]["trabajo_esperando_observaciones"] = False
        user_states[user_id]["trabajo_esperando_partido"] = True
        keyboard = [
            [InlineKeyboardButton("⏭️ Saltar paso", callback_data="trabajo_skip|partido")],
            botones_navegacion(),
        ]
        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_trabajo_parcial(user_states[user_id]) + "\n✍️ Escribe el partido:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if user_states[user_id].get("trabajo_esperando_partido"):
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_partido"] = texto
        user_states[user_id]["trabajo_esperando_partido"] = False
        user_states[user_id]["trabajo_esperando_perdida"] = True
        keyboard = [
            [InlineKeyboardButton("⏭️ Saltar paso", callback_data="trabajo_skip|perdida")],
            botones_navegacion(),
        ]
        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_trabajo_parcial(user_states[user_id]) + "\n💸 Escribe la pérdida (acepta signo y coma/punto):",
        )
        return

    if user_states[user_id].get("trabajo_esperando_perdida"):
        try:
            valor = parse_numero_con_signo(texto)
        except ValueError:
            await update.message.reply_text("❌ Valor de pérdida no válido.")
            return

        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_perdida"] = valor
        user_states[user_id]["trabajo_esperando_perdida"] = False
        user_states[user_id]["trabajo_esperando_beneficio"] = True
        keyboard = [
            [InlineKeyboardButton("⏭️ Saltar paso", callback_data="trabajo_skip|beneficio")],
            botones_navegacion(),
        ]
        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_trabajo_parcial(user_states[user_id]) + "\n💰 Escribe el beneficio (acepta signo y coma/punto):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if user_states[user_id].get("trabajo_esperando_beneficio"):
        try:
            valor = parse_numero_con_signo(texto)
        except ValueError:
            await update.message.reply_text("❌ Valor de beneficio no válido.")
            return

        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_beneficio"] = valor
        user_states[user_id]["trabajo_esperando_beneficio"] = False
        user_states[user_id]["trabajo_esperando_observaciones_finales"] = True
        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_trabajo_parcial(user_states[user_id]) + "\n📝 Escribe observaciones finales (se guardan en columna S):",
        )
        return

    if user_states[user_id].get("trabajo_esperando_observaciones_finales"):
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_observaciones_finales"] = texto
        user_states[user_id]["trabajo_esperando_observaciones_finales"] = False

        guardar_registro_trabajo(user_states[user_id])

        resumen_guardado = (
            "✅ Registro de trabajo guardado en PromosDone.\n\n"
            + resumen_trabajo_parcial(user_states[user_id])
        )
        await update.message.reply_text(resumen_guardado)

        await desplazar_menu_al_final(
            context,
            user_id,
            "💼 Trabajo",
            teclado_menu_trabajo(),
        )
        return
    # ================= TRABAJO AÑADIR GASTO =================

    if user_states[user_id].get("trabajo_gasto_esperando_info"):
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_gasto_info"] = texto
        user_states[user_id]["trabajo_gasto_esperando_info"] = False
        user_states[user_id]["trabajo_gasto_esperando_cantidad"] = True
        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_trabajo_gasto_parcial(user_states[user_id]) + "\n💰 Escribe la Cantidad:",
            reply_markup=InlineKeyboardMarkup([botones_navegacion()]),
        )
        return

    if user_states[user_id].get("trabajo_gasto_esperando_cantidad"):
        try:
            cantidad = parse_numero_con_signo(texto)
        except ValueError:
            await update.message.reply_text("❌ Cantidad no válida.")
            return

        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_gasto_cantidad"] = cantidad
        user_states[user_id]["trabajo_gasto_esperando_cantidad"] = False
        user_states[user_id]["trabajo_gasto_esperando_fecha"] = True
        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_trabajo_gasto_parcial(user_states[user_id]) + "\n📅 Escribe la Fecha (DD/MM/YYYY):",
            reply_markup=InlineKeyboardMarkup([botones_navegacion()]),
        )
        return

    if user_states[user_id].get("trabajo_gasto_esperando_fecha"):
        try:
            fecha = datetime.strptime(texto, "%d/%m/%Y")
        except ValueError:
            await update.message.reply_text("❌ Fecha inválida. Usa DD/MM/YYYY")
            return

        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_gasto_fecha"] = fecha.strftime("%d/%m/%Y")
        user_states[user_id]["trabajo_gasto_esperando_fecha"] = False

        guardar_gasto_trabajo(user_states[user_id])

        resumen_guardado = (
            "✅ Gasto de trabajo guardado en Calculs.\n\n"
            + resumen_trabajo_gasto_parcial(user_states[user_id])
        )
        await update.message.reply_text(resumen_guardado)

        await desplazar_menu_al_final(
            context,
            user_id,
            "💼 Trabajo",
            teclado_menu_trabajo(),
        )
        return

    # ================= LISTA COMPRA =================
    
    if user_states[user_id].get("esperando_lista_productos"):
        
        supermercado = user_states[user_id]["lista_supermercado"]
        
        productos = [p.strip() for p in texto.split(",") if p.strip()]
        
        if not productos:
            await update.message.reply_text("No se detectaron productos.")
            return
            
        hoja = {
            "Carrefour": sheet_carrefour,
            "Mercadona": sheet_mercadona,
            "Sirena": sheet_sirena,
            "Otros": sheet_otros
        }[supermercado]
        
        for producto in productos:
            hoja.append_row([producto])
            
        await notificar_lista_actualizada(context, mover_menu=True)
        await update.message.reply_text(
            "🛒 Lista actualizada correctamente en Excel.\n"
            f"Supermercado: {supermercado}\n"
            f"Productos: {', '.join(productos)}"
        )

        await desplazar_menu_al_final(
            context,
            user_id,
            "🛒 Lista de la compra",
            teclado_menu_lista(),
        )
        return

    # FECHA MANUAL
    if user_states[user_id].get("esperando_fecha_manual"):
        try:
            fecha = datetime.strptime(texto, "%d/%m/%Y")
            user_states[user_id]["history"].append(user_states[user_id].copy())
            user_states[user_id]["fecha"] = fecha.strftime("%d/%m/%Y")
            user_states[user_id]["esperando_fecha_manual"] = False
        except ValueError:
            await update.message.reply_text("❌ Fecha inválida. Usa DD/MM/YYYY")
            return

        personas = get_personas_gasto()
        keyboard = [[InlineKeyboardButton(p, callback_data=f"persona|{p}")]
                    for p in personas]
        keyboard.append(botones_navegacion())

        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_parcial(user_states[user_id]) + "\n¿De quién es el gasto?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # OBSERVACION
    if user_states[user_id].get("esperando_observacion_texto"):
        user_states[user_id]["observacion"] = texto
        user_states[user_id]["esperando_observacion_texto"] = False
        user_states[user_id]["esperando_importe"] = True
        await actualizar_mensaje_flujo(
            update,
            context,
            user_id,
            resumen_parcial(user_states[user_id]) + "\n💰 Escribe el importe:",
        )
        return

    # IMPORTE
    if user_states[user_id].get("esperando_importe"):
        try:
            importe = float(texto.replace(",", "."))
            if importe <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Importe no válido.")
            return

        data = user_states[user_id]

        sheet.append_row([
            formatear_fecha_para_sheet(data.get("fecha", "")),
            data.get("persona", ""),
            data.get("pagador", ""),
            data.get("tipo", ""),
            data.get("categoria", ""),
            data.get("sub1", "—"),
            data.get("sub2", "—"),
            data.get("sub3", "—"),
            data.get("observacion", ""),
            importe
        ], value_input_option="USER_ENTERED")
        resumen_guardado = (
            "✅ Movimiento guardado correctamente en Excel.\n\n"
            f"Fecha: {data.get('fecha', '')}\n"
            f"Persona: {data.get('persona', '')}\n"
            f"Pagador: {data.get('pagador', '')}\n"
            f"Tipo: {data.get('tipo', '')}\n"
            f"Categoría: {data.get('categoria', '')}\n"
            f"Sub1: {data.get('sub1', '—')}\n"
            f"Sub2: {data.get('sub2', '—')}\n"
            f"Sub3: {data.get('sub3', '—')}\n"
            f"Observación: {data.get('observacion', '') or '—'}\n"
            f"Importe: {importe}"
        )
        await update.message.reply_text(resumen_guardado)

        await desplazar_menu_al_final(
            context,
            user_id,
            "💰 Gestión de dinero",
            teclado_menu_gestion(),
        )


# =========================
# BOTONES
# =========================

async def button_handler(update, context):
    query=update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if not await verificar_autorizacion(update, context):
        return

    user_id=query.from_user.id
    data=query.data

    if user_id not in user_states:
        user_states[user_id]={}

    registrar_mensaje_interactivo(user_id, query)
    
    # CANCELAR
    if data=="cancelar":
        user_states.pop(user_id,None)
        await mostrar_menu(query)
        return

    # VOLVER MENU
    if data=="menu|volver":
        await mostrar_menu(query)
        return
    # MENU TRABAJO
    if data == "menu|trabajo":
        await query.edit_message_text(
            "💼 Trabajo",
            reply_markup=InlineKeyboardMarkup(teclado_menu_trabajo())
        )
        return
        
    if data == "trabajo_gasto|menu":
        user_states[user_id] = {
            "history": [],
            "flujo": "trabajo_gasto",
            "ui_chat_id": query.message.chat_id,
            "ui_message_id": query.message.message_id,
        }

        keyboard = [
            [InlineKeyboardButton("Ramon", callback_data="trabajo_gasto_persona|Ramon")],
            [InlineKeyboardButton("Claudia", callback_data="trabajo_gasto_persona|Claudia")],
            botones_navegacion(),
        ]
        await query.edit_message_text(
            "💼 Trabajo · Añadir gasto\n\n¿De qué persona quieres añadir el gasto?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("trabajo_gasto_persona|"):
        persona = data.split("|", 1)[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_persona"] = persona

        keyboard = [
            [InlineKeyboardButton(usuario, callback_data=f"trabajo_gasto_usuario|{usuario}")]
            for usuario in TRABAJO_GASTOS_COLUMNAS[persona].keys()
        ]
        keyboard.append(botones_navegacion())

        await query.edit_message_text(
            resumen_trabajo_gasto_parcial(user_states[user_id]) + "\nSelecciona usuario:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("trabajo_gasto_usuario|"):
        usuario = data.split("|", 1)[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_gasto_usuario"] = usuario
        user_states[user_id]["trabajo_gasto_esperando_info"] = True

        await query.edit_message_text(
            resumen_trabajo_gasto_parcial(user_states[user_id]) + "\n✍️ Escribe la Información:",
            reply_markup=InlineKeyboardMarkup([botones_navegacion()]),
        )
        return

    # DENTRO DE MENU TRABAJO
    if data.startswith("trabajo|"):

        persona = data.split("|")[1]

        user_states[user_id] = {
            "history": [],
            "flujo": "trabajo",
            "trabajo_persona": persona,
            "ui_chat_id": query.message.chat_id,
            "ui_message_id": query.message.message_id,
        }

        user_states[user_id]["trabajo_promotores"] = []
        keyboard = construir_teclado_promotores(persona, [])
    
        await query.edit_message_text(
            f"💼 Trabajo · {persona}\n\n¿Quién hace la promoción?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("trabajo_promotor_toggle|"):
        promotor = data.split("|", 1)[1]
        persona = user_states[user_id]["trabajo_persona"]
        seleccionados = user_states[user_id].setdefault("trabajo_promotores", [])

        if promotor in seleccionados:
            seleccionados.remove(promotor)
        else:
            seleccionados.append(promotor)

        keyboard = construir_teclado_promotores(persona, seleccionados)
        await query.edit_message_text(
            f"💼 Trabajo · {persona}\n\n¿Quién hace la promoción?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "trabajo_promotor_confirmar":
        seleccionados = user_states[user_id].get("trabajo_promotores", [])
        if not seleccionados:
            await query.answer("Selecciona al menos un promotor", show_alert=True)
            return

        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_promotor"] = seleccionados[0]

        keyboard = [
            [InlineKeyboardButton("Hoy", callback_data="trabajo_fecha|hoy"),
             InlineKeyboardButton("Ayer", callback_data="trabajo_fecha|ayer")],
            [InlineKeyboardButton("Otra", callback_data="trabajo_fecha|otra")],
            botones_navegacion(),
        ]

        await query.edit_message_text(
            resumen_trabajo_parcial(user_states[user_id]) + "\n\n📅 Selecciona fecha:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("trabajo_fecha|"):
        opcion = data.split("|", 1)[1]
        if opcion == "otra":
            user_states[user_id]["trabajo_esperando_fecha_manual"] = True
            await query.edit_message_text("✍️ Escribe fecha DD/MM/YYYY")
            return

        if opcion == "hoy":
            fecha = datetime.now().strftime("%d/%m/%Y")
        else:
            fecha = (datetime.now()-timedelta(days=1)).strftime("%d/%m/%Y")

        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_fecha"] = fecha
        user_states[user_id]["trabajo_esperando_casa_input"] = True
        await query.edit_message_text(
            resumen_trabajo_parcial(user_states[user_id]) +
            "\n\nEscribe la casa de apuestas (ej: RETA, WilliamHill, CasinoGranMadrid):"
        )
        return

    if data == "trabajo_casa_reintentar":
        user_states[user_id]["trabajo_esperando_casa_input"] = True
        await query.edit_message_text(
            resumen_trabajo_parcial(user_states[user_id]) +
            "\n\nEscribe de nuevo la casa de apuestas:"
        )
        return

    if data.startswith("trabajo_casa_idx|"):
        idx = int(data.split("|", 1)[1])
        sugerencias = user_states[user_id].get("trabajo_casa_sugerencias", [])
        if idx < 0 or idx >= len(sugerencias):
            await query.answer("Selección inválida", show_alert=True)
            return

        casa = sugerencias[idx]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_casa"] = casa
        user_states[user_id]["trabajo_esperando_casa_input"] = False

        keyboard = [[InlineKeyboardButton(x, callback_data=f"trabajo_tipo_bono|{x}")]
                    for x in TRABAJO_TIPOS_BONO]
        keyboard.append(botones_navegacion())
        await query.edit_message_text(
            resumen_trabajo_parcial(user_states[user_id]) + "\n\n🎁 Tipo de bono:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("trabajo_tipo_bono|"):
        valor = data.split("|", 1)[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_tipo_bono"] = valor

        keyboard = [[InlineKeyboardButton(x, callback_data=f"trabajo_tipo_promo|{x}")]
                    for x in TRABAJO_TIPOS_PROMO]
        keyboard.append(botones_navegacion())
        await query.edit_message_text(
            resumen_trabajo_parcial(user_states[user_id]) + "\n\n🏷️ Tipo de promoción:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("trabajo_tipo_promo|"):
        valor = data.split("|", 1)[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["trabajo_tipo_promo"] = valor
        user_states[user_id]["trabajo_esperando_observaciones"] = True
        await query.edit_message_text(
            resumen_trabajo_parcial(user_states[user_id]) +
            "\n\n📝 Escribe condiciones de la promo:"
        )
        return

    if data.startswith("trabajo_skip|"):
        paso = data.split("|", 1)[1]

        if paso == "partido" and user_states[user_id].get("trabajo_esperando_partido"):
            user_states[user_id]["history"].append(user_states[user_id].copy())
            user_states[user_id]["trabajo_partido"] = ""
            user_states[user_id]["trabajo_esperando_partido"] = False
            user_states[user_id]["trabajo_esperando_perdida"] = True
            keyboard = [
                [InlineKeyboardButton("⏭️ Saltar paso", callback_data="trabajo_skip|perdida")],
                botones_navegacion(),
            ]
            await query.edit_message_text(
                resumen_trabajo_parcial(user_states[user_id]) +
                "\n\n💸 Escribe la pérdida (acepta signo y coma/punto):",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if paso == "perdida" and user_states[user_id].get("trabajo_esperando_perdida"):
            user_states[user_id]["history"].append(user_states[user_id].copy())
            user_states[user_id]["trabajo_perdida"] = ""
            user_states[user_id]["trabajo_esperando_perdida"] = False
            user_states[user_id]["trabajo_esperando_beneficio"] = True
            keyboard = [
                [InlineKeyboardButton("⏭️ Saltar paso", callback_data="trabajo_skip|beneficio")],
                botones_navegacion(),
            ]
            await query.edit_message_text(
                resumen_trabajo_parcial(user_states[user_id]) +
                "\n\n💰 Escribe el beneficio (acepta signo y coma/punto):",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        if paso == "beneficio" and user_states[user_id].get("trabajo_esperando_beneficio"):
            user_states[user_id]["history"].append(user_states[user_id].copy())
            user_states[user_id]["trabajo_beneficio"] = ""
            user_states[user_id]["trabajo_esperando_beneficio"] = False
            user_states[user_id]["trabajo_esperando_observaciones_finales"] = True
            await query.edit_message_text(
                resumen_trabajo_parcial(user_states[user_id]) +
                "\n\n📝 Escribe observaciones finales (se guardan en columna S):"
            )
            return
        
    # MENU GESTIÓN
    if data == "menu|gestion":
        await query.edit_message_text(
            "💰 Gestión de dinero",
            reply_markup=InlineKeyboardMarkup(teclado_menu_gestion())
        )
        return

    # MENU ADD
    if data=="menu|add":
        
        # 🔴 RESETEAR ESTADO COMPLETAMENTE
        user_states[user_id] = {
            "history": [],
            "ui_chat_id": query.message.chat_id,
            "ui_message_id": query.message.message_id,
        }
    
        keyboard=[
            [InlineKeyboardButton("Hoy",callback_data="fecha|hoy"),
             InlineKeyboardButton("Ayer",callback_data="fecha|ayer")],
            [InlineKeyboardButton("Otra",callback_data="fecha|otra")],
            botones_navegacion()
        ]
    
        await query.edit_message_text(
            "📅 Selecciona la fecha:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data=="menu|resumen":
        await mostrar_selector_meses(query)
        return

    if data.startswith("resumen_mes|"):
        _, año, mes = data.split("|")

        keyboard = [
            [InlineKeyboardButton("Ramon", callback_data=f"resumen_final|{año}|{mes}|Ramon")],
            [InlineKeyboardButton("Claudia", callback_data=f"resumen_final|{año}|{mes}|Claudia")],
            [InlineKeyboardButton("Común", callback_data=f"resumen_final|{año}|{mes}|Común")],
            [InlineKeyboardButton("⬅ Volver", callback_data="menu|resumen")]
        ]
    
        await query.edit_message_text(
            "👤 ¿De quién quieres ver el resumen?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return


    if data.startswith("resumen_año|"):
        _, año = data.split("|")
    
        keyboard = [
            [InlineKeyboardButton("Ramon", callback_data=f"resumen_final|{año}|0|Ramon")],
            [InlineKeyboardButton("Claudia", callback_data=f"resumen_final|{año}|0|Claudia")],
            [InlineKeyboardButton("Común", callback_data=f"resumen_final|{año}|0|Común")],
            [InlineKeyboardButton("⬅ Volver", callback_data="menu|resumen")]
        ]
    
        await query.edit_message_text(
            "👤 ¿De quién quieres ver el resumen?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return


    # ================= RESUMEN FINAL =================

    if data.startswith("resumen_final|"):
        _, año, mes, persona = data.split("|")
    
        mes = int(mes)
        if mes == 0:
            mes = None
    
        await generar_resumen(query, int(año), mes, persona)
        return



    # FECHA
    if data.startswith("fecha|"):
        opcion=data.split("|")[1]

        if opcion=="hoy":
            fecha=datetime.now().strftime("%d/%m/%Y")
        elif opcion=="ayer":
            fecha=(datetime.now()-timedelta(days=1)).strftime("%d/%m/%Y")
        else:
            user_states[user_id]["esperando_fecha_manual"]=True
            await query.edit_message_text("✍️ Escribe fecha DD/MM/YYYY:")
            return

        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["fecha"]=fecha
        
        personas=get_personas_gasto()

        keyboard=[[InlineKeyboardButton(p,callback_data=f"persona|{p}")]
                  for p in personas]
        keyboard.append(botones_navegacion())

        await query.edit_message_text(
            resumen_parcial(user_states[user_id])+"\n¿De quién es el gasto?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
            
    # ================= PERSONA =================

    if data.startswith("persona|"):
        persona = data.split("|")[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["persona"] = persona

        pagadores = get_quien_paga()

        keyboard = [[InlineKeyboardButton(p, callback_data=f"pagador|{p}")]
                    for p in pagadores]

        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="back"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
        ])

        await query.edit_message_text(
            resumen_parcial(user_states[user_id]) +
            "\n¿Quién paga?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= PAGADOR =================

    if data.startswith("pagador|"):
        pagador = data.split("|")[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["pagador"] = pagador

        tipos = get_tipos()

        keyboard = [[InlineKeyboardButton(t, callback_data=f"tipo|{t}")]
                    for t in tipos]

        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="back"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
        ])

        await query.edit_message_text(
            resumen_parcial(user_states[user_id]) +
            "\nSelecciona TIPO:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= TIPO =================

    if data.startswith("tipo|"):
        tipo = data.split("|")[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["tipo"] = tipo

        categorias = get_categorias(tipo)

        keyboard = [[InlineKeyboardButton(c, callback_data=f"categoria|{c}")]
                    for c in categorias]

        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="back"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
        ])

        await query.edit_message_text(
            resumen_parcial(user_states[user_id]) +
            "\nSelecciona CATEGORÍA:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= CATEGORIA =================

    if data.startswith("categoria|"):
        categoria = data.split("|")[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["categoria"] = categoria

        sub1_list = get_sub1(user_states[user_id]["tipo"], categoria)

        keyboard = [[InlineKeyboardButton(s, callback_data=f"sub1|{s}")]
                    for s in sub1_list]

        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="back"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
        ])

        await query.edit_message_text(
            resumen_parcial(user_states[user_id]) +
            "\nSelecciona SUB1:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= SUB1 =================

    if data.startswith("sub1|"):
        sub1 = data.split("|")[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["sub1"] = sub1

        sub2_list = get_sub2(
            user_states[user_id]["tipo"],
            user_states[user_id]["categoria"],
            sub1
        )

        if not sub2_list:
            user_states[user_id]["sub2"] = "—"
            user_states[user_id]["sub3"] = "—"

            keyboard = [[
                InlineKeyboardButton("Sí", callback_data="obs|si"),
                InlineKeyboardButton("No", callback_data="obs|no")
            ]]

            keyboard.append([
                InlineKeyboardButton("⬅ Volver", callback_data="back"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
            ])

            await query.edit_message_text(
                resumen_parcial(user_states[user_id]) +
                "\n¿Quieres añadir una observación?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        keyboard = [[InlineKeyboardButton(s, callback_data=f"sub2|{s}")]
                    for s in sub2_list]

        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="back"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
        ])

        await query.edit_message_text(
            resumen_parcial(user_states[user_id]) +
            "\nSelecciona SUB2:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= SUB2 =================

    if data.startswith("sub2|"):
        sub2 = data.split("|")[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["sub2"] = sub2

        sub3_list = get_sub3(
            user_states[user_id]["tipo"],
            user_states[user_id]["categoria"],
            user_states[user_id]["sub1"],
            sub2
        )

        if not sub3_list:
            user_states[user_id]["sub3"] = "—"

            keyboard = [[
                InlineKeyboardButton("Sí", callback_data="obs|si"),
                InlineKeyboardButton("No", callback_data="obs|no")
            ]]

            keyboard.append([
                InlineKeyboardButton("⬅ Volver", callback_data="back"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
            ])

            await query.edit_message_text(
                resumen_parcial(user_states[user_id]) +
                "\n¿Quieres añadir una observación?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        keyboard = [[InlineKeyboardButton(s, callback_data=f"sub3|{s}")]
                    for s in sub3_list]

        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="back"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
        ])

        await query.edit_message_text(
            resumen_parcial(user_states[user_id]) +
            "\nSelecciona SUB3:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= SUB3 =================

    if data.startswith("sub3|"):
        sub3 = data.split("|")[1]
        user_states[user_id]["history"].append(user_states[user_id].copy())
        user_states[user_id]["sub3"] = sub3

        keyboard = [[
            InlineKeyboardButton("Sí", callback_data="obs|si"),
            InlineKeyboardButton("No", callback_data="obs|no")
        ]]

        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="back"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")
        ])

        await query.edit_message_text(
            resumen_parcial(user_states[user_id]) +
            "\n¿Quieres añadir una observación?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ================= OBS =================

    if data.startswith("obs|"):
        opcion = data.split("|")[1]

        if opcion == "si":
            user_states[user_id]["esperando_observacion_texto"] = True
            await query.edit_message_text(
                resumen_parcial(user_states[user_id]) + "\n✍️ Escribe la observación:"
            )
        else:
            user_states[user_id]["observacion"] = ""
            user_states[user_id]["esperando_importe"] = True
            await query.edit_message_text(
                resumen_parcial(user_states[user_id]) + "\n💰 Escribe el importe:"
            )
        return
        
    # ================= BACK =================

    if data == "back":

        history = user_states[user_id].get("history", [])
    
        if not history:
            await mostrar_menu(query)
            return
    
        # Recuperar estado anterior
        previous_state = history.pop()
        user_states[user_id] = previous_state
    
        # Reconstruir pantalla automáticamente
        data_state = user_states[user_id]
        
        if data_state.get("flujo") == "trabajo_gasto":
            if "trabajo_gasto_usuario" in data_state:
                await query.edit_message_text(
                    resumen_trabajo_gasto_parcial(data_state) + "\n✍️ Escribe la Información:",
                    reply_markup=InlineKeyboardMarkup([botones_navegacion()])
                )
                return

            if "trabajo_persona" in data_state:
                persona = data_state["trabajo_persona"]
                keyboard = [
                    [InlineKeyboardButton(usuario, callback_data=f"trabajo_gasto_usuario|{usuario}")]
                    for usuario in TRABAJO_GASTOS_COLUMNAS[persona].keys()
                ]
                keyboard.append(botones_navegacion())
                await query.edit_message_text(
                    resumen_trabajo_gasto_parcial(data_state) + "\nSelecciona usuario:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            keyboard = [
                [InlineKeyboardButton("Ramon", callback_data="trabajo_gasto_persona|Ramon")],
                [InlineKeyboardButton("Claudia", callback_data="trabajo_gasto_persona|Claudia")],
                botones_navegacion(),
            ]
            await query.edit_message_text(
                "💼 Trabajo · Añadir gasto\n\n¿De qué persona quieres añadir el gasto?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return


        if data_state.get("flujo") == "trabajo":
            if "trabajo_tipo_promo" in data_state:
                keyboard = [[InlineKeyboardButton(x, callback_data=f"trabajo_tipo_promo|{x}")]
                            for x in TRABAJO_TIPOS_PROMO]
                keyboard.append(botones_navegacion())
                await query.edit_message_text(
                    resumen_trabajo_parcial(data_state) + "\n\n🏷️ Tipo de promoción:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            if "trabajo_tipo_bono" in data_state:
                keyboard = [[InlineKeyboardButton(x, callback_data=f"trabajo_tipo_bono|{x}")]
                            for x in TRABAJO_TIPOS_BONO]
                keyboard.append(botones_navegacion())
                await query.edit_message_text(
                    resumen_trabajo_parcial(data_state) + "\n\n🎁 Tipo de bono:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            if "trabajo_casa" in data_state or data_state.get("trabajo_esperando_casa_input"):
                await query.edit_message_text(
                    resumen_trabajo_parcial(data_state) +
                    "\n\nEscribe la casa de apuestas (ej: RETA, WilliamHill, CasinoGranMadrid):"
                )
                return

            if "trabajo_fecha" in data_state:
                keyboard = [
                    [InlineKeyboardButton("Hoy", callback_data="trabajo_fecha|hoy"),
                     InlineKeyboardButton("Ayer", callback_data="trabajo_fecha|ayer")],
                    [InlineKeyboardButton("Otra", callback_data="trabajo_fecha|otra")],
                    botones_navegacion(),
                ]
                await query.edit_message_text(
                    resumen_trabajo_parcial(data_state) + "\n\n📅 Selecciona fecha:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            if "trabajo_promotor" in data_state or data_state.get("trabajo_promotores"):
                persona = data_state["trabajo_persona"]
                seleccionados = data_state.get("trabajo_promotores", [])
                keyboard = construir_teclado_promotores(persona, seleccionados)
                await query.edit_message_text(
                    f"💼 Trabajo · {persona}\n\n¿Quién hace la promoción?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
    
        if "sub3" in data_state:
            await query.edit_message_text(
                resumen_parcial(data_state) +
                "\nSelecciona SUB3:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(s, callback_data=f"sub3|{s}")]
                     for s in get_sub3(
                        data_state["tipo"],
                        data_state["categoria"],
                        data_state["sub1"],
                        data_state["sub2"]
                     )] + [botones_navegacion()]
                )
            )
            return
    
        if "sub2" in data_state:
            await query.edit_message_text(
                resumen_parcial(data_state) +
                "\nSelecciona SUB2:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(s, callback_data=f"sub2|{s}")]
                     for s in get_sub2(
                        data_state["tipo"],
                        data_state["categoria"],
                        data_state["sub1"]
                     )] + [botones_navegacion()]
                )
            )
            return
    
        if "sub1" in data_state:
            await query.edit_message_text(
                resumen_parcial(data_state) +
                "\nSelecciona SUB1:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(s, callback_data=f"sub1|{s}")]
                     for s in get_sub1(
                        data_state["tipo"],
                        data_state["categoria"]
                     )] + [botones_navegacion()]
                )
            )
            return
    
        if "categoria" in data_state:
            await query.edit_message_text(
                resumen_parcial(data_state) +
                "\nSelecciona CATEGORÍA:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(c, callback_data=f"categoria|{c}")]
                     for c in get_categorias(data_state["tipo"])] + [botones_navegacion()]
                )
            )
            return
    
        if "tipo" in data_state:
            await query.edit_message_text(
                resumen_parcial(data_state) +
                "\nSelecciona TIPO:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t, callback_data=f"tipo|{t}")]
                     for t in get_tipos()] + [botones_navegacion()]
                )
            )
            return
    
        if "pagador" in data_state:
            await query.edit_message_text(
                resumen_parcial(data_state) +
                "\n¿Quién paga?",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(p, callback_data=f"pagador|{p}")]
                     for p in get_quien_paga()] + [botones_navegacion()]
                )
            )
            return
    
        if "persona" in data_state:
            await query.edit_message_text(
                resumen_parcial(data_state) +
                "\n¿De quién es el gasto?",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(p, callback_data=f"persona|{p}")]
                     for p in get_personas_gasto()] + [botones_navegacion()]
                )
            )
            return
    
        if "fecha" in data_state:
            keyboard = [
                [InlineKeyboardButton("Hoy", callback_data="fecha|hoy"),
                 InlineKeyboardButton("Ayer", callback_data="fecha|ayer")],
                [InlineKeyboardButton("Otra", callback_data="fecha|otra")],
                botones_navegacion()
            ]
    
            await query.edit_message_text(
                "📅 Selecciona la fecha:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    # ================= MENU LISTA =================
    
    if data == "menu|lista":
        await query.edit_message_text(
            "🛒 Lista de la compra",
            reply_markup=InlineKeyboardMarkup(teclado_menu_lista())
        )
        return

    if data == "lista|add":
    
        keyboard = [
            [InlineKeyboardButton("Carrefour", callback_data="lista_add|Carrefour")],
            [InlineKeyboardButton("Mercadona", callback_data="lista_add|Mercadona")],
            [InlineKeyboardButton("Sirena", callback_data="lista_add|Sirena")],
            [InlineKeyboardButton("Otros", callback_data="lista_add|Otros")],
            [InlineKeyboardButton("⬅ Volver", callback_data="menu|lista")]
        ]
    
        await query.edit_message_text(
            "Selecciona supermercado:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("lista_add|"):
    
        supermercado = data.split("|")[1]
    
        user_states[user_id] = {
            "lista_supermercado": supermercado,
            "esperando_lista_productos": True,
            "ui_chat_id": query.message.chat_id,
            "ui_message_id": query.message.message_id,
        }
    
        await query.edit_message_text(
            f"Escribe los productos separados por coma.\nEjemplo:\nLeche, Pan, Huevos\n\nSupermercado: {supermercado}"
        )
        return

    if data == "lista|ver":
    
        mensaje = "🛒 LISTA DE LA COMPRA\n\n"
    
        for nombre, hoja in [
            ("Carrefour", sheet_carrefour),
            ("Mercadona", sheet_mercadona),
            ("Sirena", sheet_sirena),
            ("Otros", sheet_otros)
        ]:
    
            productos = hoja.col_values(1)[1:]
    
            mensaje += f"📍 {nombre}\n"
    
            if productos:
                for p in productos:
                    mensaje += f"  • {p}\n"
            else:
                mensaje += "  (Vacío)\n"
    
            mensaje += "\n"
    
        keyboard = [[InlineKeyboardButton("⬅ Volver", callback_data="menu|lista")]]
    
        await query.edit_message_text(
            mensaje,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "lista|borrar":
    
        keyboard = [
            [InlineKeyboardButton("Carrefour", callback_data="lista_borrar|Carrefour")],
            [InlineKeyboardButton("Mercadona", callback_data="lista_borrar|Mercadona")],
            [InlineKeyboardButton("Sirena", callback_data="lista_borrar|Sirena")],
            [InlineKeyboardButton("Otros", callback_data="lista_borrar|Otros")],
            [InlineKeyboardButton("🗑️ Borrar TODO", callback_data="lista_borrar|todo")],
            [InlineKeyboardButton("⬅ Volver", callback_data="menu|lista")]
        ]
    
        await query.edit_message_text(
            "Selecciona qué quieres borrar:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "lista_borrar|todo":

        for hoja in [sheet_carrefour, sheet_mercadona, sheet_sirena, sheet_otros]:
    
            filas = hoja.row_count
    
            if filas > 1:
                hoja.batch_clear([f"A2:A{filas}"])
                
        await notificar_lista_actualizada(context)
        await mostrar_menu_lista(query)
        await notificar_lista_actualizada(context, mover_menu=True)
        await desplazar_menu_al_final(
            context,
            user_id,
            "🛒 Lista de la compra",
            teclado_menu_lista(),
        )
        return

    if data.startswith("lista_borrar|"):
    
        supermercado = data.split("|")[1]
    
        hoja = {
            "Carrefour": sheet_carrefour,
            "Mercadona": sheet_mercadona,
            "Sirena": sheet_sirena,
            "Otros": sheet_otros
        }[supermercado]
    
        productos = hoja.col_values(1)[1:]  # quitar cabecera
    
        if not productos:
            await query.edit_message_text("Lista vacía.")
            return
    
        user_states[user_id] = {
            "modo_borrado": True,
            "supermercado": supermercado,
            "seleccionados": set(),
            "ui_chat_id": query.message.chat_id,
            "ui_message_id": query.message.message_id,
        }
    
        keyboard = []

        for i, producto in enumerate(productos, start=2):
            keyboard.append([
                InlineKeyboardButton(
                    f"☐ {producto}",
                    callback_data=f"lista_toggle|{i}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton("🗑️ Eliminar seleccionados", callback_data="lista_confirm_delete")
        ])
        
        # 🔴 NUEVO BOTÓN
        keyboard.append([
            InlineKeyboardButton(
                "🗑️ Borrar TODO este supermercado",
                callback_data=f"lista_delete_all|{supermercado}"
            )
        ])
        
        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="menu|lista")
        ])
    
        await query.edit_message_text(
            f"Selecciona productos a borrar ({supermercado}):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

        # ================= BORRAR TODO SUPERMERCADO =================
    
    if data.startswith("lista_delete_all|"):

        _, supermercado = data.split("|")
    
        hoja = {
            "Carrefour": sheet_carrefour,
            "Mercadona": sheet_mercadona,
            "Sirena": sheet_sirena,
            "Otros": sheet_otros
        }[supermercado]
    
        filas_con_datos = len(hoja.col_values(1))
    
        if filas_con_datos > 1:
            hoja.batch_clear([f"A2:A{filas_con_datos}"])
    
        await query.answer("Lista borrada ✅")
        await notificar_lista_actualizada(context, mover_menu=True)
        await desplazar_menu_al_final(
            context,
            user_id,
            "🛒 Lista de la compra",
            teclado_menu_lista(),
        )
        return

    if data.startswith("lista_toggle|"):

        fila = int(data.split("|")[1])
    
        estado = user_states[user_id]
        supermercado = estado["supermercado"]
    
        hoja = {
            "Carrefour": sheet_carrefour,
            "Mercadona": sheet_mercadona,
            "Sirena": sheet_sirena,
            "Otros": sheet_otros
        }[supermercado]
    
        productos = hoja.col_values(1)[1:]
    
        if fila in estado["seleccionados"]:
            estado["seleccionados"].remove(fila)
        else:
            estado["seleccionados"].add(fila)
    
        # reconstruir teclado
        keyboard = []
    
        for i, producto in enumerate(productos, start=2):
            marca = "✅" if i in estado["seleccionados"] else "☐"
            keyboard.append([
                InlineKeyboardButton(
                    f"{marca} {producto}",
                    callback_data=f"lista_toggle|{i}"
                )
            ])
    
        keyboard.append([
            InlineKeyboardButton("🗑️ Eliminar seleccionados", callback_data="lista_confirm_delete")
        ])
        keyboard.append([
            InlineKeyboardButton("⬅ Volver", callback_data="menu|lista")
        ])
    
        await query.edit_message_text(
            f"Selecciona productos a borrar ({supermercado}):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "lista_confirm_delete":

        estado = user_states.get(user_id)
    
        if not estado or not estado["seleccionados"]:
            await query.answer("No hay productos seleccionados.")
            return
    
        supermercado = estado["supermercado"]
    
        hoja = {
            "Carrefour": sheet_carrefour,
            "Mercadona": sheet_mercadona,
            "Sirena": sheet_sirena,
            "Otros": sheet_otros
        }[supermercado]
    
        # borrar desde abajo hacia arriba
        for fila in sorted(estado["seleccionados"], reverse=True):
            hoja.delete_rows(fila)
    
        user_states.pop(user_id)
    
        await query.answer("Productos eliminados ✅")
        await notificar_lista_actualizada(context, mover_menu=True)
        await desplazar_menu_al_final(
            context,
            user_id,
            "🛒 Lista de la compra",
            teclado_menu_lista(),
        )
        return


        

# =========================
# REGISTRO DE HANDLERS
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
        webhook_url=f"{WEBHOOK_BASE_URL}/{TOKEN}",
        url_path=TOKEN,
    )
