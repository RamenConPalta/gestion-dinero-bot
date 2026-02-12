import os
import logging
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==============================
# CONFIGURACIÓN
# ==============================

TOKEN = os.environ.get("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

if not TOKEN:
    raise ValueError("Falta BOT_TOKEN en variables de entorno")

if not RENDER_EXTERNAL_URL:
    raise ValueError("Falta RENDER_EXTERNAL_URL en variables de entorno")

WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}/{TOKEN}"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

app = Flask(__name__)

# Crear aplicación del bot
application = ApplicationBuilder().token(TOKEN).build()


# ==============================
# COMANDOS DEL BOT
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola 👋 Soy tu bot de gestión de dinero.\n\n"
        "Escribe cualquier mensaje y lo recibiré correctamente."
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Recibido: {update.message.text}")


application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))


# ==============================
# RUTAS FLASK
# ==============================

@app.route("/")
def home():
    return "Bot funcionando correctamente ✅"


@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "ok"


# ==============================
# INICIALIZACIÓN
# ==============================

@app.before_first_request
async def setup():
    await application.initialize()
    await application.bot.set_webhook(WEBHOOK_URL)
    print("Webhook configurado correctamente")


# ==============================
# MAIN
# ==============================
import threading

def run_bot():
    application.run_polling()

# Ejecutar el bot en un hilo separado
bot_thread = threading.Thread(target=run_bot)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
