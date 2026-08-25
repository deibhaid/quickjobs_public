#!/usr/bin/env python3
"""Probe remaining quickjobs hubs and apply scrape configs when HTTP API works."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import hub_http
import hub_playwright
import hub_tools

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

OUT_MANIFEST = hub_tools.report_path("quickjobs-hub-conversions.tsv")
PROBE_KW = "devops"

sys.path.insert(0, str(hub_tools.HUBS_DIR))
import discover_career_endpoints as discover  # noqa: E402
import hub_probe_journal as journal  # noqa: E402
import probe_hub_scrape_methods as probe  # noqa: E402

METHOD_TO_TYPE = dict(probe.METHOD_TO_TYPE)
METHOD_TO_TYPE.update(
    {
        "ashby": "ashby",
        "icims": "icims",
        "lever": "lever",
        "smartrecruiters": "smartrecruiters",
    }
)


def curl_fetch(url: str, *, referer: str = "") -> tuple[int, str, str]:
    return hub_http.curl_fetch(url, referer=referer)


def fetch_with_playwright_fallback(
    url: str,
    *,
    referer: str,
) -> tuple[int, str, str, dict[str, Any]]:
    ref = hub_http.careers_referer(referer or url, url)
    code, final_url, body = curl_fetch(url, referer=ref)
    meta: dict[str, Any] = {"curl_http_code": code, "playwright": False}
    if hub_playwright.should_playwright_fallback(code, body):
        meta["curl_blocked"] = True
        pw_code, pw_final, pw_body = hub_playwright.playwright_fetch(url, referer=ref)
        if pw_code == 200 and pw_body and len(pw_body) > 200:
            meta["playwright"] = True
            meta["note"] = f"curl blocked (http {code}); playwright fetch ok"
            return pw_code, pw_final, pw_body, meta
        meta["note"] = f"curl blocked (http {code}); playwright failed"
    return code, final_url, body, meta


def probe_company(co: dict) -> dict | None:
    cid = str(co["id"])
    hub = str(co.get("hub_url") or "").strip()
    tests: list[dict] = []
    if not hub:
        journal.record_probe(
            co,
            outcome="no_hub_url",
            tests=[],
            source="batch",
            error="missing hub_url",
        )
        return None
    target = {"id": cid, "careers_url": hub, "hub_url": hub}

    def note_attempt(url: str, code: int, final_url: str, methods: list[str]) -> None:
        tests.append(
            {
                "url": url,
                "http_code": code,
                "final_url": final_url,
                "methods": methods,
                "note": "",
            }
        )

    def try_probes(url: str, final_url: str, body: str) -> dict | None:
        methods: list[str] = []
        for fn in (
            lambda: probe.probe_phenom(cid, hub, final_url, body),
            lambda: probe.probe_greenhouse(cid, hub, body),
            lambda: probe.probe_oracle_hcm(cid, hub, body, final_url),
            lambda: probe.probe_eightfold_pcsx(cid, final_url, body),
            lambda: probe.probe_workday_from_html(cid, hub, final_url, body),
            lambda: probe.probe_successfactors(cid, final_url, body),
            lambda: probe.probe_talentbrew(cid, final_url or url),
            lambda: discover.probe_lever(cid, body, final_url),
            lambda: discover.probe_smartrecruiters(cid, body, final_url),
            lambda: discover.probe_icims(cid, body, final_url),
            lambda: discover.probe_ashby(cid, body, final_url),
        ):
            row = fn()
            if row:
                methods.append(f"{row.method}:{row.status}")
                if row.status == "ok":
                    note_attempt(url, 200, final_url, methods)
                    return {
                        "id": cid,
                        "method": row.method,
                        "type": METHOD_TO_TYPE.get(row.method, ""),
                        "hint": row.config_hint,
                        "total_jobs": row.total_jobs,
                        "url": final_url or url,
                    }
        note_attempt(url, 200, final_url, methods or ["no ATS match"])
        return None

    for url in probe.careers_urls_for_target(target):
        code, final_url, body, meta = fetch_with_playwright_fallback(url, referer=hub)
        usable_body = body if body and len(body) > 200 else ""
        if code != 200 and not usable_body:
            tests.append(
                {
                    "url": url,
                    "http_code": code,
                    "final_url": final_url,
                    "methods": ["playwright_fetch:ok"] if meta.get("playwright") else [],
                    "note": meta.get("note") or f"http {code}",
                }
            )
            continue
        if meta.get("playwright"):
            tests.append(
                {
                    "url": url,
                    "http_code": code,
                    "final_url": final_url,
                    "methods": ["playwright_fetch:ok"],
                    "note": meta.get("note") or "curl blocked; playwright fetch ok",
                }
            )
        hit = try_probes(url, final_url, usable_body or body)
        if hit:
            journal.record_probe(
                co,
                outcome="converted",
                tests=tests,
                source="batch",
                method=hit["method"],
                apply="yes",
                config_hint=hit.get("hint") or "",
                url_tested=hit.get("url") or "",
            )
            return hit
        for extra in probe.extra_probe_urls(hub, final_url, body):
            code2, final2, body2, meta2 = fetch_with_playwright_fallback(extra, referer=hub)
            if code2 != 200:
                tests.append(
                    {
                        "url": extra,
                        "http_code": code2,
                        "final_url": final2,
                        "methods": ["playwright_fetch:ok"] if meta2.get("playwright") else [],
                        "note": meta2.get("note") or f"http {code2}",
                    }
                )
                continue
            methods = []
            for fn in (
                lambda: probe.probe_successfactors(cid, final2, body2),
                lambda: probe.probe_talentbrew(cid, extra),
                lambda: probe.probe_phenom(cid, hub, final2, body2),
            ):
                row = fn()
                if row:
                    methods.append(f"{row.method}:{row.status}")
                    if row.status == "ok":
                        tests.append(
                            {
                                "url": extra,
                                "http_code": 200,
                                "final_url": final2,
                                "methods": methods,
                                "note": "",
                            }
                        )
                        hit = {
                            "id": cid,
                            "method": row.method,
                            "type": METHOD_TO_TYPE.get(row.method, ""),
                            "hint": row.config_hint,
                            "total_jobs": row.total_jobs,
                            "url": final2,
                        }
                        journal.record_probe(
                            co,
                            outcome="converted",
                            tests=tests,
                            source="batch",
                            method=hit["method"],
                            apply="yes",
                            config_hint=hit.get("hint") or "",
                            url_tested=hit.get("url") or "",
                        )
                        return hit
            tests.append(
                {
                    "url": extra,
                    "http_code": 200,
                    "final_url": final2,
                    "methods": methods or ["no ATS match"],
                    "note": "",
                }
            )
    journal.record_probe(
        co,
        outcome="no_handler",
        tests=tests,
        source="batch",
        apply="no",
    )
    return None


def apply_conversion(co: dict, hit: dict) -> None:
    fields = probe.parse_hint_fields(hit.get("hint") or "")
    rtype = hit.get("type") or ""
    co.pop("hub_url", None)
    co.pop("hub_note", None)
    co["type"] = rtype
    browse = fields.get("browse_url") or hit.get("url") or ""
    if browse:
        co["browse_url"] = browse
    co["max_details"] = co.get("max_details") or 12
    co["cache_ttl_hours"] = co.get("cache_ttl_hours") or 24
    co["skip_verify"] = True
    if rtype == "phenom":
        if fields.get("phenom_base"):
            co["phenom_base"] = fields["phenom_base"]
        if fields.get("phenom_refnum"):
            co["phenom_refnum"] = fields["phenom_refnum"]
        co.setdefault("default_loc", "remote")
    elif rtype == "oracle_hcm":
        for k in ("oracle_api_base", "oracle_site_number"):
            if fields.get(k):
                co[k] = fields[k]
        co.setdefault("default_loc", "remote")
    elif rtype == "greenhouse":
        if fields.get("board"):
            co["board"] = fields["board"]
        co["discover"] = True
        co.setdefault("default_loc", "remote")
    elif rtype == "successfactors":
        base = fields.get("search_base") or browse
        if base:
            co["search_base"] = base
        co.setdefault("default_loc", "remote")
    elif rtype == "talentbrew":
        if fields.get("talentbrew_host"):
            co["talentbrew_host"] = fields["talentbrew_host"]
        co["talentbrew_max_queries"] = 4
        if not co.get("default_loc"):
            co["default_loc"] = "remote"
    elif rtype == "lever":
        if fields.get("board"):
            co["board"] = fields["board"]
        co.setdefault("default_loc", "remote")
    elif rtype == "smartrecruiters":
        sr = fields.get("smartrecruiters_id") or fields.get("board")
        if sr:
            co["smartrecruiters_id"] = sr
        co.setdefault("default_loc", "remote")
    elif rtype == "icims":
        tpl = fields.get("search_url_template")
        if tpl:
            co["search_url_template"] = tpl
        co.setdefault("default_loc", "remote")
    elif rtype == "ashby":
        slug = fields.get("board") or ""
        if not slug:
            m = re.search(
                r"job-board/([^/\s\"]+)|ashby slug=([^\s;]+)",
                hit.get("hint") or "",
                re.I,
            )
            if m:
                slug = m.group(1) or m.group(2) or ""
        if slug:
            co["ashby_board"] = slug
            co["browse_url"] = f"https://jobs.ashbyhq.com/{slug}"
        co["discover"] = True
        co["type"] = "ashby"
        co.setdefault("default_loc", "remote")
    elif rtype == "playwright" and fields.get("eightfold_fetch") == "pcsx":
        co["playwright_kind"] = "eightfold"
        co["eightfold_fetch"] = "pcsx"
        co.setdefault("default_loc", "remote")


def apply_hit(hit: dict) -> None:
    cfg = hub_tools.load_base_bundle()
    by_id = {c["id"]: c for c in cfg["companies"]}
    co = by_id.get(hit["id"])
    if co and str(co.get("type") or "").lower() == "hub":
        apply_conversion(co, hit)
        hub_tools.save_base_bundle(cfg)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=0, help="Thread pool size (0=QUICKJOBS_HUB_MAX_WORKERS)")
    parser.add_argument("--limit", type=int, default=0, help="Max hubs per run (0=all)")
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Rotate hub list by N before --limit (covers all employers across rounds)",
    )
    args = parser.parse_args()

    cfg = hub_tools.load_base_bundle()
    hubs = [c for c in cfg["companies"] if str(c.get("type") or "").lower() == "hub"]
    total = len(hubs)
    if total and args.offset:
        off = args.offset % total
        hubs = hubs[off:] + hubs[:off]
    if args.limit > 0:
        hubs = hubs[: args.limit]
    workers = max(1, args.workers or hub_http.hub_max_workers(12))
    print(
        f"Probing {len(hubs)} hubs (of {total}, offset {args.offset}) "
        f"via curl, workers={workers}, delay_ms={hub_http.hub_delay_ms()}…",
        flush=True,
    )
    hits: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(probe_company, co): co for co in hubs}
        for fut in as_completed(futs):
            co = futs[fut]
            done += 1
            try:
                hit = fut.result()
            except Exception as exc:
                print(f"  [{done}/{len(hubs)}] {co['id']}: probe error ({exc})", flush=True)
                continue
            if hit:
                hits.append(hit)
                print(
                    f"  [{done}/{len(hubs)}] {co['id']}: {hit['type']} "
                    f"({hit['method']}, {hit['total_jobs']} jobs)",
                    flush=True,
                )
                if args.apply and not args.dry_run:
                    apply_hit(hit)
            else:
                print(f"  [{done}/{len(hubs)}] {co['id']}: no API", flush=True)

    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with OUT_MANIFEST.open("a" if args.limit else "w") as fh:
        if OUT_MANIFEST.stat().st_size == 0:
            fh.write("id\ttype\tmethod\ttotal_jobs\turl\thint\n")
        for h in hits:
            fh.write(
                f"{h['id']}\t{h['type']}\t{h['method']}\t{h['total_jobs']}\t{h['url']}\t{h['hint']}\n"
            )
    print(f"\nConvertible this run: {len(hits)} / {len(hubs)} → {OUT_MANIFEST}")
    if args.apply:
        print(f"Applied {len(hits)} conversions to {BASE} (incremental)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
