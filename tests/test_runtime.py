"""Tests for choosing the local polling or production webhook mode."""

from types import SimpleNamespace

import pytest

from src.app import ALLOWED_UPDATES, run_bot


class FakeApplication:
    """Record how the real bot would have been started."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run_polling(self, **kwargs) -> None:
        self.calls.append(("polling", kwargs))

    def run_webhook(self, **kwargs) -> None:
        self.calls.append(("webhook", kwargs))


def settings(**overrides) -> SimpleNamespace:
    values = {
        "debug": True,
        "webhook_url": None,
        "webhook_secret": None,
        "webhook_listen": "127.0.0.1",
        "webhook_port": 8080,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_debug_mode_uses_long_polling() -> None:
    application = FakeApplication()

    run_bot(application, settings(debug=True))

    method, kwargs = application.calls[0]
    assert method == "polling"
    assert kwargs["allowed_updates"] == ALLOWED_UPDATES


def test_production_mode_uses_the_webhook_path_from_the_url() -> None:
    application = FakeApplication()

    run_bot(
        application,
        settings(
            debug=False,
            webhook_url="https://qal.example.com/telegram",
            webhook_secret="secret-token",
        ),
    )

    method, kwargs = application.calls[0]
    assert method == "webhook"
    assert kwargs["listen"] == "127.0.0.1"
    assert kwargs["port"] == 8080
    assert kwargs["url_path"] == "/telegram"
    assert kwargs["webhook_url"] == "https://qal.example.com/telegram"
    assert kwargs["secret_token"] == "secret-token"
    assert kwargs["allowed_updates"] == ALLOWED_UPDATES


def test_webhook_url_without_a_path_uses_the_root() -> None:
    application = FakeApplication()

    run_bot(
        application,
        settings(
            debug=False,
            webhook_url="https://qal.example.com",
            webhook_secret="secret-token",
        ),
    )

    assert application.calls[0][1]["url_path"] == "/"


def test_webhook_mode_without_a_url_fails_clearly() -> None:
    with pytest.raises(RuntimeError, match="WEBHOOK_URL"):
        run_bot(
            FakeApplication(),
            settings(debug=False, webhook_url=None),
        )
