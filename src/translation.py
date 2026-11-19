"""On-demand translation of transcripts to English."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any

from addisai import (
    AddisAI,
    AddisAIError,
    APIConnectionError,
    APIError,
    AuthenticationError,
    InsufficientCreditsError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

logger = logging.getLogger(__name__)

# Only these source languages can be translated to English by Addis AI.
TRANSLATABLE_LANGUAGES: frozenset[str] = frozenset({"am", "om", "ti"})


def is_translatable(language: str) -> bool:
    """Return True when Addis AI can translate this language to English."""
    return language in TRANSLATABLE_LANGUAGES


class TranslationError(Exception):
    """A failure with a message that is safe to show to the Telegram user."""

    def __init__(self, user_message: str, notify_owner: bool = False) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.notify_owner = notify_owner


def _log_api_error(exc: APIError) -> None:
    logger.warning(
        "Addis AI translate failed: class=%s status=%s code=%s",
        type(exc).__name__,
        exc.status,
        exc.code,
    )


def _translate_sync(text: str, source: str, api_key: str) -> dict[str, Any]:
    """Blocking call. Always run this through asyncio.to_thread()."""
    with AddisAI(api_key=api_key, timeout=180.0) as addis:
        return addis.translate.create(
            text=text,
            source=source,  # type: ignore[arg-type]
            target="en",
            request_options={"timeout": 180.0},
        )


async def translate_text(text: str, source: str, api_key: str) -> str:
    """Translate text to English without blocking the event loop."""
    try:
        result = await asyncio.to_thread(_translate_sync, text, source, api_key)
    except InsufficientCreditsError as exc:
        _log_api_error(exc)
        balance = exc.available_balance
        if balance is None:
            message = (
                "Addis AI credits are used up. "
                "Please ask the bot owner to top up the account."
            )
        else:
            message = (
                f"Addis AI credits are used up (remaining: {balance:g} ETB). "
                "Please ask the bot owner to top up the account."
            )
        raise TranslationError(message, notify_owner=True) from None
    except RateLimitError as exc:
        _log_api_error(exc)
        if exc.retry_after is not None:
            message = (
                "Addis AI is busy right now. "
                f"Please try again in about {exc.retry_after} seconds."
            )
        else:
            message = "Addis AI is busy right now. Please try again in a minute."
        raise TranslationError(message) from None
    except (AuthenticationError, PermissionDeniedError) as exc:
        _log_api_error(exc)
        raise TranslationError(
            "Addis AI rejected the bot's API key. "
            "The owner needs to check ADDIS_API_KEY.",
            notify_owner=True,
        ) from None
    except UnprocessableEntityError as exc:
        _log_api_error(exc)
        raise TranslationError(
            "Addis AI could not translate this text. Please try again."
        ) from None
    except APIConnectionError:
        raise TranslationError(
            "Could not reach Addis AI. Please try again."
        ) from None
    except APIError as exc:
        _log_api_error(exc)
        raise TranslationError(
            "Addis AI could not translate this text. Please try again."
        ) from None
    except AddisAIError:
        logger.warning("Addis AI returned an unexpected translation response")
        raise TranslationError(
            "Addis AI could not translate this text. Please try again."
        ) from None

    translated = result.get("text")
    if not isinstance(translated, str) or not translated.strip():
        raise TranslationError("Addis AI returned no translation. Please try again.")
    return translated.strip()


class TranslationCache:
    """Short-lived, in-memory store for transcripts awaiting translation.

    Keys are short random strings (never the text). Nothing is persisted.
    """

    def __init__(self, ttl_seconds: int = 900) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[str, str, float]] = {}

    def put(self, text: str, source: str, user_id: int) -> str:
        key = secrets.token_hex(8)
        self._entries[key] = (text, source, time.monotonic() + self._ttl)
        return key

    def get(self, key: str) -> tuple[str, str] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        text, source, expires = entry
        if time.monotonic() > expires:
            del self._entries[key]
            return None
        return text, source

    def remove(self, key: str) -> None:
        self._entries.pop(key, None)