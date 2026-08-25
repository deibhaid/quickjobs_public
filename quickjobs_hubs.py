#!/usr/bin/env python3
"""Unified CLI for index hub conversion, discovery, probe journal, and manual careers list."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent


def _is_portable_layout() -> bool:
    return (_MODULE_DIR / "quickjobs.py").is_file()


if _is_portable_layout():
    REPO_ROOT = Path(os.environ.get("QUICKJOBS_ROOT", str(_MODULE_DIR))).resolve()
    HUBS_DIR = REPO_ROOT
    PY = Path(
        os.environ.get(
            "QUICKJOBS_PYTHON",
            str(REPO_ROOT / "python_venv" / "bin" / "python"),
        )
    )
    REPORTS_DIR = REPO_ROOT / "output" / "quickjobs-reports"
else:
    REPO_ROOT = _MODULE_DIR
    HUBS_DIR = REPO_ROOT / "scripts" / "hubs"
    PY = Path.home() / ".v/bin/python"
    REPORTS_DIR = Path.home() / "ws/scriptdir/output/quickjobs-reports"

sys.path.insert(0, str(HUBS_DIR))
LOG_CONVERSION = REPORTS_DIR / "quickjobs-index-hub-conversion.log"
LOG_PROBE = REPORTS_DIR / "quickjobs-probe-all-hidden.log"


def _run_module(script: str, argv: list[str]) -> int:
    path = HUBS_DIR / script
    proc = subprocess.run([str(PY), str(path), *argv], cwd=str(REPO_ROOT))
    return int(proc.returncode or 0)


def cmd_convert(argv: list[str]) -> int:
    return _run_module("batch_convert_hubs.py", argv)


def cmd_discover(argv: list[str]) -> int:
    return _run_module("discover_hub_ats_paths.py", argv)


def cmd_probe(argv: list[str]) -> int:
    return _run_module("hub_probe_journal.py", argv)


def cmd_sync_manual(_argv: list[str]) -> int:
    import hub_probe_journal as journal
    import hub_tools

    n = journal.sync_deferred_from_journal()
    print(f"Wrote {journal.DEFERRED_PATH} ({n} deferred hubs)")
    hub_tools.rebuild_manual_careers()
    return 0


def cmd_apply_hub_urls(argv: list[str]) -> int:
    return _run_module("apply_discovered_hub_urls.py", argv)


def cmd_build_manual(argv: list[str]) -> int:
    return _run_module("build_unconvertible_careers_list.py", argv)


def cmd_refresh_index(argv: list[str]) -> int:
    return _run_module("refresh_index_hub_careers_urls.py", argv)


def cmd_fingerprint(argv: list[str]) -> int:
    return _run_module("fingerprint_hub_ats.py", argv)


def cmd_career_endpoints(argv: list[str]) -> int:
    return _run_module("discover_career_endpoints.py", argv)


def cmd_scrape_probe(argv: list[str]) -> int:
    return _run_module("probe_hub_scrape_methods.py", argv)


def cmd_normalize(argv: list[str]) -> int:
    return _run_module("normalize_manual_hubs.py", argv)


def cmd_add_index(argv: list[str]) -> int:
    return _run_module("add_index_company_hubs.py", argv)


def cmd_add_it_platform(argv: list[str]) -> int:
    return _run_module("add_it_platform_companies.py", argv)


def cmd_add_aviation(argv: list[str]) -> int:
    return _run_module("add_aviation_pilot_companies.py", argv)


def cmd_loop_conversion(_argv: list[str]) -> int:
    import hub_tools

    chunk = 35
    workers = 14
    hub_tools.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_CONVERSION
    round_no = 0
    no_progress = 0

    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"=== quickjobs_hubs loop conversion start ===\n")
        fh.flush()
        while True:
            n = hub_tools.hub_count()
            if n == 0:
                break
            round_no += 1
            off = ((round_no - 1) * chunk) % n
            fh.write(f"--- round {round_no}: {n} hubs remaining (offset {off}) ---\n")
            fh.flush()
            subprocess.run(
                [str(PY), str(HUBS_DIR / "batch_convert_hubs.py"),
                 "--workers", str(workers), "--limit", str(chunk),
                 "--offset", str(off), "--apply"],
                cwd=str(REPO_ROOT),
            )
            n_mid = hub_tools.hub_count()
            subprocess.run(
                [str(PY), str(HUBS_DIR / "discover_hub_ats_paths.py"),
                 "--workers", str(workers), "--limit", str(chunk),
                 "--offset", str(off), "--apply"],
                cwd=str(REPO_ROOT),
            )
            n_after = hub_tools.hub_count()
            if n_after < n:
                no_progress = 0
                fh.write(f"round {round_no}: converted {n - n_after} (now {n_after} hubs)\n")
            else:
                no_progress += 1
                fh.write(f"round {round_no}: no conversions ({no_progress} idle rounds)\n")
            fh.flush()
            subprocess.run(
                [str(PY), str(HUBS_DIR / "hub_probe_journal.py"),
                 "--probe-missing", "--workers", "8", "--limit", "10",
                 "--offset", str(off)],
                cwd=str(REPO_ROOT),
            )
            subprocess.run(
                [str(PY), str(HUBS_DIR / "hub_probe_journal.py"), "--sync-all"],
                cwd=str(REPO_ROOT),
            )
            cycles = (n + chunk - 1) // chunk
            if no_progress >= cycles:
                fh.write(
                    f"=== stopping: no conversions for {no_progress} rounds (full cycle) ===\n"
                )
                break
        fh.write(f"=== done; hubs left: {hub_tools.hub_count()} ===\n")
    print(f"Conversion loop log: {log}")
    return 0


def cmd_loop_probe_hidden(_argv: list[str]) -> int:
    sys.path.insert(0, str(HUBS_DIR))
    import hub_probe_journal as journal
    import hub_tools

    hub_tools.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    chunk = 25
    workers = 12
    log = LOG_PROBE
    round_no = 0

    def missing_count() -> int:
        journal_data = journal.load_journal()
        return sum(
            1
            for co in journal.load_all_hidden_hub_companies()
            if not journal.journal_is_complete(
                (journal_data.get("employers") or {}).get(str(co.get("id") or ""))
            )
        )

    with log.open("a", encoding="utf-8") as fh:
        fh.write("=== quickjobs_hubs loop probe-hidden start ===\n")
        fh.flush()
        while True:
            n = missing_count()
            if n == 0:
                break
            round_no += 1
            off = ((round_no - 1) * chunk) % n
            fh.write(f"--- probe round {round_no}: {n} hubs need journal (offset {off}) ---\n")
            fh.flush()
            subprocess.run(
                [str(PY), str(HUBS_DIR / "hub_probe_journal.py"),
                 "--probe-missing", "--workers", str(workers),
                 "--limit", str(chunk), "--offset", str(off)],
                cwd=str(REPO_ROOT),
            )
            subprocess.run(
                [str(PY), str(HUBS_DIR / "hub_probe_journal.py"), "--sync-all"],
                cwd=str(REPO_ROOT),
            )
        fh.write(f"=== done; missing={missing_count()} ===\n")
    print(f"Probe loop log: {log}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=not argv)

    sub.add_parser("convert", help="Batch probe hubs and apply HTTP conversions")
    sub.add_parser("discover", help="Deep ATS discovery on hub URLs")
    sub.add_parser("probe", help="Hub probe journal (pass through flags)")
    sub.add_parser("sync-manual", help="Sync deferred hubs and rebuild manual careers JSON")
    sub.add_parser(
        "apply-hub-urls",
        help="Copy probed careers URLs into hub_url on base.json (pass --apply)",
    )
    sub.add_parser(
        "loop-conversion",
        help="Rotate batch convert + discover until idle (append log)",
    )
    sub.add_parser(
        "loop-probe-hidden",
        help="Probe all hidden hubs missing journal entries",
    )
    sub.add_parser("build-manual", help="Rebuild quickjobs-manual-careers.json")
    sub.add_parser("refresh-index", help="Refresh index hub careers URLs")
    sub.add_parser("fingerprint", help="Fingerprint hub ATS types")
    sub.add_parser("career-endpoints", help="Discover public career endpoints")
    sub.add_parser("scrape-probe", help="Probe scrape methods per hub")
    sub.add_parser("normalize", help="Normalize manual hub entries")
    sub.add_parser("add-index", help="Bulk-add index company hubs")
    sub.add_parser("add-it-platform", help="Add IT/platform employers")
    sub.add_parser("add-aviation", help="Add aviation pilot employers")

    if not argv:
        parser.print_help()
        return 1

    cmd, rest = argv[0], argv[1:]
    handlers = {
        "convert": cmd_convert,
        "discover": cmd_discover,
        "probe": cmd_probe,
        "sync-manual": cmd_sync_manual,
        "apply-hub-urls": cmd_apply_hub_urls,
        "loop-conversion": cmd_loop_conversion,
        "loop-probe-hidden": cmd_loop_probe_hidden,
        "build-manual": cmd_build_manual,
        "refresh-index": cmd_refresh_index,
        "fingerprint": cmd_fingerprint,
        "career-endpoints": cmd_career_endpoints,
        "scrape-probe": cmd_scrape_probe,
        "normalize": cmd_normalize,
        "add-index": cmd_add_index,
        "add-it-platform": cmd_add_it_platform,
        "add-aviation": cmd_add_aviation,
    }
    if cmd not in handlers:
        parser.print_help()
        return 1
    if cmd in ("loop-conversion", "loop-probe-hidden", "sync-manual"):
        return handlers[cmd]([])
    return handlers[cmd](rest)


if __name__ == "__main__":
    raise SystemExit(main())
