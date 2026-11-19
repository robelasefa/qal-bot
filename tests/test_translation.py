"""Tests for on-demand translation to English (no network)."""

import asyncio
import time
from unittest.mock import patch

import pytest
from addisai import (
    APIConnectionError,
    APIError,
    InsufficientCreditsError,
    RateLimitError,
)

from src import translation


def test_translatable_languages_are_am_om_ti_only() -> None:
    assert translation.TRANSLATABLE_LANGUAGES == {"am", "om", "ti"}
    for code in ("am", "om", "ti"):
        assert translation.is_translatable(code) is True
    for code in ("sw", "ha", "sid", "wal", "en", "xx"):
        assert translation.is_translatable(code) is False


def test_cache_round_trip() -> None:
    cache = translation.TranslationCache(ttl_seconds=60)

    key = cache.put("hello", "am", 1)
    assert len(key) == 16
    assert cache.get(key) == ("hello", "am")


def test_cache_expires() -> None:
    cache = translation.TranslationCache(ttl_seconds=1)
    key = cache.put("hello", "am", 1)

    with patch("src.translation.time.monotonic", return_value=time.monotonic() + 2):
        assert cache.get(key) is None

    # A second read stays expired.
    assert cache.get(key) is None


def test_cache_remove() -> None:
    cache = translation.TranslationCache()
    key = cache.put("hello", "am", 1)
    cache.remove(key)
    assert cache.get(key) is None


def test_cache_missing_key_returns_none() -> None:
    cache = translation.TranslationCache()
    assert cache.get("nope") is None


def run_translate(monkeypatch, error=None, result=None):
    def fake(text, source, api_key):
        if error is not None:
            raise error
        return result if result is not None else {"text": "Hello"}

    monkeypatch.setattr(translation, "_translate_sync", fake)
    return asyncio.run(translation.translate_text("hi", "am", "test-key"))


def test_translate_returns_text(monkeypatch) -> None:
    text = run_translate(monkeypatch)
    assert text == "Hello"


def test_translate_insufficient_credits_alerts_owner(monkeypatch) -> None:
    with pytest.raises(translation.TranslationError) as caught:
        run_translate(monkeypatch, InsufficientCreditsError(402, "no credits"))
    assert "credits" in caught.value.user_message.lower()
    assert caught.value.notify_owner is True


def test_translate_rate_limit_message(monkeypatch) -> None:
    with pytest.raises(translation.TranslationError) as caught:
        run_translate(
            monkeypatch,
            RateLimitError(429, "slow", headers={"retry-after": "30"}),
        )
    assert "30 seconds" in caught.value.user_message


def test_translate_api_error_message(monkeypatch) -> None:
    with pytest.raises(translation.TranslationError) as caught:
        run_translate(monkeypatch, APIError(500, "boom"))
    assert "could not translate" in caught.value.user_message.lower()


def test_translate_connection_error_message(monkeypatch) -> None:
    with pytest.raises(translation.TranslationError) as caught:
        run_translate(monkeypatch, APIConnectionError())
    assert "reach Addis AI" in caught.value.user_message


def test_translate_empty_result_raises(monkeypatch) -> None:
    with pytest.raises(translation.TranslationError) as caught:
        run_translate(monkeypatch, result={"text": ""})
    assert "no translation" in caught.value.user_message.lower()