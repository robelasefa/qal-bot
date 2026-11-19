"""Application wiring: logging, handlers, and polling/webhook startup."""

from __future__ import annotations

import asyncio
import logging
import sys
from urllib.parse import urlparse

from telegram import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .config import ConfigError, Settings, load_settings
from .error import error_handler
from .handlers import (
    Services,
    handle_audio,
    handle_text,
    help_command,
    language_chosen,
    language_command,
    start,
    stats_command,
    translate_callback,
)
from .languages import LanguageStore
from .rate_limit import DailyBudget, RateLimiter
from .stats import Stats
from .translation import TranslationCache

logger = logging.getLogger(__name__)

# Qal only handles messages and language-button taps. Asking Telegram for less
# avoids delivering update types the bot will ignore.
ALLOWED_UPDATES = ["message", "callback_query"]


_COLORS = {
    "DEBUG": "\033[36m",     # cyan
    "INFO": "\033[32m",      # green
    "WARNING": "\033[33m",   # yellow
    "ERROR": "\033[31m",     # red
    "CRITICAL": "\033[1;31m",  # bold red
}
_RESET = "\033[0m"
_DIM = "\033[2m"


class _CleanFormatter(logging.Formatter):
    """Aligned, readable log lines. Color only on a real terminal."""

    def __init__(self, debug: bool) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self.debug = debug

    def format(self, record: logging.LogRecord) -> str:
        time_str = self.formatTime(record, self.datefmt)
        level = record.levelname
        # Shorten logger names: "src.handlers" -> "handlers", "telegram.ext" -> "telegram.ext"
        name = record.name.removeprefix("src.")
        # Pad for alignment.
        level_padded = level.ljust(8)
        name_padded = name.ljust(22)[:22]

        message = record.getMessage()
        if record.exc_info:
            message = message + "\n" + self.formatException(record.exc_info)

        if sys.stdout.isatty():
            color = _COLORS.get(level, "")
            if color:
                level_padded = f"{color}{level_padded}{_RESET}"
            name_padded = f"{_DIM}{name_padded}{_RESET}"

        return f"{_DIM}{time_str}{_RESET}  {level_padded}  {name_padded}  {message}"


def setup_logging(debug: bool) -> None:
    """Configure one readable log stream for local use and systemd."""
    handler = logging.StreamHandler()
    handler.setFormatter(_CleanFormatter(debug))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    # Replace any handlers added by imports (e.g. by libraries) with ours.
    root.handlers = [handler]
    # The Bot API client logs every GET/POST at INFO. Keep warnings and errors,
    # but do not let request-level noise bury the bot's own messages.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def post_init(application: Application) -> None:
    """Register Telegram's command menu once the bot starts."""
    commands = [
        BotCommand("start", "Start Qal"),
        BotCommand("language", "Choose the spoken language"),
        BotCommand("help", "How it works and the limits"),
    ]

    try:
        await application.bot.set_my_commands(
            commands, scope=BotCommandScopeAllPrivateChats()
        )
    except TelegramError:
        logger.warning("Could not register the command menu")

    services: Services | None = application.bot_data.get("services")
    owner_id = services.settings.owner_user_id if services else None
    if owner_id is None:
        return

    try:
        await application.bot.set_my_commands(
            commands + [BotCommand("stats", "Usage statistics")],
            scope=BotCommandScopeChat(chat_id=owner_id),
        )
    except TelegramError:
        logger.warning("Could not register the owner command menu")


def build_application(settings: Settings) -> Application:
    """Create the PTB application and register every handler."""
    services = Services(
        settings=settings,
        languages=LanguageStore(settings.data_dir / "languages.json"),
        limiter=RateLimiter(
            limit=settings.rate_limit_per_hour,
            window_seconds=3600,
        ),
        daily=DailyBudget(
            limit=settings.daily_transcription_limit,
            path=settings.data_dir / "daily_budget.json",
        ),
        transcribe_slots=asyncio.Semaphore(settings.transcribe_concurrency),
        stats=Stats(),
        translations=TranslationCache(),
    )

    application = (
        Application.builder()
        .token(settings.telegram_token)
        .post_init(post_init)
        .build()
    )
    application.bot_data["services"] = services

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("language", language_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(
        CallbackQueryHandler(language_chosen, pattern=r"^lang:")
    )
    application.add_handler(
        CallbackQueryHandler(translate_callback, pattern=r"^tr:")
    )
    application.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, handle_audio)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    application.add_error_handler(error_handler)

    return application


def run_bot(application: Application, settings: Settings) -> None:
    """Run with long polling in development and a webhook in production."""
    if settings.debug:
        logger.info("Mode: long polling (DEBUG=true, development bot)")
        application.run_polling(allowed_updates=ALLOWED_UPDATES)
        return

    if settings.webhook_url is None:
        raise RuntimeError("WEBHOOK_URL is required when DEBUG is false")

    path = urlparse(settings.webhook_url).path or "/"
    logger.info(
        "Mode: webhook on %s:%s%s (public host %s)",
        settings.webhook_listen,
        settings.webhook_port,
        path,
        urlparse(settings.webhook_url).netloc,
    )
    application.run_webhook(
        listen=settings.webhook_listen,
        port=settings.webhook_port,
        url_path=path,
        webhook_url=settings.webhook_url,
        secret_token=settings.webhook_secret,
        allowed_updates=ALLOWED_UPDATES,
    )


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    setup_logging(settings.debug)

    logger.info(
        "Starting Qal in %s mode (max_audio_seconds=%s, "
        "rate_limit_per_hour=%s, daily_limit=%s, concurrency=%s, "
        "allowlist=%s, owner_configured=%s)",
        settings.mode,
        settings.max_audio_seconds,
        settings.rate_limit_per_hour,
        settings.daily_transcription_limit,
        settings.transcribe_concurrency,
        len(settings.allowed_user_ids),
        settings.owner_user_id is not None,
    )
    run_bot(build_application(settings), settings)
