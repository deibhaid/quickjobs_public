#!/usr/bin/env python3
"""Probe efficient scrape methods for quickjobs hub / blocked Workday employers.

Tests (HTTP only, no Playwright):
  - Workday CXS POST (from blocked-sources TSV browse_url)
  - Eightfold PCSX /api/pcsx/search
  - Oracle HCM recruitingCEJobRequisitions
  - Greenhouse boards-api
  - Phenom /widgets refineSearch (refNum from HTML)
  - SuccessFactors HTML jobTitle-link count

Output: ~/ws/scriptdir/output/quickjobs-scrape-method-probe.tsv
        ~/ws/scriptdir/output/quickjobs-scrape-method-probe-summary.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import hub_http
import hub_tools  # noqa: E402

DEFAULT_BASE = hub_tools.BASE_JSON
sys.path.insert(0, str(hub_tools.HUBS_DIR))

DEFAULT_BLOCKED_TSV = hub_tools.BLOCKED_TSV
DEFAULT_OUT_TSV = hub_tools.report_path("quickjobs-scrape-method-probe.tsv")
DEFAULT_OUT_SUMMARY = hub_tools.report_path("quickjobs-scrape-method-probe-summary.txt")
DEFAULT_RECOMMEND_TSV = hub_tools.report_path("quickjobs-422-recommendations.tsv")
SKIP_APPLY_TYPES = frozenset({"hub", "entries"})
APPLY_SCRAPE_TYPES = frozenset(
    {"phenom", "oracle_hcm", "greenhouse", "successfactors", "talentbrew", "playwright"}
)
METHOD_TO_TYPE = {
    "phenom_widgets": "phenom",
    "oracle_hcm": "oracle_hcm",
    "greenhouse": "greenhouse",
    "successfactors_html": "successfactors",
    "talentbrew_search": "talentbrew",
    "eightfold_pcsx": "playwright",
    "workday_cxs": "playwright",
    "taleo_searchjobs": "taleo_cws",
}
USER_AGENT = hub_http.BROWSER_USER_AGENT
PROBE_KEYWORD = "devops"
ORACLE_HTML_SCAN = 250_000

# Extra seed URLs when hub_url is a marketing page or wrong path (company id -> list).
KNOWN_HUB_URL_ALIASES: dict[str, list[str]] = {
    "duke-energy": [
        "https://www.duke-energy.com/our-company/careers",
        "https://dukeenergy.wd1.myworkdayjobs.com/Search",
    ],
    "marvell-technology": [
        "https://marvell.wd1.myworkdayjobs.com/MarvellCareers",
    ],
    "advanced-micro-devices": [
        "https://careers.amd.com/careers-home/jobs",
        "https://careers.amd.com/jobs",
    ],
    "howmet-aerospace": ["https://www.howmet.com/joinus/"],
    "abbott": ["https://www.jobs.abbott/us/en"],
    "agilent": [
        "https://careers.agilent.com/",
        "https://agilent.wd5.myworkdayjobs.com/Agilent_Careers",
    ],
    "caterpillar": [
        "https://careers.caterpillar.com/en/",
        "https://cat.wd5.myworkdayjobs.com/CaterpillarCareers",
    ],
    "best-buy": [
        "https://jobs.bestbuy.com/bby",
        "https://bestbuy.wd5.myworkdayjobs.com/BestBuyCareers",
    ],
}
WORKDAY_CXS_BODY = json.dumps(
    {"appliedFacets": {}, "limit": 10, "offset": 0, "searchText": PROBE_KEYWORD}
).encode()


@dataclass
class ProbeRow:
    id: str
    source: str
    url_tested: str
    method: str
    status: str
    total_jobs: str
    keyword_hits: str
    latency_ms: int
    config_hint: str
    error: str


def http_get(
    url: str,
    timeout: int = hub_http.DEFAULT_TIMEOUT,
    *,
    referer: str = "",
) -> tuple[int, str, str]:
    return hub_http.http_get(url, timeout=timeout, referer=referer)


def http_post_json(url: str, payload: dict, timeout: int = hub_http.DEFAULT_TIMEOUT) -> tuple[int, str]:
    return hub_http.http_post_json(url, payload, timeout=timeout)


def parse_workday_cxs(browse_url: str) -> tuple[str, str, str] | None:
    match = re.search(
        r"https://([^/]+)\.myworkdayjobs\.com/(?:[^/]+/)?([^/?#]+)",
        str(browse_url or "").strip(),
    )
    if not match:
        return None
    host, site = match.group(1), match.group(2)
    tenant = host.split(".")[0]
    if not tenant or not site:
        return None
    return host, tenant, site


def probe_workday_cxs(company_id: str, browse_url: str) -> ProbeRow:
    t0 = time.monotonic()
    target = parse_workday_cxs(browse_url)
    if not target:
        return ProbeRow(
            company_id, "blocked_tsv", browse_url, "workday_cxs", "skip", "", "", 0, "", "invalid browse_url"
        )
    host, tenant, site = target
    url = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    req = urllib.request.Request(
        url,
        data=WORKDAY_CXS_BODY,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read().decode("utf-8", "replace")
        data = json.loads(body)
        jobs = data.get("jobPostings") or []
        total = int(data.get("total") or len(jobs))
        ms = int((time.monotonic() - t0) * 1000)
        hint = f'type=playwright playwright_kind=workday browse_url="{browse_url}"'
        return ProbeRow(
            company_id,
            "blocked_tsv",
            url,
            "workday_cxs",
            "ok",
            str(total),
            str(len(jobs)),
            ms,
            hint,
            "",
        )
    except urllib.error.HTTPError as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return ProbeRow(
            company_id,
            "blocked_tsv",
            url,
            "workday_cxs",
            "fail",
            "",
            "",
            ms,
            "workday_skip_playwright_on_422: false for playwright fallback",
            f"HTTP {exc.code}",
        )
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return ProbeRow(company_id, "blocked_tsv", url, "workday_cxs", "fail", "", "", ms, "", str(exc))


def eightfold_domain_from_url(url: str) -> tuple[str, str] | None:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    if not host:
        return None
    params = urllib.parse.parse_qs(parsed.query)
    domain = (params.get("domain") or [None])[0]
    if domain:
        return host, str(domain)
    if host.startswith("careers.") and host.count(".") >= 2:
        return host, host[len("careers.") :]
    if host.startswith("jobs.") and host.count(".") >= 2:
        return host, host[len("jobs.") :]
    return None


def discover_eightfold_domain_from_html(body: str) -> str | None:
    """Hidden domain field on Eightfold-powered marketing careers pages."""
    snippet = (body or "")[:120_000]
    for pattern in (
        r'name=["\']domain["\'][^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\'][^>]*name=["\']domain["\']',
        r'careers/visitor\?domain=([^&"\'\s]+)',
        r'"domain"\s*:\s*"([a-z0-9.-]+\.[a-z]{2,})"',
    ):
        match = re.search(pattern, snippet, re.I)
        if match:
            return match.group(1).strip()
    return None


def eightfold_probe_targets(start_url: str, body: str = "") -> list[tuple[str, str, str]]:
    """(api_host, pcsx_domain, browse_url) candidates for Eightfold PCSX."""
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(host: str, domain: str, browse: str) -> None:
        key = (host.lower(), domain.lower())
        if key in seen or not host or not domain:
            return
        seen.add(key)
        out.append((host, domain, browse.rstrip("/") or f"https://{host}/"))

    parsed = urllib.parse.urlsplit(start_url)
    host = parsed.netloc
    browse_base = start_url.split("?")[0].rstrip("/") or f"https://{host}/"

    if body:
        dom = discover_eightfold_domain_from_html(body)
        if dom:
            add(host, dom, browse_base)
            if host.startswith("careers."):
                jobs_host = "jobs." + host[len("careers.") :]
                add(jobs_host, dom, f"https://{jobs_host}/")
        if re.search(r"eightfold|wordpress_eightfold", body, re.I):
            if host.startswith("careers.") and host.count(".") >= 2:
                slug_domain = host[len("careers.") :]
                add("jobs." + slug_domain, slug_domain, f"https://jobs.{slug_domain}/")
                if not dom:
                    add(host, slug_domain, browse_base)

    direct = eightfold_domain_from_url(start_url)
    if direct:
        add(direct[0], direct[1], browse_base)

    return out


def probe_eightfold_pcsx(company_id: str, start_url: str, body: str = "") -> ProbeRow | None:
    targets = eightfold_probe_targets(start_url, body)
    if not targets:
        return None
    best: ProbeRow | None = None
    for host, domain, browse in targets:
        url = (
            f"https://{host}/api/pcsx/search?"
            + urllib.parse.urlencode(
                {"domain": domain, "start": "0", "num": "10", "keyword": PROBE_KEYWORD}
            )
        )
        t0 = time.monotonic()
        code, _, resp_body = http_get(url)
        ms = int((time.monotonic() - t0) * 1000)
        if code != 200:
            row = ProbeRow(
                company_id, "hub", start_url, "eightfold_pcsx", "fail", "", "", ms, "", f"HTTP {code}"
            )
            if not best:
                best = row
            continue
        try:
            data = json.loads(resp_body)
            block = data.get("data") if isinstance(data, dict) else {}
            positions = (block or {}).get("positions") or []
            total = int((block or {}).get("count") or len(positions))
        except json.JSONDecodeError:
            continue
        hint = (
            f'type=playwright playwright_kind=eightfold eightfold_fetch=pcsx '
            f'browse_url="{browse}"'
        )
        row = ProbeRow(
            company_id,
            "hub",
            url,
            "eightfold_pcsx",
            "ok" if total > 0 else "empty",
            str(total),
            str(len(positions)),
            ms,
            hint,
            "",
        )
        if row.status == "ok" and (not best or best.status != "ok"):
            best = row
        elif row.status == "ok" and best and int(row.total_jobs or 0) > int(best.total_jobs or 0):
            best = row
        elif not best:
            best = row
    return best


def embed_ats_urls_from_html(body: str, base_url: str) -> list[str]:
    """Extract embedded ATS career URLs from HTML (iframe/src/href)."""
    if not body:
        return []
    blob = body[:150_000]
    parsed = urllib.parse.urlsplit(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
    urls: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        u = raw.strip().rstrip("\\").split('"')[0].split("'")[0]
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/") and origin:
            u = origin + u
        if not u.startswith("http"):
            return
        if u not in seen:
            seen.add(u)
            urls.append(u)

    ats_host = re.compile(
        r"https?://[^\"'\s<>]*(?:"
        r"myworkdayjobs\.com|\.icims\.com|greenhouse\.io|lever\.co|ashbyhq\.com|"
        r"phenompeople|phenom\.com|oraclecloud\.com|smartrecruiters\.com|"
        r"eightfold\.ai|taleo\.net|brassring\.com|jobvite\.com|avature\.net|"
        r"successfactors\.com|talentbrew|radancy"
        r")[^\"'\s<>]*",
        re.I,
    )
    for match in ats_host.finditer(blob):
        add(match.group(0))
    for match in re.finditer(r'(?:href|src)=["\']([^"\']+)["\']', blob, re.I):
        href = match.group(1)
        if any(
            token in href.lower()
            for token in (
                "workday",
                "icims",
                "greenhouse",
                "lever",
                "ashby",
                "phenom",
                "oraclecloud",
                "smartrecruiters",
                "eightfold",
                "taleo",
                "brassring",
                "jobvite",
                "avature",
                "successfactors",
                "search-jobs",
                "jobTitle-link",
            )
        ):
            add(href)
    return urls


def discover_oracle_from_html(final_url: str, body: str) -> dict[str, str] | None:
    blob = final_url + " " + body[:ORACLE_HTML_SCAN]
    host_match = re.search(
        r"(https://[a-z0-9.-]+\.fa\.[a-z0-9.]+\.oraclecloud\.com)/hcmRestApi",
        blob,
        re.I,
    )
    if not host_match:
        host_match = re.search(r"(https://[a-z0-9.-]+\.fa\.[a-z0-9.]+\.oraclecloud\.com)", blob, re.I)
    if not host_match:
        return None
    api_base = host_match.group(1).rstrip("/") + "/hcmRestApi/resources/latest"
    site_match = re.search(r"sites/(CX_\d+)", blob, re.I)
    site_number = site_match.group(1) if site_match else "CX_1001"
    ce_match = re.search(r"(https://[a-z0-9.-]+\.fa\.[a-z0-9.]+\.oraclecloud\.com/hcmUI/CandidateExperience/en/sites/[^\"'\s]+)", blob, re.I)
    out = {"oracle_api_base": api_base, "oracle_site_number": site_number}
    if ce_match:
        out["oracle_ce_base"] = ce_match.group(1).split("?")[0].rstrip("/")
        out["browse_url"] = out["oracle_ce_base"] + "/jobs"
    return out


def probe_oracle_hcm(company_id: str, start_url: str, body: str, final_url: str) -> ProbeRow | None:
    discovered = discover_oracle_from_html(final_url, body)
    if not discovered:
        return None
    api_base = discovered["oracle_api_base"]
    site_number = discovered["oracle_site_number"]
    facets = (
        "LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3B"
        "ORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS"
    )
    finder = (
        f"findReqs;siteNumber={site_number},facetsList={facets},limit=10,"
        f"keyword={urllib.parse.quote(PROBE_KEYWORD)}"
    )
    url = f"{api_base}/recruitingCEJobRequisitions?onlyData=true&expand=all&finder={finder}"
    t0 = time.monotonic()
    code, _, resp_body = http_get(url)
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(company_id, "hub", url, "oracle_hcm", "fail", "", "", ms, "", f"HTTP {code}")
    try:
        payload = json.loads(resp_body)
        items = payload.get("items") or []
        row = items[0] if items else {}
        total = int(row.get("TotalJobsCount") or 0)
        reqs = row.get("requisitionList") or []
    except json.JSONDecodeError:
        return ProbeRow(company_id, "hub", url, "oracle_hcm", "fail", "", "", ms, "", "invalid JSON")
    if total == 0:
        finder_open = f"findReqs;siteNumber={site_number},facetsList={facets},limit=10,keyword="
        url_open = f"{api_base}/recruitingCEJobRequisitions?onlyData=true&expand=all&finder={finder_open}"
        code2, _, resp2 = http_get(url_open)
        if code2 == 200:
            try:
                payload2 = json.loads(resp2)
                items2 = payload2.get("items") or []
                row2 = items2[0] if items2 else {}
                total = int(row2.get("TotalJobsCount") or 0)
                if total > 0:
                    reqs = row2.get("requisitionList") or []
                    url = url_open
            except json.JSONDecodeError:
                pass
    hint = "type=oracle_hcm " + " ".join(f'{k}="{v}"' for k, v in discovered.items())
    return ProbeRow(
        company_id,
        "hub",
        url,
        "oracle_hcm",
        "ok" if total > 0 else "empty",
        str(total),
        str(len(reqs)),
        ms,
        hint,
        "",
    )


def discover_greenhouse_board(url: str, body: str) -> str | None:
    blob = url + " " + body[:60_000]
    for pattern in (
        r'boards-api\.greenhouse\.io/v1/boards/([^/"?\s]+)',
        r'job-boards\.greenhouse\.io/embed/job_board\?for=([^"&\s]+)',
        r'"board_token"\s*:\s*"([^"]+)"',
        r"boards\.greenhouse\.io/([^/\"?\s]+)",
    ):
        match = re.search(pattern, blob, re.I)
        if match:
            return match.group(1)
    return None


def probe_greenhouse(company_id: str, start_url: str, body: str) -> ProbeRow | None:
    board = discover_greenhouse_board(start_url, body)
    if not board:
        return None
    api = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    t0 = time.monotonic()
    code, _, resp = http_get(api)
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(company_id, "hub", api, "greenhouse", "fail", "", "", ms, "", f"HTTP {code}")
    try:
        jobs = json.loads(resp).get("jobs") or []
    except json.JSONDecodeError:
        return ProbeRow(company_id, "hub", api, "greenhouse", "fail", "", "", ms, "", "invalid JSON")
    hits = [
        j
        for j in jobs
        if PROBE_KEYWORD in str(j.get("title") or "").lower()
    ]
    hint = f'type=greenhouse board="{board}" browse_url="{start_url}"'
    return ProbeRow(
        company_id,
        "hub",
        api,
        "greenhouse",
        "ok" if jobs else "empty",
        str(len(jobs)),
        str(len(hits)),
        ms,
        hint,
        "",
    )


def phenom_search_url(hub_url: str, final_url: str) -> str:
    parsed = urllib.parse.urlsplit(final_url or hub_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if "search-results" in (final_url or ""):
        return final_url.split("?")[0] + f"?q={PROBE_KEYWORD}"
    return f"{base}/global/en/search-results?q={PROBE_KEYWORD}"


def discover_phenom_refnum(body: str) -> str | None:
    for pattern in (r'"refNum"\s*:\s*"([^"]+)"', r"'refNum'\s*:\s*'([^']+)'"):
        match = re.search(pattern, body)
        if match:
            return match.group(1)
    return None


def probe_phenom(company_id: str, hub_url: str, final_url: str, body: str) -> ProbeRow | None:
    if "phenom" not in body.lower() and "phenompeople" not in body.lower():
        if not re.search(r"jobs\.[a-z0-9.-]+\.(com|net)/global", final_url, re.I):
            return None
    ref = discover_phenom_refnum(body)
    if not ref:
        search_page = phenom_search_url(hub_url, final_url)
        code, _, search_body = http_get(search_page)
        if code != 200:
            return None
        ref = discover_phenom_refnum(search_body)
        body = search_body
    if not ref:
        return None
    parsed = urllib.parse.urlsplit(final_url or hub_url)
    widgets = f"{parsed.scheme}://{parsed.netloc}/widgets"
    payload = {
        "lang": "en_global",
        "deviceType": "desktop",
        "country": "global",
        "pageName": "search-results",
        "size": 10,
        "from": 0,
        "jobs": True,
        "counts": True,
        "keywords": PROBE_KEYWORD,
        "refNum": ref,
        "ddoKey": "refineSearch",
        "siteType": "external",
        "global": True,
    }
    t0 = time.monotonic()
    code, resp = http_post_json(widgets, payload)
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(company_id, "hub", widgets, "phenom_widgets", "fail", "", "", ms, "", f"HTTP {code}")
    try:
        data = json.loads(resp)
        block = data.get("refineSearch") or {}
        total = int(block.get("totalHits") or 0)
        jobs = ((block.get("data") or {}).get("jobs") or []) if isinstance(block.get("data"), dict) else []
    except json.JSONDecodeError:
        return ProbeRow(company_id, "hub", widgets, "phenom_widgets", "fail", "", "", ms, "", "invalid JSON")
    base = f"{parsed.scheme}://{parsed.netloc}"
    hint = (
        f'type=phenom phenom_base="{base}" phenom_refnum="{ref}" '
        f'browse_url="{final_url or hub_url}"'
    )
    return ProbeRow(
        company_id,
        "hub",
        widgets,
        "phenom_widgets",
        "ok" if total > 0 else "empty",
        str(total),
        str(len(jobs)),
        ms,
        hint,
        "",
    )


def probe_successfactors(company_id: str, start_url: str, body: str) -> ProbeRow | None:
    if "jobTitle-link" not in body and "successfactors" not in body.lower():
        return None
    matches = re.findall(r'class="jobTitle-link[^"]*"[^>]*href="([^"]+)"', body, flags=re.I)
    if not matches:
        return None
    hits = [m for m in matches if PROBE_KEYWORD in m.lower()]
    base = successfactors_search_base(start_url)
    hint = f'type=successfactors search_base="{base}" browse_url="{start_url}"'
    return ProbeRow(
        company_id,
        "hub",
        start_url,
        "successfactors_html",
        "ok" if matches else "empty",
        str(len(matches)),
        str(len(hits)),
        0,
        hint,
        "",
    )


def successfactors_search_base(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    if "/go/search" in path.lower():
        return f"{origin}/go/Search/"
    if path.endswith("/search"):
        return f"{origin}/search/"
    return f"{origin}/search/"


def discover_workday_browse_urls(body: str, final_url: str) -> list[str]:
    """Extract myworkdayjobs career site URLs (skip login-only paths)."""
    cleaned = (body or "").replace("&amp;", "&").replace("\\/", "/").replace("&#34;", '"')
    blob = (final_url or "") + " " + cleaned[:ORACLE_HTML_SCAN]
    out: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(
        r"https?://([a-z0-9-]+\.myworkdayjobs\.com(?:/[^\"'\s<>\\]*)?)",
        blob,
        re.I,
    ):
        raw = match.group(0).split("\\")[0].split('"')[0].split("'")[0]
        raw = raw.split("?")[0].rstrip("/")
        if "/login" in raw.lower():
            continue
        if raw not in seen:
            seen.add(raw)
            out.append(raw)
    return out


def probe_workday_from_html(
    company_id: str, hub_url: str, final_url: str, body: str
) -> ProbeRow | None:
    """When marketing HTML embeds Workday, try CXS on discovered tenant URLs."""
    direct = [u for u in (final_url, hub_url) if u and "myworkdayjobs.com" in u.lower()]
    for browse in direct:
        row = probe_workday_cxs(company_id, browse.split("?")[0].rstrip("/"))
        if row.status == "ok":
            return row
    best: ProbeRow | None = None
    for browse in discover_workday_browse_urls(body, final_url):
        row = probe_workday_cxs(company_id, browse)
        if row.status == "ok" and int(row.total_jobs or 0) > 0:
            return row
        if row.status == "ok" and not best:
            best = row
    return best


def discover_jobvite_company(body: str, final_url: str) -> str | None:
    blob = (final_url or "") + " " + (body or "")[:120_000]
    for pattern in (
        r"jobs\.jobvite\.com/([^/\"?\s]+)",
        r"jobvite\.com/[^/]+/([^/\"?\s]+)/jobs",
        r'"companyId"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, blob, re.I)
        if match:
            return match.group(1)
    return None


def probe_jobvite(company_id: str, start_url: str, body: str, final_url: str) -> ProbeRow | None:
    company = discover_jobvite_company(body, final_url)
    if not company:
        return None
    browse = f"https://jobs.jobvite.com/{company}/jobs"
    t0 = time.monotonic()
    code, fin, page = http_get(browse)
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(company_id, "hub", browse, "jobvite_html", "fail", "", "", ms, "", f"HTTP {code}")
    jobs = re.findall(r'class="jv-job-list__title[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"', page, re.I)
    if not jobs:
        jobs = re.findall(r'href="(/[^"]+/job/[^"]+)"', page, re.I)
    hint = f'type=hub hub_url="{browse}" browse_url="{fin or browse}"'
    return ProbeRow(
        company_id,
        "hub",
        fin or browse,
        "jobvite_html",
        "ok" if jobs else "empty",
        str(len(jobs)),
        "",
        ms,
        hint,
        "jobvite: no public JSON API; manual hub",
    )


def discover_brassring_ids(body: str, final_url: str) -> tuple[str, str] | None:
    blob = (final_url or "") + " " + (body or "")[:120_000]
    for pattern in (
        r"partnerid=(\d+)[^&\"'\s]*&(?:amp;)?siteid=(\d+)",
        r"siteid=(\d+)[^&\"'\s]*&(?:amp;)?partnerid=(\d+)",
    ):
        match = re.search(pattern, blob, re.I)
        if match:
            return match.group(1), match.group(2)
    return None


def probe_brassring(company_id: str, start_url: str, body: str, final_url: str) -> ProbeRow | None:
    ids = discover_brassring_ids(body, final_url)
    if not ids:
        return None
    partner_id, site_id = ids
    home = (
        f"https://sjobs.brassring.com/TGnewUI/Search/Home/Home"
        f"?partnerid={partner_id}&siteid={site_id}"
    )
    referer = home
    api = "https://sjobs.brassring.com/TgNewUI/Search/Ajax/MatchedJobs"
    payload = {
        "partnerId": int(partner_id),
        "siteId": int(site_id),
        "keyword": PROBE_KEYWORD,
        "pageNumber": 1,
        "pageSize": 10,
    }
    t0 = time.monotonic()
    code, resp = hub_http.http_post_json(
        api,
        payload,
        referer=referer,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(
            company_id, "hub", home, "brassring_ajax", "fail", "", "", ms, "", f"HTTP {code}"
        )
    total = len(re.findall(r'"JobTitle"', resp)) or len(re.findall(r"jobtitle", resp, re.I))
    hint = (
        f'type=hub hub_url="{home}" browse_url="{home}" '
        f'brassring_partner="{partner_id}" brassring_site="{site_id}"'
    )
    return ProbeRow(
        company_id,
        "hub",
        api,
        "brassring_ajax",
        "ok" if total else "empty",
        str(total),
        "",
        ms,
        hint,
        "brassring: session Ajax; manual hub unless fetcher added",
    )


def probe_avature(company_id: str, start_url: str, body: str, final_url: str) -> ProbeRow | None:
    blob = (final_url or "") + " " + (body or "")[:120_000]
    host_match = re.search(r"https?://([a-z0-9-]+\.avature\.net)", blob, re.I)
    if not host_match:
        return None
    host = host_match.group(1).lower()
    search = f"https://{host}/careers/SearchJobs"
    t0 = time.monotonic()
    code, fin, page = http_get(search)
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(company_id, "hub", search, "avature_html", "fail", "", "", ms, "", f"HTTP {code}")
    jobs = re.findall(r'class="[^"]*jobTitle[^"]*"[^>]*href="([^"]+)"', page, re.I)
    if not jobs:
        jobs = re.findall(r'href="(/careers/JobDetail[^"]+)"', page, re.I)
    hint = f'type=hub hub_url="{search}" browse_url="{fin or search}" avature_host="{host}"'
    return ProbeRow(
        company_id,
        "hub",
        fin or search,
        "avature_html",
        "ok" if jobs else "empty",
        str(len(jobs)),
        "",
        ms,
        hint,
        "avature: HTML scrape; manual hub unless fetcher added",
    )


def discover_adp_portal(body: str, final_url: str) -> str | None:
    blob = (final_url or "") + " " + (body or "")[:120_000]
    match = re.search(
        r"(https://workforcenow\.adp\.com/mascsr/default/careersite/[^\"'\s<>]+)",
        blob,
        re.I,
    )
    if match:
        return match.group(1).split("?")[0]
    match = re.search(r"cid=([0-9a-f-]{36})", blob, re.I)
    if match:
        return f"https://workforcenow.adp.com/mascsr/default/careersite/{match.group(1)}"
    return None


def probe_adp(company_id: str, start_url: str, body: str, final_url: str) -> ProbeRow | None:
    portal = discover_adp_portal(body, final_url)
    if not portal:
        return None
    api = portal.rstrip("/") + "/jobs"
    t0 = time.monotonic()
    code, fin, resp = http_get(api)
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(company_id, "hub", portal, "adp_jobs", "fail", "", "", ms, "", f"HTTP {code}")
    try:
        data = json.loads(resp)
        jobs = data if isinstance(data, list) else data.get("jobs") or data.get("jobRequisitions") or []
    except json.JSONDecodeError:
        jobs = re.findall(r'"requisitionTitle"', resp)
    hint = f'type=hub hub_url="{portal}" browse_url="{portal}" adp_portal="{portal}"'
    return ProbeRow(
        company_id,
        "hub",
        api,
        "adp_jobs",
        "ok" if jobs else "empty",
        str(len(jobs) if isinstance(jobs, list) else jobs),
        "",
        ms,
        hint,
        "adp: OData/jobs endpoint; manual hub unless fetcher added",
    )


def discover_taleo_portal(body: str, final_url: str) -> tuple[str, str, str] | None:
    """Return (host_base, career_section, portal_id) for legacy Taleo searchjobs API."""
    blob = (final_url or "") + " " + (body or "")[:ORACLE_HTML_SCAN]
    host_match = re.search(r"https?://([a-z0-9-]+\.taleo\.net)", blob, re.I)
    if not host_match:
        return None
    host = host_match.group(1).lower()
    section_match = re.search(r"/careersection/([^/\"'\s?]+)/", blob, re.I)
    section = section_match.group(1) if section_match else ""
    portal_match = re.search(r"[?&]portal=([^&\"'\s]+)", blob, re.I)
    portal = portal_match.group(1) if portal_match else ""
    if not section:
        return None
    return host, section, portal


def probe_taleo_legacy(company_id: str, start_url: str, body: str, final_url: str) -> ProbeRow | None:
    found = discover_taleo_portal(body, final_url)
    if not found:
        return None
    host, section, portal = found
    referer = f"https://{host}/careersection/{section}/jobsearch.ftl?lang=en"
    qs = f"lang=en&portal={portal}" if portal else "lang=en"
    api = f"https://{host}/careersection/rest/jobboard/searchjobs?{qs}"
    payload = {
        "multilineEnabled": False,
        "sortingSelection": {"sortBySelectionParam": "1", "ascendingSortingOrder": "false"},
        "fieldData": {
            "fields": {"KEYWORD": PROBE_KEYWORD, "LOCATION": ""},
            "valid": True,
        },
        "pageNo": 1,
    }
    t0 = time.monotonic()
    code, resp = hub_http.http_post_json(
        api,
        payload,
        referer=referer,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(
            company_id, "hub", referer, "taleo_searchjobs", "fail", "", "", ms, "", f"HTTP {code}"
        )
    try:
        data = json.loads(resp)
        jobs = data.get("requisitionList") or []
        total = int((data.get("pagingData") or {}).get("totalCount") or len(jobs))
    except json.JSONDecodeError:
        jobs = []
        total = 0
    hint = (
        f'type=taleo_cws taleo_host="https://{host}/careersection/rest/jobboard" '
        f'taleo_org="{section}" taleo_cws="{portal or section}" browse_url="{referer}"'
    )
    return ProbeRow(
        company_id,
        "hub",
        api,
        "taleo_searchjobs",
        "ok" if total else "empty",
        str(total),
        "",
        ms,
        hint,
        "",
    )


def extra_probe_urls(hub_url: str, final_url: str, body: str) -> list[str]:
    """Additional careers URLs when landing page has no API match."""
    start = (final_url or hub_url).strip()
    if not start:
        return []
    parsed = urllib.parse.urlsplit(start)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    blob = (body or "")[:120_000].lower()
    if "search-jobs" in blob or "talentbrew" in blob or "radancy" in blob:
        add(f"{origin}/search-jobs/{urllib.parse.quote(PROBE_KEYWORD)}")
    if "successfactors" in blob or "jobTitle-link" in blob:
        add(f"{origin}/search/?q={urllib.parse.quote(PROBE_KEYWORD)}")
        add(f"{origin}/go/Search/?q={urllib.parse.quote(PROBE_KEYWORD)}")
        add(f"{origin}/search/")
    if re.search(r"jobs\.[a-z0-9.-]+\.(com|net)", start, re.I):
        add(start)
    if "://careers." in start:
        add(start.replace("://careers.", "://jobs.", 1))
    if "://jobs." in start:
        add(start.replace("://jobs.", "://careers.", 1))
    for wd in discover_workday_browse_urls(body or "", start):
        add(wd)
    for embed in embed_ats_urls_from_html(body or "", start):
        add(embed)
    return urls


def probe_talentbrew(company_id: str, start_url: str) -> ProbeRow | None:
    parsed = urllib.parse.urlsplit(start_url)
    if "/search-jobs" not in start_url:
        host = f"{parsed.scheme}://{parsed.netloc}"
        start_url = f"{host}/search-jobs/{urllib.parse.quote(PROBE_KEYWORD)}"
    t0 = time.monotonic()
    code, final_url, body = http_get(start_url)
    ms = int((time.monotonic() - t0) * 1000)
    if code != 200:
        return ProbeRow(company_id, "hub", start_url, "talentbrew_search", "fail", "", "", ms, "", f"HTTP {code}")
    rows = []
    card_pat = re.compile(
        r'<a[^>]+href="(/job/[^"]+)"[^>]*data-job-id="(\d+)"',
        re.I,
    )
    for match in card_pat.finditer(body):
        chunk = body[match.start() : match.start() + 800]
        title_m = re.search(r"<h2[^>]*>(.*?)</h2>", chunk, re.I | re.DOTALL)
        if not title_m:
            continue
        rows.append(match.group(2))
    ids = rows or re.findall(r'data-job-id="(\d+)"', body)
    if not ids:
        return None
    host = f"{urllib.parse.urlsplit(final_url).scheme}://{urllib.parse.urlsplit(final_url).netloc}"
    hint = (
        f'type=talentbrew talentbrew_host="{host}" '
        f'browse_url="{host}/search-jobs/{urllib.parse.quote(PROBE_KEYWORD)}"'
    )
    return ProbeRow(
        company_id,
        "hub",
        final_url or start_url,
        "talentbrew_search",
        "ok",
        str(len(set(ids))),
        str(len(ids)),
        ms,
        hint,
        "",
    )


def probe_careers_site(company_id: str, careers_url: str, *, source: str = "careers") -> list[ProbeRow]:
    cid = str(company_id or "")
    hub_url = str(careers_url or "").strip()
    if not hub_url:
        return [ProbeRow(cid, source, "", "none", "skip", "", "", 0, "", "missing careers URL")]
    t0 = time.monotonic()
    code, final_url, body = http_get(hub_url)
    fetch_ms = int((time.monotonic() - t0) * 1000)
    partial_body = body if body and not body.startswith("HTTP") else ""

    def collect_from_page(page_url: str, page_body: str, page_final: str) -> list[ProbeRow]:
        out: list[ProbeRow] = []
        for row in (
            probe_phenom(cid, hub_url, page_final, page_body),
            probe_greenhouse(cid, hub_url, page_body),
            probe_oracle_hcm(cid, hub_url, page_body, page_final),
            probe_eightfold_pcsx(cid, page_final or hub_url, page_body),
            probe_eightfold_pcsx(cid, hub_url, page_body),
            probe_workday_from_html(cid, hub_url, page_final, page_body),
            probe_successfactors(cid, page_final or hub_url, page_body),
            probe_talentbrew(cid, page_url),
            probe_jobvite(cid, hub_url, page_body, page_final),
            probe_brassring(cid, hub_url, page_body, page_final),
            probe_avature(cid, hub_url, page_body, page_final),
            probe_adp(cid, hub_url, page_body, page_final),
            probe_taleo_legacy(cid, hub_url, page_body, page_final),
        ):
            if row:
                out.append(row)
        return out

    if code != 200:
        rows: list[ProbeRow] = []
        if partial_body and len(partial_body) > 200:
            rows = collect_from_page(hub_url, partial_body, final_url)
            for row in rows:
                if row.status == "ok":
                    return [row]
            for extra_url in extra_probe_urls(hub_url, final_url, partial_body):
                code2, final2, body2 = http_get(extra_url)
                if code2 == 200 or (body2 and len(body2) > 200):
                    extra_rows = collect_from_page(extra_url, body2, final2)
                    rows.extend(extra_rows)
                    for row in extra_rows:
                        if row.status == "ok":
                            return [row]
        if rows:
            return [rows[0]]
        return [
            ProbeRow(
                cid,
                source,
                hub_url,
                "fetch",
                "fail",
                "",
                "",
                fetch_ms,
                "",
                f"HTTP {code}",
            )
        ]

    candidates = collect_from_page(final_url or hub_url, body, final_url)
    for row in candidates:
        if row.status == "ok":
            return [row]
    for extra_url in extra_probe_urls(hub_url, final_url, body):
        code2, final2, body2 = http_get(extra_url)
        if code2 != 200:
            continue
        extra_rows = collect_from_page(extra_url, body2, final2)
        candidates.extend(extra_rows)
        for row in extra_rows:
            if row.status == "ok":
                return [row]
    if candidates:
        return [candidates[0]]

    return [
        ProbeRow(
            cid,
            source,
            final_url or hub_url,
            "none",
            "no_handler",
            "",
            "",
            fetch_ms,
            "keep hub or add Playwright shard",
            "no HTTP API matched",
        )
    ]


def probe_hub_company(company: dict) -> list[ProbeRow]:
    cid = str(company.get("id") or "")
    target = {
        "id": cid,
        "careers_url": str(company.get("hub_url") or "").strip(),
        "hub_url": str(company.get("hub_url") or "").strip(),
    }
    for url in careers_urls_for_target(target):
        rows = probe_careers_site(cid, url, source="hub")
        if any(r.status == "ok" for r in rows):
            return rows
    return probe_careers_site(cid, str(company.get("hub_url") or ""), source="hub")


def load_hubs(base_path: Path) -> list[dict]:
    cfg = hub_tools.load_base_bundle(base_path)
    return [c for c in cfg.get("companies", []) if str(c.get("type") or "").lower() == "hub"]


def load_blocked(tsv_path: Path) -> list[dict]:
    if not tsv_path.is_file():
        return []
    rows: list[dict] = []
    with tsv_path.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            browse = (row.get("browse_url") or "").strip()
            if browse and "myworkdayjobs.com" in browse:
                rows.append(
                    {
                        "id": row["id"],
                        "browse_url": browse,
                        "careers_url": (row.get("guess_public_careers") or "").strip(),
                    }
                )
    return rows


def load_companies_by_id(base_path: Path) -> dict[str, dict]:
    cfg = hub_tools.load_base_bundle(base_path)
    return {str(c["id"]): c for c in cfg.get("companies", []) if c.get("id")}


def careers_urls_for_target(target: dict) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    cid = str(target.get("id") or "")

    def add(u: str) -> None:
        u = str(u or "").strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    for raw in (
        target.get("careers_url") or "",
        target.get("careers_url_alt") or "",
        target.get("hub_url") or "",
    ):
        add(raw)
        u = str(raw or "").strip()
        if "://careers." in u:
            add(u.replace("://careers.", "://jobs.", 1))
        if "://www." in u and "jobs-" not in u:
            add(u.replace("://www.", "://", 1))
    for alias in KNOWN_HUB_URL_ALIASES.get(cid, []):
        add(alias)
    return urls


def load_recommendation_targets(base_path: Path, blocked_tsv: Path) -> list[dict]:
    """Hub employers + 422 Workday rows (careers URL probe)."""
    by_id = load_companies_by_id(base_path)
    targets: dict[str, dict] = {}
    for cid, co in by_id.items():
        if str(co.get("type") or "").lower() == "hub" and co.get("hub_url"):
            targets[cid] = {
                "id": cid,
                "careers_url": str(co.get("hub_url") or "").strip(),
                "workday_url": "",
                "current_type": "hub",
            }
    for row in load_blocked(blocked_tsv):
        cid = row["id"]
        entry = targets.setdefault(
            cid,
            {
                "id": cid,
                "careers_url": row.get("careers_url") or "",
                "workday_url": row["browse_url"],
                "current_type": str(by_id.get(cid, {}).get("type") or ""),
            },
        )
        if row.get("careers_url"):
            entry["careers_url_alt"] = row["careers_url"]
        if not entry.get("workday_url"):
            entry["workday_url"] = row["browse_url"]
        if cid in by_id:
            entry["current_type"] = str(by_id[cid].get("type") or "")
            if str(by_id[cid].get("type") or "").lower() == "hub":
                entry["hub_url"] = str(by_id[cid].get("hub_url") or "").strip()
    return list(targets.values())


def parse_hint_fields(hint: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in re.finditer(r'(\w+)="([^"]*)"', hint or ""):
        out[match.group(1)] = match.group(2)
    return out


def recommendation_from_probes(
    target: dict,
    careers_rows: list[ProbeRow],
    workday_row: ProbeRow | None,
) -> dict[str, str]:
    cid = target["id"]
    workday_status = ""
    workday_err = ""
    if workday_row:
        workday_status = workday_row.status
        workday_err = workday_row.error

    best: ProbeRow | None = None
    for row in careers_rows:
        if row.status == "ok":
            best = row
            break
    if not best:
        for row in careers_rows:
            if row.status == "empty" and row.total_jobs and int(row.total_jobs or 0) > 0:
                best = row
                break
    if not best and careers_rows:
        best = careers_rows[0]

    rec_type = ""
    action = "keep_hub"
    apply = "no"
    method = best.method if best else ""
    status = best.status if best else "no_probe"
    total = best.total_jobs if best else ""
    kw_hits = best.keyword_hits if best else ""
    fields = parse_hint_fields(best.config_hint if best else "")

    if workday_row and workday_row.status == "ok":
        rec_type = "playwright"
        action = "use_workday_cxs"
        apply = "yes"
        fields = {
            "browse_url": target.get("workday_url") or workday_row.url_tested,
            "playwright_kind": "workday",
            "workday_fetch": "cxs",
        }
        method = "workday_cxs"
        status = "ok"
        total = workday_row.total_jobs
        kw_hits = workday_row.keyword_hits
    elif best and best.status == "ok" and best.method in METHOD_TO_TYPE:
        rec_type = METHOD_TO_TYPE[best.method]
        action = f"convert_to_{rec_type}"
        apply = "yes"
        if rec_type == "playwright" and best.method == "eightfold_pcsx":
            fields["playwright_kind"] = "eightfold"
            fields["eightfold_fetch"] = "pcsx"
        if rec_type == "playwright" and best.method == "workday_cxs":
            fields["playwright_kind"] = "workday"
            fields["workday_fetch"] = "cxs"
        if rec_type == "successfactors":
            fields.setdefault("search_base", fields.get("browse_url", target.get("careers_url", "")))
    elif workday_err and "422" in workday_err:
        action = "playwright_shard_or_hub"
        rec_type = "hub"
    elif best and best.status == "empty":
        action = "manual_or_try_playwright"
        rec_type = METHOD_TO_TYPE.get(best.method, "") or "hub"

    return {
        "id": cid,
        "current_type": target.get("current_type") or "",
        "careers_url": target.get("careers_url") or "",
        "workday_url": target.get("workday_url") or "",
        "workday_cxs": workday_status,
        "workday_error": workday_err,
        "best_method": method,
        "probe_status": status,
        "total_jobs": total,
        "keyword_hits": kw_hits,
        "recommended_type": rec_type,
        "action": action,
        "apply": apply,
        "config_hint": best.config_hint if best else "",
        "phenom_base": fields.get("phenom_base", ""),
        "phenom_refnum": fields.get("phenom_refnum", ""),
        "oracle_api_base": fields.get("oracle_api_base", ""),
        "oracle_site_number": fields.get("oracle_site_number", ""),
        "board": fields.get("board", ""),
        "browse_url": fields.get("browse_url", target.get("careers_url", "")),
        "playwright_kind": fields.get("playwright_kind", ""),
        "eightfold_fetch": fields.get("eightfold_fetch", ""),
    }


def write_recommendations(rows: list[dict[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "current_type",
        "careers_url",
        "workday_url",
        "workday_cxs",
        "workday_error",
        "best_method",
        "probe_status",
        "total_jobs",
        "keyword_hits",
        "recommended_type",
        "action",
        "apply",
        "config_hint",
        "phenom_base",
        "phenom_refnum",
        "oracle_api_base",
        "oracle_site_number",
        "board",
        "browse_url",
    ]
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def apply_recommendations(base_path: Path, rec_path: Path) -> tuple[int, list[str]]:
    cfg = hub_tools.load_base_bundle(base_path)
    companies = cfg.get("companies", [])
    by_id = {str(c["id"]): c for c in companies}
    applied: list[str] = []
    with rec_path.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row.get("apply") != "yes":
                continue
            cid = row["id"]
            co = by_id.get(cid)
            if not co:
                continue
            rtype = row.get("recommended_type") or ""
            if rtype in SKIP_APPLY_TYPES or not rtype:
                continue
            if str(co.get("type") or "") == rtype and rtype in APPLY_SCRAPE_TYPES:
                continue
            if (
                rtype == "playwright"
                and row.get("best_method") == "workday_cxs"
                and str(co.get("type") or "") == "playwright"
                and str(co.get("playwright_kind") or "") == "workday"
            ):
                continue
            co.pop("hub_url", None)
            co.pop("hub_note", None)
            co["type"] = rtype
            browse = (row.get("browse_url") or row.get("careers_url") or "").strip()
            if browse:
                co["browse_url"] = browse
            if rtype == "phenom":
                if row.get("phenom_base"):
                    co["phenom_base"] = row["phenom_base"]
                if row.get("phenom_refnum"):
                    co["phenom_refnum"] = row["phenom_refnum"]
            elif rtype == "oracle_hcm":
                if row.get("oracle_api_base"):
                    co["oracle_api_base"] = row["oracle_api_base"]
                if row.get("oracle_site_number"):
                    co["oracle_site_number"] = row["oracle_site_number"]
            elif rtype == "greenhouse":
                if row.get("board"):
                    co["board"] = row["board"]
                co.setdefault("discover", True)
            elif rtype == "successfactors":
                fields_sf = parse_hint_fields(row.get("config_hint") or "")
                co["search_base"] = fields_sf.get("search_base") or browse or co.get("search_base", "")
            elif rtype == "talentbrew":
                fields_tb = parse_hint_fields(row.get("config_hint") or "")
                if fields_tb.get("talentbrew_host"):
                    co["talentbrew_host"] = fields_tb["talentbrew_host"]
                co["talentbrew_max_queries"] = 4
                co.setdefault("default_loc", "remote")
            elif rtype == "playwright":
                kind = (row.get("playwright_kind") or "").strip()
                if not kind:
                    kind = (
                        "eightfold"
                        if row.get("best_method") == "eightfold_pcsx"
                        else "workday"
                    )
                co["playwright_kind"] = kind
                if kind == "workday":
                    co["workday_fetch"] = "cxs"
                    wd = (row.get("workday_url") or browse).strip()
                    if wd:
                        co["browse_url"] = wd
                if kind == "eightfold" or row.get("eightfold_fetch"):
                    co["eightfold_fetch"] = row.get("eightfold_fetch") or "pcsx"
            applied.append(cid)
    hub_tools.save_base_bundle(cfg)
    return len(applied), applied


def run_recommendations(
    base_path: Path,
    blocked_tsv: Path,
    *,
    workers: int,
) -> list[dict[str, str]]:
    targets = load_recommendation_targets(base_path, blocked_tsv)
    recs: list[dict[str, str]] = []

    def task(target: dict) -> dict[str, str]:
        cid = target["id"]
        try:
            careers_rows: list[ProbeRow] = []
            for url in careers_urls_for_target(target):
                careers_rows = probe_careers_site(cid, url, source="careers")
                if any(r.status == "ok" for r in careers_rows):
                    target = {**target, "careers_url": url}
                    break
            wd_row: ProbeRow | None = None
            if target.get("workday_url"):
                wd_row = probe_workday_cxs(cid, target["workday_url"])
            return recommendation_from_probes(target, careers_rows, wd_row)
        except Exception as exc:
            return recommendation_from_probes(
                target,
                [
                    ProbeRow(
                        cid,
                        "careers",
                        target.get("careers_url") or "",
                        "error",
                        "fail",
                        "",
                        "",
                        0,
                        "",
                        str(exc),
                    )
                ],
                None,
            )

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(task, t) for t in targets]
        for fut in as_completed(futures):
            try:
                recs.append(fut.result())
            except Exception as exc:
                recs.append(
                    {
                        "id": "?",
                        "apply": "no",
                        "action": "error",
                        "recommended_type": "",
                        "workday_error": str(exc),
                    }
                )
    recs.sort(key=lambda r: (r.get("apply") != "yes", r["id"]))
    return recs


def write_outputs(rows: list[ProbeRow], out_tsv: Path, out_summary: Path) -> None:
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "source",
        "url_tested",
        "method",
        "status",
        "total_jobs",
        "keyword_hits",
        "latency_ms",
        "config_hint",
        "error",
    ]
    with out_tsv.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "id": row.id,
                    "source": row.source,
                    "url_tested": row.url_tested,
                    "method": row.method,
                    "status": row.status,
                    "total_jobs": row.total_jobs,
                    "keyword_hits": row.keyword_hits,
                    "latency_ms": row.latency_ms,
                    "config_hint": row.config_hint,
                    "error": row.error,
                }
            )

    ok = [r for r in rows if r.status == "ok"]
    empty = [r for r in rows if r.status == "empty"]
    fail = [r for r in rows if r.status in {"fail", "no_handler"}]
    by_method: dict[str, list[ProbeRow]] = {}
    for r in ok:
        by_method.setdefault(r.method, []).append(r)

    lines = [
        f"Probe keyword: {PROBE_KEYWORD}",
        f"Total rows: {len(rows)}",
        f"OK: {len(ok)}  empty: {len(empty)}  fail/no_handler: {len(fail)}",
        "",
        "Working methods:",
    ]
    for method, group in sorted(by_method.items(), key=lambda x: -len(x[1])):
        lines.append(f"  {method}: {len(group)} — {', '.join(r.id for r in group[:12])}")
        if len(group) > 12:
            lines.append(f"    ... +{len(group) - 12} more")
    lines.extend(["", "Failures (sample):"])
    for r in fail[:20]:
        lines.append(f"  {r.id}: {r.method} — {r.error or r.status}")
    out_summary.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--blocked-tsv", type=Path, default=DEFAULT_BLOCKED_TSV)
    parser.add_argument("--out-tsv", type=Path, default=DEFAULT_OUT_TSV)
    parser.add_argument("--out-summary", type=Path, default=DEFAULT_OUT_SUMMARY)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--hubs-only", action="store_true")
    parser.add_argument("--workday-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max employers per section (0=all)")
    parser.add_argument(
        "--recommend",
        action="store_true",
        help="Build 422/hub recommendations TSV (careers ATS probe + Workday CXS)",
    )
    parser.add_argument(
        "--recommend-out",
        type=Path,
        default=DEFAULT_RECOMMEND_TSV,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply rows with apply=yes from --recommend-out to quickjobs.base.json",
    )
    args = parser.parse_args()

    if args.apply:
        count, ids = apply_recommendations(args.base, args.recommend_out)
        print(f"Applied {count} companies: {', '.join(ids)}")
        return 0

    if args.recommend:
        recs = run_recommendations(args.base, args.blocked_tsv, workers=args.workers)
        write_recommendations(recs, args.recommend_out)
        apply_yes = [r for r in recs if r.get("apply") == "yes"]
        print(f"Wrote {args.recommend_out} ({len(recs)} rows, {len(apply_yes)} apply=yes)")
        for r in apply_yes[:25]:
            print(
                f"  {r['id']}: {r['recommended_type']} via {r['best_method']} "
                f"({r['total_jobs']} jobs, kw={r['keyword_hits']})"
            )
        if len(apply_yes) > 25:
            print(f"  ... +{len(apply_yes) - 25} more")
        return 0

    tasks: list[tuple[str, callable]] = []
    if not args.workday_only:
        hubs = load_hubs(args.base)
        if args.limit:
            hubs = hubs[: args.limit]
        for co in hubs:
            tasks.append((co["id"], lambda c=co: probe_hub_company(c)))

    if not args.hubs_only:
        blocked = load_blocked(args.blocked_tsv)
        if args.limit:
            blocked = blocked[: args.limit]
        for row in blocked:
            tasks.append(
                (
                    row["id"],
                    lambda r=row: [probe_workday_cxs(r["id"], r["browse_url"])],
                )
            )

    rows: list[ProbeRow] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(fn): cid for cid, fn in tasks}
        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                result = fut.result()
                if isinstance(result, list):
                    rows.extend(result)
                else:
                    rows.append(result)
            except Exception as exc:
                rows.append(
                    ProbeRow(cid, "?", "", "error", "fail", "", "", 0, "", str(exc))
                )

    rows.sort(key=lambda r: (r.source, r.id))
    write_outputs(rows, args.out_tsv, args.out_summary)
    print(args.out_summary.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
