"""Addis AI transcription, kept off the asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path

from addisai import (
    AddisAI,
    AddisAIError,
    APIConnectionError,
    APIConnectionTimeoutError,
    APIError,
    AuthenticationError,
    ConflictError,
    InsufficientCreditsError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
    ulid,
)

logger = logging.getLogger(__name__)

# A 10-minute voice note is normally transcribed well within this time.
# Passing it as a request option stops the SDK from raising it to 600 s.
REQUEST_TIMEOUT_SECONDS = 180.0

# Recovery is a small read-only call; it should not hang the bot.
RECOVERY_TIMEOUT_SECONDS = 30.0


class TranscriptionError(Exception):
    """A failure with a message that is safe to show to the Telegram user."""

    def __init__(self, user_message: str, notify_owner: bool = False) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.notify_owner = notify_owner


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _log_api_error(exc: APIError) -> None:
    """Log only non-sensitive error metadata."""
    logger.warning(
        "Addis AI request failed: class=%s status=%s code=%s",
        type(exc).__name__,
        exc.status,
        exc.code,
    )


def _transcribe_sync(
    path: Path,
    language: str,
    api_key: str,
    request_id: str,
) -> str:
    """Blocking call. Always run this through asyncio.to_thread()."""
    with (
        AddisAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS) as addis,
        path.open("rb") as audio,
    ):
        result = addis.scribe.transcribe(
            # Name and MIME type match the real file (Telegram voice = OGG/Opus).
            audio=(path.name, audio, _content_type(path)),
            language=language,
            backend="turbo",
            # Keep this ID: it is the receipt for recovery if the response is lost.
            request_id=request_id,
            request_options={"timeout": REQUEST_TIMEOUT_SECONDS},
        )

    text = result.get("text")
    if not isinstance(text, str):
        raise TranscriptionError(
            "Addis AI returned an unexpected response. Please try again."
        )
    return text.strip()


def _recover_sync(request_id: str, api_key: str) -> dict[str, object]:
    """Blocking recovery call. Always run this through asyncio.to_thread()."""
    with AddisAI(api_key=api_key, timeout=RECOVERY_TIMEOUT_SECONDS) as addis:
        return addis.scribe.recover(request_id)


async def _recover_or_raise(request_id: str, api_key: str) -> str:
    """Ask Addis AI what happened to a request whose response was lost.

    This never sends the audio again. If the request finished, we return its
    transcript. Otherwise we raise a clear message about what we know.
    """
    try:
        result = await asyncio.to_thread(_recover_sync, request_id, api_key)

    except NotFoundError:
        logger.warning("Addis AI never received the request")
        raise TranscriptionError(
            "Addis AI never received that audio. It is safe to send it again."
        ) from None

    except ConflictError as exc:
        code = (exc.code or "").upper()
        if code in {"IN_PROGRESS", "BILLING_PENDING"}:
            raise TranscriptionError(
                "Addis AI is still working on that audio. "
                "Please wait a minute before sending it again."
            ) from None
        if code == "REQUEST_INTERRUPTED":
            raise TranscriptionError(
                "Addis AI interrupted that request before finishing. "
                "Please send the audio again."
            ) from None
        if code == "REQUEST_CANCELLED":
            raise TranscriptionError(
                "Addis AI cancelled that request before finishing. "
                "Please send the audio again."
            ) from None

        _log_api_error(exc)
        raise TranscriptionError(
            "Addis AI could not confirm that request. "
            "Please wait a minute before sending it again."
        ) from None

    except APIConnectionError:
        raise TranscriptionError(
            "The connection dropped and Addis AI could not confirm the request. "
            "Please wait a minute before sending it again."
        ) from None

    except APIError as exc:
        _log_api_error(exc)
        raise TranscriptionError(
            "Addis AI could not confirm whether the request finished. "
            "Please wait a minute before sending it again."
        ) from None

    except AddisAIError:
        logger.warning("Addis AI returned an unexpected recovery response")
        raise TranscriptionError(
            "Addis AI could not confirm whether the request finished. "
            "Please wait a minute before sending it again."
        ) from None

    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    raise TranscriptionError(
        "Addis AI finished the request but returned no text. Please try again."
    )


def _usage_sync(api_key: str) -> dict[str, object]:
    """Blocking call to the owner-only usage endpoint."""
    with AddisAI(api_key=api_key, timeout=30.0) as addis:
        return addis.scribe.usage()


async def fetch_usage(api_key: str) -> dict[str, object]:
    """Return the Addis AI account usage without blocking the event loop.

    Raises TranscriptionError with a short, owner-facing message on failure.
    """
    try:
        return await asyncio.to_thread(_usage_sync, api_key)

    except APIConnectionTimeoutError:
        logger.warning("Addis AI usage request timed out")
        raise TranscriptionError(
            "Addis AI took too long to answer. Try /stats again."
        ) from None

    except APIConnectionError:
        logger.warning("Could not connect to Addis AI for usage")
        raise TranscriptionError(
            "Could not reach Addis AI. Try /stats again."
        ) from None

    except AuthenticationError as exc:
        _log_api_error(exc)
        raise TranscriptionError(
            "Addis AI rejected the bot's API key. Check ADDIS_API_KEY."
        ) from None

    except APIError as exc:
        _log_api_error(exc)
        raise TranscriptionError(
            f"Could not read Addis AI usage (status {exc.status})."
        ) from None

    except AddisAIError:
        logger.warning("Addis AI returned an unexpected usage response")
        raise TranscriptionError(
            "Addis AI returned an unexpected usage response."
        ) from None


async def transcribe_audio(path: Path, language: str, api_key: str) -> str:
    """Transcribe an audio file without blocking the bot's event loop.

    Raises TranscriptionError with a user-friendly message on failure.
    """
    # One ID for the whole paid attempt, so recovery can find the right request.
    request_id = ulid()

    try:
        return await asyncio.to_thread(
            _transcribe_sync,
            path,
            language,
            api_key,
            request_id,
        )

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
        raise TranscriptionError(message, notify_owner=True) from None

    except RateLimitError as exc:
        _log_api_error(exc)
        if exc.retry_after is not None:
            message = (
                "Addis AI is busy right now. "
                f"Please try again in about {exc.retry_after} seconds."
            )
        else:
            message = "Addis AI is busy right now. Please try again in a minute."
        raise TranscriptionError(message) from None

    except (AuthenticationError, PermissionDeniedError) as exc:
        _log_api_error(exc)
        raise TranscriptionError(
            "Addis AI rejected the bot's API key. "
            "The owner needs to check ADDIS_API_KEY.",
            notify_owner=True,
        ) from None

    except UnprocessableEntityError as exc:
        _log_api_error(exc)
        raise TranscriptionError(
            "Addis AI could not read this audio. "
            "Try a shorter recording or a different file."
        ) from None

    except APIConnectionError:
        logger.warning("Addis AI connection failed; checking the request")
        return await _recover_or_raise(request_id, api_key)

    except APIError as exc:
        _log_api_error(exc)
        raise TranscriptionError(
            f"The transcription service failed (status {exc.status}). "
            "Please try again."
        ) from None

    except AddisAIError:
        logger.warning("Addis AI returned an unexpected response")
        raise TranscriptionError(
            "Addis AI returned an unexpected response. Please try again."
        ) from None

    except OSError:
        logger.warning("Could not read the temporary audio file")
        raise TranscriptionError(
            "Could not read the downloaded audio. Please send it again."
        ) from None
