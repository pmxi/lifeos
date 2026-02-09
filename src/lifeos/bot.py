import logging
import os
from datetime import datetime, timezone

import telegramify_markdown
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from lifeos.agent import UploadedFile, clear_conversation, process_message
from lifeos.db import execute_sql_tool, init_db
from lifeos.speech import transcribe_audio

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


async def handle_clear(update: Update, context) -> None:
    """Handle /clear command to reset conversation history."""
    if not update.message:
        return

    from_user = update.message.from_user
    if not from_user or str(from_user.id) != _allowed_user_id:
        return

    chat_id = str(update.message.chat_id)
    clear_conversation(chat_id)
    log.info("Cleared conversation for chat_id=%s", chat_id)
    await update.message.reply_text("Conversation cleared.")


async def handle_message(update: Update, context) -> None:
    if not update.message:
        return

    # For DMs, chat.id == from_user.id (private chat ID equals user ID)
    from_user = update.message.from_user
    if not from_user:
        log.warning("Message has no from_user")
        return
    if str(from_user.id) != _allowed_user_id:
        log.warning("Unauthorized user_id=%s", from_user.id)
        return

    # Extract text (from message or caption for photos)
    text = update.message.text or update.message.caption or ""
    if update.message.text:
        log.debug("Text message length=%d", len(update.message.text))
    if update.message.caption:
        log.debug("Caption length=%d", len(update.message.caption))

    # Extract image data if present
    image_data: bytes | None = None
    if update.message.photo:
        # Get largest photo size (last in list)
        photo = update.message.photo[-1]
        file = await photo.get_file()
        image_data = await file.download_as_bytearray()
        log.info(
            "Received photo from %s (%d bytes)",
            from_user.username or "unknown",
            len(image_data),
        )

    # Extract PDF document data if present
    uploaded_file: UploadedFile | None = None
    if update.message.document:
        document = update.message.document
        filename = document.file_name or "upload.pdf"
        mime_type = document.mime_type or "application/octet-stream"
        is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")

        if not is_pdf:
            log.info(
                "Rejected non-PDF document from %s (%s, mime=%s)",
                from_user.username or "unknown",
                filename,
                mime_type,
            )
            await update.message.reply_text("Only PDF uploads are supported right now.")
            return

        file = await document.get_file()
        document_data = await file.download_as_bytearray()
        uploaded_file = {
            "filename": filename,
            "mime_type": "application/pdf",
            "data": bytes(document_data),
        }
        log.info(
            "Received PDF from %s (%s, %d bytes)",
            from_user.username or "unknown",
            filename,
            len(document_data),
        )

    # Extract voice data and transcribe if present
    if update.message.voice:
        file = await update.message.voice.get_file()
        voice_data = await file.download_as_bytearray()
        log.info(
            "Received voice note from %s (%d bytes, duration=%ss)",
            from_user.username or "unknown",
            len(voice_data),
            update.message.voice.duration,
        )
        try:
            text = await transcribe_audio(bytes(voice_data), filename="voice.ogg")
        except Exception:
            log.exception("Failed to transcribe voice note")
            await update.message.reply_text("Transcription failed.")
            return
        log.debug("Transcription text length=%d", len(text))

    if not text and not image_data and not uploaded_file:
        # No text, photo, or PDF - nothing to process
        log.debug("No usable content found (text/photo/voice/pdf empty)")
        return

    if (
        update.message.text
        or update.message.caption
        or update.message.voice
        or update.message.document
    ):
        log.info("Received message from %s", from_user.username or "unknown")

    chat_id = str(update.message.chat_id)
    response = await process_message(
        text, chat_id, image_data=image_data, uploaded_file=uploaded_file
    )
    log.debug("LLM response length=%d", len(response))
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
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VOICE | filters.Document.ALL)
        & ~filters.COMMAND,
        handle_message,
    ))

    log.info("Bot started")
    app.run_polling()
