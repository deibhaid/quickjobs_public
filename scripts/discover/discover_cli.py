#!/usr/bin/env python3
"""quickjobs discover / discover-sync / validate CLI (dev machine only).

Wraps the employer-catalog miners under scripts/{dice,hn,builtin}/ and can
append conservative API-scrapable direct employers to quickjobs.base.json.

Candidate source for discover-sync: the newest dated report JSON per source
(``<source>-new-candidates-YYYY-MM-DD.json`` under OUTPUT_DIR), field
``all_api_scrapable_direct_not_in_base``. Falls back to the persistent catalog
only when no report file exists.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
SHARED_DIR = REPO_ROOT / "scripts" / "_shared"
OUTPUT_DIR = Path.home() / "ws" / "scriptdir" / "output"
DEFAULT_BASE = REPO_ROOT / "quickjobs.base.json"
DEFAULT_PROFILE = REPO_ROOT / "quickjobs.profile.json"
PYTHON = Path.home() / ".v" / "bin" / "python"
MAIN_PY = REPO_ROOT / "quickjobs.py"

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
import discovery_common as dc  # noqa: E402
import config_backup  # noqa: E402
import config_bundle  # noqa: E402

SOURCES = ("dice", "hn", "builtin")

MINER_SCRIPTS: dict[str, Path] = {
    "dice": REPO_ROOT / "scripts" / "dice" / "discover_dice_employers.py",
    "hn": REPO_ROOT / "scripts" / "hn" / "discover_hn_employers.py",
    "builtin": REPO_ROOT / "scripts" / "builtin" / "discover_builtin_employers.py",
}

REPORT_GLOBS: dict[str, str] = {
    "dice": "dice-new-candidates-*.json",
    "hn": "hn-new-candidates-*.json",
    "builtin": "builtin-new-candidates-*.json",
}

CATALOG_PATHS: dict[str, Path] = {
    "dice": OUTPUT_DIR / "dice-employer-catalog.json",
    "hn": OUTPUT_DIR / "hn-employer-catalog.json",
    "builtin": OUTPUT_DIR / "builtin-employer-catalog.json",
}

# Default discover miner args: widest net, API fingerprint for dice (omit posted_date).
DEFAULT_DISCOVER_ARGS: dict[str, list[str]] = {
    "dice": ["--fingerprint", "api"],
    "hn": ["--fingerprint", "api"],
    "builtin": ["--fingerprint", "api", "--pages", "5"],
}

DEFAULT_SEARCH_KEYWORDS = [
    "devops",
    "devops engineer",
    "site reliability engineer",
    "sre",
    "platform engineer",
    "platform engineering",
    "infrastructure engineer",
    "cloud engineer",
    "cloud operations",
    "systems engineer",
    "production engineer",
    "release engineer",
    "principal engineer",
    "staff engineer",
    "software engineer",
    "observability",
    "terraform",
    "kubernetes",
]

# Required company fields per ATS type (beyond id, name, label, type, browse_url).
TYPE_REQUIRED: dict[str, tuple[str, ...]] = {
    "greenhouse": ("board",),
    "ashby": ("ashby_board",),
    "lever": ("lever_site",),
    "smartrecruiters": ("smartrecruiters_id",),
    "icims": ("search_url_template",),
    "phenom": ("phenom_base", "phenom_refnum"),
    "oracle_hcm": ("oracle_api_base", "oracle_site_number"),
    "json_feed": ("json_url", "json_variant"),
    "taleo_cws": ("taleo_org", "taleo_cws"),
    "successfactors": ("search_base", "site_origin"),
}


def _python() -> str:
    return str(PYTHON if PYTHON.is_file() else Path(sys.executable))


def backup_config_bundle(base_path: Path) -> list[Path]:
    """Rolling backups for base + companies (7-day retention)."""
    return config_backup.rolling_backup_bundle(base_path, retention_days=config_backup.DEFAULT_RETENTION_DAYS)


def latest_report_json(source: str) -> Path | None:
    pattern = REPORT_GLOBS[source]
    matches = sorted(OUTPUT_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def candidates_from_catalog(source: str) -> list[dict[str, Any]]:
    """Fallback: derive candidate views from the persistent employer catalog."""
    catalog_path = CATALOG_PATHS[source]
    if not catalog_path.is_file():
        return []
    catalog = dc.load_catalog(catalog_path)
    employers = catalog.get("employers") or {}
    out: list[dict[str, Any]] = []
    for e in employers.values():
        ats = e.get("ats") or {}
        if not ats.get("api_scrapable"):
            continue
        if e.get("is_agency"):
            continue
        if e.get("in_base_json"):
            continue
        out.append(
            {
                "name": e["name"],
                "postings": e.get("postings", 0),
                "is_agency": False,
                "in_base_json": False,
                "base_id": None,
                "ats_type": ats.get("type"),
                "ats_slug": ats.get("slug"),
                "ats_api_scrapable": True,
                "ats_confidence": ats.get("confidence"),
                "browse_url": ats.get("browse_url"),
                "salary_min": (e.get("salary") or {}).get("min"),
                "salary_max": (e.get("salary") or {}).get("max"),
                "job_types": e.get("job_types") or [],
                "sample_titles": (e.get("titles") or [])[:5],
                "locations": (e.get("locations") or [])[:5],
                "careers_urls": (e.get("careers_urls") or [])[:3],
                "_config_hint": ats.get("config_hint") or "",
            }
        )
    out.sort(key=lambda v: (-int(v.get("postings") or 0), str(v.get("name") or "").lower()))
    return out


def load_candidates(source: str) -> tuple[list[dict[str, Any]], str]:
    report = latest_report_json(source)
    if report is not None:
        data = json.loads(report.read_text(encoding="utf-8"))
        rows = data.get("all_api_scrapable_direct_not_in_base")
        if isinstance(rows, list):
            return rows, f"report {report.name}"
    rows = candidates_from_catalog(source)
    return rows, f"catalog {CATALOG_PATHS[source].name} (no report JSON)"


def passes_conservative_filters(
    row: dict[str, Any],
    *,
    require_api: bool = True,
    require_high_conf: bool = True,
    exclude_agency: bool = True,
    exclude_in_base: bool = True,
    min_salary: int | None = None,
) -> bool:
    if require_api and not row.get("ats_api_scrapable"):
        return False
    if require_high_conf and str(row.get("ats_confidence") or "").lower() != "high":
        return False
    if exclude_agency and row.get("is_agency"):
        return False
    if exclude_in_base and row.get("in_base_json"):
        return False
    if min_salary is not None:
        sal_max = row.get("salary_max")
        if sal_max is None or int(sal_max) < min_salary:
            return False
    ats_type = str(row.get("ats_type") or "").strip()
    ats_slug = str(row.get("ats_slug") or "").strip()
    if not ats_type or not ats_slug:
        return False
    if ats_type not in dc.API_SCRAPABLE_TYPES:
        return False
    return True


def company_ats_key(co: dict[str, Any]) -> tuple[str, str] | None:
    t = str(co.get("type") or "")
    slug = ""
    if t == "greenhouse":
        slug = str(co.get("board") or "")
    elif t == "lever":
        slug = str(co.get("lever_site") or "")
    elif t == "ashby":
        slug = str(co.get("ashby_board") or "")
    elif t == "smartrecruiters":
        slug = str(co.get("smartrecruiters_id") or "")
    elif t == "icims":
        slug = str(co.get("browse_url") or "")
    elif t == "phenom":
        slug = str(co.get("phenom_refnum") or "")
    elif t == "oracle_hcm":
        slug = str(co.get("oracle_site_number") or "")
    elif t == "json_feed":
        slug = str(co.get("json_url") or "")
    elif t == "taleo_cws":
        slug = f"{co.get('taleo_org') or ''}:{co.get('taleo_cws') or ''}"
    elif t == "successfactors":
        slug = str(co.get("site_origin") or co.get("browse_url") or "")
    else:
        slug = str(co.get("board") or co.get("browse_url") or "")
    slug = slug.strip().lower()
    if t and slug:
        return (t, slug)
    return None


def _unique_id(name: str, existing_ids: set[str]) -> str:
    base = dc.slugify(name)
    cid = base
    n = 2
    while cid in existing_ids:
        cid = f"{base}-{n}"
        n += 1
    return cid


def _apply_config_hint(entry: dict[str, Any], hint: str) -> None:
    if not hint:
        return
    hubs_dir = REPO_ROOT / "scripts" / "hubs"
    if str(hubs_dir) not in sys.path:
        sys.path.insert(0, str(hubs_dir))
    try:
        import probe_hub_scrape_methods as probe  # noqa: E402
    except ImportError:
        return
    fields = probe.parse_hint_fields(hint)
    for key, val in fields.items():
        if key == "type":
            continue
        if key == "board" and entry["type"] == "ashby":
            entry.setdefault("ashby_board", val)
        elif key == "board" and entry["type"] == "lever":
            entry.setdefault("lever_site", val)
        elif key not in entry or not entry[key]:
            entry[key] = val


def build_company_entry(row: dict[str, Any], existing_ids: set[str]) -> dict[str, Any]:
    ats_type = str(row["ats_type"])
    slug = str(row["ats_slug"])
    name = str(row["name"]).strip()
    browse = str(row.get("browse_url") or "").strip()
    cid = _unique_id(name, existing_ids)

    entry: dict[str, Any] = {
        "section": "matching",
        "id": cid,
        "name": name,
        "label": f"{name} (Remote US)",
        "type": ats_type,
        "default_salary": "maybe",
        "cache_ttl_hours": 12,
        "search_keywords": list(DEFAULT_SEARCH_KEYWORDS),
        "discover": True,
    }
    if browse:
        entry["browse_url"] = browse

    if ats_type == "greenhouse":
        entry["board"] = slug
        if not browse:
            entry["browse_url"] = f"https://boards.greenhouse.io/{slug}"
    elif ats_type == "ashby":
        entry["ashby_board"] = slug
        if not browse:
            entry["browse_url"] = f"https://jobs.ashbyhq.com/{slug}"
    elif ats_type == "lever":
        entry["lever_site"] = slug
        if not browse:
            entry["browse_url"] = f"https://jobs.lever.co/{slug}"
        entry["max_details"] = 12
        entry["skip_verify"] = True
    elif ats_type == "smartrecruiters":
        entry["smartrecruiters_id"] = slug
        if not browse:
            entry["browse_url"] = f"https://jobs.smartrecruiters.com/{slug}"
        entry["max_details"] = 12
        entry["skip_verify"] = True
        entry["default_loc"] = "remote"
    elif ats_type == "icims":
        entry["max_details"] = 12
        entry["skip_verify"] = True
        entry["default_loc"] = "remote"
    elif ats_type in ("phenom", "oracle_hcm", "json_feed", "taleo_cws", "successfactors"):
        entry["max_details"] = 12
        entry["skip_verify"] = True
        entry["default_loc"] = "remote"
    elif ats_type == "workday_cxs":
        entry["max_details"] = 12
        entry["skip_verify"] = True
        entry["default_loc"] = "remote"

    hint = str(row.get("_config_hint") or "")
    _apply_config_hint(entry, hint)
    return entry


def validate_new_entry(entry: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    cid = str(entry.get("id") or "").strip()
    ctype = str(entry.get("type") or "").strip()
    if not cid:
        issues.append("missing id")
    if not str(entry.get("name") or "").strip():
        issues.append(f"{cid}: missing name")
    if not ctype:
        issues.append(f"{cid}: missing type")
        return issues
    for req in TYPE_REQUIRED.get(ctype, ()):
        if ctype in ("greenhouse", "ashby", "lever", "smartrecruiters") and req:
            if not str(entry.get(req) or "").strip():
                issues.append(f"{cid}: missing {req} for type={ctype}")
    if ctype in ("greenhouse", "ashby", "lever", "smartrecruiters"):
        if not str(entry.get("browse_url") or "").strip():
            issues.append(f"{cid}: missing browse_url")
    return issues


def find_ats_duplicate_groups(
    companies: list[Any],
) -> list[tuple[tuple[str, str], list[dict[str, Any]]]]:
    """Return ATS (type, slug) keys shared by more than one company entry."""
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in companies:
        if not isinstance(row, dict):
            continue
        key = company_ats_key(row)
        if key:
            by_key.setdefault(key, []).append(row)
    return sorted(
        [(key, rows) for key, rows in by_key.items() if len(rows) > 1],
        key=lambda item: (-len(item[1]), item[0][0], item[0][1]),
    )


def format_ats_duplicate_report(
    groups: list[tuple[tuple[str, str], list[dict[str, Any]]]],
    *,
    base_label: str = "base.json",
) -> list[str]:
    lines: list[str] = []
    for (ats_type, slug), rows in groups:
        ids = [str(r.get("id") or "?") for r in rows]
        names = [str(r.get("name") or "?") for r in rows]
        detail = ", ".join(f"{cid} ({name})" for cid, name in zip(ids, names))
        slug_short = slug if len(slug) <= 60 else slug[:57] + "..."
        lines.append(
            f"{base_label}: duplicate ATS {ats_type}/{slug_short}: {len(rows)} entries — {detail}"
        )
    return lines


def run_validate_static_config(*, quiet: bool = False) -> tuple[int, str]:
    cmd = [_python(), str(MAIN_PY), "validate-static-config", "--dir", str(REPO_ROOT)]
    if quiet:
        cmd.append("-q")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    err = (proc.stderr or proc.stdout or "").strip()
    return proc.returncode, err


def cmd_validate(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate quickjobs static config bundle.")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--no-py-compile", action="store_true")
    parser.add_argument(
        "--duplicates",
        action="store_true",
        help="Report companies sharing the same ATS type+board/slug (does not modify base.json)",
    )
    parser.add_argument(
        "--strict-duplicates",
        action="store_true",
        help="Fail validation when duplicate ATS keys exist (implies --duplicates)",
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    args = parser.parse_args(argv)
    if args.strict_duplicates:
        args.duplicates = True

    issues: list[str] = []
    static_rc, static_err = run_validate_static_config(quiet=True)
    if static_rc != 0:
        if static_err:
            for line in static_err.splitlines():
                line = line.strip()
                if line.startswith("- "):
                    issues.append(line[2:])
                elif line and "validation failed" not in line.lower():
                    issues.append(line)
        else:
            issues.append("validate-static-config failed")

    if not args.no_py_compile:
        import py_compile

        try:
            py_compile.compile(str(MAIN_PY), doraise=True)
        except py_compile.PyCompileError as err:
            issues.append(f"Python compile failed: {MAIN_PY}: {err}")

    base_data: dict[str, Any] | None = None
    companies_path = config_bundle.companies_path_for_base(args.base)
    for label, path in (("base", args.base), ("profile", DEFAULT_PROFILE)):
        if not path.is_file():
            if label == "profile":
                continue
            issues.append(f"missing {label} config: {path}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            issues.append(f"{path}: invalid JSON: {err}")
            continue
        if label == "base":
            if data.get("companies") is not None:
                issues.append(
                    f"{path}: companies must live in {companies_path.name}, not inline in base.json"
                )
            tier1 = data.get("keywords_include_tier1")
            tier2 = data.get("keywords_include_tier2")
            if not isinstance(tier1, list) or not tier1:
                issues.append(f"{path}: keywords_include_tier1 must be a non-empty list")
            if not isinstance(tier2, list) or not tier2:
                issues.append(f"{path}: keywords_include_tier2 must be a non-empty list")

    if not companies_path.is_file():
        issues.append(f"missing companies config: {companies_path}")
    else:
        try:
            co_data = json.loads(companies_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            issues.append(f"{companies_path}: invalid JSON: {err}")
        else:
            co_issues = config_bundle.validate_companies_list(
                    co_data.get("companies"),
                    path_label=str(companies_path),
                )
            issues.extend(co_issues)
            if not co_issues:
                try:
                    base_data = config_bundle.load_base_bundle(args.base)
                except RuntimeError as err:
                    issues.append(str(err))

    duplicate_groups: list[tuple[tuple[str, str], list[dict[str, Any]]]] = []
    if base_data is not None and args.duplicates:
        companies = base_data.get("companies") or []
        if isinstance(companies, list):
            duplicate_groups = find_ats_duplicate_groups(companies)

    if issues:
        print("Validation failed:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    if duplicate_groups and args.strict_duplicates:
        issues.extend(format_ats_duplicate_report(duplicate_groups, base_label=args.base.name))
        print("Validation failed:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    if not args.quiet:
        n = len((base_data or {}).get("companies") or [])
        print(f"Validation OK: companies ({n} rows), base/profile OK, {MAIN_PY.name} compiles")
        if duplicate_groups:
            print(f"Duplicate ATS keys: {len(duplicate_groups)} group(s)")
            for line in format_ats_duplicate_report(duplicate_groups, base_label=args.base.name):
                print(f"  - {line}")
    elif duplicate_groups and args.duplicates:
        print(f"Duplicate ATS keys: {len(duplicate_groups)} group(s)")
        for line in format_ats_duplicate_report(duplicate_groups, base_label=args.base.name):
            print(f"  - {line}")
    return 0


def cmd_dedup(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Report duplicate ATS keys in quickjobs.base.json (report-only by default).",
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Merge duplicate entries (not implemented: use report to review manually)",
    )
    args = parser.parse_args(argv)

    if args.apply:
        print(
            "dedup --apply is not implemented: prior manual merges used case-by-case survivor "
            "rules and layoff_prone remaps. Run without --apply to list duplicate ATS groups.",
            file=sys.stderr,
        )
        return 1

    if not args.base.is_file():
        print(f"Missing base config: {args.base}", file=sys.stderr)
        return 1

    base = config_bundle.load_base_bundle(args.base)
    companies = base.get("companies")
    if not isinstance(companies, list):
        print(f"{args.base}: companies must be a list", file=sys.stderr)
        return 1

    groups = find_ats_duplicate_groups(companies)
    if not groups:
        print(f"No duplicate ATS keys in {args.base} ({len(companies)} companies)")
        return 0

    print(f"Duplicate ATS keys: {len(groups)} group(s) in {args.base} ({len(companies)} companies)")
    for line in format_ats_duplicate_report(groups, base_label=args.base.name):
        print(f"  - {line}")
    return 0


def cmd_discover(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run employer-catalog discovery miners (does not modify base.json).",
    )
    parser.add_argument("source", choices=[*SOURCES, "all"])
    parser.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="Extra args forwarded to the miner script (prefix with --)",
    )
    args = parser.parse_args(argv)
    extra = [a for a in args.extra if a != "--"]
    sources = list(SOURCES) if args.source == "all" else [args.source]
    rc = 0
    for source in sources:
        script = MINER_SCRIPTS[source]
        if not script.is_file():
            print(f"Missing miner script: {script}", file=sys.stderr)
            return 1
        cmd = [_python(), str(script), *DEFAULT_DISCOVER_ARGS.get(source, []), *extra]
        print(f"discover {source}: {' '.join(cmd[2:])}", flush=True)
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
        if proc.returncode != 0:
            rc = proc.returncode
            if args.source == "all":
                print(f"discover {source} failed (exit {proc.returncode})", file=sys.stderr)
                return rc
    return rc


def _sync_one_source(
    source: str,
    base: dict[str, Any],
    *,
    dry_run: bool,
    limit: int,
    filters: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], str]:
    rows, origin = load_candidates(source)
    filtered = [r for r in rows if passes_conservative_filters(r, **filters)]
    filtered.sort(key=lambda v: (-int(v.get("postings") or 0), str(v.get("name") or "").lower()))

    companies: list[dict[str, Any]] = base.setdefault("companies", [])
    existing_ids = {str(c.get("id") or "") for c in companies if isinstance(c, dict)}
    slug_keys = {k for c in companies if isinstance(c, dict) for k in [company_ats_key(c)] if k}

    added: list[dict[str, Any]] = []
    skipped: list[str] = []
    for row in filtered:
        if limit > 0 and len(added) >= limit:
            break
        ats_type = str(row.get("ats_type") or "")
        slug = str(row.get("ats_slug") or "").lower()
        key = (ats_type, slug)
        if key in slug_keys:
            skipped.append(f"{row.get('name')} (duplicate {ats_type}/{slug})")
            continue
        cid_guess = dc.slugify(str(row.get("name") or ""))
        if cid_guess in existing_ids:
            skipped.append(f"{row.get('name')} (id {cid_guess} exists)")
            continue
        entry = build_company_entry(row, existing_ids)
        entry_issues = validate_new_entry(entry)
        if entry_issues:
            skipped.append(f"{row.get('name')} ({'; '.join(entry_issues)})")
            continue
        if company_ats_key(entry) in slug_keys:
            skipped.append(f"{row.get('name')} (duplicate after build)")
            continue
        if dry_run:
            added.append(entry)
            existing_ids.add(entry["id"])
            slug_keys.add(key)
            continue
        companies.append(entry)
        added.append(entry)
        existing_ids.add(entry["id"])
        slug_keys.add(key)

    return added, skipped, origin


def cmd_discover_sync(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Append conservative discovery candidates to quickjobs.base.json.",
    )
    parser.add_argument("source", choices=[*SOURCES, "all"])
    parser.add_argument("--dry-run", action="store_true", help="Print would-add ids/names; no backup/write")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max adds per source per run (0 = no limit; default 0)",
    )
    parser.add_argument("--include-review", action="store_true", help="Allow ats_confidence != high")
    parser.add_argument("--include-agency", action="store_true")
    parser.add_argument("--include-in-base", action="store_true")
    parser.add_argument("--min-salary", type=int, default=None, help="Optional annual salary floor")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    args = parser.parse_args(argv)

    if not args.base.is_file():
        print(f"Missing base config: {args.base}", file=sys.stderr)
        return 1

    filters = {
        "require_api": True,
        "require_high_conf": not args.include_review,
        "exclude_agency": not args.include_agency,
        "exclude_in_base": not args.include_in_base,
        "min_salary": args.min_salary,
    }

    sources = list(SOURCES) if args.source == "all" else [args.source]
    base = config_bundle.load_base_bundle(args.base)
    total_added: list[dict[str, Any]] = []

    for source in sources:
        added, skipped, origin = _sync_one_source(
            source, base, dry_run=args.dry_run, limit=args.limit, filters=filters,
        )
        print(
            f"discover-sync {source}: read {origin}; "
            f"{'would add' if args.dry_run else 'added'} {len(added)}",
            flush=True,
        )
        for entry in added:
            print(f"  + {entry['id']}: {entry['name']} ({entry['type']})")
        if skipped and args.dry_run:
            for msg in skipped[:5]:
                print(f"  skip: {msg}")
            if len(skipped) > 5:
                print(f"  skip: ... and {len(skipped) - 5} more")
        total_added.extend(added)

    if args.dry_run:
        print(f"dry-run complete: {len(total_added)} would be added across {len(sources)} source(s)")
        return 0

    if not total_added:
        print("No new companies to add.")
        return 0

    backup_paths = backup_config_bundle(args.base)
    for backup_path in backup_paths:
        print(f"Backup: {backup_path}")

    config_bundle.save_base_bundle(args.base, base)
    co_path = config_bundle.companies_path_for_base(args.base)
    print(f"Wrote {len(total_added)} company(ies) to {co_path}")

    rc = cmd_validate(["-q"])
    if rc != 0:
        print(
            "Validation failed after write; restore from the newest backups under "
            f"{config_backup.BACKUP_ROOT}/",
            file=sys.stderr,
        )
        for backup_path in backup_paths:
            print(f"  {backup_path}", file=sys.stderr)
        return rc
    print("Post-write validation OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    cli = list(argv if argv is not None else sys.argv[1:])
    if not cli or cli[0] in ("-h", "--help"):
        print(__doc__)
        print("\nUsage: discover_cli.py <discover|discover-sync|validate|dedup> ...")
        return 0 if not cli else 0
    cmd = cli[0]
    rest = cli[1:]
    if cmd == "discover":
        return cmd_discover(rest)
    if cmd == "discover-sync":
        return cmd_discover_sync(rest)
    if cmd == "validate":
        return cmd_validate(rest)
    if cmd == "dedup":
        return cmd_dedup(rest)
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
