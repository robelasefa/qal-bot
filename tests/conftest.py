"""Shared pytest fixtures."""

import pytest


class FakeClock:
    """A clock the tests can move forward without sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def env(monkeypatch):
    """A clean environment with both bot tokens and the Addis AI key.

    Tests run in development mode, so they do not need webhook settings.
    """
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_DEV_BOT_TOKEN",
        "ADDIS_API_KEY",
        "MAX_AUDIO_SECONDS",
        "RATE_LIMIT_PER_HOUR",
        "ALLOWED_USER_IDS",
        "OWNER_USER_ID",
        "DAILY_TRANSCRIPTION_LIMIT",
        "TRANSCRIBE_CONCURRENCY",
        "DEBUG",
        "WEBHOOK_URL",
        "WEBHOOK_SECRET",
        "WEBHOOK_LISTEN",
        "WEBHOOK_PORT",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-prod-token")
    monkeypatch.setenv("TELEGRAM_DEV_BOT_TOKEN", "test-dev-token")
    monkeypatch.setenv("ADDIS_API_KEY", "test-key")
    monkeypatch.setenv("DEBUG", "true")
    return monkeypatch
