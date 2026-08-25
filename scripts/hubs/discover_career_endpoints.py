#!/usr/bin/env python3
"""Discover real public careers ATS endpoints (no Workday CXS/Playwright).

Reads employers that were on Workday shard or blocked-sources TSV, probes
careers/jobs URLs for Phenom, Oracle, Greenhouse, Lever, Eightfold, SF, etc.,
and optionally applies quickjobs.david.base.json (--apply).

Output: ~/ws/scriptdir/output/quickjobs-career-endpoints.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import hub_http
import hub_tools

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

BLOCKED_TSV = hub_tools.BLOCKED_TSV
OUT_TSV = hub_tools.report_path("quickjobs-career-endpoints.tsv")
USER_AGENT = "Mozilla/5.0 (compatible; QuickJobsProbe/1.0)"
PROBE_KEYWORD = "devops"

# Import probe helpers from sibling module
sys.path.insert(0, str(hub_tools.HUBS_DIR))
import probe_hub_scrape_methods as probe  # noqa: E402

APPLY_TYPES = frozenset(
    {
        "phenom",
        "oracle_hcm",
        "greenhouse",
        "successfactors",
        "lever",
        "smartrecruiters",
        "icims",
        "talentbrew",
        "ashby",
    }
)
EIGHTFOLD_TYPE = "playwright"  # eightfold_fetch: pcsx
ICIMS_TYPE = "icims"  # HTTP search + detail on *.icims.com


def probe_lever(company_id: str, body: str, final_url: str) -> probe.ProbeRow | None:
    for pattern in (
        r"jobs\.lever\.co/([^/\"?\s]+)",
        r"api\.lever\.co/v0/postings/([^/\"?\s]+)",
        r'"account"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, body + final_url, re.I)
        if not match:
            continue
        company_slug = match.group(1)
        api = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        code, _, resp = probe.http_get(api)
        if code != 200:
            continue
        try:
            jobs = json.loads(resp)
        except json.JSONDecodeError:
            continue
        if not isinstance(jobs, list):
            continue
        hits = [j for j in jobs if PROBE_KEYWORD in str(j.get("text", "")).lower()]
        hint = f'type=lever board="{company_slug}" browse_url="{final_url}"'
        return probe.ProbeRow(
            company_id,
            "careers",
            api,
            "lever",
            "ok" if jobs else "empty",
            str(len(jobs)),
            str(len(hits)),
            0,
            hint,
            "",
        )
    return None


def probe_smartrecruiters(company_id: str, body: str, final_url: str) -> probe.ProbeRow | None:
    for pattern in (
        r"jobs\.smartrecruiters\.com/([^/\"?\s]+)",
        r"careers\.smartrecruiters\.com/([^/\"?\s]+)",
        r"api\.smartrecruiters\.com/v1/companies/([^/\"?\s]+)",
        r'"companyIdentifier"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, body + final_url, re.I)
        if not match:
            continue
        sr_id = match.group(1)
        api = f"https://api.smartrecruiters.com/v1/companies/{sr_id}/postings"
        code, _, resp = probe.http_get(api)
        if code != 200:
            continue
        try:
            payload = json.loads(resp)
        except json.JSONDecodeError:
            continue
        jobs = payload.get("content") or []
        try:
            total_found = int(payload.get("totalFound") or len(jobs) or 0)
        except (TypeError, ValueError):
            total_found = len(jobs)
        keyword_hits = len(
            [j for j in jobs if PROBE_KEYWORD in str(j.get("name", "")).lower()]
        )
        # Tiny leftover SR boards (1–4 irrelevant postings) create mass false converts.
        status = "ok" if (total_found >= 5 or keyword_hits > 0) else "empty"
        hint = f'type=smartrecruiters smartrecruiters_id="{sr_id}" browse_url="{final_url}"'
        return probe.ProbeRow(
            company_id,
            "careers",
            api,
            "smartrecruiters",
            status,
            str(total_found),
            str(keyword_hits),
            0,
            hint,
            "",
        )
    return None


def _icims_slug_from_careers_url(url: str) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host.startswith("careers."):
        return host.split(".", 1)[1].split(".")[0]
    if host.startswith("jobs."):
        return host.split(".", 1)[1].split(".")[0]
    return ""


def _icims_search_candidates(body: str, final_url: str) -> list[str]:
    hosts: list[str] = []
    for match in re.finditer(r"https?://([a-z0-9-]+\.icims\.com)", body + final_url, re.I):
        host = match.group(1).lower()
        if host == "www.icims.com" or host.startswith("employee-"):
            continue
        if host not in hosts:
            hosts.append(host)
    slug = _icims_slug_from_careers_url(final_url)
    if slug:
        for prefix in ("careers", "external", "career", "jobs"):
            guess = f"{prefix}-{slug}.icims.com"
            if guess not in hosts:
                hosts.append(guess)

    def host_rank(h: str) -> tuple[int, str]:
        if h.startswith("internal-") or h.startswith("employee-"):
            return (9, h)
        if h.startswith("careers-"):
            return (0, h)
        if h.startswith("external-"):
            return (1, h)
        if h.startswith("jobs-"):
            return (2, h)
        return (5, h)

    hosts.sort(key=host_rank)
    out: list[str] = []
    for host in hosts:
        out.append(f"https://{host}/jobs/search?ss=1&in_iframe=1")
    return out


def probe_icims(company_id: str, body: str, final_url: str) -> probe.ProbeRow | None:
    for search_url in _icims_search_candidates(body, final_url):
        referer = hub_http.careers_referer(final_url, search_url)
        code, _, page = probe.http_get(search_url, referer=referer)
        if code != 200:
            continue
        if "/jobs/" not in page and "icims" not in page.lower():
            continue
        links = len(re.findall(r'href="[^"]*/jobs/[^"]+"', page, re.I))
        tpl = search_url.replace("ss=1", "searchKeyword={query}")
        if "{query}" not in tpl:
            sep = "&" if "?" in tpl else "?"
            tpl = f"{tpl}{sep}searchKeyword={{query}}"
        hint = (
            f'type=icims browse_url="{search_url}" '
            f'search_url_template="{tpl}"'
        )
        return probe.ProbeRow(
            company_id,
            "careers",
            search_url,
            "icims",
            "ok" if links else "empty",
            str(links),
            "",
            0,
            hint,
            "",
        )
    return None


def probe_ashby(company_id: str, body: str, final_url: str) -> probe.ProbeRow | None:
    for pattern in (
        r"jobs\.ashbyhq\.com/([^/\"?\s]+)",
        r"api\.ashbyhq\.com/posting-api/job-board/([^/\"?\s]+)",
        r'"ashbyBoardSlug"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, body + final_url, re.I)
        if not match:
            continue
        slug = match.group(1)
        api = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        code, _, resp = probe.http_get(api)
        if code != 200:
            continue
        try:
            payload = json.loads(resp)
        except json.JSONDecodeError:
            continue
        jobs = payload.get("jobs") or []
        hint = f"ashby slug={slug} browse_url={final_url}"
        return probe.ProbeRow(
            company_id,
            "careers",
            api,
            "ashby",
            "ok" if jobs else "empty",
            str(len(jobs)),
            "",
            0,
            hint,
            "",
        )
    return None


def probe_careers_full(company_id: str, url: str) -> list[probe.ProbeRow]:
    rows = probe.probe_careers_site(company_id, url, source="careers")
    if rows and rows[0].method == "none":
        for extra in probe.extra_probe_urls(url, url, ""):
            extra_rows = probe.probe_careers_site(company_id, extra, source="careers")
            if any(r.status == "ok" for r in extra_rows):
                return extra_rows
    return rows


def probe_successfactors(company_id: str, start_url: str, body: str) -> probe.ProbeRow | None:
    return probe.probe_successfactors(company_id, start_url, body)


def _public_careers_url(co: dict, blocked_row: dict | None) -> str:
    """Prefer marketing careers site over Workday tenant URL."""
    for raw in (
        (blocked_row or {}).get("guess_public_careers"),
        co.get("hub_url"),
        co.get("browse_url"),
        (blocked_row or {}).get("browse_url"),
    ):
        u = str(raw or "").strip()
        if not u or "myworkdayjobs.com" in u.lower():
            continue
        return u
    return str((blocked_row or {}).get("guess_public_careers") or co.get("hub_url") or "").strip()


def load_targets(base_path: Path, blocked_path: Path) -> list[dict]:
    cfg = hub_tools.load_base_bundle(base_path)
    by_id = {str(c["id"]): c for c in cfg.get("companies", []) if c.get("id")}
    blocked_by_id: dict[str, dict] = {}
    if blocked_path.is_file():
        for row in csv.DictReader(blocked_path.open(), delimiter="\t"):
            blocked_by_id[row["id"]] = row

    targets: dict[str, dict] = {}
    for cid, co in by_id.items():
        is_hub = str(co.get("type") or "").lower() == "hub"
        is_shard = co.get("workday_pw_shard") is not None
        is_wd_playwright = (
            str(co.get("type") or "").lower() == "playwright"
            and str(co.get("playwright_kind") or "").lower() == "workday"
        )
        if not (is_hub or is_shard or is_wd_playwright):
            continue
        blocked = blocked_by_id.get(cid)
        public = _public_careers_url(co, blocked)
        targets[cid] = {
            "id": cid,
            "name": co.get("name") or cid,
            "hub_url": public,
            "careers_url_alt": (blocked or {}).get("guess_public_careers", "").strip() if blocked else "",
        }

    for cid, row in blocked_by_id.items():
        if cid in targets:
            continue
        if "myworkdayjobs" not in (row.get("browse_url") or ""):
            continue
        alt = (row.get("guess_public_careers") or "").strip()
        targets[cid] = {
            "id": cid,
            "name": row.get("label") or cid,
            "hub_url": alt,
            "careers_url_alt": alt,
        }

    return list(targets.values())


def careers_url_list(target: dict) -> list[str]:
    return probe.careers_urls_for_target(
        {
            "careers_url": target.get("hub_url") or target.get("careers_url_alt") or "",
            "careers_url_alt": target.get("careers_url_alt") or "",
            "hub_url": target.get("hub_url") or "",
        }
    )


def discover_one(target: dict) -> dict[str, str]:
    cid = target["id"]
    best_row: probe.ProbeRow | None = None
    best_url = ""
    for url in careers_url_list(target):
        rows = probe_careers_full(cid, url)
        for row in rows:
            if row.status == "ok" and row.method not in ("fetch", "ashby"):
                best_row = row
                best_url = url
                break
            if row.status == "ok" and row.method == "ashby" and not best_row:
                best_row = row
                best_url = url
            if not best_row and row.method == "none":
                best_row = row
                best_url = url
        if best_row and best_row.status == "ok":
            break

    fields = probe.parse_hint_fields(best_row.config_hint if best_row else "")
    method = best_row.method if best_row else ""
    method_to_type = {
        "phenom_widgets": "phenom",
        "oracle_hcm": "oracle_hcm",
        "greenhouse": "greenhouse",
        "successfactors_html": "successfactors",
        "successfactors": "successfactors",
        "eightfold_pcsx": EIGHTFOLD_TYPE,
        "lever": "lever",
        "smartrecruiters": "smartrecruiters",
        "talentbrew_search": "talentbrew",
        "icims": ICIMS_TYPE,
        "ashby": "ashby",
    }
    rec_type = method_to_type.get(method, "hub")

    apply = (
        "yes"
        if best_row
        and best_row.status == "ok"
        and rec_type in (APPLY_TYPES | {EIGHTFOLD_TYPE, ICIMS_TYPE})
        else "no"
    )

    return {
        "id": cid,
        "name": target.get("name") or cid,
        "careers_url_used": best_url,
        "ats_method": method,
        "status": best_row.status if best_row else "fail",
        "total_jobs": best_row.total_jobs if best_row else "",
        "keyword_hits": best_row.keyword_hits if best_row else "",
        "recommended_type": rec_type,
        "apply": apply,
        "config_hint": best_row.config_hint if best_row else "",
        "phenom_base": fields.get("phenom_base", ""),
        "phenom_refnum": fields.get("phenom_refnum", ""),
        "oracle_api_base": fields.get("oracle_api_base", ""),
        "oracle_site_number": fields.get("oracle_site_number", ""),
        "board": fields.get("board", fields.get("smartrecruiters_id", "")),
        "browse_url": fields.get("browse_url", best_url),
        "note": "Do not use Workday CXS — blocked off-VPN",
    }


def strip_workday_from_hubs(cfg: dict, blocked_path: Path) -> int:
    """Remove myworkdayjobs browse URLs from hub entries; set hub_url from blocked TSV."""
    blocked: dict[str, str] = {}
    if blocked_path.is_file():
        for row in csv.DictReader(blocked_path.open(), delimiter="\t"):
            alt = (row.get("guess_public_careers") or "").strip()
            if alt and "myworkdayjobs" not in alt.lower():
                blocked[row["id"]] = alt
    cleaned = 0
    for co in cfg.get("companies", []):
        if str(co.get("type") or "").lower() != "hub":
            continue
        for key in ("browse_url", "search_url_template", "workday_pw_shard", "playwright_kind"):
            if key in co and (
                key == "workday_pw_shard"
                or key == "playwright_kind"
                or "myworkdayjobs.com" in str(co.get(key) or "").lower()
            ):
                co.pop(key, None)
                cleaned += 1
        hub = str(co.get("hub_url") or "").strip()
        if not hub or "myworkdayjobs.com" in hub.lower():
            alt = blocked.get(str(co.get("id") or ""), "")
            if alt:
                co["hub_url"] = alt
                cleaned += 1
    return cleaned


def apply_to_base(base_path: Path, report_path: Path, blocked_path: Path) -> tuple[int, int, int]:
    cfg = hub_tools.load_base_bundle(base_path)
    by_id = {str(c["id"]): c for c in cfg.get("companies", [])}
    applied = 0
    hubbed = 0
    for row in csv.DictReader(report_path.open(), delimiter="\t"):
        co = by_id.get(row["id"])
        if not co:
            continue
        for key in (
            "workday_pw_shard",
            "workday_playwright_max_queries",
            "playwright_kind",
            "workday_fetch",
            "workday_skip_playwright_on_422",
            "search_url_template",
            "hub_url",
            "hub_note",
        ):
            co.pop(key, None)

        rtype = row.get("recommended_type") or "hub"
        fields = probe.parse_hint_fields(row.get("config_hint") or "")
        ats_method = row.get("ats_method") or ""
        if row.get("apply") == "yes" and rtype in (APPLY_TYPES | {EIGHTFOLD_TYPE, ICIMS_TYPE}):
            co["type"] = rtype
            co.pop("eightfold_fetch", None)
            browse = (row.get("browse_url") or row.get("careers_url_used") or "").strip()
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
                browse = (row.get("browse_url") or "").strip()
                if "my-profile" in browse or "&#" in browse:
                    used = (row.get("careers_url_used") or "").strip()
                    if used:
                        co["browse_url"] = used
            elif rtype == "greenhouse":
                if row.get("board"):
                    co["board"] = row["board"]
                co["discover"] = True
            elif rtype == "lever":
                if row.get("board"):
                    co["board"] = row["board"]
            elif rtype == "smartrecruiters":
                if row.get("board"):
                    co["smartrecruiters_id"] = row["board"]
            elif rtype == "successfactors":
                base = fields.get("search_base") or browse
                if base:
                    co["search_base"] = base
                if browse:
                    co["browse_url"] = browse
            elif rtype == "talentbrew":
                if fields.get("talentbrew_host"):
                    co["talentbrew_host"] = fields["talentbrew_host"]
                co["talentbrew_max_queries"] = 4
                if not co.get("default_loc"):
                    co["default_loc"] = "remote"
            elif rtype == "icims":
                tpl = fields.get("search_url_template", "")
                if tpl:
                    co["search_url_template"] = tpl
                co.setdefault("default_loc", "remote")
            elif ats_method == "eightfold_pcsx" or rtype == EIGHTFOLD_TYPE:
                co["playwright_kind"] = "eightfold"
                co["eightfold_fetch"] = "pcsx"
            elif rtype == "ashby":
                slug = fields.get("board") or ""
                if not slug:
                    m = re.search(
                        r"job-board/([^/\s\"]+)|ashby slug=([^\s;]+)",
                        row.get("config_hint") or "",
                        re.I,
                    )
                    if m:
                        slug = m.group(1) or m.group(2) or ""
                if slug:
                    co["ashby_board"] = slug
                    co["browse_url"] = f"https://jobs.ashbyhq.com/{slug}"
                co["discover"] = True
            co["max_details"] = 12
            co["cache_ttl_hours"] = 24
            applied += 1
        else:
            co["type"] = "hub"
            careers = (row.get("careers_url_used") or "").strip()
            if not careers or "myworkdayjobs.com" in careers.lower():
                careers = (row.get("browse_url") or "").strip()
            if "myworkdayjobs.com" in careers.lower():
                careers = ""
            co.pop("browse_url", None)
            co.pop("search_url_template", None)
            if careers:
                co["hub_url"] = careers
            co["hub_note"] = (
                f"Public ATS: {row.get('ats_method') or 'unknown'} — "
                f"{row.get('note') or 'manual search'}"
            )
            hubbed += 1

    strip_workday_from_hubs(cfg, blocked_path)
    hub_tools.save_base_bundle(cfg)
    return applied, hubbed, len(by_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--blocked-tsv", type=Path, default=BLOCKED_TSV)
    parser.add_argument("--out", type=Path, default=OUT_TSV)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument(
        "--hubs-only",
        action="store_true",
        help="Only probe companies still type=hub in base config",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--strip-workday-hubs",
        action="store_true",
        help="Only remove Workday URLs from hub entries (no discovery report needed)",
    )
    args = parser.parse_args()

    if args.strip_workday_hubs:
        cfg = hub_tools.load_base_bundle(args.base)
        n = strip_workday_from_hubs(cfg, args.blocked_tsv)
        hub_tools.save_base_bundle(cfg)
        print(f"Stripped Workday fields from hub entries ({n} field updates)")
        return 0

    if args.apply:
        if not args.out.is_file():
            print(f"Missing {args.out}; run discovery first", file=sys.stderr)
            return 1
        applied, hubbed, _ = apply_to_base(args.base, args.out, args.blocked_tsv)
        print(f"Applied {applied} scrape configs; {hubbed} remain hub (Workday paths removed)")
        return 0

    targets = load_targets(args.base, args.blocked_tsv)
    if args.hubs_only:
        cfg = hub_tools.load_base_bundle(args.base)
        hub_ids = {
            str(c["id"])
            for c in cfg.get("companies", [])
            if str(c.get("type") or "").lower() == "hub" and c.get("id")
        }
        targets = [t for t in targets if t["id"] in hub_ids]
    print(f"Discovering public careers endpoints for {len(targets)} employers (no Workday)…")
    rows: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(discover_one, t): t["id"] for t in targets}
        for fut in as_completed(futures):
            rows.append(fut.result())

    rows.sort(key=lambda r: (r["apply"] != "yes", r["id"]))
    fieldnames = list(rows[0].keys()) if rows else []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    ok = [r for r in rows if r["apply"] == "yes"]
    print(f"Wrote {args.out}")
    print(f"Scrape-ready: {len(ok)}  hub/manual: {len(rows) - len(ok)}")
    for r in ok[:20]:
        print(f"  {r['id']}: {r['recommended_type']} via {r['ats_method']} ({r['total_jobs']} jobs)")
    if len(ok) > 20:
        print(f"  … +{len(ok) - 20} more")
    print("\nRun with --apply to update quickjobs.david.base.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
