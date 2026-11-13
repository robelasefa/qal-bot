"""Global error handling for unhandled Telegram update failures."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

if TYPE_CHECKING:
    from .handlers import Services

logger = logging.getLogger(__name__)

# A broken handler should not flood the owner with identical alerts.
ERROR_NOTIFY_INTERVAL_SECONDS = 300.0


def is_critical_error(error: BaseException) -> bool:
    """Decide whether an unhandled error is worth waking the owner for.

    Telegram errors are usually about one chat or a transient network issue.
    They still get a full traceback, but alerting the owner for every blocked
    user would be noise.
    """
    return not isinstance(error, TelegramError)


def update_kind(update: object) -> str:
    """Name the kind of update without logging its contents."""
    if not isinstance(update, Update):
        return "unknown update"
    if update.callback_query is not None:
        return "callback query"
    if update.message is not None:
        return "message"
    if update.edited_message is not None:
        return "edited message"
    return "other update"


def format_error_notice(error: BaseException, update: object) -> str:
    """Build the short owner alert. Never include the update payload."""
    detail = " ".join(str(error).split())
    if len(detail) > 300:
        detail = detail[:297] + "..."

    return (
        "⚠️ Qal hit an unexpected error.\n\n"
        f"Type: {type(error).__name__}\n"
        f"Update: {update_kind(update)}\n"
        f"Detail: {detail or 'no detail'}\n\n"
        "The full traceback is in the server logs."
    )


async def alert_owner(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Send the owner a short alert, rate-limited to one every five minutes."""
    services: Services | None = context.application.bot_data.get("services")
    owner_id = services.settings.owner_user_id if services else None
    if owner_id is None:
        return

    now = time.monotonic()
    last_notice = context.application.bot_data.get("last_error_notice")
    if last_notice is not None and now - last_notice < ERROR_NOTIFY_INTERVAL_SECONDS:
        return
    context.application.bot_data["last_error_notice"] = now

    try:
        await context.bot.send_message(chat_id=owner_id, text=text)
    except TelegramError:
        logger.warning("Could not notify the owner")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled exceptions and alert the owner about code-level failures."""
    error = context.error
    if error is None:
        return

    # Log first, so the traceback is never lost if the alert itself fails.
    logger.error("Unhandled exception while handling an update", exc_info=error)

    if not is_critical_error(error):
        return

    await alert_owner(context, format_error_notice(error, update))
