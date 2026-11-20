"""Tests for log redaction and formatting."""

import logging
import sys

from src.app import _CleanFormatter, setup_logging

FAKE_TOKEN = "123456:ABC-DEF_secret"


def make_record(msg, *args, level=logging.INFO, exc_info=None, name="httpx"):
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )
    return record


def test_redacts_token_from_info_log_with_args():
    redact = lambda s: s.replace(FAKE_TOKEN, "***")
    formatter = _CleanFormatter(debug=False, redact=redact)
    url = f"https://api.telegram.org/bot{FAKE_TOKEN}/getMe"
    record = make_record("GET %s", url)
    out = formatter.format(record)
    assert FAKE_TOKEN not in out
    assert "***" in out
    assert "GET" in out


def test_redacts_token_from_exception_traceback():
    redact = lambda s: s.replace(FAKE_TOKEN, "***")
    formatter = _CleanFormatter(debug=False, redact=redact)
    url = f"https://api.telegram.org/bot{FAKE_TOKEN}/getMe"
    try:
        raise ValueError(f"request to {url} failed")
    except ValueError:
        record = make_record("boom", exc_info=sys.exc_info(), name="src.app")
    out = formatter.format(record)
    assert FAKE_TOKEN not in out
    assert "***" in out
    assert "ValueError" in out


def test_no_redaction_when_token_missing():
    formatter = _CleanFormatter(debug=False, redact=None)
    record = make_record("hello world")
    out = formatter.format(record)
    assert "hello world" in out


def test_no_color_codes_when_not_a_tty():
    # stdout is not a tty in tests, so no ANSI escape codes.
    formatter = _CleanFormatter(debug=False, redact=None)
    record = make_record("hello")
    out = formatter.format(record)
    assert "\033[" not in out


def test_setup_logging_accepts_token():
    setup_logging(False, redact=lambda s: s.replace(FAKE_TOKEN, "***"))
    root = logging.getLogger()
    assert root.handlers
    # httpx stays at WARNING.
    assert logging.getLogger("httpx").level == logging.WARNING