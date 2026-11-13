"""Supported languages and per-user language preferences."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Final

DEFAULT_LANGUAGE: Final = "am"

# Short code -> name shown to the user.
LANGUAGES: Final[dict[str, str]] = {
    "am": "Amharic",
    "om": "Afaan Oromo",
    "ti": "Tigrinya",
    "sw": "Swahili",
    "ha": "Hausa",
    "sid": "Sidama",
    "wal": "Wolaytta",
}


def normalize_language(code: str | None) -> str:
    """Return a supported language code, or the default if unknown."""
    if code is None:
        return DEFAULT_LANGUAGE

    cleaned = code.strip().lower()
    if cleaned in LANGUAGES:
        return cleaned
    return DEFAULT_LANGUAGE


def language_label(code: str) -> str:
    """Return the human-readable name for a language code."""
    return LANGUAGES[normalize_language(code)]


class LanguageStore:
    """Remember each Telegram user's language in a small JSON file.

    The file is loaded once at startup. Every change rewrites it atomically,
    so a crash cannot leave half-written JSON behind.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._choices: dict[str, str] = self._load()

    def get(self, user_id: int) -> str:
        """Return this user's language, or the default."""
        return self._choices.get(str(user_id), DEFAULT_LANGUAGE)

    def set(self, user_id: int, code: str) -> None:
        """Save this user's language choice."""
        if code not in LANGUAGES:
            raise ValueError(f"Unsupported language code: {code!r}")

        self._choices[str(user_id)] = code
        self._save()

    def _load(self) -> dict[str, str]:
        """Read the file, ignoring anything malformed."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(raw, dict):
            return {}

        # Keep only entries that are valid: string user IDs and known codes.
        return {
            user_id: code
            for user_id, code in raw.items()
            if isinstance(user_id, str)
            and isinstance(code, str)
            and code in LANGUAGES
        }

    def _save(self) -> None:
        """Write the whole file atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=".languages-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(
                    self._choices,
                    temp_file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                temp_file.write("\n")
            os.replace(temp_name, self.path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
