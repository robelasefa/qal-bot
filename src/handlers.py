"""Telegram handlers and the shared per-process services."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .config import Settings
from .error import alert_owner
from .formatting import (
    format_duration,
    format_stats,
    format_wait,
    split_text,
)
from .languages import LANGUAGES, LanguageStore, language_label
from .rate_limit import DailyBudget, RateLimiter
from .stats import Stats
from .transcriber import TranscriptionError, fetch_usage, transcribe_audio

logger = logging.getLogger(__name__)

PRIVATE_BOT_MESSAGE = "🔒 Qal is a private bot. Ask the owner for access."

# Telegram Bot API lets bots download files up to 20 MB.
TELEGRAM_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

# Do not make Telegram fetch or render links found inside a transcript.
NO_LINK_PREVIEW = LinkPreviewOptions(is_disabled=True)

ALLOWED_AUDIO_SUFFIXES = {
    ".ogg",
    ".oga",
    ".opus",
    ".mp3",
    ".m4a",
    ".wav",
    ".flac",
    ".aif",
    ".aiff",
    ".webm",
    ".mkv",
}


@dataclass
class Services:
    """Long-lived objects shared by all handlers."""

    settings: Settings
    languages: LanguageStore
    limiter: RateLimiter
    daily: DailyBudget
    transcribe_slots: asyncio.Semaphore
    stats: Stats


def is_allowed(services: Services, user_id: int) -> bool:
    """Check the allowlist. An empty list means the bot is public.

    The owner is always allowed, even when the allowlist is configured.
    """
    settings = services.settings
    if not settings.allowed_user_ids:
        return True
    return (
        user_id in settings.allowed_user_ids
        or user_id == settings.owner_user_id
    )


def is_owner(services: Services, user_id: int) -> bool:
    """Return True only when an owner is configured and the ID matches."""
    owner_id = services.settings.owner_user_id
    return owner_id is not None and user_id == owner_id


def language_keyboard(current: str) -> InlineKeyboardMarkup:
    """One button per language, with a check mark on the current one."""
    rows = [
        [
            InlineKeyboardButton(
                ("✅ " if code == current else "") + label,
                callback_data=f"lang:{code}",
            )
        ]
        for code, label in LANGUAGES.items()
    ]
    rows.append([InlineKeyboardButton("Done", callback_data="lang:done")])
    return InlineKeyboardMarkup(rows)


def audio_suffix(message: Message, file_path: str | None) -> str:
    """Pick a file extension the Addis AI SDK can label correctly."""
    if message.voice is not None:
        return ".ogg"

    name = message.audio.file_name if message.audio is not None else None
    suffix = Path(name or file_path or "").suffix.lower()
    return suffix if suffix in ALLOWED_AUDIO_SUFFIXES else ".mp3"


async def set_status(status: Message, text: str) -> None:
    """Replace the 'Transcribing…' message, falling back to a new reply."""
    try:
        await status.edit_text(text)
    except TelegramError:
        try:
            await status.reply_text(text)
        except TelegramError:
            logger.warning("Could not deliver a message to the user")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    services: Services = context.application.bot_data["services"]
    if not is_allowed(services, user.id):
        await message.reply_text(PRIVATE_BOT_MESSAGE)
        return

    services.stats.record_user(user.id)
    current = services.languages.get(user.id)

    commands = (
        "/language — choose the spoken language\n"
        "/help — how it works and the limits"
    )

    await message.reply_text(
        "👋 Hi! I'm Qal (ቃል).\n\n"
        "Send me a voice message or an audio file and I'll transcribe it "
        "with Addis AI.\n\n"
        f"Current language: {language_label(current)}\n\n"
        "Commands:\n"
        f"{commands}"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    services: Services = context.application.bot_data["services"]
    if not is_allowed(services, user.id):
        await message.reply_text(PRIVATE_BOT_MESSAGE)
        return

    services.stats.record_user(user.id)

    await message.reply_text(
        "How to use Qal:\n\n"
        "1. Send a voice message or an audio file.\n"
        "2. I transcribe it and reply with the text.\n\n"
        "Use /language to pick a language."
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    services: Services = context.application.bot_data["services"]
    settings = services.settings

    if settings.owner_user_id is None:
        await message.reply_text(
            "Owner access is not configured. Set OWNER_USER_ID in .env."
        )
        return

    if not is_owner(services, user.id):
        await message.reply_text("This command is owner-only.")
        return

    try:
        usage = await fetch_usage(settings.addis_api_key)
    except TranscriptionError as exc:
        await message.reply_text(exc.user_message)
        return

    await message.reply_text(
        format_stats(
            services.stats,
            usage,
            used=services.daily.used(),
            limit=settings.daily_transcription_limit,
        )
    )


async def language_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    services: Services = context.application.bot_data["services"]
    if not is_allowed(services, user.id):
        await message.reply_text(PRIVATE_BOT_MESSAGE)
        return

    services.stats.record_user(user.id)
    current = services.languages.get(user.id)

    await message.reply_text(
        f"Current language: {language_label(current)}.\n"
        "Choose the language spoken in your audio:",
        reply_markup=language_keyboard(current),
    )


async def language_chosen(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    code = query.data.removeprefix("lang:")
    if code == "done":
        await query.answer("Done.")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            logger.warning("Could not remove the language keyboard")
        return

    if code not in LANGUAGES:
        await query.answer("Unknown language.", show_alert=True)
        return

    services: Services = context.application.bot_data["services"]
    user_id = query.from_user.id

    if not is_allowed(services, user_id):
        await query.answer("This bot is private.", show_alert=True)
        return

    services.stats.record_user(user_id)

    if services.languages.get(user_id) == code:
        await query.answer(f"Already using {language_label(code)}.")
        return

    services.languages.set(user_id, code)
    await query.answer(f"Language set to {language_label(code)}.")

    try:
        await query.edit_message_text(
            f"Language set to {language_label(code)}.\n"
            "Send me a voice message or an audio file.",
            reply_markup=language_keyboard(code),
        )
    except TelegramError:
        logger.warning("Could not edit the language message")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    services: Services = context.application.bot_data["services"]
    if not is_allowed(services, user.id):
        await message.reply_text(PRIVATE_BOT_MESSAGE)
        return

    services.stats.record_user(user.id)

    await message.reply_text(
        "Send me a voice message or an audio file. "
        "Use /help to see how it works."
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    media = message.voice or message.audio
    if media is None:
        return

    services: Services = context.application.bot_data["services"]
    settings = services.settings

    if not is_allowed(services, user.id):
        await message.reply_text(PRIVATE_BOT_MESSAGE)
        return

    services.stats.record_user(user.id)

    # Duration and size checks happen before consuming quota.
    duration = int(media.duration or 0)
    if duration > settings.max_audio_seconds:
        await message.reply_text(
            f"That audio is {format_duration(duration)} long. "
            f"The limit is {format_duration(settings.max_audio_seconds)}. "
            "Please send a shorter one."
        )
        return

    if media.file_size and media.file_size > TELEGRAM_MAX_DOWNLOAD_BYTES:
        await message.reply_text(
            "That file is larger than Telegram lets bots download (20 MB). "
            "Please send a shorter audio."
        )
        return

    # Check the shared daily cap before spending this user's hourly quota.
    if services.daily.remaining() <= 0:
        await message.reply_text(
            "Qal has reached today's limit. Please try again tomorrow."
        )
        return

    if not services.limiter.allow(user.id):
        wait = services.limiter.retry_after(user.id)
        await message.reply_text(
            f"You have used your {settings.rate_limit_per_hour} transcriptions "
            f"for this hour. Try again in about {format_wait(wait)}."
        )
        return

    # No await since the check above, so this cannot fail here.
    services.daily.allow()

    language = services.languages.get(user.id)
    services.stats.record_request(user.id, language, duration)
    logger.info(
        "Transcription requested: user=%s language=%s duration=%ss",
        user.id,
        language,
        duration,
    )
    status = await message.reply_text("⏳ Transcribing...")

    try:
        telegram_file = await media.get_file()
        suffix = audio_suffix(message, telegram_file.file_path)

        # The temporary folder is removed on success, failure, or cancellation.
        with tempfile.TemporaryDirectory(prefix="qal-") as temp_dir:
            audio_path = Path(temp_dir) / f"audio{suffix}"
            await telegram_file.download_to_drive(custom_path=audio_path)
            async with services.transcribe_slots:
                started = time.monotonic()
                text = await transcribe_audio(
                    audio_path,
                    language,
                    settings.addis_api_key,
                )
                elapsed = time.monotonic() - started

    except TranscriptionError as exc:
        services.stats.record_failure()
        logger.warning(
            "Transcription failed: user=%s language=%s reason=%s",
            user.id,
            language,
            type(exc).__name__,
        )
        await set_status(status, exc.user_message)
        if exc.notify_owner:
            await alert_owner(
                context,
                "⚠️ Addis AI credits are used up.\n"
                "Top up the account so transcription can continue.",
            )
        return
    except TelegramError:
        services.stats.record_failure()
        logger.exception("Telegram file download failed: user=%s", user.id)
        await set_status(
            status,
            "I could not download that audio from Telegram. Please try again.",
        )
        return
    except Exception:
        services.stats.record_failure()
        await set_status(status, "Something went wrong. Please try again.")
        # Re-raise so the global handler logs the traceback and alerts the owner.
        raise

    chunks = split_text(text)
    if not chunks:
        services.stats.record_failure()
        await set_status(
            status,
            "I could not hear any speech in that audio. Please try again.",
        )
        return

    services.stats.record_success(len(text), elapsed)
    logger.info(
        "Transcription completed: user=%s language=%s characters=%s elapsed=%.1fs",
        user.id,
        language,
        len(text),
        elapsed,
    )

    try:
        await status.edit_text(chunks[0], link_preview_options=NO_LINK_PREVIEW)
    except TelegramError:
        for chunk in chunks:
            await message.reply_text(chunk, link_preview_options=NO_LINK_PREVIEW)
        return

    for chunk in chunks[1:]:
        await message.reply_text(chunk, link_preview_options=NO_LINK_PREVIEW)
