#!/usr/bin/env python3
"""Timestamp-prefixed stdout and scrape phase timing for quickjobs runs."""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime

# At least six spaces between wall timestamp and message body.
_LOG_TIMESTAMP_SEP = "      "
_WRAPPER_INSTALLED = False

# MM-DD-YYYY HH:MM:SS (scrape log prefix)
_LEADING_MM_DD_RE = re.compile(r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}\s+")
# MM/DD/YYYY HH:MM:SS (progress status embedded stamp)
_LEADING_MM_SLASH_RE = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\s+")
# YYYY-MM-DD HH:MM:SS [TZ] with optional trailing " - " (legacy CLI banners)
_LEADING_ISO_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\s+[A-Z]{2,5})?(?:\s*-\s*)?"
)
# N/M sources - (X jobs live) - MM/DD/YYYY HH:MM:SS (already stamped progress status)
_PROGRESS_STATUS_LINE_RE = re.compile(
    r"^\s*\d+/\d+\s+sources\s+-\s+\(\d+\s+jobs live\)\s+-\s+"
    r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\s*$"
)


def _timing_verbose() -> bool:
    return os.environ.get("QUICKJOBS_VERBOSE", "").strip() == "1"


class RunPhaseTimer:
    """Monotonic elapsed seconds since run start; emits [timing] markers on stdout."""

    def __init__(self) -> None:
        self._start = time.monotonic()
        self._phases: list[tuple[str, float]] = []

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def log_phase(self, name: str) -> float:
        elapsed = self.elapsed()
        self._phases.append((name, elapsed))
        if _timing_verbose():
            print(f"[timing] {name}: {elapsed:.1f}s", flush=True)
        return elapsed

    @property
    def phases(self) -> list[tuple[str, float]]:
        return list(self._phases)


_TIMER: RunPhaseTimer | None = None


def format_log_timestamp(when: datetime | None = None) -> str:
    """Local wall time for log line prefixes (MM-DD-YYYY HH:MM:SS)."""
    dt = when or datetime.now().astimezone()
    return dt.strftime("%m-%d-%Y %H:%M:%S")


def strip_leading_log_timestamp(line: str) -> str:
    """Remove an existing quickjobs log prefix so lines are not double-stamped."""
    stripped = _LEADING_MM_DD_RE.sub("", line, count=1)
    if stripped is line:
        stripped = _LEADING_MM_SLASH_RE.sub("", line, count=1)
    if stripped is line:
        stripped = _LEADING_ISO_TS_RE.sub("", line, count=1)
    return stripped


def line_is_progress_status(line: str) -> bool:
    """True when the line already carries the scrape progress status stamp."""
    return bool(_PROGRESS_STATUS_LINE_RE.match(line))


def line_has_log_content(line: str) -> bool:
    """True when a line should receive a timestamp prefix (non-empty message body)."""
    if not line:
        return False
    return bool(strip_leading_log_timestamp(line).strip())


class TimestampPrefixedStdout:
    """Wrap stdout: prefix complete lines; pass TTY carriage-return progress through raw."""

    def __init__(self, stream) -> None:
        self._stream = stream
        self._buffer = ""
        self._is_tty = bool(getattr(stream, "isatty", lambda: False)())

    def _emit_prefixed(self, line: str, *, newline: bool) -> None:
        if line_is_progress_status(line):
            self._stream.write(line)
            if newline:
                self._stream.write("\n")
            return
        if not line_has_log_content(line):
            return
        body = strip_leading_log_timestamp(line)
        self._stream.write(f"{format_log_timestamp()}{_LOG_TIMESTAMP_SEP}{body}")
        if newline:
            self._stream.write("\n")

    def write(self, text: str) -> int:
        if not text:
            return 0
        # TTY progress uses \\r (and often ANSI clear); do not prefix partial updates.
        if self._is_tty and "\r" in text:
            if self._buffer:
                self._emit_prefixed(self._buffer, newline=True)
                self._buffer = ""
            self._stream.write(text)
            return len(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit_prefixed(line, newline=True)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._emit_prefixed(self._buffer, newline=not self._is_tty)
            self._buffer = ""
        self._stream.flush()

    def fileno(self) -> int:
        return self._stream.fileno()

    def isatty(self) -> bool:
        return self._stream.isatty()

    @property
    def encoding(self) -> str:
        return getattr(self._stream, "encoding", "utf-8")

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def install_run_log_stream(*, enable_timing: bool = True) -> RunPhaseTimer | None:
    """Install stdout wrapper once per process; optional phase timer for scrape runs."""
    global _WRAPPER_INSTALLED, _TIMER
    if _WRAPPER_INSTALLED:
        return _TIMER
    sys.stdout = TimestampPrefixedStdout(sys.stdout)
    _WRAPPER_INSTALLED = True
    if enable_timing:
        _TIMER = RunPhaseTimer()
        if _timing_verbose():
            _TIMER.log_phase("run_start")
    return _TIMER


def get_run_timer() -> RunPhaseTimer | None:
    return _TIMER


def log_run_phase(name: str) -> float | None:
    timer = _TIMER
    if timer is None:
        return None
    return timer.log_phase(name)


def phase_duration(timing: dict[str, float], start: str, end: str) -> float | None:
    if start not in timing or end not in timing:
        return None
    return max(0.0, timing[end] - timing[start])
