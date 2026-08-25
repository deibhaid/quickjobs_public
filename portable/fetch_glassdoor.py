#!/usr/bin/env python3
"""Populate Glassdoor ratings for manual career hubs (cache + optional meta file).

Anonymous fetch uses curl_cffi (Chrome TLS impersonation). No Glassdoor login.
If that is blocked, pass --browser --headed once with a persistent Chrome profile.

  python_venv/bin/python fetch_glassdoor.py --limit 10
  python_venv/bin/python fetch_glassdoor.py --workers 8
  python_venv/bin/python fetch_glassdoor.py --browser --headed --limit 5

After fetching, rebuild the board: python_venv/bin/python run.py rebuild-snapshot
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
META_PATH = ROOT / "quickjobs.manual-career-meta.json"
PROFILE_DIR = ROOT / "cache" / "run" / "glassdoor-browser-profile"


def _load_quickjobs():
    path = ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_portable", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


qj = None


def _init_qj():
    global qj
    if qj is None:
        qj = _load_quickjobs()
    return qj


def load_meta() -> dict[str, Any]:
    if META_PATH.is_file():
        data = json.loads(META_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {"employers": {}}


def save_meta(data: dict[str, Any]) -> None:
    META_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def hub_companies(cfg: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for company in cfg.get("companies") or []:
        if not isinstance(company, dict):
            continue
        if not qj.company_is_hub_link(company):
            continue
        cid = str(company.get("id") or "").strip()
        name = qj.manual_career_display_name(
            str(company.get("name") or cid),
            str(company.get("label") or ""),
        )
        if cid and name:
            rows.append((cid, name))
    rows.sort(key=lambda row: row[1].lower())
    return rows


def fetch_html_playwright(company_name: str, *, headed: bool, profile_dir: Path) -> str:
    from playwright.sync_api import sync_playwright

    url = qj.glassdoor_search_url(company_name)
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=not headed,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=not headed,
                args=["--disable-blink-features=AutomationControlled"],
            )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(4000 if headed else 2500)
        html = page.content()
        context.close()
    return html


def merge_employer_meta(store: dict[str, Any], company_id: str, parsed: dict[str, str]) -> bool:
    if not parsed.get("glassdoor_rating"):
        return False
    employers = store.setdefault("employers", {})
    if not isinstance(employers, dict):
        employers = {}
        store["employers"] = employers
    entry = employers.setdefault(company_id, {})
    if not isinstance(entry, dict):
        entry = {}
        employers[company_id] = entry
    glassdoor = entry.setdefault("glassdoor", {})
    if not isinstance(glassdoor, dict):
        glassdoor = {}
        entry["glassdoor"] = glassdoor
    glassdoor["rating"] = parsed["glassdoor_rating"]
    if parsed.get("glassdoor_reviews"):
        glassdoor["reviews"] = parsed["glassdoor_reviews"]
    if parsed.get("glassdoor_url"):
        glassdoor["url"] = parsed["glassdoor_url"]
    qj.save_glassdoor_meta_cache(company_id, parsed)
    return True


def has_cached_rating(company_id: str) -> bool:
    return bool(qj.load_glassdoor_meta_cache(company_id).get("glassdoor_rating"))


def main() -> int:
    from portable_runtime import apply_portable_env, ensure_venv_python

    ensure_venv_python()
    apply_portable_env()
    _init_qj()

    parser = argparse.ArgumentParser(description="Fetch Glassdoor ratings for manual career hubs")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Use Playwright instead of anonymous curl_cffi fetch",
    )
    parser.add_argument("--headed", action="store_true", help="Visible browser (with --browser)")
    parser.add_argument("--limit", type=int, default=0, help="Max companies (0 = all missing)")
    parser.add_argument("--only", action="append", metavar="ID", help="Company id(s) only")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel HTTP workers (0 = QUICKJOBS_GLASSDOOR_WORKERS or 8; 1 = sequential)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=-1.0,
        help="Seconds between companies (browser/sequential; -1 = default)",
    )
    args = parser.parse_args()

    cfg = qj.load_config_base()
    meta = load_meta()

    todo: list[tuple[str, str]] = []
    for cid, name in hub_companies(cfg):
        if args.only and cid not in args.only:
            continue
        if has_cached_rating(cid) and not args.only:
            continue
        todo.append((cid, name))
    if args.limit and args.limit > 0:
        todo = todo[: args.limit]

    if not todo:
        print("Nothing to fetch (all hub companies already have cached Glassdoor ratings).")
        return 0

    if args.workers > 0:
        os.environ["QUICKJOBS_GLASSDOOR_WORKERS"] = str(args.workers)
    if args.delay >= 0:
        os.environ["QUICKJOBS_GLASSDOOR_DELAY"] = str(args.delay)

    print(f"Fetching Glassdoor for {len(todo)} companies…")
    ok = 0
    if args.browser:
        delay = args.delay if args.delay >= 0 else 0.8
        for idx, (cid, name) in enumerate(todo, 1):
            print(f"[{idx}/{len(todo)}] {name} ({cid})")
            html = fetch_html_playwright(name, headed=args.headed, profile_dir=PROFILE_DIR)
            parsed = qj.parse_glassdoor_search_html(html, name)
            if not parsed.get("glassdoor_rating"):
                print("  skipped — no rating parsed (bot block or no match)")
            elif merge_employer_meta(meta, cid, parsed):
                ok += 1
                print(
                    f"  {parsed.get('glassdoor_rating')}★"
                    f" — {parsed.get('glassdoor_url') or qj.glassdoor_search_url(name)}"
                )
                save_meta(meta)
            if idx < len(todo) and delay > 0:
                time.sleep(delay)
    else:
        workers = qj._glassdoor_configured_workers()
        print(f"HTTP fetch (×{min(workers, len(todo))} workers)…")
        ok = qj.prefetch_glassdoor_ratings(todo, label="Glassdoor")
        for cid, _name in todo:
            cached = qj.load_glassdoor_meta_cache(cid)
            if cached.get("glassdoor_rating"):
                merge_employer_meta(meta, cid, cached)
        if ok:
            save_meta(meta)

    print(f"Done — {ok}/{len(todo)} updated.")
    print("Rebuild HTML: python_venv/bin/python run.py rebuild-snapshot")
    return 0 if ok else 1


if __name__ == "__main__":
    # PUBLIC_BUILD_STUB — Glassdoor fetch disabled in the public repo
    print("Glassdoor fetch disabled in public build", flush=True)
    raise SystemExit(0)

    raise SystemExit(main())
