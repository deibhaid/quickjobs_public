#!/usr/bin/env python3
"""Shared paths and manual-careers list builder for quickjobs hub tooling."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent


def is_portable_layout() -> bool:
    """True when hub_tools.py lives in the flat portable package (next to quickjobs.py)."""
    return (_MODULE_DIR / "quickjobs.py").is_file()


def get_quickjobs_root() -> Path:
    """Package or repo root; honors QUICKJOBS_ROOT in portable layout."""
    if is_portable_layout():
        try:
            import portable_runtime as pr

            return pr.get_quickjobs_root()
        except ImportError:
            return Path(os.environ.get("QUICKJOBS_ROOT", str(_MODULE_DIR))).resolve()
    return _MODULE_DIR.parents[1]


HUBS_DIR = _MODULE_DIR
REPO_ROOT = get_quickjobs_root()

_SHARED_DIR = _MODULE_DIR.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
import config_bundle  # noqa: E402

if is_portable_layout():
    BASE_JSON = REPO_ROOT / "quickjobs.base.json"
    COMPANIES_JSON = REPO_ROOT / "quickjobs.companies.json"
    OUTPUT_ROOT = REPO_ROOT / "output"
    MANUAL_CAREERS_LEGACY = REPO_ROOT / "quickjobs.unconvertible-careers.json"
else:
    BASE_JSON = REPO_ROOT / "quickjobs.base.json"
    COMPANIES_JSON = REPO_ROOT / "quickjobs.companies.json"
    OUTPUT_ROOT = Path.home() / "ws/scriptdir/output"
    MANUAL_CAREERS_LEGACY = REPO_ROOT / "quickjobs.unconvertible-careers.json"


def load_base_bundle(base_path: Path | None = None) -> dict:
    """Merged base settings + companies catalog."""
    return config_bundle.load_base_bundle(base_path or BASE_JSON)


def save_base_bundle(merged: dict, base_path: Path | None = None) -> None:
    """Persist base settings and companies to split JSON files."""
    config_bundle.save_base_bundle(base_path or BASE_JSON, merged)

REPORTS_DIR = OUTPUT_ROOT / "quickjobs-reports"
JOURNAL_PATH = OUTPUT_ROOT / "quickjobs-hub-probe-journal.json"
DEFERRED_PATH = OUTPUT_ROOT / "quickjobs-deferred-hubs.json"
BLOCKED_TSV = REPORTS_DIR / "quickjobs-blocked-sources.tsv"
MANUAL_CAREERS_OUTPUT = OUTPUT_ROOT / "quickjobs-manual-careers.json"
MANUAL_CAREERS_TSV = REPORTS_DIR / "quickjobs-unconvertible-careers.tsv"


def report_path(name: str) -> Path:
    """Hub/discovery TSV and log outputs (not runtime sidecar data)."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR / name

MANUAL_CAREERS_INTRO = (
    "Employers with no workable public scrape API from this network (no VPN). "
    "Links are the marketing careers site, not Workday. Hidden by default."
)

MANUAL_CAREERS_URLS: dict[str, str] = {
    "blue-origin": "https://www.blueorigin.com/careers",
    "citadel": "https://www.citadel.com/careers/",
    "coinbase": "https://www.coinbase.com/careers",
    "epic": "https://careers.epic.com/",
    "goldman-sachs": "https://www.goldmansachs.com/careers/",
    "goldman-sachs-wd": "https://www.goldmansachs.com/careers/",
    "hashicorp": "https://www.hashicorp.com/en/careers",
    "precision-castparts": "https://www.precast.com/en/careers",
    "progressive": "https://www.progressive.com/careers/",
    "saic": "https://www.saic.com/careers",
}


def manual_careers_load_paths() -> list[Path]:
    """Prefer generated output; keep legacy repo copy for backward compatibility."""
    paths: list[Path] = []
    if MANUAL_CAREERS_OUTPUT.is_file():
        paths.append(MANUAL_CAREERS_OUTPUT)
    if MANUAL_CAREERS_LEGACY.is_file() and MANUAL_CAREERS_LEGACY not in paths:
        paths.append(MANUAL_CAREERS_LEGACY)
    return paths


def ensure_manual_careers_migrated() -> None:
    """One-time copy legacy JSON into output/ when output is missing."""
    if MANUAL_CAREERS_OUTPUT.is_file() or not MANUAL_CAREERS_LEGACY.is_file():
        return
    MANUAL_CAREERS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_CAREERS_OUTPUT.write_text(
        MANUAL_CAREERS_LEGACY.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def load_journal_by_id() -> dict[str, dict]:
    if not JOURNAL_PATH.is_file():
        return {}
    data = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for cid, rec in (data.get("employers") or {}).items():
        if isinstance(rec, dict):
            out[str(cid)] = rec
    return out


def public_careers_url(entry: dict, blocked: dict | None) -> str:
    cid = str(entry.get("id") or "")
    for raw in (
        entry.get("careers_url"),
        MANUAL_CAREERS_URLS.get(cid),
        entry.get("hub_url"),
        (blocked or {}).get("guess_public_careers"),
        entry.get("browse_url"),
    ):
        u = str(raw or "").strip()
        if not u or "myworkdayjobs.com" in u.lower():
            continue
        return u
    return ""


def note_for(entry: dict, blocked: dict | None, journal_row: dict | None = None) -> str:
    if journal_row and str(journal_row.get("probe_note") or "").strip():
        return str(journal_row["probe_note"]).strip()
    if str(entry.get("probe_note") or "").strip():
        return str(entry["probe_note"]).strip()
    if str(entry.get("note") or "").strip():
        return str(entry["note"]).strip()
    hub_note = str(entry.get("hub_note") or "").strip()
    if hub_note:
        return hub_note.replace("Public ATS: unknown — ", "").strip() or hub_note
    if blocked and "422" in str(blocked.get("search_note") or ""):
        return "No public HTTP scrape API; Workday CXS blocked off-VPN"
    return "No public HTTP scrape API — manual search on careers site"


def load_manual_career_entries() -> list[dict]:
    blocked_by_id: dict[str, dict] = {}
    if BLOCKED_TSV.is_file():
        for row in csv.DictReader(BLOCKED_TSV.open(), delimiter="\t"):
            blocked_by_id[row["id"]] = row

    by_id: dict[str, dict] = {}
    if DEFERRED_PATH.is_file():
        data = json.loads(DEFERRED_PATH.read_text(encoding="utf-8"))
        for entry in data.get("deferred_hubs") or []:
            if entry.get("id"):
                by_id[str(entry["id"])] = dict(entry)

    base = load_base_bundle() if BASE_JSON.is_file() else {}
    for co in base.get("companies") or []:
        if str(co.get("type") or "").lower() != "hub" or not co.get("id"):
            continue
        cid = str(co["id"])
        if cid in by_id:
            merged = dict(co)
            merged.update(by_id[cid])
            by_id[cid] = merged
        else:
            by_id[cid] = dict(co)

    journal_by_id = load_journal_by_id()
    out: list[dict] = []
    for cid in sorted(by_id):
        entry = by_id[cid]
        blocked = blocked_by_id.get(cid)
        journal_row = journal_by_id.get(cid)
        url = public_careers_url(entry, blocked)
        if journal_row and str(journal_row.get("careers_url") or "").strip():
            url = str(journal_row["careers_url"]).strip()
        tests = list((journal_row or {}).get("tests") or entry.get("probe_tests") or [])
        if not tests and url:
            tests = [
                {
                    "url": url,
                    "http_code": "",
                    "methods": [],
                    "note": "seed careers_url only; run quickjobs_hubs.py probe --probe-missing",
                }
            ]
        row = {
            "id": cid,
            "name": str(entry.get("name") or cid),
            "label": str(entry.get("label") or entry.get("name") or cid),
            "careers_url": url,
            "note": note_for(entry, blocked, journal_row),
            "section": str(entry.get("section") or "matching"),
            "probe_tests": tests,
        }
        if journal_row:
            row["last_probed_at"] = journal_row.get("last_probed_at")
            row["probe_outcome"] = journal_row.get("outcome")
        elif entry.get("probe_outcome"):
            row["probe_outcome"] = entry.get("probe_outcome")
        if entry.get("probe_journal_at"):
            row["last_probed_at"] = entry.get("probe_journal_at")
        out.append(row)
    return out


def rebuild_manual_careers(
    *,
    json_path: Path | None = None,
    tsv_path: Path | None = None,
    mirror_legacy: bool = True,
) -> int:
    """Write manual careers JSON (+ TSV). Returns employer count."""
    json_out = json_path or MANUAL_CAREERS_OUTPUT
    tsv_out = tsv_path or MANUAL_CAREERS_TSV
    employers = load_manual_career_entries()
    missing_url = [e["id"] for e in employers if not e["careers_url"]]
    payload = {
        "intro": MANUAL_CAREERS_INTRO,
        "employers": employers,
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    json_out.write_text(text, encoding="utf-8")
    if mirror_legacy and json_out != MANUAL_CAREERS_LEGACY:
        MANUAL_CAREERS_LEGACY.write_text(text, encoding="utf-8")

    tsv_out.parent.mkdir(parents=True, exist_ok=True)
    tsv_fields = [
        "id",
        "name",
        "label",
        "careers_url",
        "note",
        "section",
        "last_probed_at",
        "probe_outcome",
    ]
    with tsv_out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=tsv_fields, delimiter="\t")
        writer.writeheader()
        for row in employers:
            writer.writerow({k: row.get(k, "") for k in tsv_fields})

    print(f"Wrote {json_out} ({len(employers)} employers)")
    print(f"Wrote {tsv_out}")
    if missing_url:
        print(f"Missing public careers URL ({len(missing_url)}): {', '.join(missing_url)}")
    return len(employers)


def hub_count() -> int:
    if not BASE_JSON.is_file():
        return 0
    cfg = load_base_bundle()
    return sum(
        1
        for c in cfg.get("companies") or []
        if str(c.get("type") or "").lower() == "hub"
    )


def discovered_hub_url_lookup() -> dict[str, str]:
    """Best public careers URL per hub id (journal, manual list, known overrides)."""
    lookup: dict[str, str] = {}
    for cid, url in MANUAL_CAREERS_URLS.items():
        u = str(url or "").strip()
        if u and "myworkdayjobs.com" not in u.lower():
            lookup[cid] = u

    if MANUAL_CAREERS_OUTPUT.is_file():
        data = json.loads(MANUAL_CAREERS_OUTPUT.read_text(encoding="utf-8"))
        for entry in data.get("employers") or []:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            cid = str(entry["id"])
            u = str(entry.get("careers_url") or "").strip()
            if u and "myworkdayjobs.com" not in u.lower():
                lookup[cid] = u

    for cid, row in load_journal_by_id().items():
        u = str(row.get("careers_url") or "").strip()
        if u and "myworkdayjobs.com" not in u.lower():
            lookup[cid] = u

    return lookup


def apply_discovered_hub_urls(*, apply: bool = False) -> list[str]:
    """Set hub_url on manual hubs that are missing it (from probe journal / manual list)."""
    if not BASE_JSON.is_file():
        return []
    base = load_base_bundle()
    lookup = discovered_hub_url_lookup()
    log: list[str] = []
    for company in base.get("companies") or []:
        if str(company.get("type") or "").lower() != "hub":
            continue
        if str(company.get("hub_url") or "").strip():
            continue
        cid = str(company.get("id") or "")
        url = lookup.get(cid)
        if not url:
            continue
        company["hub_url"] = url
        log.append(f"hub_url: {cid} -> {url}")

    if apply and log:
        save_base_bundle(base)
    return log
