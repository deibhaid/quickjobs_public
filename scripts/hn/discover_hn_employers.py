#!/usr/bin/env python3
"""Schedulable Hacker News "Who is hiring?" employer-catalog miner for quickjobs.

Mirrors ``scripts/dice/discover_dice_employers.py``: build up an EMPLOYER catalog
over time (direct companies, NOT live jobs). Source is the monthly "Ask HN: Who
is hiring?" threads, read through the public, no-auth Algolia HN Search API
(https://hn.algolia.com/api). Each top-level comment is one employer's posting;
they are overwhelmingly DIRECT employers (founders / eng leaders posting their
own roles) and frequently include a salary, a remote flag, and a link to the
company's own careers/ATS site -- an ideal signal for a remote senior-infra
profile.

Data flow (one pass, idempotent):
  1. Enumerate the N most recent "Who is hiring?" story threads via the Algolia
     ``search_by_date`` endpoint (tags ``story,author_whoishiring``).
  2. Fetch each thread's comment tree via ``items/<id>``.
  3. Keep top-level comments that mention the DevOps/Platform/SRE/Infra keyword
     set (``--all-roles`` disables the filter), extract employer name + salary +
     job type + a careers URL from the HN post header.
  4. Merge into a persistent employer catalog keyed by normalized name (deduped
     by HN comment id, so reruns never inflate counts). New, non-agency employers
     are ATS-fingerprinted ONCE (reusing scripts/hubs; seeded with the scraped
     careers URL when present) and cached.
  5. Flag agencies, base.json membership, and API-scrapability; emit a dated
     "new candidates" report.

HN Algolia API notes (verified 2026-07):
  * No auth. Documented soft limit ~10,000 requests/hour per IP; this miner makes
    ~1 request per thread plus one per thread's items endpoint (tiny footprint).
  * ``search_by_date?tags=story,author_whoishiring`` returns the monthly threads
    (Who is hiring / Who wants to be hired / Freelancer). We keep only the "Who
    is hiring?" titles.
  * ``items/<id>`` returns the full nested comment tree in one JSON document.

Reads (never writes): quickjobs.base.json (only for the in-base flag).
Writes: ~/ws/scriptdir/output/hn-employer-catalog.json (+ dated report .md/.json).

Cron-friendly: absolute paths, ~/.v python, idempotent. NEVER installs cron;
print an example line with --print-cron.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
import discovery_common as dc  # noqa: E402

OUTPUT_DIR = dc.OUTPUT_DIR
DEFAULT_CATALOG = OUTPUT_DIR / "hn-employer-catalog.json"
SCRIPT_PATH = Path(__file__).resolve()

ALGOLIA = "https://hn.algolia.com/api/v1"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) quickjobs-discovery"

# DevOps/Platform/SRE/Infra net. Kept specific enough to avoid matching generic
# "we build infrastructure" marketing copy (hence "infrastructure engineer", not
# bare "infrastructure").
INFRA_KEYWORDS = [
    "devops", "sre", "site reliability", "reliability engineer",
    "platform engineer", "platform engineering", "infrastructure engineer",
    "cloud engineer", "cloud infrastructure", "systems engineer",
    "kubernetes", "terraform", "observability", "ci/cd", "cicd",
    "infrastructure team", "platform team",
]
INFRA_RE = re.compile("|".join(re.escape(k) for k in INFRA_KEYWORDS), re.I)

_LOC_STATE_RE = re.compile(r",\s*[A-Z]{2}\b")
_LOC_WORDS = {
    "remote", "onsite", "on-site", "hybrid", "us", "usa", "u.s.", "uk", "eu",
    "emea", "apac", "worldwide", "anywhere", "global", "distributed", "us only",
    "us-only", "remote (us)", "remote us", "north america",
}
_JOBTYPE_RE = re.compile(
    r"\b(full[\s-]?time|part[\s-]?time|contract|contractor|intern(ship)?|freelance)\b",
    re.I,
)
_ROLE_RE = re.compile(
    r"engineer|developer|devops|sre|reliability|architect|manager|scientist|"
    r"designer|programmer|administrator|\blead\b|head of|director|founding|"
    r"platform|infrastructure",
    re.I,
)
# Salary substrings: "$200-298k", "$150K", "150k-250k", "$120,000 - $180,000".
_SALARY_RE = re.compile(
    r"(?:USD|US\$|\$)\s?\d[\d,]*(?:\.\d+)?\s*[kKmM]?"
    r"(?:\s*(?:-|–|—|to)\s*(?:USD|US\$|\$)?\s?\d[\d,]*(?:\.\d+)?\s*[kKmM]?)?"
    r"|\b\d{2,3}\s*[kK]\s*(?:-|–|—|to)\s*\d{2,3}\s*[kK]\b"
)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def http_json(url: str, timeout: int) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as err:
        print(f"  HN API error for {url}: {err}", file=sys.stderr)
        return None


def find_threads(n: int, timeout: int) -> list[dict]:
    """Return up to n most recent 'Who is hiring?' story threads."""
    url = (
        f"{ALGOLIA}/search_by_date?tags=story,author_whoishiring"
        f"&query={urllib.parse.quote('who is hiring')}"
        f"&restrictSearchableAttributes=title&hitsPerPage={max(n * 3, 12)}"
    )
    data = http_json(url, timeout) or {}
    threads = []
    for hit in data.get("hits", []):
        title = str(hit.get("title") or "")
        if re.search(r"who\s+is\s+hiring", title, re.I):
            threads.append({"id": str(hit.get("objectID")), "title": title,
                            "num_comments": hit.get("num_comments")})
        if len(threads) >= n:
            break
    return threads


# --------------------------------------------------------------------------- #
# Comment parsing
# --------------------------------------------------------------------------- #

def _clean_text(raw_html: str) -> str:
    t = raw_html or ""
    t = re.sub(r"(?i)</?p>", "\n", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def _looks_like_location(field: str) -> bool:
    f = field.strip().lower()
    if not f:
        return True
    if f in _LOC_WORDS or "remote" in f:
        return True
    if _LOC_STATE_RE.search(field):
        return True
    return False


def _looks_like_salary(field: str) -> bool:
    return bool(_SALARY_RE.search(field))


def _looks_like_jobtype(field: str) -> bool:
    return bool(_JOBTYPE_RE.fullmatch(field.strip()) or _JOBTYPE_RE.search(field) and len(field) < 24)


def extract_company(header: str) -> str:
    """Pick the employer name from an HN 'Who is hiring' header line."""
    fields = [f.strip() for f in header.split("|")]
    fields = [f for f in fields if f]
    if not fields:
        return ""
    for f in fields[:3]:
        if _looks_like_salary(f) or _looks_like_location(f) or _looks_like_jobtype(f):
            continue
        cand = f
        break
    else:
        cand = fields[0]
    # Strip a trailing URL / parenthetical noise, collapse whitespace.
    cand = re.sub(r"https?://\S+", "", cand).strip(" -–—:·•")
    cand = re.sub(r"\s+", " ", cand)
    # Reject if the "company" is actually a sentence (too long / no pipes case).
    if len(cand) > 64 or len(cand) < 2:
        return ""
    return cand


def extract_salary(text: str, header: str) -> str:
    for scope in (header, text):
        for m in _SALARY_RE.finditer(scope):
            label = m.group(0).strip()
            lo, hi, _ = dc.parse_salary(label)
            if lo is not None or hi is not None:
                return label
    return ""


def extract_jobtypes(text: str) -> list[str]:
    out: list[str] = []
    canon = {
        "full time": "Full-time", "fulltime": "Full-time", "full-time": "Full-time",
        "part time": "Part-time", "parttime": "Part-time", "part-time": "Part-time",
        "contract": "Contract", "contractor": "Contract",
        "intern": "Internship", "internship": "Internship", "freelance": "Contract",
    }
    for m in _JOBTYPE_RE.finditer(text):
        key = re.sub(r"[\s-]+", " ", m.group(0).lower())
        val = canon.get(key) or canon.get(key.replace(" ", ""))
        if val and val not in out:
            out.append(val)
    return out


def extract_role(header: str, company: str) -> str:
    """Best-effort role/title from the HN header's pipe fields."""
    for f in [x.strip() for x in header.split("|") if x.strip()]:
        if f == company or _looks_like_salary(f) or _looks_like_location(f):
            continue
        if _ROLE_RE.search(f) and 3 <= len(f) <= 80:
            return re.sub(r"\s+", " ", f)
    return ""


def extract_careers_url(raw_html: str) -> str:
    hrefs = re.findall(r'href="([^"]+)"', raw_html or "")
    cleaned = [html.unescape(h) for h in hrefs if h.startswith("http")]
    cleaned = [h for h in cleaned if "news.ycombinator.com" not in h and "ycombinator.com/item" not in h]
    if not cleaned:
        return ""
    ats_hint = re.compile(
        r"careers|/jobs|greenhouse|lever\.co|ashbyhq|myworkdayjobs|smartrecruiters|"
        r"jobs\.|/join|/hiring|workatastartup|ashby",
        re.I,
    )
    for h in cleaned:
        if ats_hint.search(h):
            return h
    return cleaned[0]


def parse_comment(child: dict) -> dict | None:
    raw = child.get("text") or ""
    if not raw:
        return None
    text = _clean_text(raw)
    if not text:
        return None
    header = text.split("\n", 1)[0]
    company = extract_company(header)
    if not company:
        return None
    return {
        "id": str(child.get("id") or ""),
        "author": child.get("author") or "",
        "company": company,
        "role": extract_role(header, company),
        "salary": extract_salary(text, header),
        "job_types": extract_jobtypes(text),
        "careers_url": extract_careers_url(raw),
        "remote": bool(re.search(r"\bremote\b", text, re.I)),
        "keyword_match": (INFRA_RE.search(text).group(0).lower() if INFRA_RE.search(text) else ""),
        "text": text,
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

CRON_EXAMPLE = (
    "# Monthly HN 'Who is hiring' employer-catalog refresh (7th, 07:20). "
    "Uses ~/.v python; no cd needed.\n"
    "20 7 7 * * cron-exec /path/to/venv/bin/python "
    f"{SCRIPT_PATH} --threads 2 --max-fingerprint 40\n"
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--threads", type=int, default=3,
                   help="Number of most-recent 'Who is hiring?' threads to mine (default 3)")
    p.add_argument("--thread-ids", type=str, default="",
                   help="Comma-separated HN story ids to mine (overrides --threads)")
    p.add_argument("--all-roles", action="store_true",
                   help="Catalog every posting (default: only DevOps/Platform/SRE/Infra)")
    p.add_argument("--fingerprint", choices=("full", "api", "off"), default="full",
                   help="ATS fingerprint mode for NEW employers (default full; uses scraped careers URL)")
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
    p.add_argument("--delay", type=float, default=0.3)
    p.add_argument("--print-cron", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.print_cron:
        print(CRON_EXAMPLE)
        return 0

    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.thread_ids.strip():
        threads = [{"id": t.strip(), "title": f"(id {t.strip()})", "num_comments": None}
                   for t in args.thread_ids.split(",") if t.strip()]
    else:
        threads = find_threads(args.threads, args.timeout)
    if not threads:
        print("No 'Who is hiring?' threads found.", file=sys.stderr)
        return 1

    print(f"HN employer discovery @ {run_ts}\n"
          f"  threads={len(threads)} infra_filter={not args.all_roles} "
          f"fingerprint={args.fingerprint}", flush=True)
    for t in threads:
        print(f"  thread {t['id']}: {t['title']} ({t.get('num_comments')} comments)", flush=True)

    catalog = dc.load_catalog(args.catalog)
    employers = catalog["employers"]
    pre_existing_keys = set(employers)

    total_comments = 0
    kept = 0
    parse_fail = 0
    for t in threads:
        data = http_json(f"{ALGOLIA}/items/{t['id']}", args.timeout)
        if not data:
            continue
        children = data.get("children") or []
        for child in children:
            total_comments += 1
            post = parse_comment(child)
            if not post:
                parse_fail += 1
                continue
            if not args.all_roles and not post["keyword_match"]:
                continue
            kept += 1
            key = dc.catalog_key(post["company"])
            entry = employers.get(key)
            if entry is None:
                entry = dc.new_entry(post["company"], run_ts)
                employers[key] = entry
            entry.setdefault("hn_authors", [])
            if post["author"] and post["author"] not in entry["hn_authors"]:
                entry["hn_authors"].append(post["author"])
            dc.merge_common(
                entry,
                run_ts=run_ts,
                source_id=post["id"],
                title=post["role"],
                salary_label=post["salary"],
                job_type=(post["job_types"][0] if post["job_types"] else ""),
                keyword=post["keyword_match"] or "hn",
                remote=post["remote"],
                careers_url=post["careers_url"],
                posting_url=f"https://news.ycombinator.com/item?id={post['id']}",
            )
            for jt in post["job_types"][1:]:
                if jt not in entry["job_types"]:
                    entry["job_types"].append(jt)
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
        last_config={"threads": [t["id"] for t in threads], "infra_filter": not args.all_roles,
                     "fingerprint": args.fingerprint},
    )

    stats = dc.compute_stats(
        catalog, new_keys, fingerprinted_keys,
        extra={"threads_mined": len(threads), "comments_scanned": total_comments,
               "postings_kept": kept, "comments_unparsed": parse_fail},
    )
    report_md = args.report_dir / f"hn-new-candidates-{run_ts[:10]}.md"
    report_json = args.report_dir / f"hn-new-candidates-{run_ts[:10]}.json"
    args.report_dir.mkdir(parents=True, exist_ok=True)
    dc.write_reports(
        report_md=report_md, report_json=report_json, catalog=catalog,
        new_keys=new_keys, fingerprinted_keys=fingerprinted_keys, run_ts=run_ts,
        stats=stats, source_label="HN 'Who is hiring?'",
        source_note=("Read-only discovery for quickjobs. Source: Hacker News "
                     "'Ask HN: Who is hiring?' threads via the public Algolia HN "
                     "Search API. base.json was NOT modified."),
    )

    print(
        "SUMMARY: run={run} threads={threads_mined} comments={comments_scanned} "
        "kept={postings_kept} employers={employers_in_catalog} new={new_employers_this_run} "
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
