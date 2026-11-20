"""Read and validate configuration from .env."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# Load .env once, when this module is imported.
# Existing environment variables (e.g. on a server) win over the file.
load_dotenv(ENV_FILE, override=True)


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


def _user_ids(name: str) -> frozenset[int]:
    """Read a comma-separated list of Telegram user IDs."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return frozenset()

    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise ConfigError(
                f"{name} must be a comma-separated list of numeric user IDs."
            ) from exc
        if value <= 0:
            raise ConfigError(
                f"{name} must contain only positive user IDs, got {value}."
            )
        ids.add(value)

    if not ids:
        raise ConfigError(
            f"{name} must contain at least one user ID, or be left empty."
        )
    return frozenset(ids)


def _optional_user_id(name: str) -> int | None:
    """Read one optional Telegram user ID."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None

    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"{name} must be a numeric user ID, got {raw!r}."
        ) from exc

    if value <= 0:
        raise ConfigError(
            f"{name} must be a positive user ID, got {value}."
        )
    return value


def _positive_int(name: str, default: int) -> int:
    """Read a positive whole number from the environment."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default

    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"{name} must be a whole number, got {raw!r}."
        ) from exc

    if value <= 0:
        raise ConfigError(
            f"{name} must be greater than zero, got {value}."
        )

    return value


def _bool(name: str, default: bool) -> bool:
    """Read a true/false flag without being fussy about its spelling."""
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(
        f"{name} must be true or false, got {raw!r}."
    )


def _text(name: str, default: str) -> str:
    """Read a non-empty string, falling back to a default."""
    return os.getenv(name, "").strip() or default


def _default_port() -> int:
    """Azure App Service sets PORT; fall back to 8080 for local work."""
    try:
        return int(os.getenv("PORT", "8080"))
    except ValueError:
        return 8080


def _default_listen() -> str:
    """Bind to all interfaces on Azure, to localhost otherwise."""
    return "0.0.0.0" if os.getenv("WEBSITE_INSTANCE_ID") else "127.0.0.1"


def _https_url(name: str) -> str | None:
    """Read an optional public URL. Telegram only accepts HTTPS webhooks."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None

    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(
            f"{name} must be a full https:// URL, got {raw!r}."
        )
    return raw


def _webhook_secret(name: str) -> str | None:
    """Read the optional Telegram secret token.

    Telegram only allows letters, digits, underscores, and hyphens.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return None

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", raw):
        raise ConfigError(
            f"{name} may only contain letters, digits, underscores, and "
            "hyphens (1-256 characters)."
        )
    return raw


@dataclass(frozen=True)
class Settings:
    """Values the bot needs, loaded once at startup."""

    # Resolved from TELEGRAM_DEV_BOT_TOKEN (DEBUG=true) or
    # TELEGRAM_BOT_TOKEN (DEBUG=false). The unused token is never stored.
    telegram_token: str = field(repr=False)
    addis_api_key: str = field(repr=False)
    max_audio_seconds: int
    rate_limit_per_hour: int
    allowed_user_ids: frozenset[int]
    owner_user_id: int | None
    daily_transcription_limit: int
    transcribe_concurrency: int
    debug: bool
    webhook_url: str | None
    webhook_secret: str | None = field(repr=False)
    webhook_listen: str
    webhook_port: int
    data_dir: Path

    @property
    def mode(self) -> str:
        """Human-readable mode for startup logs."""
        return "development" if self.debug else "production"

    def redact(self, text: str) -> str:
        """Replace known secrets in ``text`` with ``***``.

        Empty or very short values are skipped so a blank token can never
        wipe out unrelated text.
        """
        for secret in (self.telegram_token, self.webhook_secret, self.addis_api_key):
            if secret and len(secret) >= 8:
                text = text.replace(secret, "***")
        return text


def load_settings() -> Settings:
    """Load settings from .env, raising ConfigError if something is wrong."""
    debug = _bool("DEBUG", False)
    token_name = (
        "TELEGRAM_DEV_BOT_TOKEN" if debug else "TELEGRAM_BOT_TOKEN"
    )
    telegram_token = os.getenv(token_name, "").strip()
    addis_api_key = os.getenv("ADDIS_API_KEY", "").strip()

    missing = []
    if not telegram_token:
        missing.append(token_name)
    if not addis_api_key:
        missing.append("ADDIS_API_KEY")

    if missing:
        mode = "development" if debug else "production"
        names = ", ".join(missing)
        raise ConfigError(
            f"Missing required {mode} setting(s): {names}. "
            "Copy .env.example to .env and fill them in."
        )

    webhook_url = _https_url("WEBHOOK_URL")
    webhook_secret = _webhook_secret("WEBHOOK_SECRET")

    if not debug:
        missing_webhook = []
        if webhook_url is None:
            missing_webhook.append("WEBHOOK_URL")
        if webhook_secret is None:
            missing_webhook.append("WEBHOOK_SECRET")
        if missing_webhook:
            names = ", ".join(missing_webhook)
            raise ConfigError(
                f"Webhook mode requires {names}. "
                "Set them in .env, or set DEBUG=true for local polling."
            )

    return Settings(
        telegram_token=telegram_token,
        addis_api_key=addis_api_key,
        max_audio_seconds=_positive_int("MAX_AUDIO_SECONDS", 600),
        rate_limit_per_hour=_positive_int("RATE_LIMIT_PER_HOUR", 5),
        allowed_user_ids=_user_ids("ALLOWED_USER_IDS"),
        owner_user_id=_optional_user_id("OWNER_USER_ID"),
        daily_transcription_limit=_positive_int(
            "DAILY_TRANSCRIPTION_LIMIT", 100
        ),
        transcribe_concurrency=_positive_int("TRANSCRIBE_CONCURRENCY", 2),
        debug=debug,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        webhook_listen=_text("WEBHOOK_LISTEN", _default_listen()),
        webhook_port=_positive_int("WEBHOOK_PORT", _default_port()),
        data_dir=Path(
            os.getenv("DATA_DIR")
            or (
                "/home/data"
                if os.getenv("WEBSITE_INSTANCE_ID")
                else str(PROJECT_ROOT / "data")
            )
        ),
    )
