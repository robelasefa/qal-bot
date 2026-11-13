"""Tests for language validation and preference storage."""

import json

import pytest

from src.languages import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    LanguageStore,
    language_label,
    normalize_language,
)


def test_supported_languages_match_the_sdk() -> None:
    assert LANGUAGES == {
        "am": "Amharic",
        "om": "Afaan Oromo",
        "ti": "Tigrinya",
        "sw": "Swahili",
        "ha": "Hausa",
        "sid": "Sidama",
        "wal": "Wolaytta",
    }
    assert DEFAULT_LANGUAGE == "am"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("am", "am"),
        ("AM", "am"),
        (" ti ", "ti"),
        ("om", "om"),
        ("sw", "sw"),
        ("ha", "ha"),
        ("sid", "sid"),
        ("wal", "wal"),
        ("xx", DEFAULT_LANGUAGE),
        ("", DEFAULT_LANGUAGE),
        (None, DEFAULT_LANGUAGE),
    ],
)
def test_normalize_language(raw: str | None, expected: str) -> None:
    assert normalize_language(raw) == expected


def test_language_label_uses_display_name() -> None:
    assert language_label("om") == LANGUAGES["om"]


def test_language_label_falls_back_for_unknown_code() -> None:
    assert language_label("xx") == LANGUAGES[DEFAULT_LANGUAGE]


def test_store_defaults_to_am_for_a_new_user(tmp_path) -> None:
    store = LanguageStore(tmp_path / "languages.json")
    assert store.get(123) == DEFAULT_LANGUAGE


def test_store_saves_and_survives_a_restart(tmp_path) -> None:
    path = tmp_path / "data" / "languages.json"

    store = LanguageStore(path)
    store.set(123, "ti")

    assert store.get(123) == "ti"
    assert LanguageStore(path).get(123) == "ti"
    assert json.loads(path.read_text(encoding="utf-8")) == {"123": "ti"}


def test_store_rejects_an_unsupported_code(tmp_path) -> None:
    store = LanguageStore(tmp_path / "languages.json")

    with pytest.raises(ValueError):
        store.set(1, "xx")


def test_store_ignores_broken_json(tmp_path) -> None:
    path = tmp_path / "languages.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert LanguageStore(path).get(1) == DEFAULT_LANGUAGE


def test_store_drops_unknown_codes_when_loading(tmp_path) -> None:
    path = tmp_path / "languages.json"
    path.write_text(
        json.dumps({"1": "xx", "2": "ti", "not-a-user": 5}),
        encoding="utf-8",
    )

    store = LanguageStore(path)

    assert store.get(1) == DEFAULT_LANGUAGE
    assert store.get(2) == "ti"
