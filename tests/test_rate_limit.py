"""Tests for the rolling-window rate limiter."""

import pytest

from src.rate_limit import DailyBudget, RateLimiter


def make_limiter(
    clock,
    limit: int = 2,
    window_seconds: float = 3600,
) -> RateLimiter:
    return RateLimiter(
        limit=limit,
        window_seconds=window_seconds,
        clock=clock,
    )


def test_allows_requests_up_to_the_limit(clock) -> None:
    limiter = make_limiter(clock)

    assert limiter.allow(1) is True
    assert limiter.allow(1) is True


def test_blocks_the_request_after_the_limit(clock) -> None:
    limiter = make_limiter(clock)
    limiter.allow(1)
    limiter.allow(1)

    assert limiter.allow(1) is False


def test_users_have_separate_budgets(clock) -> None:
    limiter = make_limiter(clock)
    limiter.allow(1)
    limiter.allow(1)

    assert limiter.allow(1) is False
    assert limiter.allow(2) is True


def test_old_requests_leave_the_window(clock) -> None:
    limiter = make_limiter(clock, limit=2, window_seconds=3600)
    limiter.allow(1)
    limiter.allow(1)

    clock.now = 3600
    assert limiter.allow(1) is True
    assert limiter.remaining(1) == 1


def test_retry_after_counts_down(clock) -> None:
    limiter = make_limiter(clock, limit=2, window_seconds=3600)
    limiter.allow(1)
    limiter.allow(1)

    clock.now = 1800
    assert limiter.retry_after(1) == 1800.0

    clock.now = 3600
    assert limiter.retry_after(1) == 0.0


def test_remaining_never_goes_negative(clock) -> None:
    limiter = make_limiter(clock, limit=1)
    limiter.allow(1)
    limiter.allow(1)

    assert limiter.remaining(1) == 0


def test_reset_clears_one_user_or_everyone(clock) -> None:
    limiter = make_limiter(clock, limit=1)
    limiter.allow(1)
    limiter.allow(2)

    limiter.reset(1)
    assert limiter.allow(1) is True
    assert limiter.allow(2) is False

    limiter.reset()
    assert limiter.allow(2) is True


@pytest.mark.parametrize(
    ("limit", "window_seconds"),
    [(0, 3600), (-1, 3600), (1, 0), (1, -1)],
)
def test_rejects_invalid_settings(
    clock,
    limit: int,
    window_seconds: float,
) -> None:
    with pytest.raises(ValueError):
        make_limiter(clock, limit=limit, window_seconds=window_seconds)


def test_daily_budget_allows_up_to_the_limit(clock) -> None:
    budget = DailyBudget(limit=2, clock=clock)

    assert budget.allow() is True
    assert budget.allow() is True
    assert budget.allow() is False


def test_daily_budget_reports_used_and_remaining(clock) -> None:
    budget = DailyBudget(limit=3, clock=clock)
    budget.allow()

    assert budget.used() == 1
    assert budget.remaining() == 2


def test_daily_budget_resets_at_utc_midnight(clock) -> None:
    budget = DailyBudget(limit=1, clock=clock)
    assert budget.allow() is True
    assert budget.allow() is False

    # One second before the next UTC day: still capped.
    clock.now = DailyBudget.SECONDS_PER_DAY - 1
    assert budget.remaining() == 0

    # At the boundary the count starts over.
    clock.now = DailyBudget.SECONDS_PER_DAY
    assert budget.remaining() == 1
    assert budget.allow() is True
    assert budget.used() == 1


def test_daily_budget_reset_clears_todays_count(clock) -> None:
    budget = DailyBudget(limit=1, clock=clock)
    budget.allow()

    budget.reset()

    assert budget.used() == 0
    assert budget.allow() is True


def test_daily_budget_rejects_an_invalid_limit(clock) -> None:
    with pytest.raises(ValueError):
        DailyBudget(limit=0, clock=clock)


def test_daily_budget_persists_across_instances(tmp_path, clock) -> None:
    path = tmp_path / "daily.json"

    first = DailyBudget(limit=2, clock=clock, path=path)
    assert first.allow() is True
    assert first.allow() is True
    assert first.allow() is False

    second = DailyBudget(limit=2, clock=clock, path=path)
    assert second.used() == 2
    assert second.allow() is False


def test_daily_budget_ignores_a_stale_file(tmp_path, clock) -> None:
    path = tmp_path / "daily.json"
    path.write_text('{"day": 0, "used": 99}', encoding="utf-8")

    clock.now = DailyBudget.SECONDS_PER_DAY
    budget = DailyBudget(limit=2, clock=clock, path=path)
    assert budget.used() == 0
    assert budget.allow() is True
