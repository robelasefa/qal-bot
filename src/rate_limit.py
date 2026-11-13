"""A small in-memory rolling-window rate limiter."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class RateLimiter:
    """Allow at most `limit` requests per user in any rolling window.

    Time is injected as `clock` so tests can control it without sleeping.
    This lives in memory: restarting the bot clears every user's history.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float = 3600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")

        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._requests: dict[int, deque[float]] = {}

    def allow(self, user_id: int) -> bool:
        """Return True and record the request, or False if the user is over the limit."""
        now = self._clock()
        history = self._requests.setdefault(user_id, deque())
        self._prune(history, now)

        if len(history) >= self.limit:
            return False

        history.append(now)
        return True

    def remaining(self, user_id: int) -> int:
        """How many requests this user can still make in the current window."""
        history = self._requests.get(user_id)
        if history is None:
            return self.limit

        self._prune(history, self._clock())
        return max(0, self.limit - len(history))

    def retry_after(self, user_id: int) -> float:
        """Seconds until this user may make another request (0 if allowed now)."""
        now = self._clock()
        history = self._requests.get(user_id)
        if history is None:
            return 0.0

        self._prune(history, now)
        if len(history) < self.limit:
            return 0.0

        return max(0.0, history[0] + self.window_seconds - now)

    def reset(self, user_id: int | None = None) -> None:
        """Forget one user's history, or everyone's when user_id is None."""
        if user_id is None:
            self._requests.clear()
        else:
            self._requests.pop(user_id, None)

    def _prune(self, history: deque[float], now: float) -> None:
        """Drop timestamps that have fallen out of the window."""
        cutoff = now - self.window_seconds
        while history and history[0] <= cutoff:
            history.popleft()


class DailyBudget:
    """A global cap on requests per UTC day, shared by every user.

    This protects the owner's credits when many different users arrive; the
    per-user RateLimiter cannot do that on its own. Time is injected so tests
    can cross midnight without sleeping.

    The count is persisted to a small JSON file when `path` is given, so a
    restart no longer wipes today's usage. Per-user limits stay in memory.
    """

    SECONDS_PER_DAY = 86_400

    def __init__(
        self,
        limit: int,
        clock: Callable[[], float] = time.time,
        path: Path | None = None,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        self.limit = limit
        self._clock = clock
        self._path = path
        self._day: int | None = None
        self._used = 0
        self._load()

    def allow(self) -> bool:
        """Return True and record a request, or False if today's cap is reached."""
        self._roll_over()
        if self._used >= self.limit:
            return False

        self._used += 1
        self._save()
        return True

    def remaining(self) -> int:
        """How many requests the bot can still make today."""
        self._roll_over()
        return max(0, self.limit - self._used)

    def used(self) -> int:
        """How many requests have been made today."""
        self._roll_over()
        return self._used

    def reset(self) -> None:
        """Forget today's count without changing the day boundary."""
        self._used = 0
        self._save()

    def _load(self) -> None:
        """Read a persisted count for today, if the file is valid."""
        if self._path is None:
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return

        if not isinstance(raw, dict):
            return

        day = raw.get("day")
        used = raw.get("used")
        if not isinstance(day, int) or not isinstance(used, int):
            return
        if used < 0:
            return

        today = int(self._clock() // self.SECONDS_PER_DAY)
        if day == today:
            self._day = day
            self._used = min(used, self.limit)

    def _save(self) -> None:
        """Persist today's count atomically. Failures are logged, not raised."""
        if self._path is None:
            return

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                dir=self._path.parent,
                prefix=".daily-budget-",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                    json.dump(
                        {"day": self._day, "used": self._used},
                        temp_file,
                    )
                    temp_file.write("\n")
                os.replace(temp_name, self._path)
            except BaseException:
                Path(temp_name).unlink(missing_ok=True)
                raise
        except OSError:
            logger.warning("Could not persist the daily transcription budget")

    def _roll_over(self) -> None:
        """Start a new count when the UTC date changes."""
        today = int(self._clock() // self.SECONDS_PER_DAY)
        if today != self._day:
            self._day = today
            self._used = 0