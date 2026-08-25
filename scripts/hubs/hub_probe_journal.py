#!/usr/bin/env python3
"""Record hub probe attempts and sync non-working hubs to deferred / unconvertible lists.

Journal: ~/ws/scriptdir/output/quickjobs-hub-probe-journal.json
Deferred: ~/ws/scriptdir/output/quickjobs-deferred-hubs.json
Rebuild: quickjobs.unconvertible-careers.json via build_unconvertible_careers_list.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import hub_tools

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

JOURNAL_PATH = hub_tools.JOURNAL_PATH
DEFERRED_PATH = hub_tools.DEFERRED_PATH
BLOCKED_TSV = hub_tools.BLOCKED_TSV
BUILD_UNCONV = hub_tools.HUBS_DIR / "build_unconvertible_careers_list.py"
MAX_TESTS_STORED = 48
MAX_NOTE_CHARS = 4000
MIN_TESTS_FOR_COMPLETE = 3
_WRITE_LOCK = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_journal() -> dict[str, Any]:
    if not JOURNAL_PATH.is_file():
        return {"version": 1, "updated_at": "", "employers": {}}
    data = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
    data.setdefault("employers", {})
    return data


def save_journal(data: dict[str, Any]) -> None:
    data["updated_at"] = _now_iso()
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _dedupe_tests(tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for t in tests:
        url = str(t.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(t)
        if len(out) >= MAX_TESTS_STORED:
            break
    return out


def _pick_careers_url(
    co: dict[str, Any],
    tests: list[dict[str, Any]],
) -> str:
    for t in reversed(tests):
        if int(t.get("http_code") or 0) == 200:
            u = str(t.get("final_url") or t.get("url") or "").strip()
            if u and "myworkdayjobs.com" not in u.lower():
                return u
    hub = str(co.get("hub_url") or "").strip()
    if hub and "myworkdayjobs.com" not in hub.lower():
        return hub
    for t in tests:
        u = str(t.get("url") or "").strip()
        if u and "myworkdayjobs.com" not in u.lower():
            return u
    return hub


def format_probe_note(
    tests: list[dict[str, Any]],
    outcome: str,
    method: str = "",
    source: str = "",
) -> str:
    parts = [f"Last probe {_now_iso()[:10]} ({source or 'probe'}): {outcome}"]
    if method:
        parts[0] += f" via {method}"
    shown = 0
    for t in tests:
        if shown >= 16:
            parts.append(f"+{len(tests) - shown} more URLs in probe_tests (journal JSON)")
            break
        url = str(t.get("url") or "")
        if len(url) > 72:
            url = url[:69] + "..."
        code = t.get("http_code", "?")
        methods = t.get("methods") or []
        m = ",".join(methods) if methods else str(t.get("note") or "no ATS match")
        parts.append(f"  {url} -> HTTP {code} ({m})")
        shown += 1
    text = "\n".join(parts)
    return text[:MAX_NOTE_CHARS]


def record_probe(
    co: dict[str, Any],
    *,
    outcome: str,
    tests: list[dict[str, Any]],
    source: str,
    method: str = "",
    status: str = "",
    apply: str = "no",
    config_hint: str = "",
    url_tested: str = "",
    error: str = "",
) -> None:
    cid = str(co.get("id") or "").strip()
    if not cid:
        return
    tests = _dedupe_tests(tests)
    careers_url = _pick_careers_url(co, tests)
    with _WRITE_LOCK:
        data = load_journal()
        employers = data["employers"]
        prev = employers.get(cid) if isinstance(employers.get(cid), dict) else {}
        merged_tests = _dedupe_tests(
            list(prev.get("tests") or []) + tests
        )
        employers[cid] = {
            "id": cid,
            "name": str(co.get("name") or cid),
            "hub_url": str(co.get("hub_url") or ""),
            "careers_url": careers_url,
            "index_tag": _index_tag(co),
            "last_probed_at": _now_iso(),
            "last_source": source,
            "outcome": outcome,
            "method": method,
            "status": status,
            "apply": apply,
            "config_hint": config_hint,
            "url_tested": url_tested,
            "error": error,
            "tests": merged_tests,
            "probe_note": format_probe_note(merged_tests, outcome, method, source),
        }
        save_journal(data)


def _index_tag(co: dict[str, Any]) -> str:
    note = str(co.get("hub_note") or "")
    if "Nasdaq" in note:
        return "Nasdaq-100"
    if "S&P" in note or "S&P 500" in note:
        return "S&P 500"
    return ""


def _seed_only_tests(co: dict[str, Any]) -> list[dict[str, Any]]:
    url = str(co.get("hub_url") or "").strip()
    if not url:
        return []
    return [
        {
            "url": url,
            "http_code": "",
            "final_url": url,
            "methods": [],
            "note": "seed hub_url only; full discover probe not run yet",
        }
    ]


def _enrich_entry_from_journal(entry: dict[str, Any], rec: dict[str, Any] | None) -> None:
    url = str(
        (rec or {}).get("careers_url")
        or (rec or {}).get("hub_url")
        or entry.get("hub_url")
        or ""
    ).strip()
    if url:
        entry["hub_url"] = url
    if rec and journal_is_complete(rec):
        note = str(rec.get("probe_note") or "").strip()
        if note:
            entry["hub_note"] = note
            entry["probe_note"] = note
        entry["probe_journal_at"] = rec.get("last_probed_at")
        entry["probe_outcome"] = rec.get("outcome")
        entry["last_source"] = rec.get("last_source")
        entry["probe_tests"] = list(rec.get("tests") or [])
        return
    if rec:
        note = str(rec.get("probe_note") or "").strip()
        if note:
            entry["hub_note"] = note
            entry["probe_note"] = note
        entry["probe_journal_at"] = rec.get("last_probed_at")
        entry["probe_outcome"] = rec.get("outcome") or "partial_probe"
        entry["last_source"] = rec.get("last_source")
        entry["probe_tests"] = list(rec.get("tests") or []) or _seed_only_tests(entry)
        return
    seed = _seed_only_tests(entry)
    pending = (
        f"Pending full discover probe. Seed careers URL: {entry.get('hub_url') or '(none)'}"
    )
    entry["hub_note"] = pending
    entry["probe_note"] = pending
    entry["probe_outcome"] = "pending_probe"
    entry["probe_tests"] = seed


def journal_is_complete(rec: dict[str, Any] | None) -> bool:
    if not rec or not isinstance(rec, dict):
        return False
    tests = rec.get("tests") or []
    if len(tests) < MIN_TESTS_FOR_COMPLETE:
        return False
    seed_note = "seed hub_url only"
    if all(seed_note in str(t.get("note") or "") for t in tests):
        return False
    return True


def load_all_hidden_hub_companies() -> list[dict[str, Any]]:
    """Every hidden hub: base type=hub + deferred file + existing unconvertible list."""
    by_id: dict[str, dict[str, Any]] = {}
    unconv_path = hub_tools.REPO_ROOT / "quickjobs.unconvertible-careers.json"
    if BASE.is_file():
        for co in hub_tools.load_base_bundle().get("companies") or []:
            if str(co.get("type") or "").lower() == "hub" and co.get("id"):
                by_id[str(co["id"])] = dict(co)
    if DEFERRED_PATH.is_file():
        for entry in json.loads(DEFERRED_PATH.read_text(encoding="utf-8")).get("deferred_hubs") or []:
            if entry.get("id"):
                cid = str(entry["id"])
                merged = dict(by_id.get(cid) or {})
                merged.update(entry)
                by_id[cid] = merged
    if unconv_path.is_file():
        for entry in json.loads(unconv_path.read_text(encoding="utf-8")).get("employers") or []:
            if not entry.get("id"):
                continue
            cid = str(entry["id"])
            if cid in by_id:
                continue
            by_id[cid] = {
                "id": cid,
                "name": entry.get("name") or cid,
                "hub_url": entry.get("careers_url") or "",
                "section": entry.get("section") or "matching",
                "type": "hub",
            }
    return list(by_id.values())


def probe_hidden_hubs(
    *,
    workers: int = 10,
    limit: int = 0,
    offset: int = 0,
    only_missing: bool = True,
) -> tuple[int, int]:
    """Run discover_company on hidden hubs; journal is updated per employer."""
    sys.path.insert(0, str(hub_tools.HUBS_DIR))
    import discover_hub_ats_paths as discover  # noqa: E402

    companies = load_all_hidden_hub_companies()
    journal = load_journal().get("employers") or {}
    if only_missing:
        companies = [
            co
            for co in companies
            if not journal_is_complete(
                journal.get(str(co.get("id") or ""))
                if isinstance(journal.get(str(co.get("id") or "")), dict)
                else None
            )
        ]
    total = len(companies)
    if offset:
        off = offset % max(total, 1)
        companies = companies[off:] + companies[:off]
    if limit > 0:
        companies = companies[:limit]
    if not companies:
        print("No hidden hubs need probing.")
        return 0, 0

    blocked: dict[str, dict] = {}
    blocked_tsv = hub_tools.BLOCKED_TSV
    if blocked_tsv.is_file():
        import csv

        for row in csv.DictReader(blocked_tsv.open(), delimiter="\t"):
            blocked[row["id"]] = row

    print(
        f"Probing {len(companies)} hidden hubs (of {total} eligible, workers={workers})…",
        flush=True,
    )
    done = 0
    converted = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {
            pool.submit(
                discover.discover_company, co, blocked.get(str(co.get("id") or ""))
            ): co
            for co in companies
        }
        for fut in as_completed(futs):
            co = futs[fut]
            done += 1
            cid = str(co.get("id") or "")
            try:
                row = fut.result()
                if row.apply == "yes":
                    converted += 1
                print(
                    f"  [{done}/{len(companies)}] {cid}: "
                    f"{row.recommended_type or 'no API'} ({len(row.tests or [])} urls logged)",
                    flush=True,
                )
            except Exception as exc:
                record_probe(
                    co,
                    outcome="probe_error",
                    tests=_seed_only_tests(co),
                    source="discover",
                    error=str(exc)[:200],
                )
                print(f"  [{done}/{len(companies)}] {cid}: error ({exc})", flush=True)
    return done, converted


def sync_deferred_from_journal(
    *,
    only_unresolved: bool = True,
    include_all_hubs_in_base: bool = True,
) -> int:
    """Write quickjobs-deferred-hubs.json; every entry gets probe_note + probe_tests."""
    journal = load_journal()
    journal_employers = journal.get("employers") or {}
    by_id: dict[str, dict[str, Any]] = {}

    for co in load_all_hidden_hub_companies():
        cid = str(co.get("id") or "")
        if cid:
            by_id[cid] = dict(co)

    if include_all_hubs_in_base and BASE.is_file():
        for co in hub_tools.load_base_bundle().get("companies") or []:
            if str(co.get("type") or "").lower() == "hub" and co.get("id"):
                by_id[str(co["id"])] = dict(co)

    for cid, rec in journal_employers.items():
        if not isinstance(rec, dict):
            continue
        if only_unresolved and rec.get("apply") == "yes":
            continue
        if only_unresolved and rec.get("outcome") == "converted":
            continue
        entry = by_id.get(cid) or {
            "id": cid,
            "name": rec.get("name") or cid,
            "section": "hubs",
            "type": "hub",
        }
        _enrich_entry_from_journal(entry, rec)
        by_id[cid] = entry

    for cid, entry in list(by_id.items()):
        rec = journal_employers.get(cid) if isinstance(journal_employers.get(cid), dict) else None
        if only_unresolved and rec and rec.get("apply") == "yes":
            continue
        _enrich_entry_from_journal(entry, rec)
        if not entry.get("probe_tests"):
            entry["probe_tests"] = _seed_only_tests(entry)
        by_id[cid] = entry

    deferred = sorted(by_id.values(), key=lambda e: str(e.get("name") or e.get("id")).lower())
    payload = {"deferred_hubs": deferred, "updated_at": _now_iso()}
    DEFERRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFERRED_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return len(deferred)


def rebuild_unconvertible() -> int:
    import hub_tools

    return hub_tools.rebuild_manual_careers()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record-from-discovery-tsv",
        type=Path,
        help="Import latest discover TSV (id, url_tested, method, apply, error)",
    )
    parser.add_argument(
        "--sync-deferred",
        action="store_true",
        help="Refresh quickjobs-deferred-hubs.json from journal + base hubs",
    )
    parser.add_argument(
        "--rebuild-unconvertible",
        action="store_true",
        help="Run build_unconvertible_careers_list.py",
    )
    parser.add_argument(
        "--sync-all",
        action="store_true",
        help="Sync deferred then rebuild unconvertible careers JSON",
    )
    parser.add_argument(
        "--probe-all",
        action="store_true",
        help="Discover-probe every hidden hub (rewrites journal per employer)",
    )
    parser.add_argument(
        "--probe-missing",
        action="store_true",
        help="Discover-probe hidden hubs without a complete journal yet",
    )
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    if args.record_from_discovery_tsv and args.record_from_discovery_tsv.is_file():
        import csv

        base_by_id = {}
        if BASE.is_file():
            for co in hub_tools.load_base_bundle().get("companies") or []:
                if co.get("id"):
                    base_by_id[str(co["id"])] = co
        with args.record_from_discovery_tsv.open() as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                cid = row.get("id") or ""
                co = base_by_id.get(cid) or {"id": cid, "name": row.get("name") or cid}
                record_probe(
                    co,
                    outcome="converted" if row.get("apply") == "yes" else "no_handler",
                    tests=[
                        {
                            "url": row.get("url_tested") or co.get("hub_url") or "",
                            "http_code": 200 if row.get("apply") == "yes" else "",
                            "methods": [row.get("method") or "none"],
                            "note": row.get("error") or row.get("notes") or "",
                        }
                    ],
                    source="discover_tsv_import",
                    method=row.get("method") or "",
                    status=row.get("status") or "",
                    apply=row.get("apply") or "no",
                    config_hint=row.get("config_hint") or "",
                    url_tested=row.get("url_tested") or "",
                    error=row.get("error") or "",
                )

    if args.probe_all or args.probe_missing:
        done, converted = probe_hidden_hubs(
            workers=args.workers,
            limit=args.limit,
            offset=args.offset,
            only_missing=not args.probe_all,
        )
        print(f"Probed {done} hidden hubs ({converted} scrape-ready)")

    if args.sync_deferred or args.sync_all:
        n = sync_deferred_from_journal()
        print(f"Wrote {DEFERRED_PATH} ({n} deferred hubs)")

    if args.rebuild_unconvertible or args.sync_all:
        n = rebuild_unconvertible()
        print(f"Unconvertible employers: {n}")

    if args.probe_all or args.probe_missing:
        sync_deferred_from_journal()
        rebuild_unconvertible()

    if not any(
        (
            args.record_from_discovery_tsv,
            args.sync_deferred,
            args.rebuild_unconvertible,
            args.sync_all,
            args.probe_all,
            args.probe_missing,
        )
    ):
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
