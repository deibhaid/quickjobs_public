#!/usr/bin/env python3
"""Manual timing harness for ATS list vs detail fetch patterns in quickjobs.py.

Times (a) board/list only, (b) full scrape-shaped detail loops (capped), and
(c) optional 4-way parallel vs sequential detail fetches. Does not import
quickjobs.py (avoids side effects); mirrors http_get URLs and caps.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import io
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any, Callable

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HTTP_CLOSE_HEADERS = {"Connection": "close"}

DEFAULT_COMPANY_IDS = (
    "anduril",
    "spacex",
    "harvey",
    "openai",
    "american-express",
    "bny-mellon",
    "chevron",
    "charter-communications",
)

# quickjobs defaults referenced in fetch_* (oracle/phenom max_details=24; talentbrew uses company max_details)
QUICKJOBS_ORACLE_MAX_DETAILS = 24
QUICKJOBS_TALENTBREW_MAX_QUERIES = 4
DEFAULT_DETAIL_CAP = 10
DEFAULT_SEARCH_KEYWORD = "devops"
PARALLEL_WORKERS = 4

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_JSON = SCRIPT_DIR / "quickjobs.base.json"

TALENTBREW_LINK_RE = re.compile(
    r'href="(/job/[^"?#]+|/jobs/[^"?#]+)"',
    re.I,
)


@dataclass
class TimedRun:
    company: str
    ats: str
    phase: str
    requests: int
    elapsed_sec: float
    detail_count: int = 0
    list_count: int = 0
    errors: list[str] = field(default_factory=list)
    notes: str = ""

    def error_summary(self) -> str:
        if not self.errors:
            return ""
        shown = self.errors[:3]
        extra = len(self.errors) - len(shown)
        text = "; ".join(shown)
        if extra > 0:
            text += f" (+{extra} more)"
        return text


class RequestCounter:
    def __init__(self) -> None:
        self.count = 0
        self.errors: list[str] = []
        self._lock = threading.Lock()

    def record(self, url: str, code: int, err: str | None = None) -> tuple[int, str]:
        with self._lock:
            self.count += 1
            if err:
                self.errors.append(f"{code} {url}: {err}")
            elif code != 200:
                self.errors.append(f"HTTP {code} {url}")
        return code, err or ""


def _ascii_safe_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parts.query, safe="/%:@!$&'()*+,;=-._~?=&")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def http_get(url: str, *, timeout: int = 25, counter: RequestCounter | None = None) -> tuple[int, str]:
    url = _ascii_safe_url(url)
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, */*",
            "Accept-Encoding": "gzip",
            **_HTTP_CLOSE_HEADERS,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            body = raw.decode("utf-8", "replace")
            code = resp.getcode()
            if counter:
                counter.record(url, code)
            return code, body
    except urllib.error.HTTPError as err:
        body = (err.read(8000) if err.fp else b"").decode("utf-8", "replace")
        if counter:
            counter.record(url, err.code)
        return err.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if counter:
            counter.record(url, 599, str(exc))
        return 599, ""


def http_post_json(url: str, payload: dict[str, Any], *, timeout: int = 25, counter: RequestCounter | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_HTTP_CLOSE_HEADERS,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            body = raw.decode("utf-8", "replace")
            code = resp.getcode()
            if counter:
                counter.record(url, code)
            return code, body
    except urllib.error.HTTPError as err:
        body = (err.read(8000) if err.fp else b"").decode("utf-8", "replace")
        if counter:
            counter.record(url, err.code)
        return err.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if counter:
            counter.record(url, 599, str(exc))
        return 599, ""


def load_companies(ids: list[str]) -> list[dict[str, Any]]:
    if not BASE_JSON.is_file():
        raise SystemExit(f"Missing base config: {BASE_JSON}")
    data = hub_tools.load_base_bundle()
    by_id = {str(c.get("id")): c for c in data.get("companies") or [] if c.get("id")}
    missing = [cid for cid in ids if cid not in by_id]
    if missing:
        raise SystemExit(f"Unknown company ids in base json: {', '.join(missing)}")
    return [by_id[cid] for cid in ids]


def parse_talentbrew_search(html_text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in TALENTBREW_LINK_RE.finditer(html_text or ""):
        path = unescape(match.group(1).strip())
        if not path or path in seen:
            continue
        seen.add(path)
        job_id = path.rstrip("/").split("/")[-1]
        title_match = re.search(
            rf'href="{re.escape(path)}"[^>]*>[\s\S{{0,400}}?<span[^>]*>([^<]+)</span>',
            html_text,
            re.I,
        )
        title = unescape(title_match.group(1).strip()) if title_match else job_id
        rows.append({"job_id": job_id, "path": path, "title": title})
    return rows


def ashby_posting_url(company: dict[str, Any], posting: dict[str, Any]) -> str:
    posting_url = str(posting.get("jobUrl") or posting.get("applyUrl") or "").strip()
    if posting_url.endswith("/application"):
        posting_url = posting_url[: -len("/application")]
    if posting_url.startswith("http"):
        return posting_url.split("?")[0]
    board = str(company.get("ashby_board") or company.get("id") or "").strip()
    job_id = str(posting.get("id") or "").strip()
    if board and job_id:
        return f"https://jobs.ashbyhq.com/{board}/{job_id}"
    return ""


def oracle_hcm_search_url(company: dict[str, Any], keyword: str, *, limit: int) -> str:
    api_base = str(
        company.get("oracle_api_base")
        or "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest"
    ).rstrip("/")
    site_number = str(company.get("oracle_site_number") or "CX_1001")
    facets = (
        "LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3B"
        "ORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS"
    )
    finder = (
        f"findReqs;siteNumber={site_number},facetsList={facets},limit={limit},"
        f"keyword={urllib.parse.quote(keyword)}"
    )
    location_id = str(company.get("oracle_location_id") or "").strip()
    if location_id:
        finder += f",locationId={location_id}"
    return f"{api_base}/recruitingCEJobRequisitions?onlyData=true&expand=all&finder={finder}"


def oracle_hcm_detail_url(company: dict[str, Any], req_id: str) -> str:
    api_base = str(
        company.get("oracle_api_base")
        or "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest"
    ).rstrip("/")
    site_number = str(company.get("oracle_site_number") or "CX_1001")
    return (
        f"{api_base}/recruitingCEJobRequisitionDetails?onlyData=true&expand=all"
        f"&finder=ById;Id={urllib.parse.quote(str(req_id))},siteNumber={site_number}"
    )


def phenom_widgets_url(company: dict[str, Any]) -> str:
    explicit = str(company.get("phenom_widgets_url") or "").strip()
    if explicit:
        return explicit
    base = str(company.get("phenom_base") or company.get("browse_url") or "").strip()
    if not base:
        return ""
    parsed = urllib.parse.urlsplit(base)
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/widgets"


def phenom_discover_refnum(browse_url: str, counter: RequestCounter) -> str | None:
    url = str(browse_url or "").strip()
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    search_url = url
    if "search-results" not in parsed.path:
        search_url = f"{parsed.scheme}://{parsed.netloc}/global/en/search-results"
    code, body = http_get(search_url, counter=counter)
    if code != 200 or not body:
        return None
    match = re.search(r'"refNum"\s*:\s*"([^"]+)"', body)
    return match.group(1) if match else None


def talentbrew_host(company: dict[str, Any]) -> str:
    return str(
        company.get("talentbrew_host")
        or company.get("site_origin")
        or ""
    ).strip().rstrip("/")


def run_greenhouse_list(company: dict[str, Any], counter: RequestCounter) -> list[int]:
    board = str(company.get("board") or company["id"]).strip()
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    code, body = http_get(url, counter=counter)
    if code != 200:
        return []
    try:
        jobs = json.loads(body).get("jobs") or []
    except json.JSONDecodeError:
        counter.errors.append(f"greenhouse list JSON parse failed for {board}")
        return []
    return [int(j["id"]) for j in jobs if isinstance(j, dict) and j.get("id") is not None]


def fetch_greenhouse_detail(board: str, job_id: int, counter: RequestCounter) -> None:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    http_get(url, counter=counter)


def run_ashby_list(company: dict[str, Any], counter: RequestCounter) -> list[dict[str, Any]]:
    board = str(company.get("ashby_board") or company["id"]).strip()
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    code, body = http_get(url, counter=counter)
    if code != 200:
        return []
    try:
        postings = json.loads(body).get("jobs") or []
    except json.JSONDecodeError:
        counter.errors.append(f"ashby list JSON parse failed for {board}")
        return []
    return [p for p in postings if isinstance(p, dict)]


def run_oracle_list(company: dict[str, Any], keyword: str, counter: RequestCounter, *, limit: int) -> list[str]:
    url = oracle_hcm_search_url(company, keyword, limit=limit)
    code, body = http_get(url, counter=counter)
    if code != 200 or not body:
        return []
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        counter.errors.append("oracle search JSON parse failed")
        return []
    items = payload.get("items") or []
    if not items or not isinstance(items[0], dict):
        return []
    reqs = items[0].get("requisitionList") or []
    return [str(r.get("Id")).strip() for r in reqs if isinstance(r, dict) and r.get("Id")]


def run_talentbrew_list(company: dict[str, Any], keyword: str, counter: RequestCounter) -> list[str]:
    host = talentbrew_host(company)
    if not host:
        counter.errors.append("talentbrew_host missing")
        return []
    url = f"{host}/search-jobs/{urllib.parse.quote(keyword)}"
    code, body = http_get(url, counter=counter)
    if code != 200 or not body:
        return []
    rows = parse_talentbrew_search(body)
    paths: list[str] = []
    for row in rows:
        path = str(row.get("path") or "").lstrip("/")
        if path:
            paths.append(urllib.parse.urljoin(host + "/", path))
    return paths


def run_phenom_list(company: dict[str, Any], keyword: str, counter: RequestCounter, *, limit: int) -> list[str]:
    widgets = phenom_widgets_url(company)
    refnum = str(company.get("phenom_refnum") or "").strip()
    if not refnum:
        refnum = phenom_discover_refnum(str(company.get("browse_url") or company.get("phenom_base") or ""), counter) or ""
    if not widgets or not refnum:
        counter.errors.append("phenom widgets/refnum missing")
        return []
    payload = {
        "lang": str(company.get("phenom_lang") or "en_global"),
        "deviceType": "desktop",
        "country": str(company.get("phenom_country") or "global"),
        "pageName": "search-results",
        "size": max(1, min(limit, 50)),
        "from": 0,
        "jobs": True,
        "counts": True,
        "keywords": keyword,
        "refNum": refnum,
        "ddoKey": "refineSearch",
        "siteType": str(company.get("phenom_site_type") or "external"),
        "global": bool(company.get("phenom_global", True)),
    }
    code, body = http_post_json(widgets, payload, counter=counter)
    if code != 200 or not body:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        counter.errors.append("phenom search JSON parse failed")
        return []
    block = data.get("refineSearch") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    jobs = ((block.get("data") or {}).get("jobs") or []) if isinstance(block.get("data"), dict) else []
    return [str(j.get("jobId") or j.get("jobSeqNo") or "").strip() for j in jobs if isinstance(j, dict)]


def phenom_fetch_detail(company: dict[str, Any], job_id: str, counter: RequestCounter) -> None:
    widgets = phenom_widgets_url(company)
    refnum = str(company.get("phenom_refnum") or "").strip()
    if not refnum:
        refnum = phenom_discover_refnum(str(company.get("browse_url") or company.get("phenom_base") or ""), counter) or ""
    if not widgets or not refnum or not job_id:
        return
    payload = {
        "lang": str(company.get("phenom_lang") or "en_global"),
        "deviceType": "desktop",
        "country": str(company.get("phenom_country") or "global"),
        "pageName": "job-details",
        "ddoKey": "jobDetail",
        "jobId": job_id,
        "refNum": refnum,
        "siteType": str(company.get("phenom_site_type") or "external"),
    }
    http_post_json(widgets, payload, counter=counter)


def list_fetch(
    company: dict[str, Any], keyword: str, counter: RequestCounter
) -> tuple[str, list[Any], str]:
    """Single list/board fetch. Returns (ats, all_targets, notes)."""
    ctype = str(company.get("type") or "").strip().lower()
    cid = str(company.get("id") or "")

    if ctype == "greenhouse":
        job_ids = run_greenhouse_list(company, counter)
        note = f"{len(job_ids)} jobs on board"
        return "greenhouse", job_ids, note

    if ctype == "ashby":
        postings = run_ashby_list(company, counter)
        urls = [ashby_posting_url(company, p) for p in postings]
        urls = [u for u in urls if u]
        note = f"{len(postings)} jobs listed, {len(urls)} posting URLs"
        return "ashby", urls, note

    if ctype == "oracle_hcm":
        req_ids = run_oracle_list(
            company,
            keyword,
            counter,
            limit=max(25, QUICKJOBS_ORACLE_MAX_DETAILS),
        )
        note = f"{len(req_ids)} reqs in search page"
        return "oracle_hcm", req_ids, note

    if ctype == "talentbrew":
        urls = run_talentbrew_list(company, keyword, counter)
        note = f"{len(urls)} job links parsed from search HTML"
        return "talentbrew", urls, note

    if ctype == "phenom":
        job_ids = run_phenom_list(company, keyword, counter, limit=50)
        note = f"{len(job_ids)} jobs in phenom search"
        return "phenom", job_ids, note

    counter.errors.append(f"unsupported type {ctype}")
    return ctype, [], f"{cid}: unsupported type {ctype!r}"


def cap_targets(
    ats: str, company: dict[str, Any], targets: list[Any], detail_cap: int
) -> tuple[list[Any], str]:
    if ats == "oracle_hcm":
        effective_cap = min(detail_cap, QUICKJOBS_ORACLE_MAX_DETAILS, len(targets))
        note = (
            f"quickjobs max_details default={QUICKJOBS_ORACLE_MAX_DETAILS}; "
            f"test cap={effective_cap} of {len(targets)} search hits"
        )
        return targets[:effective_cap], note
    if ats == "greenhouse":
        effective_cap = min(detail_cap, len(targets))
        note = (
            f"quickjobs fetches detail for every filtered board job "
            f"({len(targets)} on board); test cap={effective_cap}"
        )
        return targets[:effective_cap], note
    if ats == "ashby":
        effective_cap = min(detail_cap, len(targets))
        note = (
            f"quickjobs may GET posting HTML per parsed job ({len(targets)} URLs); "
            f"test cap={effective_cap}"
        )
        return targets[:effective_cap], note
    if ats == "talentbrew":
        max_details = int(company.get("max_details") or 0)
        effective_cap = min(detail_cap, len(targets))
        note = (
            f"config type=talentbrew; company max_details={max_details}; "
            f"test cap={effective_cap} of {len(targets)} links"
        )
        return targets[:effective_cap], note
    if ats == "phenom":
        effective_cap = min(detail_cap, QUICKJOBS_ORACLE_MAX_DETAILS, len(targets))
        note = (
            f"quickjobs max_details default={QUICKJOBS_ORACLE_MAX_DETAILS}; "
            f"test cap={effective_cap} of {len(targets)} search hits"
        )
        return targets[:effective_cap], note
    effective_cap = min(detail_cap, len(targets))
    return targets[:effective_cap], f"test cap={effective_cap}"


def run_list_only(company: dict[str, Any], keyword: str) -> TimedRun:
    counter = RequestCounter()
    cid = str(company.get("id") or "")
    t0 = time.perf_counter()
    ats, _targets, notes = list_fetch(company, keyword, counter)
    elapsed = time.perf_counter() - t0
    return TimedRun(
        company=cid,
        ats=ats,
        phase="list_only",
        requests=counter.count,
        elapsed_sec=elapsed,
        list_count=counter.count,
        errors=list(counter.errors),
        notes=notes,
    )


def _fetch_details(
    company: dict[str, Any],
    ats: str,
    targets: list[Any],
    counter: RequestCounter,
    *,
    parallel: int | None,
) -> None:
    if not targets:
        return

    def _one(target: Any) -> None:
        if ats == "greenhouse":
            board = str(company.get("board") or company["id"]).strip()
            fetch_greenhouse_detail(board, int(target), counter)
        elif ats == "ashby":
            http_get(str(target), counter=counter)
        elif ats == "oracle_hcm":
            http_get(oracle_hcm_detail_url(company, str(target)), counter=counter)
        elif ats == "talentbrew":
            http_get(str(target), counter=counter)
        elif ats == "phenom":
            phenom_fetch_detail(company, str(target), counter)

    if parallel and parallel > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
            list(pool.map(_one, targets))
    else:
        for target in targets:
            _one(target)


def run_full(
    company: dict[str, Any],
    keyword: str,
    detail_cap: int,
    *,
    parallel: int | None,
    phase_name: str,
) -> TimedRun:
    cid = str(company.get("id") or "")
    counter = RequestCounter()
    t0 = time.perf_counter()
    ats, all_targets, list_note = list_fetch(company, keyword, counter)
    list_requests = counter.count
    targets, cap_note = cap_targets(ats, company, all_targets, detail_cap)
    _fetch_details(company, ats, targets, counter, parallel=parallel)
    elapsed = time.perf_counter() - t0
    return TimedRun(
        company=cid,
        ats=ats,
        phase=phase_name,
        requests=counter.count,
        elapsed_sec=elapsed,
        list_count=list_requests,
        detail_count=len(targets),
        errors=list(counter.errors),
        notes=f"{list_note}; {cap_note}",
    )


def print_results(results: list[TimedRun]) -> None:
    headers = ("company", "ats", "phase", "requests", "elapsed_s", "details", "errors", "notes")
    rows = []
    for r in results:
        rows.append(
            (
                r.company,
                r.ats,
                r.phase,
                str(r.requests),
                f"{r.elapsed_sec:.2f}",
                str(r.detail_count),
                r.error_summary() or "-",
                (r.notes[:70] + "…") if len(r.notes) > 70 else (r.notes or "-"),
            )
        )
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(col)) for w, col in zip(widths, row)]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--companies",
        nargs="+",
        default=list(DEFAULT_COMPANY_IDS),
        help=f"Company ids from {BASE_JSON.name} (default: stall-log set)",
    )
    parser.add_argument(
        "--keyword",
        default=DEFAULT_SEARCH_KEYWORD,
        help="Search keyword for oracle/talentbrew/phenom list APIs",
    )
    parser.add_argument(
        "--detail-cap",
        type=int,
        default=DEFAULT_DETAIL_CAP,
        help="Max detail fetches per company in full_* phases",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Also run full_parallel_4 (4-way detail fetch) vs full_sequential",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Skip full scrape phases",
    )
    parser.add_argument(
        "--full-only",
        action="store_true",
        help="Skip list_only phase",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    companies = load_companies(args.companies)
    results: list[TimedRun] = []

    print(
        f"ATS API timing | detail_cap={args.detail_cap} keyword={args.keyword!r} "
        f"| host={os.uname().nodename}",
        flush=True,
    )
    print(f"base_json={BASE_JSON}", flush=True)
    print("", flush=True)

    for company in companies:
        if not args.full_only:
            row = run_list_only(company, args.keyword)
            results.append(row)
            print(
                f"  {row.company} list_only: {row.requests} req {row.elapsed_sec:.2f}s"
                + (f" ERR {row.error_summary()}" if row.errors else ""),
                flush=True,
            )
        if not args.list_only:
            row = run_full(
                company,
                args.keyword,
                args.detail_cap,
                parallel=None,
                phase_name="full_sequential",
            )
            results.append(row)
            print(
                f"  {row.company} full_sequential: {row.requests} req {row.elapsed_sec:.2f}s"
                + (f" ERR {row.error_summary()}" if row.errors else ""),
                flush=True,
            )
            if args.parallel:
                row = run_full(
                    company,
                    args.keyword,
                    args.detail_cap,
                    parallel=PARALLEL_WORKERS,
                    phase_name="full_parallel_4",
                )
                results.append(row)
                print(
                    f"  {row.company} full_parallel_4: {row.requests} req {row.elapsed_sec:.2f}s"
                    + (f" ERR {row.error_summary()}" if row.errors else ""),
                    flush=True,
                )

    print("", flush=True)
    print_results(results)
    failed = [r for r in results if r.errors]
    if failed:
        print("", flush=True)
        print(f"{len(failed)} phase(s) reported HTTP/parse errors (see table).", flush=True)
    return 1 if any(r.errors for r in results if r.phase == "list_only") else 0


if __name__ == "__main__":
    sys.exit(main())
