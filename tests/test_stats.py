"""Tests for in-memory statistics and the hidden /stats message."""

from src.formatting import format_stats
from src.stats import Stats


def test_new_stats_are_empty(clock) -> None:
    stats = Stats(clock=clock)

    assert stats.user_count == 0
    assert stats.requests == 0
    assert stats.succeeded == 0
    assert stats.failed == 0
    assert stats.success_rate() is None
    assert stats.seconds_since_activity() is None


def test_requests_track_users_languages_and_audio(clock) -> None:
    stats = Stats(clock=clock)

    stats.record_request(1, "am", 30)
    stats.record_request(2, "om", 90)
    stats.record_request(1, "am", 60)

    assert stats.requests == 3
    assert stats.user_count == 2
    assert stats.languages == {"am": 2, "om": 1}
    assert stats.audio_seconds == 180
    assert stats.average_audio_seconds() == 60


def test_successes_track_characters_and_turnaround(clock) -> None:
    stats = Stats(clock=clock)

    stats.record_success(1_000, 4.0)
    stats.record_success(500, 2.0)

    assert stats.succeeded == 2
    assert stats.transcript_characters == 1_500
    assert stats.average_transcription_seconds() == 3.0


def test_success_rate_counts_only_completed_requests(clock) -> None:
    stats = Stats(clock=clock)

    stats.record_success(10, 1.0)
    stats.record_success(10, 1.0)
    stats.record_failure()

    assert stats.completed() == 3
    assert stats.success_rate() == 2 / 3


def test_uptime_and_last_activity_use_the_clock(clock) -> None:
    stats = Stats(clock=clock)
    clock.now = 100

    stats.record_request(1, "am", 30)
    clock.now = 130

    assert stats.uptime_seconds() == 130
    assert stats.seconds_since_activity() == 30


def test_format_stats_shows_the_portfolio_numbers(clock) -> None:
    stats = Stats(clock=clock)
    clock.now = 100
    stats.record_request(1, "am", 30)
    stats.record_request(2, "om", 90)
    stats.record_request(1, "am", 60)
    stats.record_request(1, "am", 120)
    stats.record_success(1_000, 4.0)
    stats.record_success(500, 2.0)
    stats.record_success(250, 3.0)
    stats.record_failure()

    text = format_stats(
        stats,
        {
            "balance": 1234.5,
            "currency": "ETB",
            "pricing": {
                "unit": "characters",
                "price_per_1000_characters": 3.5,
            },
        },
        used=4,
        limit=100,
    )

    assert "Users: 2" in text
    assert "Requests: 4 total" in text
    assert "Succeeded: 3 · Failed: 1" in text
    assert "Success rate: 75%" in text
    assert "Today (UTC): 4 / 100" in text
    assert "Audio processed: 5m 0s" in text
    assert "Transcribed: 1,750 characters" in text
    assert "Avg. audio: 1m 15s" in text
    assert "Avg. transcription: 3.0s" in text
    assert "Languages: am 3 · om 1" in text
    assert "Last activity: just now" in text
    assert "Balance: 1,234.5 ETB" in text
    assert "Rate: 3.5 ETB per 1,000 characters" in text


def test_format_stats_handles_a_fresh_process(clock) -> None:
    text = format_stats(Stats(clock=clock), {}, used=0, limit=100)

    assert "Users: 0" in text
    assert "Requests: 0 total" in text
    assert "Success rate" not in text
    assert "Avg. audio" not in text
    assert "Avg. transcription" not in text
    assert "Languages" not in text
    assert "Last activity" not in text
    assert "unknown ETB" in text
    assert "Rate:" not in text
