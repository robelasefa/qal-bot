"""In-memory statistics for the hidden owner-only /stats command.

Nothing here is persisted. Restarting the bot resets every counter, which keeps
the bot database-free and makes the privacy story simple. User IDs are held in
a set only long enough to count unique users; they are never displayed.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable


class Stats:
    """Counters for the lifetime of the current bot process."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self.started_at = clock()
        self.requests = 0
        self.succeeded = 0
        self.failed = 0
        self.audio_seconds = 0.0
        self.transcript_characters = 0
        self.transcription_seconds = 0.0
        self.languages: Counter[str] = Counter()
        self.last_activity: float | None = None
        self._users: set[int] = set()

    @property
    def user_count(self) -> int:
        """How many distinct users have submitted audio."""
        return len(self._users)

    def record_request(
        self,
        user_id: int,
        language: str,
        audio_seconds: float,
    ) -> None:
        """Count an accepted request just before transcription starts."""
        self._users.add(user_id)
        self.requests += 1
        self.languages[language] += 1
        self.audio_seconds += max(0.0, audio_seconds)
        self._touch()

    def record_success(
        self,
        characters: int,
        transcription_seconds: float,
    ) -> None:
        """Count a transcript we successfully delivered."""
        self.succeeded += 1
        self.transcript_characters += max(0, characters)
        self.transcription_seconds += max(0.0, transcription_seconds)
        self._touch()

    def record_failure(self) -> None:
        """Count a request that did not produce a usable transcript."""
        self.failed += 1
        self._touch()

    def completed(self) -> int:
        return self.succeeded + self.failed

    def success_rate(self) -> float | None:
        completed = self.completed()
        if completed == 0:
            return None
        return self.succeeded / completed

    def average_audio_seconds(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.audio_seconds / self.requests

    def average_transcription_seconds(self) -> float:
        if self.succeeded == 0:
            return 0.0
        return self.transcription_seconds / self.succeeded

    def uptime_seconds(self) -> float:
        return max(0.0, self._clock() - self.started_at)

    def seconds_since_activity(self) -> float | None:
        if self.last_activity is None:
            return None
        return max(0.0, self._clock() - self.last_activity)

    def _touch(self) -> None:
        self.last_activity = self._clock()
