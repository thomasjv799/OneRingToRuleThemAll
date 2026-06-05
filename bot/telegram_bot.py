import logging
import os

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from ai.graph import run_graph

log = logging.getLogger(__name__)


async def _handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user_id = str(update.effective_user.id)
    reply = run_graph(user_id, msg.text)
    await msg.reply_text(reply or "I couldn't generate a response — please try again.")


def run() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle))
    log.info("Telegram bot started")
    app.run_polling()
