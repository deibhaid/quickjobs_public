#!/usr/bin/env python3
"""Smoke-test timestamp-prefixed stdout and [timing] lines (no scrape)."""

from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run_log import (  # noqa: E402
    TimestampPrefixedStdout,
    format_log_timestamp,
    install_run_log_stream,
    line_has_log_content,
    line_is_progress_status,
    log_run_phase,
    strip_leading_log_timestamp,
)

PREFIX_RE = re.compile(r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}\s{6,}")


def assert_prefix(line: str) -> None:
    if not PREFIX_RE.match(line):
        raise AssertionError(f"missing timestamp prefix: {line!r}")
    gap = line[19:25]
    if len(gap) < 6 or gap.strip():
        raise AssertionError(f"expected >=6 spaces after timestamp, got gap={gap!r}")


def test_strip_leading_log_timestamp() -> None:
    ts = format_log_timestamp()
    prefixed = f"{ts}      Scraping 397 companies..."
    assert strip_leading_log_timestamp(prefixed) == "Scraping 397 companies..."
    assert strip_leading_log_timestamp("[timing] run_start: 0.0s") == "[timing] run_start: 0.0s"
    legacy = "2026-06-23 12:14:38 PDT - full board"
    assert strip_leading_log_timestamp(legacy) == "full board"


def test_no_double_stamp() -> None:
    ts = format_log_timestamp()
    buf = io.StringIO()
    buf.isatty = lambda: False  # type: ignore[method-assign]
    sys.stdout = TimestampPrefixedStdout(buf)
    print(f"{ts}      already stamped")
    sys.stdout.flush()
    line = buf.getvalue().splitlines()[0]
    assert line.count(ts) == 1, line
    assert_prefix(line)


def test_progress_status_line_not_double_stamped() -> None:
    status = "  472/690 sources - (7274 jobs live) - 07/05/2026 15:20:30"
    assert line_is_progress_status(status)
    buf = io.StringIO()
    buf.isatty = lambda: False  # type: ignore[method-assign]
    sys.stdout = TimestampPrefixedStdout(buf)
    print(status)
    sys.stdout.flush()
    line = buf.getvalue().splitlines()[0]
    assert line == status, line
    assert line.count("07/05/2026") == 1
    assert "07-05-2026" not in line


def test_tty_progress_then_incremental_on_separate_lines() -> None:
    buf = io.StringIO()
    buf.isatty = lambda: True  # type: ignore[method-assign]
    wrapped = TimestampPrefixedStdout(buf)
    wrapped.write("\033[2K\r  472/690 sources - (7274 jobs live) - 07/05/2026 15:20:30")
    wrapped.write("\033[2K\r  … scrape 473/690 · capitalone (12 jobs)\n")
    wrapped.flush()
    output = buf.getvalue()
    assert "\033[2K\r" in output
    assert "07/05/2026 15:20:30" in output
    assert "capitalone" in output
    assert not re.search(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\d{2}-\d{2}-\d{4}", output)


def _assert_no_lone_timestamp(lines: list[str]) -> None:
    for line in lines:
        if PREFIX_RE.match(line):
            body = strip_leading_log_timestamp(line)
            if not body.strip():
                raise AssertionError(f"lone timestamp line: {line!r}")


def test_empty_lines_suppressed() -> None:
    buf = io.StringIO()
    buf.isatty = lambda: False  # type: ignore[method-assign]
    sys.stdout = TimestampPrefixedStdout(buf)
    print()
    print("")
    print("   ")
    print(f"{format_log_timestamp()}      ")
    print("has message")
    sys.stdout.flush()
    lines = buf.getvalue().splitlines()
    assert len(lines) == 1, lines
    assert_prefix(lines[0])
    assert "has message" in lines[0]
    _assert_no_lone_timestamp(lines)


def test_line_has_log_content() -> None:
    assert not line_has_log_content("")
    assert not line_has_log_content("   ")
    ts = format_log_timestamp()
    assert not line_has_log_content(f"{ts}      ")
    assert line_has_log_content("Scraping 397 companies...")


def main() -> int:
    test_strip_leading_log_timestamp()
    test_no_double_stamp()
    test_progress_status_line_not_double_stamped()
    test_tty_progress_then_incremental_on_separate_lines()
    test_empty_lines_suppressed()
    test_line_has_log_content()

    buf = io.StringIO()
    buf.isatty = lambda: False  # type: ignore[method-assign]
    real = sys.stdout
    sys.stdout = TimestampPrefixedStdout(buf)
    print("Scraping 397 companies...")
    print("[timing] run_start: 0.0s")
    sys.stdout.flush()
    sys.stdout = real

    lines = buf.getvalue().splitlines()
    if len(lines) != 2:
        print(f"expected 2 lines, got {len(lines)}", file=sys.stderr)
        return 1
    for line in lines:
        try:
            assert_prefix(line)
        except AssertionError as exc:
            print(exc, file=sys.stderr)
            return 1
    print(lines[0])
    print(lines[1])

    buf2 = io.StringIO()
    buf2.isatty = lambda: False  # type: ignore[method-assign]
    sys.stdout = buf2
    os.environ["QUICKJOBS_VERBOSE"] = "1"
    install_run_log_stream()
    log_run_phase("startup_end")
    sys.stdout.flush()
    sys.stdout = real
    timing_line = buf2.getvalue().strip().splitlines()[-1]
    if "[timing] startup_end:" not in timing_line:
        print(f"unexpected timing line: {timing_line!r}", file=sys.stderr)
        return 1
    try:
        assert_prefix(timing_line)
    except AssertionError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(timing_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
