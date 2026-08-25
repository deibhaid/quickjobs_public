#!/usr/bin/env python3
"""Generate quickjobs.<name>.favicon-domains.json from base config + ATS APIs.

Probes Greenhouse job absolute_url values, then fills gaps with known overrides,
id/board heuristics, and DuckDuckGo ``"{company} careers"`` lookup for misses.
Re-run after adding ATS companies to base.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_DIR = REPO_ROOT / "scripts" / "_shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
import config_bundle  # noqa: E402

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_DDG_USER_AGENT = "Mozilla/5.0 (compatible; quickjobs-favicon-gen/1.0)"
_DDG_DELAY_SEC = 1.0
_GH_API_DELAY_SEC = 0.08

_ATS_FAVICON_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "jobs.lever.co",
        "api.lever.co",
        "jobs.ashbyhq.com",
        "ashbyhq.com",
        "myworkdayjobs.com",
        "myworkdaysite.com",
        "myworkday.com",
        "dice.com",
        "www.dice.com",
        "mcp.dice.com",
        "linkedin.com",
        "www.linkedin.com",
        "smartrecruiters.com",
        "icims.com",
    }
)

# company id → registrable domain when slug/id heuristics fail
KNOWN_BY_COMPANY_ID: dict[str, str] = {
    "10x-genomics": "10xgenomics.com",
    "1password": "1password.com",
    "aflac": "aflac.com",
    "agility": "agilityrobotics.com",
    "airbnb": "airbnb.com",
    "align-technology": "aligntech.com",
    "anduril": "anduril.com",
    "anthropic": "anthropic.com",
    "archer-daniels-midland": "adm.com",
    "arize-ai": "arize.com",
    "axon-enterprise": "axon.com",
    "bill-com": "bill.com",
    "block": "block.xyz",
    "box": "box.com",
    "chainguard": "chainguard.dev",
    "character": "character.ai",
    "charles-river-laboratories": "criver.com",
    "cockroach-labs": "cockroachlabs.com",
    "coreweave": "coreweave.com",
    "d-r-horton": "drhorton.com",
    "discord": "discord.com",
    "doordash": "doordash.com",
    "elastic": "elastic.co",
    "epic-systems": "epicgames.com",
    "eqt": "eqt.com",
    "extrahop": "extrahop.com",
    "fireworks-ai": "fireworks.ai",
    "flatiron-health": "flatironhealth.com",
    "flex": "flex.com",
    "fox": "fox.com",
    "general-dynamics": "gd.com",
    "getty-images": "gettyimages.com",
    "grail": "grailbio.com",
    "grafana-labs": "grafana.com",
    "harness": "harness.io",
    "hinge-health": "hingehealth.com",
    "iex": "iex.io",
    "planet-labs": "planet.com",
    "public-service-enterprise-group": "pseg.com",
    "public-storage": "publicstorage.com",
    "pure-storage": "purestorage.com",
    "purestorage": "purestorage.com",
    "redpanda": "redpanda.com",
    "rocket-lab": "rocketlabusa.com",
    "runpod": "runpod.io",
    "scale-ai": "scale.com",
    "shieldai": "shield.ai",
    "sourcegraph": "sourcegraph.com",
    "take-two-interactive": "taketwo.com",
    "temporal": "temporal.io",
    "together-ai": "together.ai",
    "u-s-bancorp": "usbank.com",
    "unity": "unity.com",
    "universal-health-services": "uhsinc.com",
    "w-w-grainger": "grainger.com",
    "weave": "getweave.com",
    "wiz": "wiz.io",
}


@dataclass
class DomainHit:
    domain: str
    source: str  # known, gh_api, heuristic, ddg, existing


def _is_ats_favicon_host(host: str) -> bool:
    h = str(host or "").strip().lower().removeprefix("www.")
    if not h:
        return True
    if h in _ATS_FAVICON_HOSTS:
        return True
    return any(
        token in h
        for token in (
            "greenhouse.io",
            "lever.co",
            "ashbyhq.com",
            "myworkdayjobs.com",
            "myworkdaysite.com",
            "myworkday.com",
            "dice.com",
            "linkedin.com",
            "smartrecruiters.com",
            "icims.com",
        )
    )


def corporate_domain_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.netloc or "").strip().lower().removeprefix("www.")
    if not host or _is_ats_favicon_host(host):
        return ""
    return host


def greenhouse_board_slug(url: str) -> str:
    match = re.search(r"greenhouse\.io/([^/?#]+)", str(url or ""), re.I)
    return match.group(1) if match else ""


def ashby_board_slug(url: str) -> str:
    parts = urlparse(str(url or "")).path.strip("/").split("/")
    return parts[0] if parts else ""


def lever_site_slug(url: str) -> str:
    parts = urlparse(str(url or "")).path.strip("/").split("/")
    return parts[0] if parts else ""


def workday_site_slug(url: str) -> str:
    match = re.search(r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", str(url or ""), re.I)
    return match.group(1).lower() if match else ""


def smartrecruiters_company_slug(url: str) -> str:
    parts = urlparse(str(url or "")).path.strip("/").split("/")
    return parts[0] if parts else ""


def icims_careers_slug(url: str) -> str:
    host = urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    match = re.match(r"careers-([a-z0-9-]+)\.icims\.com", host)
    if match:
        return match.group(1)
    match = re.match(r"([a-z0-9-]+)\.icims\.com", host)
    return match.group(1) if match else ""


def company_display_name(co: dict) -> str:
    return str(co.get("name") or co.get("label") or co.get("id") or "").strip()


def heuristic_domain(company_id: str, board: str = "") -> str:
    cid = str(company_id or "").strip().lower()
    if cid in KNOWN_BY_COMPANY_ID:
        return KNOWN_BY_COMPANY_ID[cid]
    if cid.endswith("-ai"):
        base = cid[: -len("-ai")].replace("-", "")
        if base:
            return f"{base}.ai"
    slug = re.sub(r"[^a-z0-9]", "", cid)
    if slug:
        return f"{slug}.com"
    slug = re.sub(r"[^a-z0-9]", "", str(board or ""))
    return f"{slug}.com" if slug else ""


def is_unconfirmed_heuristic(domain: str, company_id: str, source: str) -> bool:
    if source not in ("heuristic", ""):
        return False
    if not domain:
        return True
    cid = str(company_id or "").strip().lower()
    expected = heuristic_domain(cid)
    return domain.lower() == expected.lower()


def needs_careers_lookup(hit: DomainHit | None, company_id: str) -> bool:
    if hit is None or not hit.domain:
        return True
    if hit.source in ("gh_api", "known", "ddg", "existing"):
        return False
    return is_unconfirmed_heuristic(hit.domain, company_id, hit.source)


def greenhouse_scan_board(board: str, *, timeout: float = 20.0) -> str:
    api = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    req = urllib.request.Request(api, headers={"User-Agent": "quickjobs-favicon-gen/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    counts: dict[str, int] = {}
    for job in data.get("jobs") or []:
        domain = corporate_domain_from_url(str(job.get("absolute_url") or ""))
        if domain:
            counts[domain] = counts.get(domain, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def ddg_careers_domain(company_name: str, *, timeout: float = 20.0) -> str:
    query = f"{company_name.strip()} careers"
    if not query.strip():
        return ""
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(
        _DDG_HTML_URL,
        data=data,
        headers={"User-Agent": _DDG_USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"', html):
        url = match.group(1).strip()
        domain = corporate_domain_from_url(url)
        if domain:
            return domain
    return ""


_AGGREGATOR_FAVICON_TYPES = frozenset(
    {
        "dice_mcp",
        "linkedin",
        "qualityinfo",
    }
)


def company_skips_favicon_domain(company_cfg: dict) -> bool:
    """Aggregators / job sites use per-posting employer branding."""
    group = str(company_cfg.get("source_group") or "").strip().lower()
    if group in {"job_sites", "recruiters"}:
        return True
    return str(company_cfg.get("type") or "").strip().lower() in _AGGREGATOR_FAVICON_TYPES


def resolve_domain_for_company(
    co: dict,
    *,
    probe_api: bool = True,
    careers_lookup: bool = True,
    existing_domain: str = "",
    existing_source: str = "",
) -> DomainHit:
    cid = str(co.get("id") or "").strip()
    browse = str(co.get("browse_url") or co.get("hub_url") or "").strip()
    board = str(co.get("board") or "").strip()
    domain = ""
    source = ""

    if existing_domain and existing_source == "existing":
        return DomainHit(existing_domain, "existing")

    if cid in KNOWN_BY_COMPANY_ID:
        return DomainHit(KNOWN_BY_COMPANY_ID[cid], "known")

    if company_skips_favicon_domain(co):
        return DomainHit("", "aggregator")

    for key in ("favicon_domain", "website"):
        raw = str(co.get(key) or "").strip()
        if not raw:
            continue
        hit = corporate_domain_from_url(raw if "://" in raw else f"https://{raw}")
        if hit:
            return DomainHit(hit, "known")

    if "greenhouse.io" in browse:
        board = board or greenhouse_board_slug(browse)
        if probe_api and board:
            try:
                domain = greenhouse_scan_board(board)
                time.sleep(_GH_API_DELAY_SEC)
                if domain:
                    source = "gh_api"
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError):
                domain = ""
        if not domain:
            domain = heuristic_domain(cid, board)
            source = "heuristic"
        hit = DomainHit(domain, source)
        if needs_careers_lookup(hit, cid) and careers_lookup:
            ddg = ddg_careers_domain(company_display_name(co))
            time.sleep(_DDG_DELAY_SEC)
            if ddg:
                return DomainHit(ddg, "ddg")
        return hit

    if "ashbyhq.com" in browse:
        ashby = str(co.get("ashby_board") or "").strip() or ashby_board_slug(browse)
        domain = heuristic_domain(cid, ashby)
        hit = DomainHit(domain, "heuristic")
        if needs_careers_lookup(hit, cid) and careers_lookup:
            ddg = ddg_careers_domain(company_display_name(co))
            time.sleep(_DDG_DELAY_SEC)
            if ddg:
                return DomainHit(ddg, "ddg")
        return hit

    if "lever.co" in browse:
        lever = str(co.get("lever_site") or "").strip() or lever_site_slug(browse)
        domain = heuristic_domain(cid, lever)
        hit = DomainHit(domain, "heuristic")
        if needs_careers_lookup(hit, cid) and careers_lookup:
            ddg = ddg_careers_domain(company_display_name(co))
            time.sleep(_DDG_DELAY_SEC)
            if ddg:
                return DomainHit(ddg, "ddg")
        return hit

    if "myworkdayjobs.com" in browse or "myworkdaysite.com" in browse:
        wd = workday_site_slug(browse)
        domain = heuristic_domain(cid, wd)
        hit = DomainHit(domain, "heuristic")
        if needs_careers_lookup(hit, cid) and careers_lookup:
            ddg = ddg_careers_domain(company_display_name(co))
            time.sleep(_DDG_DELAY_SEC)
            if ddg:
                return DomainHit(ddg, "ddg")
        return hit

    if "smartrecruiters.com" in browse:
        sr = smartrecruiters_company_slug(browse)
        domain = heuristic_domain(cid, sr)
        hit = DomainHit(domain, "heuristic")
        if needs_careers_lookup(hit, cid) and careers_lookup:
            ddg = ddg_careers_domain(company_display_name(co))
            time.sleep(_DDG_DELAY_SEC)
            if ddg:
                return DomainHit(ddg, "ddg")
        return hit

    if "icims.com" in browse:
        icims = icims_careers_slug(browse)
        domain = heuristic_domain(cid, icims)
        hit = DomainHit(domain, "heuristic")
        if needs_careers_lookup(hit, cid) and careers_lookup:
            ddg = ddg_careers_domain(company_display_name(co))
            time.sleep(_DDG_DELAY_SEC)
            if ddg:
                return DomainHit(ddg, "ddg")
        return hit

    if company_skips_favicon_domain(co):
        return DomainHit("", "aggregator")

    return DomainHit("", "")


def generate_for_base(
    base_path: Path,
    *,
    probe_api: bool = True,
    careers_lookup: bool = True,
    only_missing: bool = False,
    existing: dict[str, dict[str, str]] | None = None,
    limit: int | None = None,
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    base = config_bundle.load_base_bundle(base_path)
    prior = existing or {}
    prior_by_id = dict(prior.get("by_company_id") or {})
    by_company_id: dict[str, str] = dict(prior_by_id)
    by_greenhouse_board: dict[str, str] = dict(prior.get("by_greenhouse_board") or {})
    by_ashby_board: dict[str, str] = dict(prior.get("by_ashby_board") or {})
    by_lever_site: dict[str, str] = dict(prior.get("by_lever_site") or {})
    by_workday_site: dict[str, str] = dict(prior.get("by_workday_site") or {})
    by_smartrecruiters_company: dict[str, str] = dict(
        prior.get("by_smartrecruiters_company") or {}
    )
    log: list[dict[str, str]] = []
    processed = 0

    for co in base.get("companies") or []:
        if not isinstance(co, dict):
            continue
        cid = str(co.get("id") or "").strip()
        if not cid:
            continue
        if company_skips_favicon_domain(co):
            continue
        browse = str(co.get("browse_url") or co.get("hub_url") or "").strip()
        ats_backed = any(
            token in browse
            for token in (
                "greenhouse.io",
                "ashbyhq.com",
                "lever.co",
                "myworkdayjobs.com",
                "myworkdaysite.com",
                "myworkday.com",
                "dice.com",
                "smartrecruiters.com",
                "icims.com",
            )
        )
        if not ats_backed:
            continue

        existing_domain = str(prior_by_id.get(cid) or "").strip()
        if only_missing and existing_domain and not is_unconfirmed_heuristic(
            existing_domain, cid, "heuristic"
        ):
            continue

        if limit is not None and processed >= limit:
            break

        hit = resolve_domain_for_company(
            co,
            probe_api=probe_api,
            careers_lookup=careers_lookup,
            existing_domain=existing_domain,
            existing_source="existing" if existing_domain and only_missing else "",
        )
        processed += 1
        if not hit.domain:
            log.append({"id": cid, "name": company_display_name(co), "source": hit.source, "domain": ""})
            continue

        by_company_id[cid] = hit.domain
        board = str(co.get("board") or "").strip()
        if "greenhouse.io" in browse:
            gh_board = board or greenhouse_board_slug(browse)
            if gh_board:
                by_greenhouse_board[gh_board] = hit.domain
        elif "ashbyhq.com" in browse:
            ashby = str(co.get("ashby_board") or "").strip() or ashby_board_slug(browse)
            if ashby:
                by_ashby_board[ashby] = hit.domain
        elif "lever.co" in browse:
            lever = str(co.get("lever_site") or "").strip() or lever_site_slug(browse)
            if lever:
                by_lever_site[lever] = hit.domain
        elif "myworkdayjobs.com" in browse or "myworkdaysite.com" in browse:
            wd = workday_site_slug(browse)
            if wd:
                by_workday_site[wd] = hit.domain
        elif "smartrecruiters.com" in browse:
            sr = smartrecruiters_company_slug(browse)
            if sr:
                by_smartrecruiters_company[sr] = hit.domain

        log.append(
            {
                "id": cid,
                "name": company_display_name(co),
                "source": hit.source,
                "domain": hit.domain,
            }
        )

    payload = {
        "by_company_id": dict(sorted(by_company_id.items())),
        "by_greenhouse_board": dict(sorted(by_greenhouse_board.items())),
        "by_ashby_board": dict(sorted(by_ashby_board.items())),
        "by_lever_site": dict(sorted(by_lever_site.items())),
        "by_workday_site": dict(sorted(by_workday_site.items())),
        "by_smartrecruiters_company": dict(sorted(by_smartrecruiters_company.items())),
    }
    return payload, log


def default_output_path(base_path: Path) -> Path:
    stem = base_path.name.replace(".base.json", "")
    return base_path.with_name(f"{stem}.favicon-domains.json")


def load_existing(out_path: Path) -> dict[str, dict[str, str]]:
    if not out_path.is_file():
        return {}
    try:
        raw = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        "by_company_id": dict(raw.get("by_company_id") or {}),
        "by_greenhouse_board": dict(raw.get("by_greenhouse_board") or {}),
        "by_ashby_board": dict(raw.get("by_ashby_board") or {}),
        "by_lever_site": dict(raw.get("by_lever_site") or {}),
        "by_workday_site": dict(raw.get("by_workday_site") or {}),
        "by_smartrecruiters_company": dict(raw.get("by_smartrecruiters_company") or {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate quickjobs favicon domain overrides from base.json.",
    )
    parser.add_argument(
        "base_json",
        nargs="?",
        type=Path,
        default=REPO_ROOT / "quickjobs.david.base.json",
        help="Base config JSON (default: quickjobs.david.base.json)",
    )
    parser.add_argument(
        "out_json",
        nargs="?",
        type=Path,
        default=None,
        help="Output path (default: quickjobs.<name>.favicon-domains.json beside base)",
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="Skip Greenhouse API probing (heuristics + careers lookup only)",
    )
    parser.add_argument(
        "--no-careers-lookup",
        action="store_true",
        help="Skip DuckDuckGo careers search for missing/unconfirmed domains",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Keep existing domains; only fill gaps and unconfirmed slug.com heuristics",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved domains without writing output JSON",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N ATS-backed companies (for smoke tests)",
    )
    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))

    base_path = args.base_json.expanduser()
    out_path = args.out_json.expanduser() if args.out_json else default_output_path(base_path)
    existing = load_existing(out_path) if (args.only_missing or args.dry_run) else {}

    payload, log = generate_for_base(
        base_path,
        probe_api=not args.no_probe,
        careers_lookup=not args.no_careers_lookup,
        only_missing=args.only_missing,
        existing=existing if args.only_missing else None,
        limit=args.limit,
    )

    for row in log:
        print(f"{row['id']}\t{row['source'] or '-'}\t{row['domain'] or '-'}\t{row['name']}")

    if args.dry_run:
        print(
            f"Dry run: would write {out_path}: "
            f"{len(payload['by_company_id'])} companies, "
            f"{len(payload['by_greenhouse_board'])} GH boards, "
            f"{len(payload['by_ashby_board'])} Ashby, "
            f"{len(payload['by_lever_site'])} Lever "
            f"({len(log)} processed this run)"
        )
        return 0

    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Wrote {out_path}: "
        f"{len(payload['by_company_id'])} companies, "
        f"{len(payload['by_greenhouse_board'])} GH boards, "
        f"{len(payload['by_ashby_board'])} Ashby, "
        f"{len(payload['by_lever_site'])} Lever"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
