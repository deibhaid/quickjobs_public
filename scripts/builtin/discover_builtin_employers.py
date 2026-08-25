#!/usr/bin/env python3
"""Schedulable Built In (builtin.com) employer-catalog miner for quickjobs.

Mirrors ``scripts/dice/discover_dice_employers.py``: build up an EMPLOYER catalog
over time (companies, NOT live jobs). Source is Built In's public, server-rendered
remote job board. There is no open Built In JSON API (the frontend's
``api.builtin.com`` backend is not openly queryable), so this miner parses the
job cards out of the HTML of category pages, restricting itself to paths that
robots.txt ALLOWS: ``/jobs/<category>/remote?page=N`` (Built In allows
``/jobs*?page=`` and disallows ``/jobs*?search=`` -- we never use ``?search=``).

Each card yields the employer's display name + slug, job title, salary range
(e.g. ``62K-111K Annually``), seniority level, and remote flag. Built In links
company cards to its own ``/company/<slug>`` page (it does not expose the
employer's ATS), so -- exactly like the Dice miner -- each NEW, non-agency
employer is ATS-fingerprinted ONCE by name (reusing scripts/hubs) and cached.

Built In carries meaningful staffing/agency volume; those are kept in the catalog
with ``is_agency`` (not dropped) so they can be excluded from add-candidates.

Data flow (one pass, idempotent):
  1. Fetch N pages of each configured remote category.
  2. Parse job cards; keep DevOps/Platform/SRE/Infra roles (``--all-roles``
     disables the filter) by matching title + skills.
  3. Merge into a persistent catalog keyed by normalized employer name (deduped
     by Built In job id).
  4. Fingerprint NEW, non-agency employers' ATS once; flag agencies, base.json
     membership, API-scrapability; emit a dated candidates report.

Reads (never writes): quickjobs.david.base.json (only for the in-base flag).
Writes: ~/ws/scriptdir/output/builtin-employer-catalog.json (+ dated report).

Cron-friendly: absolute paths, ~/.v python, idempotent. NEVER installs cron;
print an example line with --print-cron.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
import discovery_common as dc  # noqa: E402

OUTPUT_DIR = dc.OUTPUT_DIR
DEFAULT_CATALOG = OUTPUT_DIR / "builtin-employer-catalog.json"
SCRIPT_PATH = Path(__file__).resolve()

BASE_URL = "https://builtin.com"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Robots-allowed remote category pages (paginated with ?page=). Never ?search=.
DEFAULT_CATEGORIES = ["dev-engineering/remote"]

INFRA_KEYWORDS = [
    "devops", "sre", "site reliability", "reliability engineer",
    "platform engineer", "platform engineering", "infrastructure engineer",
    "infrastructure", "cloud engineer", "cloud infrastructure",
    "systems engineer", "kubernetes", "terraform", "observability",
    "ci/cd", "cicd", "ansible", "cloudops", "systems administrator",
    "linux", "aws", "azure devops",
]
INFRA_RE = re.compile("|".join(re.escape(k) for k in INFRA_KEYWORDS), re.I)

_CARD_SPLIT = re.compile(r'(?=id="job-card-\d+")')
_RE_JOBID = re.compile(r'id="job-card-(\d+)"')
_RE_COMPANY_SLUG = re.compile(r'href="/company/([^"]+)"')
_RE_COMPANY_NAME = re.compile(r'data-id="company-title"[^>]*>\s*<span>([^<]+)</span>')
_RE_TITLE = re.compile(r'data-id="job-card-title"[^>]*>([^<]+)</a>')
_RE_JOBLINK = re.compile(r'data-alias="(/job/[^"]+)"')
_RE_SALARY = re.compile(r'sack-dollar.*?<span[^>]*>\s*([^<]+?)\s*</span>', re.S)
_RE_LEVEL = re.compile(r'trophy.*?<span[^>]*>\s*([^<]+?)\s*</span>', re.S)
_RE_SKILLS = re.compile(r'Top Skills:.*?</div>\s*</div>', re.S)
_RE_SKILL_ITEM = re.compile(r'<span[^>]*>([^<]+)</span>')
_RE_JOBTYPE = re.compile(r"\b(full[\s-]?time|part[\s-]?time|contract|intern(ship)?)\b", re.I)


def name_from_slug(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", "-").split("-") if w) or slug


def http_get(url: str, timeout: int) -> str | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        print(f"  Built In fetch error {url}: {err}", file=sys.stderr)
        return None


def parse_cards(page_html: str) -> list[dict]:
    out: list[dict] = []
    for c in _CARD_SPLIT.split(page_html):
        if not c.startswith('id="job-card-'):
            continue
        jid = _RE_JOBID.search(c)
        slug = _RE_COMPANY_SLUG.search(c)
        if not jid or not slug:
            continue
        name_m = _RE_COMPANY_NAME.search(c)
        company = html.unescape(name_m.group(1)).strip() if name_m else name_from_slug(slug.group(1))
        title_m = _RE_TITLE.search(c)
        title = html.unescape(title_m.group(1)).strip() if title_m else ""
        sal_m = _RE_SALARY.search(c)
        salary = html.unescape(sal_m.group(1)).strip() if sal_m else ""
        # Guard: the salary span must look monetary (else the icon lacked a value).
        if salary and not re.search(r"\d", salary):
            salary = ""
        lvl_m = _RE_LEVEL.search(c)
        level = html.unescape(lvl_m.group(1)).strip() if lvl_m else ""
        if level and not re.search(r"(?i)level|senior|junior|lead|principal|staff|entry|mid|expert", level):
            level = ""
        link_m = _RE_JOBLINK.search(c)
        job_url = BASE_URL + link_m.group(1) if link_m else ""
        skills_block = _RE_SKILLS.search(c)
        skills = []
        if skills_block:
            skills = [html.unescape(s).strip() for s in _RE_SKILL_ITEM.findall(skills_block.group(0))
                      if s.strip() and s.strip() != "Top Skills:"]
        jt_m = _RE_JOBTYPE.search(c)
        job_type = ""
        if jt_m:
            job_type = {"full time": "Full-time", "fulltime": "Full-time", "full-time": "Full-time",
                        "part time": "Part-time", "part-time": "Part-time", "contract": "Contract",
                        "intern": "Internship", "internship": "Internship"}.get(
                re.sub(r"[\s-]+", " ", jt_m.group(1).lower()), "")
        out.append({
            "id": slug.group(1) + ":" + jid.group(1),
            "company": company,
            "company_slug": slug.group(1),
            "title": title,
            "salary": salary,
            "level": level,
            "skills": skills[:20],
            "job_type": job_type,
            "job_url": job_url,
        })
    return out


def matches_infra(card: dict) -> str:
    hay = " ".join([card["title"]] + card["skills"])
    m = INFRA_RE.search(hay)
    return m.group(0).lower() if m else ""


CRON_EXAMPLE = (
    "# Weekly Built In remote employer-catalog refresh (Tuesdays 07:25). "
    "Uses ~/.v python; no cd needed.\n"
    "25 7 * * 2 cron-exec /path/to/venv/bin/python "
    f"{SCRIPT_PATH} --pages 5 --max-fingerprint 40 --fingerprint api\n"
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--categories", type=str, default=",".join(DEFAULT_CATEGORIES),
                   help="Comma-separated robots-allowed category paths under /jobs/ "
                        f"(default: {','.join(DEFAULT_CATEGORIES)})")
    p.add_argument("--pages", type=int, default=3, help="Pages per category (default 3)")
    p.add_argument("--start-page", type=int, default=1)
    p.add_argument("--all-roles", action="store_true",
                   help="Catalog every posting (default: only DevOps/Platform/SRE/Infra)")
    p.add_argument("--fingerprint", choices=("full", "api", "off"), default="full")
    p.add_argument("--fingerprint-url-cap", type=int, default=12)
    p.add_argument("--fingerprint-workers", type=int, default=10)
    p.add_argument("--max-fingerprint", type=int, default=0,
                   help="Cap NEW employers fingerprinted this run (0 = no cap)")
    p.add_argument("--refingerprint", action="store_true")
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    p.add_argument("--report-dir", type=Path, default=OUTPUT_DIR)
    p.add_argument("--base", type=Path, default=dc.DEFAULT_BASE,
                   help="quickjobs base.json to read for the in-base flag (READ ONLY)")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--delay", type=float, default=1.0, help="Delay between page fetches (s)")
    p.add_argument("--print-cron", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.print_cron:
        print(CRON_EXAMPLE)
        return 0

    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    categories = [c.strip().strip("/") for c in args.categories.split(",") if c.strip()]
    print(f"Built In employer discovery @ {run_ts}\n"
          f"  categories={categories} pages={args.pages} infra_filter={not args.all_roles} "
          f"fingerprint={args.fingerprint}", flush=True)

    catalog = dc.load_catalog(args.catalog)
    employers = catalog["employers"]
    pre_existing_keys = set(employers)

    cards_seen = 0
    kept = 0
    pages_fetched = 0
    for cat in categories:
        for page in range(args.start_page, args.start_page + args.pages):
            url = f"{BASE_URL}/jobs/{cat}?page={page}"
            page_html = http_get(url, args.timeout)
            if not page_html:
                break
            pages_fetched += 1
            cards = parse_cards(page_html)
            if not cards:
                print(f"  {url}: 0 cards (stopping category)", flush=True)
                break
            page_kept = 0
            for card in cards:
                cards_seen += 1
                kw = "" if args.all_roles else matches_infra(card)
                if not args.all_roles and not kw:
                    continue
                kept += 1
                page_kept += 1
                key = dc.catalog_key(card["company"])
                entry = employers.get(key)
                if entry is None:
                    entry = dc.new_entry(card["company"], run_ts)
                    employers[key] = entry
                entry.setdefault("company_slugs", [])
                if card["company_slug"] not in entry["company_slugs"]:
                    entry["company_slugs"].append(card["company_slug"])
                if card["level"]:
                    entry.setdefault("seniority_levels", [])
                    if card["level"] not in entry["seniority_levels"]:
                        entry["seniority_levels"].append(card["level"])
                if card["skills"]:
                    sk = entry.setdefault("skills_seen", [])
                    for s in card["skills"]:
                        if s not in sk and len(sk) < 40:
                            sk.append(s)
                dc.merge_common(
                    entry, run_ts=run_ts, source_id=card["id"],
                    title=card["title"], salary_label=card["salary"],
                    job_type=card["job_type"], keyword=kw or "builtin",
                    remote=True, posting_url=card["job_url"],
                )
            print(f"  {url}: {len(cards)} cards, {page_kept} kept", flush=True)
            if args.delay:
                time.sleep(args.delay)

    new_keys = [k for k in employers if k not in pre_existing_keys]

    fingerprinted_keys, _ = dc.finalize_catalog(
        catalog=catalog, employers=employers, new_keys=new_keys,
        pre_existing_keys=pre_existing_keys, run_ts=run_ts,
        base_path=args.base, catalog_path=args.catalog,
        fingerprint_mode=args.fingerprint, fingerprint_url_cap=args.fingerprint_url_cap,
        fingerprint_workers=args.fingerprint_workers, max_fingerprint=args.max_fingerprint,
        refingerprint=args.refingerprint,
        last_config={"categories": categories, "pages": args.pages,
                     "infra_filter": not args.all_roles, "fingerprint": args.fingerprint},
    )

    stats = dc.compute_stats(
        catalog, new_keys, fingerprinted_keys,
        extra={"pages_fetched": pages_fetched, "cards_scanned": cards_seen, "postings_kept": kept},
    )
    report_md = args.report_dir / f"builtin-new-candidates-{run_ts[:10]}.md"
    report_json = args.report_dir / f"builtin-new-candidates-{run_ts[:10]}.json"
    args.report_dir.mkdir(parents=True, exist_ok=True)
    dc.write_reports(
        report_md=report_md, report_json=report_json, catalog=catalog,
        new_keys=new_keys, fingerprinted_keys=fingerprinted_keys, run_ts=run_ts,
        stats=stats, source_label="Built In",
        source_note=("Read-only discovery for quickjobs. Source: builtin.com public "
                     "remote job board (robots-allowed /jobs/<category>/remote?page=N). "
                     "base.json was NOT modified."),
    )

    print(
        "SUMMARY: run={run} pages={pages_fetched} cards={cards_scanned} kept={postings_kept} "
        "employers={employers_in_catalog} new={new_employers_this_run} "
        "agencies={agencies_flagged_total} api_direct_not_in_base={api_scrapable_direct_not_in_base_total} "
        "new_api_direct={new_api_scrapable_direct_this_run} "
        "fingerprinted={employers_fingerprinted_this_run}".format(**stats),
        flush=True,
    )
    print(f"Catalog: {args.catalog}")
    print(f"Report:  {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
