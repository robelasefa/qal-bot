"""Small formatting helpers for messages and the /stats command."""

from __future__ import annotations

import math

from .stats import Stats


def format_duration(seconds: float) -> str:
    """Turn seconds into a short human-readable duration."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_wait(seconds: float) -> str:
    """Describe how long until the next request is allowed."""
    total = math.ceil(max(0.0, seconds))
    if total <= 1:
        return "a moment"
    return format_duration(total)


def format_amount(value: object) -> str:
    """Format a balance or price without leaking precision noise."""
    if isinstance(value, (int, float)):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if value is None:
        return "unknown"
    return str(value)


def format_ago(seconds: float) -> str:
    """Describe a past timestamp in a compact, human way."""
    total = max(0, int(seconds))
    if total < 5:
        return "just now"
    if total < 60:
        return f"{total}s ago"
    if total < 3600:
        return f"{total // 60}m ago"
    if total < 86_400:
        return f"{total // 3600}h ago"
    return f"{total // 86_400}d ago"


def format_stats(
    stats: Stats,
    usage: dict[str, object],
    used: int,
    limit: int,
) -> str:
    """Build the hidden owner-facing /stats message."""
    currency = str(usage.get("currency") or "ETB")
    balance = format_amount(usage.get("balance"))

    lines = [
        "Qal stats",
        "",
        f"Uptime: {format_duration(stats.uptime_seconds())}",
        f"Users: {stats.user_count:,}",
        f"Requests: {stats.requests:,} total",
        f"Succeeded: {stats.succeeded:,} · Failed: {stats.failed:,}",
    ]

    success_rate = stats.success_rate()
    if success_rate is not None:
        lines.append(f"Success rate: {success_rate:.0%}")

    lines.extend(
        [
            f"Today (UTC): {used} / {limit}",
            "",
            f"Audio processed: {format_duration(stats.audio_seconds)}",
            f"Transcribed: {stats.transcript_characters:,} characters",
        ]
    )

    if stats.requests:
        lines.append(
            f"Avg. audio: {format_duration(stats.average_audio_seconds())}"
        )
    if stats.succeeded:
        lines.append(
            "Avg. transcription: "
            f"{stats.average_transcription_seconds():.1f}s"
        )
    if stats.languages:
        languages = " · ".join(
            f"{code} {count:,}" for code, count in stats.languages.most_common()
        )
        lines.append(f"Languages: {languages}")

    since_activity = stats.seconds_since_activity()
    if since_activity is not None:
        lines.append(f"Last activity: {format_ago(since_activity)}")

    lines.extend(
        [
            "",
            "Addis AI account",
            f"Balance: {balance} {currency}",
        ]
    )

    pricing = usage.get("pricing")
    if isinstance(pricing, dict):
        price = pricing.get("price_per_1000_characters")
        unit = str(pricing.get("unit") or "characters")
        if price is not None:
            lines.append(
                f"Rate: {format_amount(price)} {currency} per 1,000 {unit}"
            )

    return "\n".join(lines)


def split_text(text: str, limit: int = 4000) -> list[str]:
    """Split a transcript into Telegram-sized chunks, preferring line breaks."""
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]

        cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit

        chunk = text[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)
    return chunks
