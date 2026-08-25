#!/usr/bin/env python3
"""Deep ATS path discovery for remaining quickjobs hub employers (no VPN, no Workday CXS).

Uses curl for fetches, tries many careers/jobs URL variants and public APIs.
Writes ~/ws/scriptdir/output/quickjobs-hub-ats-discovery.tsv

--apply: patch quickjobs.david.base.json (convert scrape-ready rows)
--exclude-unresolved: add still-unresolved ids to quickjobs.david.profile.json company_ids_exclude
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hub_http
import hub_network
import hub_discover_state as run_state
import hub_playwright
import hub_tools  # noqa: E402

REPO_ROOT = hub_tools.REPO_ROOT
BASE = hub_tools.BASE_JSON
PROFILE = REPO_ROOT / "quickjobs.david.profile.json"
sys.path.insert(0, str(hub_tools.HUBS_DIR))

BLOCKED_TSV = hub_tools.BLOCKED_TSV
DEFERRED_JSON = hub_tools.DEFERRED_PATH
OUT_TSV = hub_tools.report_path("quickjobs-hub-ats-discovery.tsv")
PROBE_KW = "devops"
sys.path.insert(0, str(hub_tools.HUBS_DIR))
import discover_career_endpoints as discover  # noqa: E402
import hub_probe_journal as journal  # noqa: E402
import probe_hub_scrape_methods as probe  # noqa: E402

METHOD_TO_TYPE = dict(probe.METHOD_TO_TYPE)
METHOD_TO_TYPE["ashby"] = "ashby"
METHOD_TO_TYPE["icims"] = "icims"

# Short/generic Greenhouse board slugs that match many unrelated employers (e.g. "air").
GENERIC_GH_BOARD_SLUGS = frozenset({"air", "go", "one"})


def _generic_greenhouse_slug(slug: str) -> bool:
    return len(slug) <= 3 or slug in GENERIC_GH_BOARD_SLUGS


@dataclass
class Discovery:
    id: str
    name: str
    careers_url: str
    method: str
    status: str
    total_jobs: str
    keyword_hits: str
    recommended_type: str
    apply: str
    config_hint: str
    url_tested: str
    error: str
    notes: str
    tests: list[dict[str, Any]] | None = None


def curl_fetch(url: str, *, referer: str = "") -> tuple[int, str, str]:
    return hub_http.curl_fetch(url, referer=referer)


def slug_variants(company_id: str, name: str) -> list[str]:
    cid = company_id.lower().replace("_", "-")
    words = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-").split("-")
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        s = s.strip("-")
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    add(cid.replace("-", ""))
    add(cid)
    if words:
        first = words[0]
        if not _generic_greenhouse_slug(first):
            add(first)
        add("".join(words))
        if len(words) >= 2:
            add("".join(words[:2]))
    aliases = {
        "jnj": ["jnj", "johnsonandjohnson"],
        "ge-aerospace": ["geaerospace", "ge"],
        "goldman-sachs-wd": ["goldmansachs"],
        "goldman-sachs": ["goldmansachs"],
        "morgan-stanley": ["morganstanley"],
        "bank-of-america": ["bankofamerica", "bofa"],
        "american-express": ["americanexpress", "amex"],
        "wellsfargo": ["wellsfargo"],
        "delta-airlines": ["delta"],
        "hca-healthcare": ["hca"],
        "lattice-semiconductor": ["latticesemi", "lattice"],
        "columbia-sportswear": ["columbia", "columbiasportswear"],
        "bristol-myers-squibb": ["bms", "bristolmyerssquibb"],
        "lockheed-martin": ["lockheedmartin"],
        "tripwire": ["tripwire", "fortra"],
        "doordash": ["doordash", "doordashusa"],
        "hashicorp": ["hashicorp"],
    }
    for s in aliases.get(cid, []):
        add(s)
    return out


def url_candidates(co: dict, blocked_row: dict | None) -> list[str]:
    cid = str(co["id"])
    name = str(co.get("name") or cid)
    seeds: list[str] = []
    for raw in (
        co.get("hub_url"),
        (blocked_row or {}).get("guess_public_careers"),
        (blocked_row or {}).get("browse_url"),
    ):
        u = str(raw or "").strip()
        if u and "myworkdayjobs.com" not in u.lower():
            seeds.append(u)

    for slug in slug_variants(cid, name):
        seeds.extend(
            [
                f"https://careers.{slug}.com/",
                f"https://jobs.{slug}.com/",
                f"https://www.{slug}.com/careers/",
            ]
        )
    if cid == "atlassian":
        seeds.append(
            "https://www.atlassian.com/company/careers/all-jobs?team=Engineering&location=Remote"
        )
    if cid == "coinbase":
        seeds.extend(["https://www.coinbase.com/careers", "https://boards.greenhouse.io/coinbase"])
    if cid == "doordash":
        seeds.append("https://careersatdoordash.com/")
    if cid == "uber":
        seeds.append("https://www.uber.com/us/en/careers/list/")
    if cid == "tesla":
        seeds.append("https://www.tesla.com/careers/search/?query=devops")
    if cid == "bristol-myers-squibb":
        seeds.extend(["https://careers.bms.com/", "https://jobs.bms.com/"])
    for alias in probe.KNOWN_HUB_URL_ALIASES.get(cid, []):
        seeds.append(alias)

    seen: set[str] = set()
    out: list[str] = []
    for seed in seeds:
        if not seed or seed in seen:
            continue
        seen.add(seed)
        out.append(seed)
        for extra in probe.careers_urls_for_target(
            {"id": cid, "careers_url": seed, "hub_url": seed, "careers_url_alt": ""}
        ):
            if extra not in seen:
                seen.add(extra)
                out.append(extra)
        parsed = urllib.parse.urlsplit(seed)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        for path in (
            f"/search-jobs/{urllib.parse.quote(PROBE_KW)}",
            f"/search-jobs?keywords={urllib.parse.quote(PROBE_KW)}",
            f"/search/?q={urllib.parse.quote(PROBE_KW)}",
            f"/go/Search/?q={urllib.parse.quote(PROBE_KW)}",
            "/careers",
            "/en/search-results",
        ):
            u = origin + path
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def _probe_greenhouse_slug(company_id: str, slug: str) -> probe.ProbeRow | None:
    api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    code, _, resp = curl_fetch(api)
    if code != 200:
        return None
    try:
        jobs = json.loads(resp).get("jobs") or []
    except json.JSONDecodeError:
        return None
    if not jobs:
        return None
    hits = [j for j in jobs if PROBE_KW in str(j.get("title") or "").lower()]
    hint = f'type=greenhouse board="{slug}" browse_url="https://boards.greenhouse.io/{slug}"'
    return probe.ProbeRow(
        company_id,
        "careers",
        api,
        "greenhouse",
        "ok",
        str(len(jobs)),
        str(len(hits)),
        0,
        hint,
        "",
    )


def probe_greenhouse_slugs(company_id: str, slugs: list[str]) -> probe.ProbeRow | None:
    specific_failed = False
    for slug in slugs:
        if _generic_greenhouse_slug(slug):
            continue
        row = _probe_greenhouse_slug(company_id, slug)
        if row:
            return row
        specific_failed = True
    if specific_failed:
        return None
    for slug in slugs:
        if not _generic_greenhouse_slug(slug):
            continue
        row = _probe_greenhouse_slug(company_id, slug)
        if row:
            return row
    return None


def probe_url_curl(
    company_id: str,
    url: str,
    *,
    referer: str = "",
) -> tuple[probe.ProbeRow | None, dict[str, Any]]:
    ref = hub_http.careers_referer(referer or url, url)
    code, final_url, body = curl_fetch(url, referer=ref)
    attempt: dict[str, Any] = {
        "url": url,
        "http_code": code,
        "final_url": final_url,
        "methods": [],
        "note": "",
    }
    curl_blocked = hub_playwright.should_playwright_fallback(code, body)
    if curl_blocked:
        attempt["curl_http_code"] = code
        pw_code, pw_final, pw_body = hub_playwright.playwright_fetch(url, referer=ref)
        if pw_code == 200 and pw_body and len(pw_body) > 200:
            attempt["note"] = f"curl blocked (http {code}); playwright fetch ok"
            attempt["methods"].append("playwright_fetch:ok")
            attempt["http_code"] = pw_code
            attempt["final_url"] = pw_final
            code, final_url, body = pw_code, pw_final, pw_body
        else:
            attempt["note"] = f"curl blocked (http {code}); playwright failed"
            if not body or len(body) <= 200:
                return None, attempt
    if code != 200 or not body:
        attempt["note"] = attempt["note"] or ("no body" if code == 200 else f"http {code}")
        if body and len(body) > 200:
            pass
        else:
            return None, attempt
    probes = (
        lambda: probe.probe_phenom(company_id, url, final_url, body),
        lambda: probe.probe_oracle_hcm(company_id, url, body, final_url),
        lambda: probe.probe_greenhouse(company_id, url, body),
        lambda: probe.probe_eightfold_pcsx(company_id, final_url, body),
        lambda: probe.probe_eightfold_pcsx(company_id, url, body),
        lambda: probe.probe_workday_from_html(company_id, url, final_url, body),
        lambda: discover.probe_successfactors(company_id, final_url, body),
        lambda: probe.probe_talentbrew(company_id, final_url or url),
        lambda: discover.probe_lever(company_id, body, final_url),
        lambda: discover.probe_smartrecruiters(company_id, body, final_url),
        lambda: discover.probe_icims(company_id, body, final_url),
        lambda: discover.probe_ashby(company_id, body, final_url),
        lambda: probe.probe_jobvite(company_id, url, body, final_url),
        lambda: probe.probe_brassring(company_id, url, body, final_url),
        lambda: probe.probe_avature(company_id, url, body, final_url),
        lambda: probe.probe_adp(company_id, url, body, final_url),
        lambda: probe.probe_taleo_legacy(company_id, url, body, final_url),
    )
    best: probe.ProbeRow | None = None
    for fn in probes:
        row = fn()
        if not row:
            continue
        attempt["methods"].append(f"{row.method}:{row.status}")
        if row.status == "ok" and (not best or int(row.total_jobs or 0) > int(best.total_jobs or 0)):
            best = row
    if not attempt["methods"]:
        attempt["note"] = "no ATS match"
    return best, attempt


def discover_company(co: dict, blocked_row: dict | None) -> Discovery:
    cid = str(co["id"])
    name = str(co.get("name") or cid)
    careers_seed = str(
        co.get("hub_url")
        or (blocked_row or {}).get("guess_public_careers")
        or (blocked_row or {}).get("browse_url")
        or ""
    ).strip()
    best: probe.ProbeRow | None = None
    best_url = ""
    errors: list[str] = []
    tests: list[dict[str, Any]] = []
    playwright_recovered = False
    for slug in slug_variants(cid, name)[:6]:
        api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        tests.append(
            {
                "url": api,
                "http_code": "",
                "final_url": api,
                "methods": ["greenhouse_api:probe"],
                "note": "slug sweep",
            }
        )
    gh_row = probe_greenhouse_slugs(cid, slug_variants(cid, name))
    if gh_row and gh_row.status == "ok":
        best = gh_row
        best_url = gh_row.url_tested
        tests.append(
            {
                "url": gh_row.url_tested,
                "http_code": 200,
                "final_url": gh_row.url_tested,
                "methods": [f"{gh_row.method}:{gh_row.status}"],
                "note": "greenhouse slug hit",
            }
        )
    for url in url_candidates(co, blocked_row):
        try:
            row, attempt = probe_url_curl(cid, url, referer=careers_seed or url)
            if "playwright_fetch:ok" in (attempt.get("methods") or []):
                playwright_recovered = True
            tests.append(attempt)
        except hub_network.HubNetworkPauseError:
            raise
        except Exception as exc:
            errors.append(str(exc)[:80])
            tests.append(
                {"url": url, "http_code": "", "methods": [], "note": str(exc)[:80]}
            )
            continue
        if row and row.status == "ok":
            if not best or int(row.total_jobs or 0) > int(best.total_jobs or 0):
                best = row
                best_url = url
        elif row and row.status == "empty" and int(row.total_jobs or 0) > 0 and not best:
            best = row
            best_url = url
    method = best.method if best else ""
    status = best.status if best else "no_handler"
    rec_type = METHOD_TO_TYPE.get(method, "")
    apply = "yes" if best and best.status == "ok" and rec_type and rec_type != "hub" else "no"
    if method == "ashby" and best and best.status == "ok":
        apply = "yes"
    outcome = "converted" if apply == "yes" else "no_handler"
    if apply == "yes" and playwright_recovered:
        notes = "curl blocked; playwright discovered ATS"
    elif apply == "yes":
        notes = ""
    elif playwright_recovered:
        notes = "curl blocked; playwright found ATS signals (no scrape-ready handler)"
    else:
        notes = "exclude or manual ATS research"
    discovery = Discovery(
        id=cid,
        name=name,
        careers_url=str(co.get("hub_url") or ""),
        method=method,
        status=status,
        total_jobs=best.total_jobs if best else "",
        keyword_hits=best.keyword_hits if best else "",
        recommended_type=rec_type if apply == "yes" else "",
        apply=apply,
        config_hint=best.config_hint if best else "",
        url_tested=best.url_tested if best else best_url,
        error=best.error if best else ("; ".join(errors[:3]) if errors else ""),
        notes=notes,
        tests=tests,
    )
    journal.record_probe(
        co,
        outcome=outcome,
        tests=tests,
        source="discover",
        method=method,
        status=status,
        apply=apply,
        config_hint=discovery.config_hint,
        url_tested=discovery.url_tested,
        error=discovery.error,
    )
    return discovery


def apply_row(co: dict, row: Discovery) -> None:
    fields = probe.parse_hint_fields(row.config_hint)
    rtype = row.recommended_type
    co.pop("hub_url", None)
    co.pop("hub_note", None)
    co["type"] = rtype
    browse = fields.get("browse_url") or row.url_tested or row.careers_url
    if browse:
        co["browse_url"] = browse
    co["max_details"] = co.get("max_details") or 12
    co["cache_ttl_hours"] = co.get("cache_ttl_hours") or 24
    co["skip_verify"] = True
    co.setdefault("default_loc", "remote")
    if rtype == "phenom":
        if fields.get("phenom_base"):
            co["phenom_base"] = fields["phenom_base"]
        if fields.get("phenom_refnum"):
            co["phenom_refnum"] = fields["phenom_refnum"]
    elif rtype == "oracle_hcm":
        for k in ("oracle_api_base", "oracle_site_number"):
            if fields.get(k):
                co[k] = fields[k]
    elif rtype == "greenhouse":
        if fields.get("board"):
            co["board"] = fields["board"]
        co["discover"] = True
    elif rtype == "lever":
        if fields.get("board"):
            co["board"] = fields["board"]
    elif rtype == "smartrecruiters":
        sr = fields.get("smartrecruiters_id") or fields.get("board")
        if sr:
            co["smartrecruiters_id"] = sr
    elif rtype == "successfactors":
        co["search_base"] = fields.get("search_base") or browse
    elif rtype == "talentbrew":
        if fields.get("talentbrew_host"):
            co["talentbrew_host"] = fields["talentbrew_host"]
        co["talentbrew_max_queries"] = 4
    elif rtype == "icims":
        tpl = fields.get("search_url_template")
        if tpl:
            co["search_url_template"] = tpl
    elif rtype == "playwright":
        kind = fields.get("playwright_kind") or "eightfold"
        co["playwright_kind"] = kind
        if kind == "eightfold" or fields.get("eightfold_fetch"):
            co["eightfold_fetch"] = "pcsx"
        tpl = fields.get("search_url_template")
        if tpl:
            co["search_url_template"] = tpl
    elif rtype == "taleo_cws":
        for k in ("taleo_host", "taleo_org", "taleo_cws"):
            if fields.get(k):
                co[k] = fields[k]
    elif rtype == "ashby":
        slug = fields.get("board") or ""
        if not slug:
            m = re.search(
                r"job-board/([^/\s\"]+)|ashby slug=([^\s;]+)",
                row.config_hint or "",
                re.I,
            )
            if m:
                slug = m.group(1) or m.group(2) or ""
        if slug:
            co["ashby_board"] = slug
            co["browse_url"] = f"https://jobs.ashbyhq.com/{slug}"
        co["discover"] = True
        co["type"] = "ashby"


def apply_ashby_fetch(quickjobs_path: Path) -> None:
    """Register ashby type in quickjobs if missing (minimal HTTP fetch)."""
    text = quickjobs_path.read_text()
    if '"ashby"' in text and "def fetch_ashby" in text:
        return
    # Ashby support added separately in quickjobs.david.py


def load_blocked() -> dict[str, dict]:
    if not BLOCKED_TSV.is_file():
        return {}
    return {r["id"]: r for r in csv.DictReader(BLOCKED_TSV.open(), delimiter="\t")}


def load_hub_targets(from_deferred: Path | None) -> list[dict]:
    if from_deferred is not None:
        data = json.loads(from_deferred.read_text())
        hubs = data.get("deferred_hubs") or data.get("companies") or []
        return [c for c in hubs if isinstance(c, dict) and c.get("id")]
    cfg = hub_tools.load_base_bundle()
    return [c for c in cfg["companies"] if str(c.get("type") or "").lower() == "hub"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=0, help="Thread pool size (0=QUICKJOBS_HUB_MAX_WORKERS)")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max hubs to process this run (0=all remaining)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Rotate hub list by N before --limit",
    )
    parser.add_argument(
        "--from-deferred",
        type=Path,
        nargs="?",
        const=DEFERRED_JSON,
        default=None,
        metavar="PATH",
        help=f"Discover deferred hubs from JSON (default {DEFERRED_JSON}) instead of base type=hub",
    )
    parser.add_argument(
        "--ids",
        type=str,
        default="",
        help="Comma-separated hub ids to probe (default: all hubs in scope)",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--exclude-unresolved",
        action="store_true",
        help="Add unresolved hub ids to profile company_ids_exclude (removes from board)",
    )
    parser.add_argument(
        "--sync-hidden",
        action="store_true",
        help="After run: sync deferred hubs + rebuild unconvertible careers JSON",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint state file (default when state exists)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore checkpoint and start a new discovery run",
    )
    args = parser.parse_args()

    cfg = hub_tools.load_base_bundle()
    hubs = load_hub_targets(args.from_deferred)
    if args.ids.strip():
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        hubs = [c for c in hubs if str(c.get("id") or "") in want]
    if not hubs:
        print("No hub employers to discover (base has no type=hub; use --from-deferred).", file=sys.stderr)
        return 1
    total_hubs = len(hubs)
    if total_hubs and args.offset:
        off = args.offset % total_hubs
        hubs = hubs[off:] + hubs[:off]
    if args.limit > 0:
        hubs = hubs[: args.limit]
    blocked = load_blocked()
    source = args.from_deferred or BASE
    workers = max(1, args.workers or hub_http.hub_max_workers(8))
    batch_hub_ids = [str(co.get("id") or "") for co in hubs]

    checkpoint: dict[str, Any] | None = None
    rows: list[Discovery] = []
    completed_ids: set[str] = set()
    if args.fresh:
        run_state.clear_state()
    elif run_state.state_path().is_file():
        checkpoint = run_state.load_state()
        if checkpoint:
            if not run_state.params_compatible(checkpoint, args):
                print(
                    "Warning: CLI args differ from checkpoint; "
                    "resuming with current hub list and skipping completed ids",
                    file=sys.stderr,
                )
            completed_ids = {str(x) for x in checkpoint.get("completed_ids") or []}
            rows = [
                run_state.discovery_from_dict(r)
                for r in checkpoint.get("rows") or []
                if isinstance(r, dict)
            ]
            in_progress = str(checkpoint.get("in_progress_hub_id") or "").strip()
            if in_progress:
                run_state.uncomplete_hub(checkpoint, in_progress)
                run_state.save_state(checkpoint)
                completed_ids = {str(x) for x in checkpoint.get("completed_ids") or []}
                print(
                    f"Resuming run {checkpoint.get('run_id', '?')}: "
                    f"retry {in_progress} from start "
                    f"({len(completed_ids)} hubs already done)…",
                    flush=True,
                )
            elif completed_ids:
                print(
                    f"Resuming run {checkpoint.get('run_id', '?')}: "
                    f"{len(completed_ids)} hubs done, "
                    f"{len(checkpoint.get('hub_ids') or []) - len(completed_ids)} remaining",
                    flush=True,
                )
            remaining = run_state.remaining_hub_ids(checkpoint)
            by_id = {str(co.get("id") or ""): co for co in hubs}
            hubs = [by_id[cid] for cid in remaining if cid in by_id]
        elif args.resume:
            print("No valid checkpoint found; starting fresh.", file=sys.stderr)
    elif args.resume:
        print("No checkpoint state file; starting fresh.", file=sys.stderr)

    if not checkpoint and batch_hub_ids:
        checkpoint = run_state.new_state(
            args,
            total_hubs=total_hubs,
            hub_ids=batch_hub_ids,
        )
        run_state.save_state(checkpoint)

    print(
        f"Discovering ATS paths for {len(hubs)} employers "
        f"(of {total_hubs} hubs, offset {args.offset}, source: {source}, "
        f"workers={workers}, delay_ms={hub_http.hub_delay_ms()})…",
        flush=True,
    )

    applied_ids: list[str] = []
    if hubs:
        done = len(completed_ids)
        total_this_run = len(completed_ids) + len(hubs)
        for co in hubs:
            cid = str(co.get("id") or "")
            while True:
                if checkpoint is not None:
                    run_state.set_in_progress(checkpoint, cid)
                    run_state.save_state(checkpoint)
                try:
                    row = discover_company(co, blocked.get(cid))
                except hub_network.HubNetworkPauseError:
                    if checkpoint is not None:
                        run_state.uncomplete_hub(checkpoint, cid)
                        run_state.set_in_progress(checkpoint, cid)
                        run_state.save_state(checkpoint)
                    print(
                        f"  paused mid-hub {cid}; waiting for connectivity…",
                        flush=True,
                    )
                    hub_network.wait_until_resumed()
                    print(f"  retrying {cid} from start…", flush=True)
                    continue
                if checkpoint is not None:
                    run_state.complete_hub(checkpoint, row)
                    run_state.save_state(checkpoint)
                    rows = [
                        run_state.discovery_from_dict(r)
                        for r in checkpoint.get("rows") or []
                        if isinstance(r, dict)
                    ]
                else:
                    rows.append(row)
                done += 1
                status = row.recommended_type if row.apply == "yes" else "no API"
                print(
                    f"  [{done}/{total_this_run}] {row.id}: {status}",
                    flush=True,
                )
                if (
                    args.apply
                    and row.apply == "yes"
                    and row.recommended_type
                ):
                    cfg = hub_tools.load_base_bundle()
                    by_id = {c["id"]: c for c in cfg["companies"]}
                    co_apply = by_id.get(row.id)
                    if co_apply and str(co_apply.get("type") or "").lower() == "hub":
                        apply_row(co_apply, row)
                        hub_tools.save_base_bundle(cfg)
                        applied_ids.append(row.id)
                        print(
                            f"  applied {row.id}: {row.recommended_type} via {row.method} "
                            f"({row.total_jobs} jobs)"
                        )
                break
    else:
        print("All hubs in scope already completed for this checkpoint.", flush=True)

    if checkpoint is not None:
        expected = len(checkpoint.get("hub_ids") or [])
        if expected and len(checkpoint.get("completed_ids") or []) >= expected:
            run_state.clear_state()
            print("Checkpoint cleared (run complete).", flush=True)

    rows.sort(key=lambda r: (r.apply != "yes", r.id))
    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "name",
        "careers_url",
        "method",
        "status",
        "total_jobs",
        "keyword_hits",
        "recommended_type",
        "apply",
        "config_hint",
        "url_tested",
        "error",
        "notes",
    ]
    with OUT_TSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({k: getattr(r, k) for k in fields})

    ok = [r for r in rows if r.apply == "yes"]
    print(f"Wrote {OUT_TSV}")
    print(f"Scrape-ready: {len(ok)} / {len(rows)}")
    for r in ok:
        print(f"  {r.id}: {r.recommended_type} via {r.method} ({r.total_jobs} jobs)")

    if args.apply and not args.from_deferred:
        print(f"Applied {len(applied_ids)} conversions to {BASE} (incremental)")
    elif args.apply and args.from_deferred:
        cfg = hub_tools.load_base_bundle()
        by_id = {c["id"]: c for c in cfg["companies"]}
        applied = []
        for r in ok:
            co = by_id.get(r.id)
            if not co:
                deferred = {c["id"]: c for c in hubs}
                co = dict(deferred.get(r.id) or {"id": r.id, "name": r.name, "section": "matching"})
                cfg["companies"].append(co)
                by_id[r.id] = co
            apply_row(co, r)
            applied.append(r.id)
        hub_tools.save_base_bundle(cfg)
        print(f"Applied {len(applied)} conversions to {BASE}")

    unresolved = [r.id for r in rows if r.apply != "yes"]
    if args.exclude_unresolved and unresolved:
        profile = json.loads(PROFILE.read_text()) if PROFILE.is_file() else {}
        exclude = set(profile.get("company_ids_exclude") or [])
        exclude.update(unresolved)
        profile["company_ids_exclude"] = sorted(exclude)
        PROFILE.write_text(json.dumps(profile, indent=2) + "\n")
        print(f"Excluded {len(unresolved)} companies from board via {PROFILE}")

    if args.sync_hidden:
        n = journal.sync_deferred_from_journal()
        print(f"Synced {n} entries to {journal.DEFERRED_PATH}")
        journal.rebuild_unconvertible()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
