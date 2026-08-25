#!/usr/bin/env python3
"""Shared employer-discovery helpers for quickjobs board miners.

Reused by ``scripts/hn/`` and ``scripts/builtin/`` and mirrors the approach and
catalog schema of ``scripts/dice/discover_dice_employers.py``. The goal across
all miners is identical: build up a persistent EMPLOYER catalog over time
(companies, NOT live jobs), recording each employer's careers/ATS site + detected
ATS type, observed salary ranges, job types/titles, locations, and first/last
seen timestamps. Recency of a posting does not matter; scheduled reruns keep
widening coverage.

This module provides:
  * employer-name normalization + agency / body-shop heuristics
  * salary parsing (annualized, tolerant of ``200-298k`` shared-suffix ranges)
  * a read-only index of ``quickjobs.base.json`` + a membership test
  * a persistent employer catalog (load / save / new_entry / merge_common)
  * ATS fingerprinting that REUSES the ``scripts/hubs`` probe machinery
    (greenhouse / lever / ashby / workday_cxs / smartrecruiters / icims /
    phenom / oracle_hcm / successfactors / taleo_cws / json_feed), optionally
    seeded with an employer-provided careers URL for higher accuracy
  * a shared "new candidates" report writer + a finalize pipeline

No miner writes ``quickjobs.base.json``; it is only READ to flag employers
already tracked.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
import config_bundle  # noqa: E402

# --------------------------------------------------------------------------- #

SHARED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SHARED_DIR.parents[1]  # .../quickjobs
HUBS_DIR = REPO_ROOT / "scripts" / "hubs"
DEFAULT_BASE = REPO_ROOT / "quickjobs.base.json"
OUTPUT_DIR = Path.home() / "ws" / "scriptdir" / "output"

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

# Periodic -> annual multipliers for salary normalization.
PERIOD_MULT = {
    "hour": 2080, "hr": 2080, "week": 52, "wk": 52, "month": 12, "mo": 12,
    "day": 260, "annum": 1, "year": 1, "yr": 1,
}

# --------------------------------------------------------------------------- #
# Name normalization + agency heuristics (shared with the Dice miner)
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
    return re.sub(r"[^a-z0-9]", "", (name or "").lower()) or "unknown"


def slugify(name: str) -> str:
    s = re.sub(r"&\w+;", " ", name or "")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "unknown"


def is_agency(name: str, hints: list[str] | None = None) -> tuple[bool, str]:
    """Classify an employer name as a staffing agency / body shop.

    ``hints`` is an optional list of source-provided type strings (e.g. Dice's
    ``employerType``). The name-based heuristics are what carry HN / Built In.
    """
    norm = normalize(name)
    hints = hints or []
    if hints and set(hints) == {"Recruiter"}:
        return True, "source type=Recruiter"
    for known in KNOWN_AGENCIES:
        if known in norm or known.replace(" ", "") in norm.replace(" ", ""):
            return True, f"known agency/body-shop ({known})"
    m = AGENCY_RE.search(name or "")
    if m:
        return True, f"agency keyword ({m.group(0).strip()})"
    if "Recruiter" in hints and "Direct Hire" not in hints:
        return True, "source type=Recruiter (multi)"
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

    Handles ``$65,000 - $70,000``, ``USD 125,000.00 - 135,000.00 per year``,
    ``USD 60.00 - 70.00 per hour``, ``$150K``, ``62K-111K Annually``, and the
    common HN shared-suffix form ``$200-298k`` (only the last number carries the
    ``k``). Periodic rates are annualized so numeric min/max stay comparable.
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

    raw_nums: list[tuple[float, str]] = []
    for m in _NUM_RE.finditer(text):
        digits = m.group(1).replace(",", "")
        try:
            val = float(digits)
        except ValueError:
            continue
        raw_nums.append((val, (m.group(2) or "").lower()))

    if not raw_nums:
        return None, None, is_hourly

    # Shared-suffix ranges: "$200-298k" -> both are thousands. If any token has a
    # k/m suffix, bare small tokens (< 1000) in the same label inherit that scale.
    group_suffix = ""
    for _, suf in raw_nums:
        if suf in ("k", "m"):
            group_suffix = suf
            break

    nums: list[float] = []
    for val, suf in raw_nums:
        if suf == "k":
            val *= 1_000
        elif suf == "m":
            val *= 1_000_000
        elif group_suffix and val < 1_000:
            val *= 1_000 if group_suffix == "k" else 1_000_000
        nums.append(val)

    annual = sorted(int(round(n * mult)) for n in nums)
    lo, hi = annual[0], annual[-1]
    # Discard obvious noise (a lone requisition number, equity %, tiny value).
    if hi < 10_000 or lo > 2_000_000:
        return None, None, is_hourly
    if lo < 10_000:  # keep the max, drop an implausibly small min
        lo = hi
    return lo, hi, is_hourly


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
    except (RuntimeError, json.JSONDecodeError, OSError):
        return idx
    comps = cfg.get("companies")
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


def _org_confirms(company: str, org: str) -> bool:
    """Strict identity check between a company name and an ATS board's org name.

    Guards against slug collisions where a board is named after a single generic
    token. Requires an exact collapsed match, >=2 shared distinctive tokens, or a
    genuine single-token company whose sole token IS the board.
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
        words = [w for w in re.split(r"[^a-z0-9]+", re.sub(r"&\w+;", " ", name.lower())) if w]
        cfull = collapse(name)
        c2 = collapse(" ".join(words[:2])) if len(words) >= 2 else ""
        s = collapse(slug)
        if s and (s == cfull or (c2 and s == c2)):
            return "high"
        if len(words) == 1 and s == collapse(words[0]) and len(s) >= 6:
            return "high"
        return "review"
    if hit.get("type") in API_SCRAPABLE_TYPES:
        endpoint = str(hit.get("endpoint") or hit.get("browse_url") or "")
        host = re.sub(r"^https?://", "", endpoint).split("/")[0].lower()
        host_flat = host.replace("-", "")
        if any(tok in host_flat for tok in {collapse(w) for w in _name_tokens(name)} if tok):
            return "high"
        return "review"
    return "non_api"


def _careers_html_probe(
    mods: dict, cid: str, name: str, url_cap: int, careers_url: str = ""
) -> dict | None:
    dh, probe, hub_network = mods["dh"], mods["probe"], mods["hub_network"]
    co = {"id": cid, "name": name}
    if careers_url:
        co["hub_url"] = careers_url
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


def fingerprint_employer(
    name: str, mode: str = "api", url_cap: int = 12, careers_url: str = ""
) -> dict:
    """Detect ATS type for one employer. mode in {'full','api','off'}.

    When ``careers_url`` is supplied (e.g. a URL scraped from an HN posting) it is
    seeded into the careers-HTML probe candidate list for higher accuracy.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = {
        "type": None, "slug": "", "endpoint": "", "browse_url": "", "method": "",
        "confidence": "none", "api_scrapable": False, "fingerprinted_at": now,
        "careers_url_seed": careers_url or "",
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
            hit = _careers_html_probe(mods, cid, name, url_cap, careers_url)
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
MAX_SALARY_LABELS = 12
MAX_URL_SAMPLES = 8


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
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".qj-cat-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(catalog, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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
        "keywords": [],
        "postings": 0,
        "posting_urls_sample": [],
        "careers_urls": [],
        "source_ids": [],
        "first_seen": run_ts,
        "last_seen": run_ts,
    }


def merge_common(
    entry: dict,
    *,
    run_ts: str,
    source_id: str = "",
    title: str = "",
    location: str = "",
    remote: bool = False,
    salary_label: str = "",
    job_type: str = "",
    keyword: str = "",
    posting_url: str = "",
    careers_url: str = "",
) -> bool:
    """Merge one posting into an employer entry. Returns True if a NEW posting.

    Idempotent when ``source_id`` is a stable per-posting id (re-running never
    inflates counts).
    """
    new_posting = True
    if source_id:
        seen = entry.setdefault("_source_id_set", set(entry.get("source_ids", [])))
        new_posting = source_id not in seen
        if new_posting:
            seen.add(source_id)
            entry.setdefault("source_ids", []).append(source_id)
    if new_posting:
        entry["postings"] = entry.get("postings", 0) + 1

    if title and title not in entry["titles"] and len(entry["titles"]) < MAX_TITLES:
        entry["titles"].append(title)
    if job_type and job_type not in entry["job_types"]:
        entry["job_types"].append(job_type)
    if location and location not in entry["locations"] and len(entry["locations"]) < MAX_LOCATIONS:
        entry["locations"].append(location)
    if remote:
        entry["seen_remote"] = True
    if keyword and keyword not in entry["keywords"]:
        entry["keywords"].append(keyword)

    if salary_label:
        smin, smax, hourly = parse_salary(salary_label)
        sal = entry["salary"]
        if salary_label not in sal["labels"] and len(sal["labels"]) < MAX_SALARY_LABELS:
            sal["labels"].append(salary_label)
        if hourly:
            sal["hourly_seen"] = True
        if smin is not None:
            sal["min"] = smin if sal["min"] is None else min(sal["min"], smin)
        if smax is not None:
            sal["max"] = smax if sal["max"] is None else max(sal["max"], smax)

    if posting_url and posting_url not in entry["posting_urls_sample"] \
            and len(entry["posting_urls_sample"]) < MAX_URL_SAMPLES:
        entry["posting_urls_sample"].append(posting_url)
    if careers_url:
        cu = entry.setdefault("careers_urls", [])
        if careers_url not in cu and len(cu) < MAX_URL_SAMPLES:
            cu.append(careers_url)

    entry["last_seen"] = run_ts
    return new_posting


# --------------------------------------------------------------------------- #
# Finalize pipeline (agency flags -> fingerprint -> base flags -> persist)
# --------------------------------------------------------------------------- #

def finalize_catalog(
    *,
    catalog: dict,
    employers: dict,
    new_keys: list[str],
    pre_existing_keys: set,
    run_ts: str,
    base_path: Path,
    catalog_path: Path,
    fingerprint_mode: str,
    fingerprint_url_cap: int,
    fingerprint_workers: int,
    max_fingerprint: int,
    refingerprint: bool,
    last_config: dict,
    agency_hint_key: str = "",
) -> tuple[list[str], dict]:
    """Steps shared by every miner. Returns (fingerprinted_keys, base_index)."""
    # 1. Agency flags (new + refresh known that grew).
    for key in new_keys:
        e = employers[key]
        hints = e.get(agency_hint_key) if agency_hint_key else None
        e["is_agency"], e["agency_reason"] = is_agency(e["name"], hints)
    for key in pre_existing_keys & set(employers):
        e = employers[key]
        if not e.get("is_agency"):
            hints = e.get(agency_hint_key) if agency_hint_key else None
            agency, reason = is_agency(e["name"], hints)
            if agency:
                e["is_agency"], e["agency_reason"] = agency, reason

    # 2. Fingerprint NEW, non-agency employers once (cached across runs).
    to_fp = [
        k for k in employers
        if not employers[k]["is_agency"]
        and (refingerprint or not (employers[k].get("ats") and employers[k]["ats"].get("fingerprinted_at")))
    ]
    to_fp.sort(key=lambda k: (-int(employers[k]["postings"] or 0), k))
    if max_fingerprint > 0:
        to_fp = to_fp[:max_fingerprint]
    fingerprinted_keys: list[str] = []
    if to_fp and fingerprint_mode != "off":
        print(f"Fingerprinting {len(to_fp)} employer(s) (mode={fingerprint_mode})…", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, fingerprint_workers)) as pool:
            futs = {}
            for k in to_fp:
                seed = ""
                cu = employers[k].get("careers_urls") or []
                if cu:
                    seed = cu[0]
                futs[pool.submit(
                    fingerprint_employer, employers[k]["name"],
                    fingerprint_mode, fingerprint_url_cap, seed
                )] = k
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
    elif fingerprint_mode == "off":
        print("Fingerprinting disabled (--fingerprint off).", flush=True)

    # 3. base.json presence flag (recompute every run).
    base_idx = load_base_index(base_path)
    for e in employers.values():
        match = base_match(e["name"], e.get("ats"), base_idx)
        e["in_base_json"] = match is not None
        e["base_id"] = match

    # 4. Persist catalog (strip transient helper keys).
    catalog["version"] = CATALOG_VERSION
    catalog["runs"] = int(catalog.get("runs", 0)) + 1
    catalog["last_run"] = run_ts
    catalog["last_config"] = last_config
    for e in employers.values():
        e.pop("_source_id_set", None)
    save_catalog(catalog_path, catalog)
    return fingerprinted_keys, base_idx


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _entry_view(e: dict) -> dict:
    ats = e.get("ats") or {}
    return {
        "name": e["name"],
        "postings": e.get("postings", 0),
        "is_agency": e.get("is_agency", False),
        "in_base_json": e.get("in_base_json", False),
        "base_id": e.get("base_id"),
        "ats_type": ats.get("type"),
        "ats_slug": ats.get("slug"),
        "ats_api_scrapable": ats.get("api_scrapable", False),
        "ats_confidence": ats.get("confidence"),
        "browse_url": ats.get("browse_url"),
        "salary_min": e["salary"]["min"],
        "salary_max": e["salary"]["max"],
        "job_types": e.get("job_types", []),
        "sample_titles": e.get("titles", [])[:5],
        "locations": e.get("locations", [])[:5],
        "careers_urls": e.get("careers_urls", [])[:3],
    }


def _table(views: list[dict]) -> str:
    if not views:
        return "_None._"
    lines = [
        "| Employer | Postings | ATS | Slug | Conf | Salary | Job types | Browse URL |",
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


def write_reports(
    *,
    report_md: Path,
    report_json: Path,
    catalog: dict,
    new_keys: list[str],
    fingerprinted_keys: list[str],
    run_ts: str,
    stats: dict,
    source_label: str,
    source_note: str,
) -> None:
    employers = catalog["employers"]
    new_views = [_entry_view(employers[k]) for k in new_keys]
    new_api_direct = [
        v for v in new_views
        if v["ats_api_scrapable"] and not v["is_agency"] and not v["in_base_json"]
    ]
    new_api_direct.sort(key=lambda v: (-int(v["postings"] or 0), v["name"].lower()))
    all_api_direct = [
        _entry_view(e) for e in employers.values()
        if (e.get("ats") or {}).get("api_scrapable") and not e["is_agency"] and not e["in_base_json"]
    ]
    all_api_direct.sort(key=lambda v: (-int(v["postings"] or 0), v["name"].lower()))
    fp_views = [_entry_view(employers[k]) for k in fingerprinted_keys]
    new_api_names = {n["name"] for n in new_api_direct}
    fp_api_direct = [
        v for v in fp_views
        if v["ats_api_scrapable"] and not v["is_agency"] and not v["in_base_json"]
        and v["name"] not in new_api_names
    ]
    fp_api_direct.sort(key=lambda v: (-int(v["postings"] or 0), v["name"].lower()))

    report_json.write_text(
        json.dumps(
            {
                "source": source_label,
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

    md: list[str] = []
    md.append(f"# {source_label} employer discovery - new candidates ({run_ts[:10]})")
    md.append("")
    md.append(source_note)
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
    md.append(_table(all_api_direct))
    md.append("")
    md.append("## New API-scrapable direct employers first seen this run")
    md.append("")
    md.append(_table(new_api_direct))
    md.append("")
    md.append("## Previously-known employers newly fingerprinted this run (API-scrapable, not in base.json)")
    md.append("")
    md.append(_table(fp_api_direct))
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


def compute_stats(catalog: dict, new_keys: list[str], fingerprinted_keys: list[str],
                  extra: dict | None = None) -> dict:
    employers = catalog["employers"]
    agencies = sum(1 for e in employers.values() if e["is_agency"])
    api_direct = sum(
        1 for e in employers.values()
        if not e["is_agency"] and not e["in_base_json"]
        and (e.get("ats") or {}).get("api_scrapable")
    )
    new_api_direct = sum(
        1 for k in new_keys
        if not employers[k]["is_agency"] and not employers[k]["in_base_json"]
        and (employers[k].get("ats") or {}).get("api_scrapable")
    )
    stats = {
        "run": catalog["runs"],
        "employers_in_catalog": len(employers),
        "new_employers_this_run": len(new_keys),
        "agencies_flagged_total": agencies,
        "api_scrapable_direct_not_in_base_total": api_direct,
        "new_api_scrapable_direct_this_run": new_api_direct,
        "employers_fingerprinted_this_run": len(fingerprinted_keys),
    }
    if extra:
        stats.update(extra)
    return stats
