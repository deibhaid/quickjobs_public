#!/usr/bin/env python3
"""Compare a quickjobs full-board run log against timing-baselines.yaml."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINES = SCRIPT_DIR / "timing-baselines.yaml"

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_STALL = "STALL"
STATUS_RUNNING = "RUNNING"
STATUS_SKIP = "SKIP"
STATUS_NA = "N/A"

LOG_LINE_PREFIX_RE = re.compile(
    r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}\s{6,}"
)
TIMING_RE = re.compile(r"\[timing\] ([^:]+): ([0-9.]+)s")

PHASE_MARKERS = {
    "startup_end": re.compile(r"^Scraping \d+ companies"),
    "http_start": re.compile(r"^HTTP/API scrape:"),
    "playwright_start": re.compile(r"^Playwright scrape:"),
    "scrape_complete": re.compile(r"^\s+\d+/\d+ sources \("),
    "dedupe": re.compile(r"^Cross-company dedupe:"),
    "glassdoor_start": re.compile(r"^Glassdoor prefetch:"),
    "validated": re.compile(r"^Validated badge structure"),
    "wrote": re.compile(r"^Wrote "),
    "rolling_backup": re.compile(r"^Rolling backup:"),
}

HEARTBEAT_RE = re.compile(
    r"still scraping \((HTTP|Playwright), (\d+)/(\d+) companies done, "
    r"(\d+)m elapsed(?:, (\d+) workers active)?\)"
)
ELAPSED_RE = re.compile(r"Elapsed:\s*([0-9.]+)\s*min")
START_RE = re.compile(
    r"^quickjobs(?: worker pid| n) (\d+)"
    r"(?: - (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (PDT|PST))?\s*$"
)
LOG_PREFIX_TS_RE = re.compile(r"^(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})")
SCRAPE_COUNT_RE = re.compile(r"Scraping (\d+) companies")
HTTP_COUNT_RE = re.compile(r"HTTP/API scrape: (\d+)")
PW_COUNT_RE = re.compile(r"Playwright scrape: (\d+)")


@dataclass
class Heartbeat:
    phase: str
    done: int
    total: int
    elapsed_sec: float
    workers: int | None


@dataclass
class ParsedLog:
    lines: list[str]
    start_ts: datetime | None = None
    company_count: int | None = None
    http_count: int | None = None
    playwright_count: int | None = None
    scrape_elapsed_sec: float | None = None
    complete: bool = False
    heartbeats: list[Heartbeat] = field(default_factory=list)
    marker_line: dict[str, int] = field(default_factory=dict)
    timing_phases: dict[str, float] = field(default_factory=dict)
    company_lines_during_http: int = 0


def strip_log_prefix(line: str) -> str:
    return LOG_LINE_PREFIX_RE.sub("", line, count=1)


def timing_delta(timing: dict[str, float], start: str, end: str) -> float | None:
    if start not in timing or end not in timing:
        return None
    return max(0.0, timing[end] - timing[start])


@dataclass
class PhaseResult:
    phase: str
    status: str
    measured_sec: float | None
    expected_sec: float | None
    warn_sec: float | None
    stall_sec: float | None
    delta_sec: float | None
    notes: str = ""


def _pacific_tz(abbrev: str) -> timezone:
    hours = -7 if abbrev == "PDT" else -8
    return timezone(timedelta(hours=hours))


def load_baselines(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise SystemExit("PyYAML required: ~/.v/bin/pip install pyyaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "phases" not in data:
        raise SystemExit(f"Invalid baselines file: {path}")
    return data


def wall_clock_sec(parsed: ParsedLog, file_mtime: float | None) -> float | None:
    if parsed.start_ts is None or file_mtime is None:
        return None
    end = datetime.fromtimestamp(file_mtime, tz=parsed.start_ts.tzinfo)
    wall = max(0.0, (end - parsed.start_ts).total_seconds())
    if parsed.scrape_elapsed_sec is not None:
        # Ignore copy-artifact mtimes (e.g. scp without -p) far beyond scrape + post.
        max_reasonable = parsed.scrape_elapsed_sec + 300
        if wall > max_reasonable * 1.5:
            return None
    elif wall > 7200:
        return None
    return wall


def parse_log_text(text: str, *, file_mtime: float | None = None) -> ParsedLog:
    parsed = ParsedLog(lines=text.splitlines())
    in_http = False
    for idx, line in enumerate(parsed.lines):
        norm = strip_log_prefix(line)
        tm = TIMING_RE.search(norm)
        if tm:
            parsed.timing_phases[tm.group(1).strip()] = float(tm.group(2))
        if parsed.start_ts is None:
            m = START_RE.match(norm)
            if m:
                if m.group(2):
                    parsed.start_ts = datetime.strptime(
                        m.group(2), "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=_pacific_tz(m.group(3)))
                else:
                    pm = LOG_PREFIX_TS_RE.match(line)
                    if pm:
                        parsed.start_ts = datetime.strptime(
                            pm.group(1), "%m-%d-%Y %H:%M:%S"
                        ).replace(tzinfo=_pacific_tz("PDT"))
        for key, pattern in PHASE_MARKERS.items():
            if key not in parsed.marker_line and pattern.search(norm):
                parsed.marker_line[key] = idx
        if norm.startswith("Scraping "):
            m = SCRAPE_COUNT_RE.search(norm)
            if m:
                parsed.company_count = int(m.group(1))
        if norm.startswith("HTTP/API scrape:"):
            in_http = True
            m = HTTP_COUNT_RE.search(norm)
            if m:
                parsed.http_count = int(m.group(1))
        elif norm.startswith("Playwright scrape:"):
            in_http = False
            m = PW_COUNT_RE.search(norm)
            if m:
                parsed.playwright_count = int(m.group(1))
        elif "scrape_complete" in parsed.marker_line and idx >= parsed.marker_line["scrape_complete"]:
            in_http = False
        elif in_http and re.match(r"^\s{2}[a-z0-9-]+\s+\d+\s+", norm):
            parsed.company_lines_during_http += 1
        m = ELAPSED_RE.search(norm)
        if m:
            parsed.scrape_elapsed_sec = float(m.group(1)) * 60.0
        hb = HEARTBEAT_RE.search(norm)
        if hb:
            parsed.heartbeats.append(
                Heartbeat(
                    phase=hb.group(1),
                    done=int(hb.group(2)),
                    total=int(hb.group(3)),
                    elapsed_sec=float(hb.group(4)) * 60.0,
                    workers=int(hb.group(5)) if hb.group(5) else None,
                )
            )
        if norm.startswith("Wrote "):
            parsed.complete = True
    return parsed


def scaled_threshold(
    base: float,
    *,
    scale: bool,
    company_count: int | None,
    baseline_count: int,
) -> float:
    if not scale or not company_count or company_count <= 0 or baseline_count <= 0:
        return base
    return base * (company_count / baseline_count)


def classify(
    measured: float | None,
    expected: float,
    warn: float,
    stall: float,
    *,
    running: bool = False,
) -> tuple[str, float | None]:
    if measured is None:
        return (STATUS_NA, None)
    delta = measured - expected
    if running and measured < expected * 0.5:
        return (STATUS_RUNNING, delta)
    if measured >= stall:
        return (STATUS_STALL, delta)
    if measured >= warn:
        return (STATUS_WARN, delta)
    return (STATUS_OK, delta)


def scrape_progress_status(
    parsed: ParsedLog,
    expected_scrape_sec: float,
) -> PhaseResult | None:
    if parsed.complete or not parsed.heartbeats:
        return None
    hb = parsed.heartbeats[-1]
    if hb.total <= 0 or expected_scrape_sec <= 0:
        return None
    expected_done = hb.total * min(1.0, hb.elapsed_sec / expected_scrape_sec)
    if expected_done <= 0:
        return None
    ratio = hb.done / expected_done
    status = STATUS_OK
    if ratio < 0.55:
        status = STATUS_STALL
    elif ratio < 0.8:
        status = STATUS_WARN
    elif not parsed.complete:
        status = STATUS_RUNNING
    return PhaseResult(
        phase="scrape_progress",
        status=status,
        measured_sec=ratio,
        expected_sec=1.0,
        warn_sec=0.8,
        stall_sec=0.55,
        delta_sec=ratio - 1.0,
        notes=(
            f"heartbeat {hb.done}/{hb.total} at {hb.elapsed_sec:.0f}s; "
            f"expected ~{expected_done:.0f} done by now"
        ),
    )


def heartbeat_rate_status(parsed: ParsedLog, expected_per_co: float, warn_per_co: float) -> PhaseResult | None:
    if not parsed.heartbeats:
        return None
    hb = parsed.heartbeats[-1]
    if hb.done <= 0:
        return None
    rate = hb.elapsed_sec / hb.done
    status = STATUS_OK
    if rate >= warn_per_co * 2:
        status = STATUS_STALL
    elif rate >= warn_per_co:
        status = STATUS_WARN
    elif not parsed.complete:
        status = STATUS_RUNNING
    return PhaseResult(
        phase="http_heartbeat_rate",
        status=status,
        measured_sec=rate,
        expected_sec=expected_per_co,
        warn_sec=warn_per_co,
        stall_sec=warn_per_co * 2,
        delta_sec=rate - expected_per_co,
        notes=f"last heartbeat {hb.phase} {hb.done}/{hb.total} @ {hb.elapsed_sec:.0f}s",
    )


def measure_phases(
    parsed: ParsedLog,
    baselines: dict[str, Any],
    *,
    file_mtime: float | None = None,
) -> list[PhaseResult]:
    meta = baselines.get("meta") or {}
    baseline_co = int(meta.get("baseline_company_count") or 393)
    company_co = parsed.company_count or baseline_co
    phase_cfg = {row["phase"]: row for row in baselines.get("phases") or []}
    results: list[PhaseResult] = []
    timing = parsed.timing_phases

    wall_sec = wall_clock_sec(parsed, file_mtime)
    if wall_sec is None and parsed.complete and parsed.scrape_elapsed_sec is not None:
        post_cfg = phase_cfg.get("post_scrape") or {}
        wall_sec = parsed.scrape_elapsed_sec + float(post_cfg.get("expected_sec") or 30)

    http_est = timing_delta(timing, "http_pool_start", "http_pool_end")
    pw_est = timing_delta(timing, "playwright_pool_start", "playwright_pool_end")
    scrape_timing = timing.get("scrape_total")
    post_timing = None
    if timing.get("write") is not None and scrape_timing is not None:
        post_timing = max(0.0, timing["write"] - scrape_timing)
    total_timing = timing.get("total")

    if http_est is None and parsed.scrape_elapsed_sec is not None:
        http_cfg = phase_cfg.get("http_scrape_total") or {}
        pw_cfg = phase_cfg.get("playwright_scrape") or {}
        http_base = float(http_cfg.get("expected_sec") or 480)
        pw_base = float(pw_cfg.get("expected_sec") or 120)
        split_total = http_base + pw_base
        if split_total > 0:
            http_est = parsed.scrape_elapsed_sec * (http_base / split_total)
            pw_est = parsed.scrape_elapsed_sec * (pw_base / split_total)

    post_est = post_timing
    if post_est is None and wall_sec is not None and parsed.scrape_elapsed_sec is not None:
        post_est = max(0.0, wall_sec - parsed.scrape_elapsed_sec)

    running = not parsed.complete

    for phase_name in (
        "startup",
        "http_scrape_total",
        "http_per_company_p50",
        "http_per_company_p95",
        "playwright_scrape",
        "scrape_total",
        "post_scrape",
        "html_write",
        "rolling_backup",
        "total_wall_clock",
    ):
        cfg = phase_cfg.get(phase_name)
        if not cfg:
            continue
        scale = bool(cfg.get("scale_with_companies"))
        expected = scaled_threshold(
            float(cfg["expected_sec"]),
            scale=scale,
            company_count=company_co,
            baseline_count=baseline_co,
        )
        warn = scaled_threshold(
            float(cfg["warn_sec"]),
            scale=scale,
            company_count=company_co,
            baseline_count=baseline_co,
        )
        stall = scaled_threshold(
            float(cfg["stall_sec"]),
            scale=scale,
            company_count=company_co,
            baseline_count=baseline_co,
        )
        measured: float | None = None
        notes = str(cfg.get("notes") or "").splitlines()[0][:80]

        if phase_name == "startup":
            measured = timing_delta(timing, "run_start", "startup_end")
            if measured is None:
                measured = 0.0 if parsed.marker_line.get("http_start") is not None else None
        elif phase_name == "http_scrape_total":
            if http_est is not None and timing.get("http_pool_end") is not None:
                measured = http_est
            elif running and parsed.heartbeats:
                hb = next((h for h in reversed(parsed.heartbeats) if h.phase == "HTTP"), None)
                if hb:
                    measured = hb.elapsed_sec
            elif http_est is not None:
                measured = http_est
        elif phase_name == "http_per_company_p50":
            if parsed.heartbeats:
                hb = parsed.heartbeats[-1]
                if hb.done > 0:
                    measured = hb.elapsed_sec / hb.done
            elif parsed.http_count and http_est:
                measured = http_est / parsed.http_count
        elif phase_name == "http_per_company_p95":
            measured = None
        elif phase_name == "playwright_scrape":
            if pw_est is not None and timing.get("playwright_pool_end") is not None:
                measured = pw_est
            elif running and any(h.phase == "Playwright" for h in parsed.heartbeats):
                hb = next(h for h in reversed(parsed.heartbeats) if h.phase == "Playwright")
                measured = hb.elapsed_sec
            elif pw_est is not None and not running:
                measured = pw_est
        elif phase_name == "scrape_total":
            if scrape_timing is not None:
                measured = scrape_timing
            elif running and parsed.heartbeats:
                measured = parsed.heartbeats[-1].elapsed_sec
            else:
                measured = parsed.scrape_elapsed_sec
        elif phase_name == "post_scrape":
            measured = post_est if parsed.complete else None
        elif phase_name == "html_write":
            html_delta = timing_delta(timing, "glassdoor_end", "html_build")
            if html_delta is not None:
                measured = html_delta
            elif parsed.complete and "wrote" in parsed.marker_line:
                measured = 3.0
        elif phase_name == "rolling_backup":
            if "rolling_backup" in parsed.marker_line:
                measured = float(cfg["expected_sec"])
            elif parsed.complete:
                measured = 0.0
                notes = "silent (no Rolling backup line)"
        elif phase_name == "total_wall_clock":
            if total_timing is not None:
                measured = total_timing
            elif wall_sec is not None:
                measured = wall_sec
            elif parsed.scrape_elapsed_sec is not None and post_est is not None:
                measured = parsed.scrape_elapsed_sec + post_est
            elif running and parsed.heartbeats:
                measured = parsed.heartbeats[-1].elapsed_sec

        if phase_name == "http_per_company_p95" and measured is None:
            status = STATUS_SKIP
            delta = None
        elif phase_name == "startup" and measured is not None:
            status, delta = STATUS_OK, 0.0
        elif measured is None and running and phase_name in (
            "post_scrape",
            "html_write",
            "rolling_backup",
            "total_wall_clock",
        ):
            status = STATUS_RUNNING
            delta = None
        else:
            status, delta = classify(
                measured,
                expected,
                warn,
                stall,
                running=running and phase_name.startswith("http"),
            )

        results.append(
            PhaseResult(
                phase=phase_name,
                status=status,
                measured_sec=measured,
                expected_sec=expected,
                warn_sec=warn,
                stall_sec=stall,
                delta_sec=delta,
                notes=notes,
            )
        )

    scrape_cfg = phase_cfg.get("scrape_total") or {}
    expected_scrape = scaled_threshold(
        float(scrape_cfg.get("expected_sec") or 612),
        scale=bool(scrape_cfg.get("scale_with_companies")),
        company_count=company_co,
        baseline_count=baseline_co,
    )
    progress_extra = scrape_progress_status(parsed, expected_scrape)
    if progress_extra and running:
        results.append(progress_extra)

    hb_extra = heartbeat_rate_status(
        parsed,
        float(phase_cfg.get("http_per_company_p50", {}).get("expected_sec") or 2),
        float(phase_cfg.get("http_per_company_p95", {}).get("expected_sec") or 15),
    )
    if hb_extra and running:
        results.append(hb_extra)

    glassdoor_delta = timing_delta(timing, "glassdoor_start", "glassdoor_end")
    if glassdoor_delta is not None:
        gd_cfg = phase_cfg.get("post_scrape") or {}
        results.append(
            PhaseResult(
                phase="glassdoor_prefetch",
                status=STATUS_OK,
                measured_sec=glassdoor_delta,
                expected_sec=float(gd_cfg.get("expected_sec") or 30) * 0.4,
                warn_sec=float(gd_cfg.get("warn_sec") or 60) * 0.5,
                stall_sec=float(gd_cfg.get("stall_sec") or 120),
                delta_sec=None,
                notes="from [timing] glassdoor_start→glassdoor_end",
            )
        )

    return results


def worst_status(results: list[PhaseResult]) -> str:
    if any(r.status == STATUS_STALL for r in results):
        return STATUS_STALL
    if any(r.status == STATUS_WARN for r in results):
        return STATUS_WARN
    if any(r.status == STATUS_RUNNING for r in results):
        return STATUS_RUNNING
    return STATUS_OK


def exit_code_for(status: str) -> int:
    return {
        STATUS_OK: 0,
        STATUS_RUNNING: 0,
        STATUS_WARN: 1,
        STATUS_STALL: 2,
    }.get(status, 0)


def format_sec(value: float | None, *, ratio: bool = False) -> str:
    if value is None:
        return "-"
    if ratio:
        return f"{value:.2f}x"
    if value < 90:
        return f"{value:.1f}s"
    return f"{value / 60:.1f}m"


def print_report(
    parsed: ParsedLog,
    results: list[PhaseResult],
    *,
    log_label: str,
    verbose: bool,
) -> None:
    complete = "COMPLETE" if parsed.complete else "RUNNING"
    co = parsed.company_count if parsed.company_count is not None else "?"
    print(f"log: {log_label}")
    print(f"run: {complete}  companies: {co}  http: {parsed.http_count}  pw: {parsed.playwright_count}")
    if parsed.start_ts:
        print(f"started: {parsed.start_ts.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if parsed.scrape_elapsed_sec is not None:
        print(f"scrape elapsed (log): {format_sec(parsed.scrape_elapsed_sec)}")
    if parsed.timing_phases:
        keys = (
            "http_pool_end",
            "playwright_pool_end",
            "scrape_total",
            "dedupe",
            "glassdoor_end",
            "html_build",
            "write",
            "total",
        )
        parts = [
            f"{k}={parsed.timing_phases[k]:.1f}s"
            for k in keys
            if k in parsed.timing_phases
        ]
        if parts:
            print(f"[timing] splits: {', '.join(parts)}")
    print()
    print(f"{'phase':<24} {'status':<8} {'measured':>10} {'expected':>10} {'warn':>10} {'delta':>10}")
    print("-" * 78)
    for row in results:
        delta_s = "-" if row.delta_sec is None else f"{row.delta_sec:+.1f}s"
        is_ratio = row.phase in ("scrape_progress",)
        print(
            f"{row.phase:<24} {row.status:<8} "
            f"{format_sec(row.measured_sec, ratio=is_ratio):>10} "
            f"{format_sec(row.expected_sec, ratio=is_ratio):>10} "
            f"{format_sec(row.warn_sec, ratio=is_ratio):>10} {delta_s:>10}"
        )
        if verbose and row.notes:
            print(f"  {row.notes}")
    print()
    overall = worst_status(results)
    print(f"overall: {overall}")


def read_log_source(path: str | None, stream: TextIO) -> tuple[str, str, float | None]:
    if path and path != "-":
        p = Path(path).expanduser()
        text = p.read_text(encoding="utf-8", errors="replace")
        return str(p), text, p.stat().st_mtime
    text = stream.read()
    return "<stdin>", text, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare quickjobs run log timing against timing-baselines.yaml",
    )
    parser.add_argument(
        "log",
        nargs="?",
        help="Path to quickjobs-run-*.log (default: stdin, use '-' explicitly)",
    )
    parser.add_argument(
        "--baselines",
        type=Path,
        default=DEFAULT_BASELINES,
        help=f"Baselines YAML (default: {DEFAULT_BASELINES.name})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Include phase notes")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only print overall status line")
    args = parser.parse_args(argv)

    baselines = load_baselines(args.baselines.expanduser())
    label, text, mtime = read_log_source(args.log, sys.stdin)
    parsed = parse_log_text(text, file_mtime=mtime)
    results = measure_phases(parsed, baselines, file_mtime=mtime)
    overall = worst_status(results)

    if args.quiet:
        print(overall)
    else:
        print_report(parsed, results, log_label=label, verbose=args.verbose)

    return exit_code_for(overall)


if __name__ == "__main__":
    raise SystemExit(main())
