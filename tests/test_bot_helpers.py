"""Tests for small pure handler and formatting helpers."""

from types import SimpleNamespace

import pytest

from src.formatting import (
    format_ago,
    format_duration,
    format_wait,
    split_text,
)
from src.handlers import audio_suffix, is_allowed, is_owner


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (59, "59s"),
        (60, "1m 0s"),
        (600, "10m 0s"),
        (3600, "1h 0m"),
        (3725, "1h 2m"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "a moment"),
        (1, "a moment"),
        (1.1, "2s"),
        (42, "42s"),
        (1800, "30m 0s"),
    ],
)
def test_format_wait(seconds: float, expected: str) -> None:
    assert format_wait(seconds) == expected


def test_split_text_returns_empty_list_for_blank_text() -> None:
    assert split_text("   \n  ") == []


def test_split_text_keeps_short_text_whole() -> None:
    assert split_text("hello", limit=10) == ["hello"]


def test_split_text_prefers_a_line_break() -> None:
    assert split_text("aaaaa\nbbbbb", limit=6) == ["aaaaa", "bbbbb"]


def test_split_text_hard_cuts_a_long_word() -> None:
    assert split_text("abcdefghij", limit=4) == ["abcd", "efgh", "ij"]


def test_split_text_never_exceeds_the_limit() -> None:
    chunks = split_text("word " * 2000, limit=100)

    assert "".join(chunks).replace(" ", "") == ("word" * 2000)
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_split_text_rejects_an_invalid_limit() -> None:
    with pytest.raises(ValueError):
        split_text("hello", limit=0)


def test_audio_suffix_for_a_voice_message() -> None:
    message = SimpleNamespace(voice=object(), audio=None)
    assert audio_suffix(message, None) == ".ogg"


def test_audio_suffix_uses_the_audio_file_name() -> None:
    message = SimpleNamespace(
        voice=None,
        audio=SimpleNamespace(file_name="clip.m4a"),
    )
    assert audio_suffix(message, None) == ".m4a"


def test_audio_suffix_falls_back_for_unknown_files() -> None:
    message = SimpleNamespace(
        voice=None,
        audio=SimpleNamespace(file_name="clip.bin"),
    )
    assert audio_suffix(message, "unknown.xyz") == ".mp3"


def services_with(allowed: set[int], owner: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(
            allowed_user_ids=frozenset(allowed),
            owner_user_id=owner,
        )
    )


def test_empty_allowlist_allows_everyone() -> None:
    services = services_with(set())

    assert is_allowed(services, 1) is True
    assert is_allowed(services, 999) is True


def test_allowlist_allows_listed_users_only() -> None:
    services = services_with({11, 22})

    assert is_allowed(services, 11) is True
    assert is_allowed(services, 33) is False


def test_owner_is_allowed_even_when_not_listed() -> None:
    services = services_with({11}, owner=99)

    assert is_allowed(services, 99) is True
    assert is_allowed(services, 98) is False


def test_owner_id_does_not_override_a_public_bot() -> None:
    services = services_with(set(), owner=99)

    assert is_allowed(services, 1) is True


def test_is_owner_requires_a_configured_owner() -> None:
    assert is_owner(services_with(set()), 1) is False


def test_is_owner_matches_only_the_owner_id() -> None:
    services = services_with(set(), owner=99)

    assert is_owner(services, 99) is True
    assert is_owner(services, 98) is False


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "just now"),
        (4, "just now"),
        (5, "5s ago"),
        (59, "59s ago"),
        (60, "1m ago"),
        (3599, "59m ago"),
        (3600, "1h ago"),
        (86_399, "23h ago"),
        (86_400, "1d ago"),
    ],
)
def test_format_ago(seconds: float, expected: str) -> None:
    assert format_ago(seconds) == expected
