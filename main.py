import os
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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
# FUNCIONES AUXILIARES
# =========================

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

# =========================
# FUNCIONES DATOS
# =========================

def get_personas_gasto():
    valores = listas_sheet.col_values(19)[1:4]
    return [v for v in valores if v and v != "—"]

def get_quien_paga():
    valores = listas_sheet.col_values(20)[1:4]
    return [v for v in valores if v and v != "—"]

def get_tipos():
    data = listas_sheet.get_all_values()[1:]
    return sorted(set(row[0] for row in data if row[0] and row[0] != "—"))

def get_categorias(tipo):
    data = listas_sheet.get_all_values()[1:]
    return sorted(set(row[1] for row in data
                      if row[0]==tipo and row[1] and row[1]!="—"))

def get_sub1(tipo, categoria):
    data = listas_sheet.get_all_values()[1:]
    return sorted(set(row[2] for row in data
                      if row[0]==tipo and row[1]==categoria and row[2]!="—"))

def get_sub2(tipo, categoria, sub1):
    data = listas_sheet.get_all_values()[1:]
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
    data = listas_sheet.get_all_values()[1:]
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

# =========================
# MENU
# =========================

async def mostrar_menu(query):
    keyboard = [
        [InlineKeyboardButton("➕ Añadir registro", callback_data="menu|add")],
        [InlineKeyboardButton("📈 Ver resumen", callback_data="menu|resumen")]
    ]
    await query.edit_message_text(
        "📊 Gestión de dinero\n\nSelecciona una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard)
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
    keyboard = [
        [InlineKeyboardButton("➕ Añadir registro", callback_data="menu|add")],
        [InlineKeyboardButton("📈 Ver resumen", callback_data="menu|resumen")]
    ]
    await update.message.reply_text(
        "📊 Gestión de dinero\n\nSelecciona una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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

            # === Barra + color ===
            if objetivo > 0:
                porcentaje = real / objetivo
                bloques = int(min(porcentaje, 1) * 10)
                barra = "█"*bloques + "░"*(10-bloques)

                if porcentaje <= 0.8:
                    icono = "🟢"
                elif porcentaje <= 1:
                    icono = "🟡"
                else:
                    icono = "🔴"

                uso_txt = f"{icono} {int(porcentaje*100)}%"
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

        except:
            continue

    return objetivos




# =========================
# RECIBIR TEXTO
# =========================

async def recibir_texto(update, context):
    user_id=update.effective_user.id
    if user_id not in user_states:
        return

    texto=update.message.text.strip()

    # FECHA MANUAL
    if user_states[user_id].get("esperando_fecha_manual"):
        try:
            fecha=datetime.strptime(texto,"%d/%m/%Y")
            user_states[user_id]["history"].append(user_states[user_id].copy())
            user_states[user_id]["fecha"]=fecha.strftime("%d/%m/%Y")
            user_states[user_id]["esperando_fecha_manual"]=False
        except:
            await update.message.reply_text("❌ Fecha inválida. Usa DD/MM/YYYY")
            return

        personas=get_personas_gasto()
        keyboard=[[InlineKeyboardButton(p,callback_data=f"persona|{p}")]
                  for p in personas]
        keyboard.append(botones_navegacion())

        await update.message.reply_text(
            resumen_parcial(user_states[user_id])+"\n¿De quién es el gasto?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # OBSERVACION
    if user_states[user_id].get("esperando_observacion_texto"):
        user_states[user_id]["observacion"]=texto
        user_states[user_id]["esperando_observacion_texto"]=False
        user_states[user_id]["esperando_importe"]=True
        await update.message.reply_text("💰 Escribe el importe:")
        return

    # IMPORTE
    if user_states[user_id].get("esperando_importe"):
        try:
            importe=float(texto.replace(",","."))
            if importe<=0: raise ValueError
        except:
            await update.message.reply_text("❌ Importe no válido.")
            return

        data=user_states[user_id]

        sheet.append_row([
            data.get("fecha",""),
            data.get("persona",""),
            data.get("pagador",""),
            data.get("tipo",""),
            data.get("categoria",""),
            data.get("sub1","—"),
            data.get("sub2","—"),
            data.get("sub3","—"),
            data.get("observacion",""),
            importe
        ])

        await update.message.reply_text("✅ Movimiento guardado correctamente.")
        user_states.pop(user_id)

# =========================
# BOTONES
# =========================

async def button_handler(update, context):
    query=update.callback_query
    await query.answer()

    user_id=query.from_user.id
    data=query.data

    if user_id not in user_states:
        user_states[user_id]={}

    # CANCELAR
    if data=="cancelar":
        user_states.pop(user_id,None)
        await mostrar_menu(query)
        return

    # VOLVER MENU
    if data=="menu|volver":
        await mostrar_menu(query)
        return

    # MENU ADD
    if data=="menu|add":
        
        # 🔴 RESETEAR ESTADO COMPLETAMENTE
        user_states[user_id] = {
            "history": []
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
            await query.edit_message_text("✍️ Escribe la observación:")
        else:
            user_states[user_id]["observacion"] = ""
            user_states[user_id]["esperando_importe"] = True
            await query.edit_message_text("💰 Escribe el importe:")
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
        webhook_url=f"https://gestion-dinero-bot.onrender.com/{TOKEN}",
        url_path=TOKEN,
    )



