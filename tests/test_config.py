"""Tests for .env parsing and validation."""

import pytest

from src.config import ConfigError, load_settings


def test_optional_settings_have_safe_defaults(env) -> None:
    settings = load_settings()

    assert settings.allowed_user_ids == frozenset()
    assert settings.owner_user_id is None
    assert settings.daily_transcription_limit == 100
    assert settings.transcribe_concurrency == 2
    assert settings.debug is True
    assert settings.mode == "development"
    assert settings.telegram_token == "test-dev-token"
    assert settings.webhook_url is None
    assert settings.webhook_secret is None
    assert settings.webhook_listen == "127.0.0.1"
    assert settings.webhook_port == 8080


def test_allowlist_accepts_spaces_and_duplicates(env) -> None:
    env.setenv("ALLOWED_USER_IDS", " 11, 22 ,11,33 ")

    assert load_settings().allowed_user_ids == frozenset({11, 22, 33})


def test_allowlist_rejects_non_numeric_ids(env) -> None:
    env.setenv("ALLOWED_USER_IDS", "11,not-a-user")

    with pytest.raises(ConfigError, match="numeric user IDs"):
        load_settings()


def test_allowlist_rejects_non_positive_ids(env) -> None:
    env.setenv("ALLOWED_USER_IDS", "11,0")

    with pytest.raises(ConfigError, match="positive user IDs"):
        load_settings()


def test_allowlist_with_no_ids_is_rejected(env) -> None:
    env.setenv("ALLOWED_USER_IDS", " , , ")

    with pytest.raises(ConfigError, match="at least one user ID"):
        load_settings()


def test_owner_id_is_optional(env) -> None:
    assert load_settings().owner_user_id is None

    env.setenv("OWNER_USER_ID", "42")
    assert load_settings().owner_user_id == 42


def test_owner_id_must_be_numeric(env) -> None:
    env.setenv("OWNER_USER_ID", "owner")

    with pytest.raises(ConfigError, match="numeric user ID"):
        load_settings()


def test_invalid_positive_int_is_rejected(env) -> None:
    env.setenv("DAILY_TRANSCRIPTION_LIMIT", "many")

    with pytest.raises(ConfigError, match="whole number"):
        load_settings()


def test_missing_required_settings_are_named(env) -> None:
    env.delenv("TELEGRAM_DEV_BOT_TOKEN")
    env.delenv("ADDIS_API_KEY")

    with pytest.raises(ConfigError) as caught:
        load_settings()

    assert "TELEGRAM_DEV_BOT_TOKEN" in str(caught.value)
    assert "ADDIS_API_KEY" in str(caught.value)
    assert "development" in str(caught.value)


def test_development_mode_uses_the_dev_token(env) -> None:
    env.delenv("TELEGRAM_BOT_TOKEN")

    settings = load_settings()

    assert settings.telegram_token == "test-dev-token"
    assert settings.mode == "development"


def test_production_mode_uses_the_production_token(env) -> None:
    env.setenv("DEBUG", "false")
    env.setenv("WEBHOOK_URL", "https://example.com/telegram")
    env.setenv("WEBHOOK_SECRET", "secret")
    env.delenv("TELEGRAM_DEV_BOT_TOKEN")

    settings = load_settings()

    assert settings.telegram_token == "test-prod-token"
    assert settings.mode == "production"


def test_missing_dev_token_is_named(env) -> None:
    env.delenv("TELEGRAM_DEV_BOT_TOKEN")

    with pytest.raises(ConfigError, match="TELEGRAM_DEV_BOT_TOKEN"):
        load_settings()


def test_missing_production_token_is_named(env) -> None:
    env.setenv("DEBUG", "false")
    env.setenv("WEBHOOK_URL", "https://example.com/telegram")
    env.setenv("WEBHOOK_SECRET", "secret")
    env.delenv("TELEGRAM_BOT_TOKEN")

    with pytest.raises(ConfigError) as caught:
        load_settings()

    assert "TELEGRAM_BOT_TOKEN" in str(caught.value)
    assert "production" in str(caught.value)


def test_secrets_are_hidden_from_repr(env) -> None:
    text = repr(load_settings())

    assert "test-dev-token" not in text
    assert "test-prod-token" not in text
    assert "test-key" not in text


def test_debug_accepts_common_true_and_false_spellings(env) -> None:
    for raw in ("1", "true", "yes", "on"):
        env.setenv("DEBUG", raw)
        assert load_settings().debug is True

    env.setenv("WEBHOOK_URL", "https://example.com/telegram")
    env.setenv("WEBHOOK_SECRET", "secret")
    for raw in ("0", "false", "no", "off"):
        env.setenv("DEBUG", raw)
        assert load_settings().debug is False


def test_invalid_debug_value_is_rejected(env) -> None:
    env.setenv("DEBUG", "maybe")

    with pytest.raises(ConfigError, match="true or false"):
        load_settings()


def test_webhook_mode_requires_url_and_secret(env) -> None:
    env.delenv("DEBUG")

    with pytest.raises(ConfigError) as caught:
        load_settings()

    assert "WEBHOOK_URL" in str(caught.value)
    assert "WEBHOOK_SECRET" in str(caught.value)


def test_webhook_mode_loads_its_settings(env) -> None:
    env.setenv("DEBUG", "false")
    env.setenv("WEBHOOK_URL", "https://qal.example.com/telegram")
    env.setenv("WEBHOOK_SECRET", "secret-token_123")

    settings = load_settings()

    assert settings.debug is False
    assert settings.mode == "production"
    assert settings.telegram_token == "test-prod-token"
    assert settings.webhook_url == "https://qal.example.com/telegram"
    assert settings.webhook_secret == "secret-token_123"


def test_webhook_url_must_be_https(env) -> None:
    env.setenv("DEBUG", "false")
    env.setenv("WEBHOOK_URL", "http://example.com/telegram")
    env.setenv("WEBHOOK_SECRET", "secret")

    with pytest.raises(ConfigError, match="https://"):
        load_settings()


def test_webhook_secret_rejects_invalid_characters(env) -> None:
    env.setenv("DEBUG", "false")
    env.setenv("WEBHOOK_URL", "https://example.com/telegram")
    env.setenv("WEBHOOK_SECRET", "not valid!")

    with pytest.raises(ConfigError, match="letters, digits"):
        load_settings()


def test_webhook_secret_is_hidden_from_repr(env) -> None:
    env.setenv("DEBUG", "false")
    env.setenv("WEBHOOK_URL", "https://example.com/telegram")
    env.setenv("WEBHOOK_SECRET", "super-secret")

    assert "super-secret" not in repr(load_settings())
