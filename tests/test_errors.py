"""Tests for the global error handler and its small, pure helpers."""

import asyncio
from types import SimpleNamespace

from telegram import Update
from telegram.error import TelegramError

from src.error import (
    alert_owner,
    error_handler,
    format_error_notice,
    is_critical_error,
    update_kind,
)


class FakeBot:
    """Record owner alerts instead of calling Telegram."""

    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


def make_context(error, bot, bot_data):
    return SimpleNamespace(
        error=error,
        bot=bot,
        application=SimpleNamespace(bot_data=bot_data),
    )


def owner_data(owner_id: int | None = 42) -> dict[str, object]:
    settings = SimpleNamespace(owner_user_id=owner_id)
    return {"services": SimpleNamespace(settings=settings)}


def run_handler(error, bot, bot_data) -> None:
    asyncio.run(error_handler(object(), make_context(error, bot, bot_data)))


def test_telegram_errors_are_not_treated_as_critical() -> None:
    assert is_critical_error(TelegramError("chat unavailable")) is False


def test_code_errors_are_treated_as_critical() -> None:
    assert is_critical_error(ValueError("bad state")) is True


def test_update_kind_handles_non_updates() -> None:
    assert update_kind(object()) == "unknown update"


def test_update_kind_handles_an_empty_update() -> None:
    assert update_kind(Update(update_id=1)) == "other update"


def test_error_notice_names_the_error_and_update_kind() -> None:
    notice = format_error_notice(ValueError("bad state"), object())

    assert "ValueError" in notice
    assert "bad state" in notice
    assert "unknown update" in notice
    assert "traceback" in notice


def test_error_notice_is_short_enough_for_telegram() -> None:
    notice = format_error_notice(ValueError("x" * 1_000), object())

    assert len(notice) < 4096


def test_format_error_notice_redacts_secret_url(env) -> None:
    token = "123456:ABC-DEF_secret"
    env.setenv("TELEGRAM_DEV_BOT_TOKEN", token)
    env.setenv("ADDIS_API_KEY", "addis-key-12345678")

    from src.config import load_settings

    settings = load_settings()
    url = f"https://api.telegram.org/bot{token}/getMe"
    notice = format_error_notice(
        ValueError(f"failed {url}"), object(), redact=settings.redact
    )

    assert token not in notice
    assert "***" in notice


def test_redact_skips_empty_and_short_secrets() -> None:
    from src.config import Settings

    settings = Settings(
        telegram_token="",
        addis_api_key="ab",
        max_audio_seconds=600,
        rate_limit_per_hour=5,
        allowed_user_ids=frozenset(),
        owner_user_id=None,
        daily_transcription_limit=100,
        transcribe_concurrency=2,
        debug=True,
        webhook_url=None,
        webhook_secret="short",
        webhook_listen="127.0.0.1",
        webhook_port=8080,
        data_dir=__import__("pathlib").Path("/tmp"),
    )

    text = "nothing secret here"
    assert settings.redact(text) == text


def test_error_handler_alerts_the_owner_about_code_errors() -> None:
    bot = FakeBot()
    data = owner_data()

    run_handler(ValueError("bad state"), bot, data)

    assert len(bot.messages) == 1
    assert bot.messages[0]["chat_id"] == 42
    assert "ValueError" in str(bot.messages[0]["text"])
    assert "last_error_notice" in data


def test_error_handler_does_not_alert_about_telegram_errors() -> None:
    bot = FakeBot()

    run_handler(TelegramError("chat unavailable"), bot, owner_data())

    assert bot.messages == []


def test_error_handler_does_not_alert_without_an_owner() -> None:
    bot = FakeBot()

    run_handler(ValueError("bad state"), bot, owner_data(owner_id=None))

    assert bot.messages == []


def test_error_handler_ignores_duplicate_alerts_within_the_cooldown() -> None:
    bot = FakeBot()
    data = owner_data()

    run_handler(ValueError("first"), bot, data)
    run_handler(ValueError("second"), bot, data)

    assert len(bot.messages) == 1
    assert "first" in str(bot.messages[0]["text"])


def test_error_handler_ignores_a_missing_error() -> None:
    bot = FakeBot()

    run_handler(None, bot, owner_data())

    assert bot.messages == []


def test_alert_owner_sends_a_message() -> None:
    bot = FakeBot()
    data = owner_data()

    asyncio.run(alert_owner(make_context(None, bot, data), "credits used up"))

    assert len(bot.messages) == 1
    assert bot.messages[0]["chat_id"] == 42
    assert "credits" in str(bot.messages[0]["text"])
