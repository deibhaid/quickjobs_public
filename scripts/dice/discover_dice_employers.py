#!/usr/bin/env python3
"""Schedulable Dice.com employer-catalog miner for quickjobs.

Purpose: build up an EMPLOYER catalog over time (companies, NOT live jobs).
For each discovered employer we accumulate: careers/ATS website URL + detected
ATS type, observed salary ranges, job types/titles seen, locations, and
first/last seen timestamps. Recency of a posting does not matter; scheduled
reruns keep widening coverage.

Data flow (all in one pass, idempotent):
  1. Query the official Dice MCP `search_jobs` tool across a DevOps/Platform/
     SRE/Infra keyword set, using the WIDEST posted_date window Dice allows
     (which is: omit posted_date entirely -> see notes below), paginating to
     the per-query page ceiling.
  2. Merge every posting into a persistent employer catalog keyed by a
     normalized employer name. New employers are fingerprinted ONCE (ATS type)
     and cached; known employers are not re-probed.
  3. Flag staffing agencies / recruiters (kept in the catalog with is_agency)
     and whether each employer is already present in quickjobs base.json and
     whether its ATS is API-scrapable.
  4. Emit a dated "new since last run" candidates report.

Dice MCP limits (verified 2026-07):
  * posted_date accepts only 'ONE' (1d), 'THREE' (3d), 'SEVEN' (7d). Values
    like FOURTEEN/THIRTY/ALL are silently treated as no-match (0 rows), NOT an
    error. Omitting posted_date returns the full unfiltered set (widest window)
    -> for "devops" that is ~9,674 results vs ~2,272 for SEVEN. So this miner
    defaults to NO posted_date to reach the oldest postings Dice still indexes.
  * jobs_per_page max is 100 (values >100 return 0 rows).
  * page_number is 1-based; you can paginate up to meta.pageCount
    (= ceil(totalResults / pageSize)). Pages beyond pageCount return 0 rows.
  * There is no date-sort param; default sortBy is 'relevance'.

Reads (never writes):
  * quickjobs.base.json  (only to compute the "already in base" flag)

Writes:
  * ~/ws/scriptdir/output/dice-employer-catalog.json          (persistent)
  * ~/ws/scriptdir/output/dice-new-candidates-<date>.md/.json (per-run report)

Cron-friendly: absolute paths, ~/.v python, safe to run repeatedly, one summary
line at the end. This script NEVER installs a crontab entry. Print an example
schedule line with --print-cron.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Paths / constants
# --------------------------------------------------------------------------- #

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]  # .../quickjobs
SHARED_DIR = REPO_ROOT / "scripts" / "_shared"
HUBS_DIR = REPO_ROOT / "scripts" / "hubs"
DEFAULT_BASE = REPO_ROOT / "quickjobs.base.json"
OUTPUT_DIR = Path.home() / "ws" / "scriptdir" / "output"
DEFAULT_CATALOG = OUTPUT_DIR / "dice-employer-catalog.json"

ENDPOINT = "https://mcp.dice.com/mcp"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) quickjobs-discovery"

# Widest DevOps/Platform/SRE/Infra keyword net for employer discovery.
DEFAULT_KEYWORDS = [
    "devops",
    "site reliability engineer",
    "sre",
    "platform engineer",
    "platform engineering",
    "infrastructure engineer",
    "cloud engineer",
    "cloud infrastructure",
    "systems engineer",
    "kubernetes",
    "terraform",
    "reliability engineer",
    "principal engineer",
    "staff engineer",
    "observability",
]

# quickjobs ATS types we consider "API-scrapable" (clean HTTP/JSON board).
API_SCRAPABLE_TYPES = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "workday_cxs",
        "smartrecruiters",
        "icims",
        "phenom",
        "oracle_hcm",
        "successfactors",
        "taleo_cws",
        "json_feed",
    }
)

# Hourly / periodic -> annual multipliers for salary normalization.
PERIOD_MULT = {
    "hour": 2080,
    "hr": 2080,
    "week": 52,
    "wk": 52,
    "month": 12,
    "mo": 12,
    "day": 260,
    "annum": 1,
    "year": 1,
    "yr": 1,
}

# --------------------------------------------------------------------------- #
# Name normalization + agency heuristics (ported/extended from the prototype)
# --------------------------------------------------------------------------- #

SUFFIX_TOKENS = {
    "inc", "incorporated", "llc", "llp", "lp", "ltd", "limited", "corp",
    "corporation", "co", "company", "the", "group", "holdings", "holding",
    "plc", "gmbh", "sa", "ag", "usa", "us", "na", "international", "intl",
    "worldwide", "global",
}

AGENCY_PATTERNS = [
    r"\bstaffing\b", r"\bstaff\b", r"\brecruit(ing|ment|er|ers)?\b",
    r"\bconsultanc", r"\bconsulting\b", r"\bconsultants?\b", r"\btalent\b",
    r"\bresourc(e|es|ing)\b", r"\bplacements?\b", r"\bworkforce\b",
    r"\bheadhunt", r"\bcontract(ing|ors?)\b", r"\bmanpower\b", r"\bpersonnel\b",
    r"\bstaff aug", r"\bprofessional services\b", r"\bit services\b",
    r"\bit solutions\b", r"\btech(nology)? solutions\b",
    r"\btechnology services\b", r"\bstaff\.? augment", r"\brpo\b",
    r"\boutsourc", r"\bsystems? integrator", r"\bsolutions group\b",
]
AGENCY_RE = re.compile("|".join(AGENCY_PATTERNS), re.I)

KNOWN_AGENCIES = {
    "teksystems", "insight global", "robert half", "apex systems", "kforce",
    "randstad", "cybercoders", "jobot", "motion recruitment", "dice",
    "beacon hill", "collabera", "compunnel", "sunrise systems", "mindlance",
    "diverse lynx", "tekwissen", "eteam", "artech", "cynet systems",
    "russell tobin", "phaidon", "harnham", "signify technology", "averity",
    "talentburst", "genuent", "systemart", "nlb services", "ntt data",
    "ust global", "ust", "hcl", "wipro", "cognizant", "infosys", "capgemini",
    "accenture", "tata consultancy", "tcs", "mphasis", "ltimindtree", "virtusa",
    "syntel", "hexaware", "iqvia", "epam", "globant", "endava",
    "persistent systems", "birlasoft", "coforge", "sonsoft", "vdart", "photon",
    "zolon", "intelliswift", "amaze systems", "softworld", "the judge group",
    "judge group", "kellymitchell", "kelly services", "aditi", "connexions",
    "connext", "next step systems", "irvine technology", "aditi consulting",
    "leidos", "saic", "gdit", "general dynamics information technology",
    "peraton", "maximus", "brillio", "nagarro", "grid dynamics",
    "iron mountain", "kforce inc", "randstad digital", "experis", "modis",
    "akkodis", "yoh", "aerotek", "adecco", "matlen silver", "pyramid consulting",
    "us tech solutions", "spectraforce", "vaco", "e-solutions", "esolutions",
    "ampcus", "prokarma", "trigyn", "kforce technology", "spar information systems",
    "amtex", "amerit", "cornerstone staffing", "apn consulting", "abbtech",
    "abacus service", "acs solutions", "american cybersystems", "sgs technologie",
    "denken solutions", "software specialists", "the dignify solutions",
    "dignify solutions", "avance consulting", "syncreon", "smart it frame",
    "iris software", "tanisha systems", "stefanini", "atos", "unisys", "dxc",
    "dxc technology", "computer task group", "ctg",
}

# IT-services body shops that DO carry a public ATS board but are not genuine
# direct product employers (bench / client-req marketing).
BODY_SHOP_SUBSTR = {
    "infotek", "infotech", "soft tech", "softtech", "computer solutions",
    "global solutions", "business solutions", "business innovation",
    "silicon partners", "link solutions", "cloud technologies", "testingxperts",
    "damcosoft", "info tech", "sriven",
}


def normalize(name: str) -> str:
    n = (name or "").lower().strip()
    n = re.sub(r"&\w+;", " ", n)
    n = re.sub(r"[.,/&'\u2019\-\u2013\u2014():|]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    tokens = [t for t in n.split() if t and t not in SUFFIX_TOKENS]
    return " ".join(tokens)


def collapse(name: str) -> str:
    """Aggressive alnum-only key derived from the normalized name."""
    return re.sub(r"[^a-z0-9]", "", normalize(name))


def catalog_key(name: str) -> str:
    key = collapse(name)
    if key:
        return key
    # Name was entirely suffix tokens (rare) -> fall back to raw alnum.
    return re.sub(r"[^a-z0-9]", "", (name or "").lower()) or "unknown"


def slugify(name: str) -> str:
    s = re.sub(r"&\w+;", " ", name or "")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "unknown"


def is_agency(name: str, employer_types: list[str]) -> tuple[bool, str]:
    norm = normalize(name)
    ets = employer_types or []
    if ets and set(ets) == {"Recruiter"}:
        return True, "dice employerType=Recruiter"
    for known in KNOWN_AGENCIES:
        if known in norm or known.replace(" ", "") in norm.replace(" ", ""):
            return True, f"known agency/body-shop ({known})"
    m = AGENCY_RE.search(name or "")
    if m:
        return True, f"agency keyword ({m.group(0).strip()})"
    if "Recruiter" in ets and "Direct Hire" not in ets:
        return True, "dice employerType=Recruiter (multi)"
    low = re.sub(r"&\w+;", " ", (name or "").lower())
    for sub in BODY_SHOP_SUBSTR:
        if sub in low:
            return True, f"IT body-shop keyword ({sub})"
    return False, ""


# --------------------------------------------------------------------------- #
# Salary parsing
# --------------------------------------------------------------------------- #

_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?")


def parse_salary(label: str) -> tuple[int | None, int | None, bool]:
    """Return (annual_min, annual_max, is_hourly) from a raw salary label.

    Handles '$65,000 - $70,000', 'USD 125,000.00 - 135,000.00 per year',
    'USD 60.00 - 70.00 per hour', '$150K', 'Up to $200,000', etc. Hourly and
    other periodic rates are annualized so numeric min/max stay comparable.
    """
    if not label:
        return None, None, False
    text = label.strip()
    low = text.lower()

    mult = 1
    is_hourly = False
    for token, factor in PERIOD_MULT.items():
        if re.search(rf"(?:per\s+|/)\s*{token}\b|\b{token}ly\b", low):
            mult = factor
            is_hourly = token in ("hour", "hr")
            break
    if mult == 1 and re.search(r"/\s*hr|hourly|per hour", low):
        mult, is_hourly = 2080, True

    nums: list[float] = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        suffix = (m.group(2) or "").lower()
        if suffix == "k":
            val *= 1_000
        elif suffix == "m":
            val *= 1_000_000
        nums.append(val)

    if not nums:
        return None, None, is_hourly

    annual = sorted(int(round(n * mult)) for n in nums)
    lo, hi = annual[0], annual[-1]
    # Discard obvious noise (e.g. a lone requisition number or a tiny value).
    if hi < 10_000 or lo > 2_000_000:
        return None, None, is_hourly
    if lo < 10_000:  # keep the max, drop an implausibly small min
        lo = hi
    return lo, hi, is_hourly


# --------------------------------------------------------------------------- #
# Dice MCP client
# --------------------------------------------------------------------------- #

def mcp_call(arguments: dict[str, Any], timeout: int) -> dict | None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search_jobs", "arguments": arguments},
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        print(f"  MCP request error: {err}", file=sys.stderr)
        return None
    data = None
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            break
    if data is None:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
    return data


def extract_payload(data: Any) -> dict:
    """Pull the structured {data, meta} payload out of an MCP response."""

    def walk(obj: Any) -> dict | None:
        if isinstance(obj, list):
            for item in obj:
                res = walk(item)
                if res:
                    return res
        if isinstance(obj, dict):
            if isinstance(obj.get("data"), list) and "meta" in obj:
                return obj
            content = obj.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        try:
                            parsed = json.loads(block["text"])
                        except (json.JSONDecodeError, TypeError):
                            continue
                        res = walk(parsed) if isinstance(parsed, (list, dict)) else None
                        return res or (parsed if isinstance(parsed, dict) else None)
            for key in ("structuredContent", "result"):
                if key in obj:
                    res = walk(obj[key])
                    if res:
                        return res
        return None

    payload = walk(data)
    return payload if isinstance(payload, dict) else {}


def search_keyword(
    keyword: str,
    *,
    workplace_types: list[str] | None,
    employment_types: list[str] | None,
    posted_date: str | None,
    jobs_per_page: int,
    max_pages: int,
    timeout: int,
    delay: float,
) -> list[dict]:
    """Return all job rows for one keyword, paginating to the page ceiling."""
    rows: list[dict] = []
    page = 1
    page_count = 1
    total_results = None
    while page <= page_count:
        if max_pages and page > max_pages:
            break
        args: dict[str, Any] = {
            "keyword": keyword,
            "jobs_per_page": jobs_per_page,
            "page_number": page,
        }
        if posted_date:
            args["posted_date"] = posted_date
        if workplace_types:
            args["workplace_types"] = workplace_types
        if employment_types:
            args["employment_types"] = employment_types
        data = mcp_call(args, timeout)
        if not data:
            break
        payload = extract_payload(data)
        page_rows = payload.get("data") or []
        meta = payload.get("meta") or {}
        page_count = int(meta.get("pageCount") or 1)
        if total_results is None:
            total_results = meta.get("totalResults")
        if not isinstance(page_rows, list) or not page_rows:
            break
        rows.extend(r for r in page_rows if isinstance(r, dict))
        page += 1
        if page <= page_count and delay:
            time.sleep(delay)
    print(
        f"  {keyword!r}: {len(rows)} rows "
        f"(pages {min(page - 1, page_count)}/{page_count}, totalResults={total_results})",
        flush=True,
    )
    return rows


# --------------------------------------------------------------------------- #
# base.json index (read-only)
# --------------------------------------------------------------------------- #

def load_base_index(base_path: Path) -> dict[str, Any]:
    idx: dict[str, Any] = {
        "ids": set(),
        "collapsed_names": set(),
        "slugs": {t: {} for t in ("greenhouse", "lever", "ashby", "smartrecruiters")},
        "id_by_collapsed": {},
    }
    if not base_path.is_file():
        return idx
    try:
        cfg = config_bundle.load_base_bundle(base_path)
    except (json.JSONDecodeError, OSError):
        return idx
    comps = cfg.get("companies") if isinstance(cfg, dict) else cfg
    for c in comps or []:
        cid = str(c.get("id") or "")
        if cid:
            idx["ids"].add(cid)
        name = str(c.get("name") or c.get("label") or cid)
        for label in (name, cid.replace("-", " ")):
            col = collapse(label)
            if col:
                idx["collapsed_names"].add(col)
                idx["id_by_collapsed"].setdefault(col, cid)
        col_id = re.sub(r"[^a-z0-9]", "", cid.lower())
        if col_id:
            idx["collapsed_names"].add(col_id)
            idx["id_by_collapsed"].setdefault(col_id, cid)
        t = str(c.get("type") or "")
        if t == "greenhouse" and c.get("board"):
            idx["slugs"]["greenhouse"][str(c["board"]).lower()] = cid
        elif t == "lever" and c.get("lever_site"):
            idx["slugs"]["lever"][str(c["lever_site"]).lower()] = cid
        elif t == "ashby" and c.get("ashby_board"):
            idx["slugs"]["ashby"][str(c["ashby_board"]).lower()] = cid
        elif t == "smartrecruiters" and c.get("smartrecruiters_id"):
            idx["slugs"]["smartrecruiters"][str(c["smartrecruiters_id"]).lower()] = cid
    return idx


def base_match(name: str, ats: dict | None, idx: dict[str, Any]) -> str | None:
    """Return the matching base.json id (or a sentinel) if present, else None."""
    col = collapse(name)
    if col and col in idx["collapsed_names"]:
        return idx["id_by_collapsed"].get(col, "(name match)")
    if ats:
        t = ats.get("type")
        slug = str(ats.get("slug") or "").lower()
        if t in idx["slugs"] and slug and slug in idx["slugs"][t]:
            return idx["slugs"][t][slug]
    return None


# --------------------------------------------------------------------------- #
# ATS fingerprinting (reuses scripts/hubs probe machinery)
# --------------------------------------------------------------------------- #

_FP_MODS: dict[str, Any] = {}


def _load_fingerprint_mods() -> dict[str, Any] | None:
    """Import the hub probe modules lazily. Returns None if unavailable."""
    if _FP_MODS:
        return _FP_MODS
    if not HUBS_DIR.is_dir():
        return None
    if str(HUBS_DIR) not in sys.path:
        sys.path.insert(0, str(HUBS_DIR))
    try:
        import discover_hub_ats_paths as dh  # noqa: E402
        import hub_http  # noqa: E402
        import hub_network  # noqa: E402
        import probe_hub_scrape_methods as probe  # noqa: E402
    except Exception as err:  # pragma: no cover - import guard
        print(f"  fingerprint modules unavailable: {err}", file=sys.stderr)
        return None
    method_type = dict(dh.METHOD_TO_TYPE)
    method_type["workday_cxs"] = "workday_cxs"
    _FP_MODS.update(
        dh=dh, hub_http=hub_http, hub_network=hub_network, probe=probe,
        method_type=method_type,
    )
    return _FP_MODS


def _get_json(hub_http: Any, url: str):
    try:
        code, _, body = hub_http.http_get(url, timeout=25)
    except Exception:
        return None
    if code != 200 or not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _direct_api_probe(mods: dict, cid: str, name: str, slugs: list[str]) -> dict | None:
    dh, probe, hub_http = mods["dh"], mods["probe"], mods["hub_http"]
    gh = dh.probe_greenhouse_slugs(cid, slugs)
    if gh and gh.status == "ok":
        fields = probe.parse_hint_fields(gh.config_hint)
        return {
            "type": "greenhouse", "slug": fields.get("board") or "",
            "endpoint": gh.url_tested, "total_jobs": gh.total_jobs,
            "method": "greenhouse_api",
            "browse_url": fields.get("browse_url") or gh.url_tested,
        }
    spec = [s for s in slugs if len(s) >= 5 and s not in dh.GENERIC_GH_BOARD_SLUGS]
    for slug in spec[:6]:
        data = _get_json(hub_http, f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if isinstance(data, list) and data:
            return {
                "type": "lever", "slug": slug, "total_jobs": str(len(data)),
                "method": "lever_api",
                "endpoint": f"https://api.lever.co/v0/postings/{slug}",
                "browse_url": f"https://jobs.lever.co/{slug}",
            }
        data = _get_json(hub_http, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if isinstance(data, dict) and data.get("jobs"):
            return {
                "type": "ashby", "slug": slug, "total_jobs": str(len(data["jobs"])),
                "method": "ashby_api",
                "endpoint": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                "browse_url": f"https://jobs.ashbyhq.com/{slug}",
            }
        data = _get_json(hub_http, f"https://api.smartrecruiters.com/v1/companies/{slug}/postings")
        if isinstance(data, dict) and data.get("content") is not None and data.get("totalFound", 0):
            return {
                "type": "smartrecruiters", "slug": slug,
                "total_jobs": str(data.get("totalFound")),
                "method": "smartrecruiters_api",
                "endpoint": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                "browse_url": f"https://jobs.smartrecruiters.com/{slug}",
            }
    return None


def _name_tokens(name: str) -> set[str]:
    n = re.sub(r"&\w+;", " ", (name or "").lower())
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return {t for t in n.split() if t and t not in SUFFIX_TOKENS and len(t) >= 3}


def _name_matches(a: str, b: str) -> bool:
    if _name_tokens(a) & _name_tokens(b):
        return True
    ca, cb = collapse(a), collapse(b)
    return bool(ca and cb and (ca in cb or cb in ca))


def _org_confirms(company: str, org: str) -> bool:
    """Strict identity check between a company name and an ATS board's org name.

    Guards against slug collisions where a board is named after a single generic
    token (e.g. greenhouse board "charles" is literally named "charles", NOT
    "Charles Schwab"; "general" resolves to "General Interest", not General
    Dynamics). Requires an exact collapsed match, a >=2 shared distinctive
    tokens, or a genuine single-token company whose sole token IS the board.
    """
    ct, ot = _name_tokens(company), _name_tokens(org)
    if not ct or not ot:
        return False
    cc, oc = collapse(company), collapse(org)
    if cc and oc and cc == oc:
        return True
    if len(ct & ot) >= 2:
        return True
    if len(ct) == 1:
        tok = next(iter(ct))
        if oc.startswith(tok) and len(oc) <= len(tok) + 3:
            return True
        if tok in ot and len(ot) == 1:
            return True
    return False


def _verify_hit(mods: dict, name: str, hit: dict) -> str:
    """Confirm a fingerprint hit's identity. Returns confidence high/review/non_api."""
    method = hit.get("method", "")
    slug = str(hit.get("slug") or "")
    if method == "greenhouse_api":
        meta = _get_json(mods["hub_http"], f"https://boards-api.greenhouse.io/v1/boards/{slug}")
        org = str((meta or {}).get("name") or "")
        if org and _org_confirms(name, org):
            return "high"
        return "review"
    if method == "smartrecruiters_api":
        data = _get_json(
            mods["hub_http"],
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
        )
        org = ""
        if isinstance(data, dict) and data.get("content"):
            org = str(((data["content"][0] or {}).get("company") or {}).get("name") or "")
        if org and _org_confirms(name, org):
            return "high"
        return "review"
    if method in ("lever_api", "ashby_api"):
        # No org name from the API -> gate strictly on slug specificity.
        words = [w for w in re.split(r"[^a-z0-9]+", re.sub(r"&\w+;", " ", name.lower())) if w]
        cfull = collapse(name)
        c2 = collapse(" ".join(words[:2])) if len(words) >= 2 else ""
        s = collapse(slug)
        if s and (s == cfull or (c2 and s == c2)):
            return "high"
        if len(words) == 1 and s == collapse(words[0]) and len(s) >= 6:
            return "high"
        return "review"
    # careers-HTML fingerprint on the company's own domain.
    if hit.get("type") in API_SCRAPABLE_TYPES:
        endpoint = str(hit.get("endpoint") or hit.get("browse_url") or "")
        host = re.sub(r"^https?://", "", endpoint).split("/")[0].lower()
        host_flat = host.replace("-", "")
        if any(tok in host_flat for tok in {collapse(w) for w in _name_tokens(name)} if tok):
            return "high"
        return "review"
    return "non_api"


def _careers_html_probe(mods: dict, cid: str, name: str, url_cap: int) -> dict | None:
    dh, probe, hub_network = mods["dh"], mods["probe"], mods["hub_network"]
    co = {"id": cid, "name": name}
    try:
        urls = dh.url_candidates(co, None)
    except Exception:
        urls = []
    best = None
    best_url = ""
    for url in urls[:url_cap]:
        try:
            row, _ = dh.probe_url_curl(cid, url, referer=url)
        except hub_network.HubNetworkPauseError:
            hub_network.wait_until_resumed()
            continue
        except Exception:
            continue
        if row and row.status == "ok":
            if not best or int(row.total_jobs or 0) > int(best.total_jobs or 0):
                best, best_url = row, url
    if not best:
        return None
    fields = probe.parse_hint_fields(best.config_hint)
    return {
        "type": mods["method_type"].get(best.method, ""),
        "slug": fields.get("board") or fields.get("smartrecruiters_id") or "",
        "endpoint": best.url_tested,
        "total_jobs": best.total_jobs,
        "method": best.method,
        "browse_url": fields.get("browse_url") or best_url,
        "config_hint": best.config_hint,
    }


def fingerprint_employer(name: str, mode: str, url_cap: int) -> dict:
    """Detect ATS type for one employer. mode in {'full','api','off'}."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = {
        "type": None, "slug": "", "endpoint": "", "browse_url": "", "method": "",
        "confidence": "none", "api_scrapable": False, "fingerprinted_at": now,
    }
    if mode == "off":
        result["confidence"] = "skipped"
        return result
    mods = _load_fingerprint_mods()
    if not mods:
        result["confidence"] = "unavailable"
        return result
    cid = slugify(name)
    slugs = mods["dh"].slug_variants(cid, name)
    hit = None
    try:
        hit = _direct_api_probe(mods, cid, name, slugs)
    except Exception as err:
        result["error"] = f"api:{err}"[:160]
    if not hit and mode == "full":
        try:
            hit = _careers_html_probe(mods, cid, name, url_cap)
        except Exception as err:
            result.setdefault("error", f"html:{err}"[:160])
    if not hit or not hit.get("type"):
        return result
    result.update(
        {k: hit.get(k, result.get(k)) for k in ("type", "slug", "endpoint", "browse_url", "method")}
    )
    if hit.get("config_hint"):
        result["config_hint"] = hit["config_hint"]
    result["api_scrapable"] = hit["type"] in API_SCRAPABLE_TYPES
    if not result["api_scrapable"]:
        result["confidence"] = "non_api"
        return result
    try:
        result["confidence"] = _verify_hit(mods, name, hit)
    except Exception as err:  # pragma: no cover - verification is best-effort
        result.setdefault("error", f"verify:{err}"[:160])
        result["confidence"] = "review"
    return result


# --------------------------------------------------------------------------- #
# Catalog load / merge / save
# --------------------------------------------------------------------------- #

CATALOG_VERSION = 1
MAX_TITLES = 60
MAX_LOCATIONS = 40
MAX_SALARY_LABELS = 10
MAX_URL_SAMPLES = 5


def load_catalog(path: Path) -> dict:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("employers"), dict):
                return data
        except (json.JSONDecodeError, OSError):
            print(f"  warning: could not parse existing catalog {path}", file=sys.stderr)
    return {"version": CATALOG_VERSION, "runs": 0, "employers": {}}


def save_catalog(path: Path, catalog: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dice-cat-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(catalog, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _job_id(row: dict) -> str:
    return str(row.get("guid") or row.get("id") or row.get("detailsPageUrl") or "").strip()


def _location_name(row: dict) -> str:
    loc = row.get("jobLocation")
    if isinstance(loc, dict):
        return str(loc.get("displayName") or "").strip()
    return str(loc or "").strip()


def merge_posting(entry: dict, row: dict, keyword: str, run_ts: str) -> bool:
    """Merge one Dice posting into an employer entry. Returns True if new posting."""
    jid = _job_id(row)
    seen_ids = entry.setdefault("job_ids", [])
    seen_set = entry.setdefault("_job_id_set", set(seen_ids))
    new_posting = bool(jid) and jid not in seen_set
    if new_posting:
        seen_set.add(jid)
        seen_ids.append(jid)
        entry["postings"] = entry.get("postings", 0) + 1

    # Employer / Dice metadata.
    et = str(row.get("employerType") or "").strip()
    if et and et not in entry["employer_types"]:
        entry["employer_types"].append(et)
    cb = str(row.get("clientBrandId") or "").strip()
    if cb and cb not in entry["client_brand_ids"]:
        entry["client_brand_ids"].append(cb)
    cp = str(row.get("companyPageUrl") or "").strip()
    if cp and cp not in entry["company_page_urls"]:
        entry["company_page_urls"].append(cp)
    if keyword not in entry["keywords"]:
        entry["keywords"].append(keyword)

    # Job type (employmentType) + title.
    emp_type = str(row.get("employmentType") or "").strip()
    if emp_type and emp_type not in entry["job_types"]:
        entry["job_types"].append(emp_type)
    title = str(row.get("title") or "").strip()
    if title and title not in entry["titles"] and len(entry["titles"]) < MAX_TITLES:
        entry["titles"].append(title)

    # Location.
    loc = _location_name(row)
    if loc and loc not in entry["locations"] and len(entry["locations"]) < MAX_LOCATIONS:
        entry["locations"].append(loc)
    if row.get("isRemote"):
        entry["seen_remote"] = True

    # Salary.
    label = str(row.get("salary") or "").strip()
    if label:
        smin, smax, hourly = parse_salary(label)
        sal = entry["salary"]
        if label not in sal["labels"] and len(sal["labels"]) < MAX_SALARY_LABELS:
            sal["labels"].append(label)
        if hourly:
            sal["hourly_seen"] = True
        if smin is not None:
            sal["min"] = smin if sal["min"] is None else min(sal["min"], smin)
        if smax is not None:
            sal["max"] = smax if sal["max"] is None else max(sal["max"], smax)

    # Posting URL sample + recency bookkeeping.
    url = str(row.get("detailsPageUrl") or "").strip()
    if url and url not in entry["posting_urls_sample"] and len(entry["posting_urls_sample"]) < MAX_URL_SAMPLES:
        entry["posting_urls_sample"].append(url)
    posted = str(row.get("postedDate") or "").strip()
    if posted and posted > (entry.get("last_posted_date") or ""):
        entry["last_posted_date"] = posted

    entry["last_seen"] = run_ts
    return new_posting


def new_entry(name: str, run_ts: str) -> dict:
    return {
        "name": name,
        "cid": slugify(name),
        "is_agency": False,
        "agency_reason": "",
        "in_base_json": False,
        "base_id": None,
        "ats": None,
        "salary": {"min": None, "max": None, "labels": [], "hourly_seen": False},
        "job_types": [],
        "titles": [],
        "locations": [],
        "seen_remote": False,
        "employer_types": [],
        "client_brand_ids": [],
        "company_page_urls": [],
        "keywords": [],
        "postings": 0,
        "posting_urls_sample": [],
        "job_ids": [],
        "last_posted_date": "",
        "first_seen": run_ts,
        "last_seen": run_ts,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _fmt_salary(sal: dict) -> str:
    lo, hi = sal.get("min"), sal.get("max")
    if lo is None and hi is None:
        return "-"
    if lo == hi:
        return f"${lo:,}"
    lo_s = f"${lo:,}" if lo is not None else "?"
    hi_s = f"${hi:,}" if hi is not None else "?"
    tag = " (annualized)" if sal.get("hourly_seen") else ""
    return f"{lo_s}-{hi_s}{tag}"


def write_reports(
    report_md: Path,
    report_json: Path,
    catalog: dict,
    new_keys: list[str],
    fingerprinted_keys: list[str],
    run_ts: str,
    stats: dict,
) -> None:
    employers = catalog["employers"]

    def entry_view(key: str) -> dict:
        e = employers[key]
        ats = e.get("ats") or {}
        return {
            "name": e["name"],
            "postings": e["postings"],
            "is_agency": e["is_agency"],
            "in_base_json": e["in_base_json"],
            "base_id": e["base_id"],
            "ats_type": ats.get("type"),
            "ats_slug": ats.get("slug"),
            "ats_api_scrapable": ats.get("api_scrapable", False),
            "ats_confidence": ats.get("confidence"),
            "browse_url": ats.get("browse_url"),
            "salary_min": e["salary"]["min"],
            "salary_max": e["salary"]["max"],
            "job_types": e["job_types"],
            "sample_titles": e["titles"][:5],
            "locations": e["locations"][:5],
        }

    new_views = [entry_view(k) for k in new_keys]
    # New direct employers on an API-scrapable ATS not already in base.json.
    new_api_direct = [
        v for v in new_views
        if v["ats_api_scrapable"] and not v["is_agency"] and not v["in_base_json"]
    ]
    new_api_direct.sort(key=lambda v: (-int(v["postings"] or 0), v["name"].lower()))
    # Whole-catalog add-candidates (API-scrapable direct employers not in base),
    # independent of which run first surfaced them.
    all_api_direct = [
        entry_view(k) for k, e in employers.items()
        if (e.get("ats") or {}).get("api_scrapable") and not e["is_agency"] and not e["in_base_json"]
    ]
    all_api_direct.sort(key=lambda v: (-int(v["postings"] or 0), v["name"].lower()))
    fp_views = [entry_view(k) for k in fingerprinted_keys]
    fp_api_direct = [
        v for v in fp_views
        if v["ats_api_scrapable"] and not v["is_agency"] and not v["in_base_json"]
        and v["name"] not in {n["name"] for n in new_api_direct}
    ]
    fp_api_direct.sort(key=lambda v: (-int(v["postings"] or 0), v["name"].lower()))

    report_json.write_text(
        json.dumps(
            {
                "run_ts": run_ts,
                "stats": stats,
                "new_employers": new_views,
                "new_api_scrapable_direct": new_api_direct,
                "newly_fingerprinted_api_direct": fp_api_direct,
                "all_api_scrapable_direct_not_in_base": all_api_direct,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def table(views: list[dict]) -> str:
        if not views:
            return "_None._"
        lines = [
            "| Employer | Dice postings | ATS | Slug | Conf | Salary | Job types | Browse URL |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for v in views:
            sal = "-"
            if v["salary_min"] is not None or v["salary_max"] is not None:
                lo = f"${v['salary_min']:,}" if v["salary_min"] is not None else "?"
                hi = f"${v['salary_max']:,}" if v["salary_max"] is not None else "?"
                sal = lo if lo == hi else f"{lo}-{hi}"
            jt = ", ".join(v["job_types"][:3]) or "-"
            lines.append(
                f"| {v['name']} | {v['postings']} | `{v['ats_type'] or '-'}` | "
                f"`{v['ats_slug'] or '-'}` | {v['ats_confidence'] or '-'} | {sal} | {jt} | "
                f"{v['browse_url'] or '-'} |"
            )
        return "\n".join(lines)

    md: list[str] = []
    md.append(f"# Dice employer discovery - new candidates ({run_ts[:10]})")
    md.append("")
    md.append(
        "Read-only discovery for quickjobs. Source: Dice.com official MCP "
        "(`search_jobs`). base.json was NOT modified."
    )
    md.append("")
    md.append("## Run stats")
    md.append("")
    for k, v in stats.items():
        md.append(f"- {k.replace('_', ' ')}: {v}")
    md.append("")
    md.append("## Add-candidates: API-scrapable direct employers not in base.json (whole catalog)")
    md.append("")
    md.append(
        "Strongest add candidates accumulated across all runs: direct employers "
        "on a clean API-scrapable ATS that are not already in base.json. Verify "
        "any `review`-confidence slug before adding (possible slug collision)."
    )
    md.append("")
    md.append(table(all_api_direct))
    md.append("")
    md.append("## New API-scrapable direct employers first seen this run")
    md.append("")
    md.append(table(new_api_direct))
    md.append("")
    md.append("## Previously-known employers newly fingerprinted this run (API-scrapable, not in base.json)")
    md.append("")
    md.append(table(fp_api_direct))
    md.append("")
    md.append("## All employers first seen this run")
    md.append("")
    if new_views:
        for v in sorted(new_views, key=lambda x: (-int(x["postings"] or 0), x["name"].lower())):
            flags = []
            if v["is_agency"]:
                flags.append("agency")
            if v["in_base_json"]:
                flags.append(f"in base ({v['base_id']})")
            if v["ats_type"]:
                flags.append(f"{v['ats_type']}/{v['ats_slug'] or '?'}")
            flag_s = f" [{', '.join(flags)}]" if flags else ""
            md.append(f"- [{v['postings']}] {v['name']}{flag_s}")
    else:
        md.append("_None._")
    md.append("")
    report_md.write_text("\n".join(md) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

CRON_EXAMPLE = (
    "# Weekly Dice employer-catalog refresh (Mondays 07:15). Uses ~/.v python; "
    "no cd needed.\n"
    "15 7 * * 1 cron-exec /path/to/venv/bin/python "
    f"{SCRIPT_PATH} --max-fingerprint 40\n"
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--keywords", type=str, default="",
                   help="Comma-separated keyword override (default: built-in DevOps/Platform/SRE net)")
    p.add_argument("--keywords-file", type=Path, default=None,
                   help="File with one keyword per line (overrides --keywords)")
    p.add_argument("--workplace-types", type=str, default="",
                   help="Comma-separated: Remote,On-Site,Hybrid (default: all / broad net)")
    p.add_argument("--employment-types", type=str, default="",
                   help="Comma-separated: FULLTIME,CONTRACTS,PARTTIME,THIRD_PARTY (default: all)")
    p.add_argument("--posted-date", type=str, default="",
                   help="ONE|THREE|SEVEN, or blank for the WIDEST window (default: blank = all dates)")
    p.add_argument("--jobs-per-page", type=int, default=100, help="1-100 (default 100)")
    p.add_argument("--max-pages", type=int, default=0,
                   help="Max pages per keyword (0 = paginate to Dice's page ceiling)")
    p.add_argument("--timeout", type=int, default=45, help="Per-request timeout (s)")
    p.add_argument("--delay", type=float, default=0.4, help="Delay between page requests (s)")
    p.add_argument("--fingerprint", choices=("full", "api", "off"), default="full",
                   help="ATS fingerprint mode for NEW employers (default full)")
    p.add_argument("--fingerprint-url-cap", type=int, default=12,
                   help="Max careers URLs probed per employer in 'full' mode")
    p.add_argument("--fingerprint-workers", type=int, default=10,
                   help="Thread pool size for fingerprinting")
    p.add_argument("--max-fingerprint", type=int, default=0,
                   help="Cap NEW employers fingerprinted this run (0 = no cap). "
                        "Cached employers are never re-probed; remaining ones get "
                        "fingerprinted on later runs.")
    p.add_argument("--refingerprint", action="store_true",
                   help="Re-probe employers even if already fingerprinted")
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG,
                   help=f"Persistent catalog path (default {DEFAULT_CATALOG})")
    p.add_argument("--report-dir", type=Path, default=OUTPUT_DIR,
                   help=f"Dir for the dated candidates report (default {OUTPUT_DIR})")
    p.add_argument("--base", type=Path, default=DEFAULT_BASE,
                   help="quickjobs base.json to read for the in-base flag (READ ONLY)")
    p.add_argument("--print-cron", action="store_true",
                   help="Print an example cron line and exit (does NOT install it)")
    return p


def resolve_keywords(args: argparse.Namespace) -> list[str]:
    if args.keywords_file:
        lines = args.keywords_file.read_text(encoding="utf-8").splitlines()
        kws = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
        return kws or DEFAULT_KEYWORDS
    if args.keywords.strip():
        return [k.strip() for k in args.keywords.split(",") if k.strip()]
    return list(DEFAULT_KEYWORDS)


def main() -> int:
    args = build_parser().parse_args()
    if args.print_cron:
        print(CRON_EXAMPLE)
        return 0

    jpp = max(1, min(100, args.jobs_per_page))
    keywords = resolve_keywords(args)
    workplace_types = [w.strip() for w in args.workplace_types.split(",") if w.strip()] or None
    employment_types = [e.strip() for e in args.employment_types.split(",") if e.strip()] or None
    posted_date = args.posted_date.strip().upper() or None
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(
        f"Dice employer discovery @ {run_ts}\n"
        f"  keywords={len(keywords)} posted_date={posted_date or '(widest/all)'} "
        f"workplace={workplace_types or 'all'} employment={employment_types or 'all'} "
        f"jobs_per_page={jpp} max_pages={args.max_pages or 'ceiling'}",
        flush=True,
    )

    catalog = load_catalog(args.catalog)
    employers: dict[str, dict] = catalog["employers"]
    pre_existing_keys = set(employers)

    # --- 1. Gather + merge postings ---------------------------------------- #
    total_rows = 0
    for kw in keywords:
        rows = search_keyword(
            kw,
            workplace_types=workplace_types,
            employment_types=employment_types,
            posted_date=posted_date,
            jobs_per_page=jpp,
            max_pages=args.max_pages,
            timeout=args.timeout,
            delay=args.delay,
        )
        for row in rows:
            name = str(row.get("companyName") or "").strip()
            if not name:
                continue
            total_rows += 1
            key = catalog_key(name)
            entry = employers.get(key)
            if entry is None:
                entry = new_entry(name, run_ts)
                employers[key] = entry
            merge_posting(entry, row, kw, run_ts)

    new_keys = [k for k in employers if k not in pre_existing_keys]

    # --- 2. Agency flags (recompute for new; keep cached for known) -------- #
    for key in new_keys:
        e = employers[key]
        agency, reason = is_agency(e["name"], e["employer_types"])
        e["is_agency"], e["agency_reason"] = agency, reason
    # Refresh agency flag for pre-existing entries whose employer_types grew.
    for key in pre_existing_keys & set(employers):
        e = employers[key]
        if not e.get("is_agency"):
            agency, reason = is_agency(e["name"], e["employer_types"])
            if agency:
                e["is_agency"], e["agency_reason"] = agency, reason

    # --- 3. Fingerprint NEW, non-agency employers once (cached) ------------ #
    to_fp = [
        k for k in employers
        if not employers[k]["is_agency"]
        and (args.refingerprint or not (employers[k].get("ats") and employers[k]["ats"].get("fingerprinted_at")))
    ]
    to_fp.sort(key=lambda k: (-int(employers[k]["postings"] or 0), k))
    if args.max_fingerprint > 0:
        to_fp = to_fp[: args.max_fingerprint]
    fingerprinted_keys: list[str] = []
    if to_fp and args.fingerprint != "off":
        print(f"Fingerprinting {len(to_fp)} employer(s) (mode={args.fingerprint})…", flush=True)
        workers = max(1, args.fingerprint_workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(fingerprint_employer, employers[k]["name"], args.fingerprint, args.fingerprint_url_cap): k
                for k in to_fp
            }
            done = 0
            for fut in as_completed(futs):
                key = futs[fut]
                try:
                    ats = fut.result()
                except Exception as err:  # pragma: no cover
                    ats = {"type": None, "confidence": "error", "error": str(err)[:160],
                           "api_scrapable": False,
                           "fingerprinted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                employers[key]["ats"] = ats
                fingerprinted_keys.append(key)
                done += 1
                if ats.get("type"):
                    print(f"  [{done}/{len(to_fp)}] {employers[key]['name']}: "
                          f"{ats['type']} slug={ats.get('slug')} ({ats.get('confidence')})", flush=True)
    elif args.fingerprint == "off":
        print("Fingerprinting disabled (--fingerprint off).", flush=True)

    # --- 4. base.json presence flag (recompute every run) ------------------ #
    base_idx = load_base_index(args.base)
    for e in employers.values():
        match = base_match(e["name"], e.get("ats"), base_idx)
        e["in_base_json"] = match is not None
        e["base_id"] = match

    # --- 5. Persist catalog (strip transient helper keys) ------------------ #
    catalog["version"] = CATALOG_VERSION
    catalog["runs"] = int(catalog.get("runs", 0)) + 1
    catalog["last_run"] = run_ts
    catalog["last_config"] = {
        "keywords": keywords, "posted_date": posted_date,
        "workplace_types": workplace_types, "employment_types": employment_types,
        "jobs_per_page": jpp, "max_pages": args.max_pages,
        "fingerprint": args.fingerprint,
    }
    for e in employers.values():
        e.pop("_job_id_set", None)
    save_catalog(args.catalog, catalog)

    # --- 6. Reports --------------------------------------------------------- #
    agencies = sum(1 for e in employers.values() if e["is_agency"])
    api_direct = sum(
        1 for e in employers.values()
        if not e["is_agency"] and not e["in_base_json"]
        and (e.get("ats") or {}).get("api_scrapable")
    )
    new_api_direct_count = sum(
        1 for k in new_keys
        if not employers[k]["is_agency"] and not employers[k]["in_base_json"]
        and (employers[k].get("ats") or {}).get("api_scrapable")
    )
    stats = {
        "run": catalog["runs"],
        "postings_processed_this_run": total_rows,
        "employers_in_catalog": len(employers),
        "new_employers_this_run": len(new_keys),
        "agencies_flagged_total": agencies,
        "api_scrapable_direct_not_in_base_total": api_direct,
        "new_api_scrapable_direct_this_run": new_api_direct_count,
        "employers_fingerprinted_this_run": len(fingerprinted_keys),
    }

    report_md = args.report_dir / f"dice-new-candidates-{run_ts[:10]}.md"
    report_json = args.report_dir / f"dice-new-candidates-{run_ts[:10]}.json"
    args.report_dir.mkdir(parents=True, exist_ok=True)
    write_reports(report_md, report_json, catalog, new_keys, fingerprinted_keys, run_ts, stats)

    print(
        "SUMMARY: run={run} postings={postings_processed_this_run} "
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
