import logging
import os

from telegram import Update
from telegram.ext import Application, MessageHandler, filters

from lifeos.agent import process_message
from lifeos.db import init_db

log = logging.getLogger(__name__)

_allowed_user_id: str  # Set in run_bot()


async def handle_message(update: Update, context) -> None:
    if not update.message or not update.message.text:
        return

    # For DMs, chat.id == from_user.id (private chat ID equals user ID)
    from_user = update.message.from_user
    if not from_user:
        log.warning("Message has no from_user")
        return
    if str(from_user.id) != _allowed_user_id:
        log.warning("Unauthorized user_id=%s", from_user.id)
        return

    log.info("Received message from %s", update.message.from_user.username if update.message.from_user else "unknown")
    chat_id = str(update.message.chat_id)
    response = await process_message(update.message.text, chat_id)
    await update.message.reply_text(response)


def run_bot() -> None:
    global _allowed_user_id

    init_db()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    user_id = os.getenv("PARAS_TELEGRAM_USER_ID")
    if not user_id:
        raise ValueError("PARAS_TELEGRAM_USER_ID not set")
    _allowed_user_id = user_id

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot started")
    app.run_polling()
