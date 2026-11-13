"""Tests for transcription error mapping and paid-request recovery (no network)."""

import asyncio
from pathlib import Path

import pytest
from addisai import (
    APIConnectionError,
    ConflictError,
    InsufficientCreditsError,
    NotFoundError,
    RateLimitError,
)

from src import transcriber


def run_transcribe(monkeypatch, error, recover=None):
    def fail(*args, **kwargs):
        raise error

    if recover is None:
        def recover(*args, **kwargs):
            raise APIConnectionError()

    monkeypatch.setattr(transcriber, "_transcribe_sync", fail)
    monkeypatch.setattr(transcriber, "_recover_sync", recover)

    return asyncio.run(
        transcriber.transcribe_audio(
            Path("unused.ogg"),
            "am",
            "test-key",
        )
    )


def user_message_for(monkeypatch, error, recover=None) -> str:
    with pytest.raises(transcriber.TranscriptionError) as caught:
        run_transcribe(monkeypatch, error, recover)

    return caught.value.user_message


def test_insufficient_credits_has_a_clear_message(monkeypatch) -> None:
    message = user_message_for(
        monkeypatch,
        InsufficientCreditsError(402, "no credits"),
    )

    assert "credits" in message.lower()
    assert "top up" in message.lower()


def test_insufficient_credits_alerts_the_owner(monkeypatch) -> None:
    with pytest.raises(transcriber.TranscriptionError) as caught:
        run_transcribe(monkeypatch, InsufficientCreditsError(402, "no credits"))

    assert caught.value.notify_owner is True


def test_rate_limit_does_not_alert_the_owner(monkeypatch) -> None:
    with pytest.raises(transcriber.TranscriptionError) as caught:
        run_transcribe(
            monkeypatch,
            RateLimitError(429, "slow down", headers={"retry-after": "30"}),
        )

    assert caught.value.notify_owner is False


def test_insufficient_credits_includes_the_balance(monkeypatch) -> None:
    message = user_message_for(
        monkeypatch,
        InsufficientCreditsError(
            402,
            "balance too low",
            details=[{"code": "balance_too_low", "message": "Remaining: 1.5"}],
        ),
    )

    assert "1.5" in message


def test_rate_limit_includes_retry_after(monkeypatch) -> None:
    message = user_message_for(
        monkeypatch,
        RateLimitError(429, "slow down", headers={"retry-after": "30"}),
    )

    assert "30 seconds" in message


def test_connection_error_without_recovery_asks_to_wait(monkeypatch) -> None:
    message = user_message_for(monkeypatch, APIConnectionError())

    assert "could not confirm" in message.lower()
    assert "wait a minute" in message.lower()


def test_recovery_returns_a_completed_transcript(monkeypatch) -> None:
    def recover(*args, **kwargs):
        return {"text": "  recovered text  ", "usage": {"settled": True}}

    text = run_transcribe(monkeypatch, APIConnectionError(), recover)

    assert text == "recovered text"


def test_recovery_uses_the_same_request_id(monkeypatch) -> None:
    seen = {}

    def fail(path, language, api_key, request_id):
        seen["sent"] = request_id
        raise APIConnectionError()

    def recover(request_id, api_key):
        seen["recovered"] = request_id
        return {"text": "ok"}

    monkeypatch.setattr(transcriber, "_transcribe_sync", fail)
    monkeypatch.setattr(transcriber, "_recover_sync", recover)

    asyncio.run(
        transcriber.transcribe_audio(Path("unused.ogg"), "am", "test-key")
    )

    assert seen["sent"] == seen["recovered"]


def test_recovery_not_found_says_it_is_safe_to_retry(monkeypatch) -> None:
    def recover(*args, **kwargs):
        raise NotFoundError(404, "missing", code="NOT_FOUND")

    message = user_message_for(monkeypatch, APIConnectionError(), recover)

    assert "never received" in message.lower()
    assert "safe to send it again" in message.lower()


def test_recovery_in_progress_asks_the_user_to_wait(monkeypatch) -> None:
    def recover(*args, **kwargs):
        raise ConflictError(409, "working", code="IN_PROGRESS")

    message = user_message_for(monkeypatch, APIConnectionError(), recover)

    assert "still working" in message.lower()
    assert "wait a minute" in message.lower()


def test_recovery_interrupted_says_to_send_again(monkeypatch) -> None:
    def recover(*args, **kwargs):
        raise ConflictError(409, "interrupted", code="REQUEST_INTERRUPTED")

    message = user_message_for(monkeypatch, APIConnectionError(), recover)

    assert "interrupted" in message.lower()
    assert "send the audio again" in message.lower()


def test_recovery_without_text_has_a_clear_message(monkeypatch) -> None:
    def recover(*args, **kwargs):
        return {"text": "   "}

    message = user_message_for(monkeypatch, APIConnectionError(), recover)

    assert "returned no text" in message.lower()
