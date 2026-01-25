import logging
import os
from datetime import datetime, timezone

import telegramify_markdown
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from lifeos.agent import process_message
from lifeos.db import execute_sql_tool, init_db

log = logging.getLogger(__name__)

_allowed_user_id: str  # Set in run_bot()


async def fire_due_reminders(bot, chat_id: str) -> None:
    """Query and fire all due reminders."""
    now = datetime.now(timezone.utc).isoformat()
    reminders = execute_sql_tool(
        f"SELECT id, prompt FROM reminder WHERE trigger_at <= '{now}' AND status = 'pending'"
    )

    for reminder in reminders:
        reminder_id = reminder["id"]
        prompt = f"[Scheduled Reminder] {reminder['prompt']}"
        log.info("Firing reminder %d: %s", reminder_id, reminder["prompt"])

        try:
            response = await process_message(prompt, chat_id)
            log.debug("Sending reminder response: %s", response)
            formatted = telegramify_markdown.markdownify(response)
            await bot.send_message(chat_id=chat_id, text=formatted, parse_mode="MarkdownV2")
            execute_sql_tool(
                f"UPDATE reminder SET status = 'triggered' WHERE id = {reminder_id}"
            )
        except Exception:
            log.exception("Failed to fire reminder %d", reminder_id)


async def check_reminders_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback to check for due reminders."""
    chat_id = context.job.chat_id  # type: ignore
    await fire_due_reminders(context.bot, str(chat_id))


async def post_init(application: Application) -> None:
    """Post-initialization: fire missed reminders and start scheduler."""
    chat_id = os.getenv("PARAS_TELEGRAM_USER_ID")
    if not chat_id:
        log.warning("PARAS_TELEGRAM_USER_ID not set, skipping reminder scheduler")
        return

    # Fire any missed reminders immediately
    await fire_due_reminders(application.bot, chat_id)

    # Schedule recurring check every 30 seconds
    application.job_queue.run_repeating(  # type: ignore[union-attr]
        check_reminders_job,
        interval=30,
        chat_id=int(chat_id),
    )
    log.info("Reminder scheduler started (30s interval)")


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
    log.debug("Sending response: %s", response)
    formatted = telegramify_markdown.markdownify(response)
    await update.message.reply_text(formatted, parse_mode="MarkdownV2")


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

    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot started")
    app.run_polling()
