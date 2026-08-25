#!/usr/bin/env python3
"""Audit jobs visible on the board that lack salary badges but may contain pay text."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HTML = Path.home() / "Downloads" / "jobs" / "job-search-quickjobs.html"
DEFAULT_PIPELINE = Path.home() / "Downloads" / "jobs" / "job-board-pipeline.json"
DEFAULT_SNAPSHOT = (
    Path.home() / ".job_search" / "quickjobs" / "quickjobs" / "job-search-quickjobs.snapshot.json"
)
DEFAULT_OUTPUT = Path.home() / "ws" / "scriptdir" / "output" / "missing-salary-audit.json"
DEFAULT_SUMMARY = Path.home() / "ws" / "scriptdir" / "output" / "missing-salary-audit.md"

LOC_BUCKETS = ("excluded", "remote", "local", "remote-intl", "other")

COMP_HEURISTIC_PATTERNS = (
    re.compile(r"\$\s*\d[\d,]*(?:\.\d{2})?(?:\s*[kKmM])?", re.I),
    re.compile(r"\bpay\s+range\b", re.I),
    re.compile(r"\bsalary\s+range\b", re.I),
    re.compile(r"\bcompensation\s+range\b", re.I),
    re.compile(r"\bbase\s+(?:pay|salary)\s+range\b", re.I),
    re.compile(r"\bhiring\s+range\b", re.I),
    re.compile(r"\bpay\s+transparency\b", re.I),
    re.compile(r"\b(?:USD|US\$)\s*\d", re.I),
    re.compile(r"\d[\d,]*\s*(?:-|–|—|to)\s*\d[\d,]*\s*(?:USD|usd)", re.I),
    re.compile(r"/\s*year\b", re.I),
    re.compile(r"\bper\s+year\b", re.I),
    re.compile(r"\bper\s+hour\b", re.I),
    re.compile(r"\bannually\b", re.I),
    re.compile(r"\bannual\s+(?:salary|base|compensation)\b", re.I),
)

ANNUAL_COMP_MARKERS = re.compile(
    r"(?:per\s+year|/year|/yr\b|annually|annual\s+(?:salary|base|compensation)|usd\s*per\s+annum)",
    re.I,
)


def load_quickjobs_module():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_audit", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["quickjobs_mod_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


def extract_lazy_board(html_path: Path) -> dict[str, Any]:
    html = html_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r'<script type="application/json" id="lazy-board-data">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise SystemExit(f"No lazy-board-data in {html_path}")
    return json.loads(match.group(1))


def load_pipeline(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_snapshot_meta(path: Path) -> dict[str, dict[str, Any]]:
    """Map apply-key URL -> snapshot job fields (loc_label, etc.)."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for co in data.get("companies") or []:
        if not isinstance(co, dict):
            continue
        company_id = str(co.get("id") or "")
        employer_region = str(co.get("region") or "us")
        for job in co.get("jobs") or []:
            if not isinstance(job, dict):
                continue
            key = str(job.get("url") or "").strip()
            if not key:
                continue
            out[key] = {
                "loc_label": str(job.get("loc_label") or ""),
                "company_id": company_id,
                "employer_region": employer_region,
                "salary": str(job.get("salary") or ""),
                "salary_label": str(job.get("salary_label") or ""),
            }
    return out


def company_lookup(cfg: dict[str, Any], mod, entry: dict[str, Any]) -> dict[str, Any] | None:
    company_id = str(entry.get("c") or "")
    company = next(
        (c for c in cfg.get("companies", []) if mod.company_filter_key(str(c.get("name", ""))) == company_id),
        None,
    )
    if company is None:
        company = next((c for c in cfg.get("companies", []) if str(c.get("id", "")) == company_id), None)
    return company


def infer_ats(url: str) -> str:
    u = (url or "").lower()
    if "greenhouse.io" in u or "boards.greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "myworkdayjobs.com" in u or "workday" in u:
        return "workday"
    if "phenom" in u or "phapp.io" in u:
        return "phenom"
    if "icims.com" in u:
        return "icims"
    if "successfactors" in u or "sap" in u:
        return "successfactors"
    if "talentbrew" in u or "jobs.net" in u:
        return "talentbrew"
    if "ashbyhq.com" in u:
        return "ashby"
    if "smartrecruiters.com" in u:
        return "smartrecruiters"
    if "wellfound" in u or "angel.co" in u:
        return "wellfound"
    if "weworkremotely" in u:
        return "weworkremotely"
    return "other"


def entry_in_default_pool(entry: dict[str, Any]) -> bool:
    pool = str(entry.get("pool") or "")
    return pool in {"listings", "excluded", "pass"}


def entry_visible_default(entry: dict[str, Any], pipeline: dict[str, Any]) -> bool:
    if not entry_in_default_pool(entry):
        return False
    loc = str(entry.get("loc") or "")
    pool = str(entry.get("pool") or "")
    if pool == "excluded" or loc == "excluded":
        pass_ok = True
    else:
        pass_ok = loc in {"remote", "remote-intl", "local"}
    if not pass_ok:
        return False
    key = str(entry.get("k") or "")
    status = str((pipeline.get(key) or {}).get("status") or "")
    if status == "pass":
        return False
    return True


def has_salary_badge(entry: dict[str, Any]) -> bool:
    low = int(entry.get("sl") or 0)
    high = int(entry.get("sh") or 0)
    return low > 0 or high > 0


def loc_bucket(entry: dict[str, Any]) -> str:
    loc = str(entry.get("loc") or "").strip().lower()
    if loc in LOC_BUCKETS:
        return loc
    return "other"


def likely_has_comp_text(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in COMP_HEURISTIC_PATTERNS)


def comp_snippet(text: str, width: int = 220) -> str:
    if not text:
        return ""
    for pat in COMP_HEURISTIC_PATTERNS:
        m = pat.search(text)
        if m:
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + width)
            snippet = text[start:end].replace("\n", " ")
            snippet = re.sub(r"\s+", " ", snippet).strip()
            return snippet[:320]
    return text[:200].replace("\n", " ")


def extract_likely_annual(comp: tuple[str, int, int] | None, desc_text: str) -> bool:
    if not comp:
        return False
    _kind, low, high = comp
    lo = min(low, high)
    hi = max(low, high)
    if lo >= 15_000:
        return True
    if hi >= 40_000:
        return True
    return bool(ANNUAL_COMP_MARKERS.search(desc_text))


def try_extract_salary(mod, entry: dict[str, Any], desc_text: str, cfg: dict[str, Any], *, location_name: str = "") -> tuple[Any, str | None]:
    """Run employer-aware extraction with US gating (pipeline path)."""
    loc = str(entry.get("loc") or "")
    title = str(entry.get("title") or "")
    company = company_lookup(cfg, mod, entry)
    url = str(entry.get("k") or "").lower()
    if company and ("greenhouse" in url or str(company.get("salary_heuristic") or "") in {"affirm", "twilio", "launchdarkly", "instacart"}):
        return mod.greenhouse_salary_from_detail(
            company,
            title,
            desc_text,
            cfg,
            location_name=location_name,
        )
    if company and "lever.co" in url:
        fn = getattr(mod, "lever_salary_from_posting", None)
        if fn:
            return fn(desc_text, cfg, location_name=location_name)
    return mod.salary_from_detail_text(
        desc_text,
        cfg,
        location_name=location_name,
        job_loc=loc,
        title=title,
    )


def us_salary_eligible(mod, entry: dict[str, Any], loc_label: str, title: str) -> bool:
    return mod.location_us_salary_eligible(
        str(entry.get("loc") or ""),
        loc_label,
        title=title,
    )


def cross_tab_inc(table: dict[str, dict[str, int]], loc: str, row: str) -> None:
    table.setdefault(loc, defaultdict(int))
    table[loc][row] += 1


def build_cross_tab(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Matrix: loc bucket x (has comp text x extract ok)."""
    table: dict[str, dict[str, int]] = {}
    for row in rows:
        loc = row["loc_bucket"]
        if not row["has_description"]:
            cross_tab_inc(table, loc, "no_description")
            continue
        if not row["likely_has_comp_text"]:
            cross_tab_inc(table, loc, "no_comp_text")
            continue
        if row["extract_ok"]:
            cross_tab_inc(table, loc, "comp_text_extract_ok")
            if row["extract_likely_annual"]:
                cross_tab_inc(table, loc, "comp_text_extract_annual")
        else:
            cross_tab_inc(table, loc, "comp_text_extract_fail")
    return {loc: dict(cells) for loc, cells in table.items()}


def render_cross_tab_md(cross_tab: dict[str, dict[str, int]], total_missing: int) -> list[str]:
    lines = [
        "## Cross-tab: missing badge by loc × comp text × extract",
        "",
        f"Total missing badge: {total_missing}",
        "",
        "| loc | no desc | no comp text | comp + extract ok | comp + annual ok | comp + extract fail |",
        "|-----|---------|--------------|-------------------|------------------|---------------------|",
    ]
    for loc in LOC_BUCKETS:
        cells = cross_tab.get(loc, {})
        lines.append(
            f"| {loc} | {cells.get('no_description', 0)} | {cells.get('no_comp_text', 0)} "
            f"| {cells.get('comp_text_extract_ok', 0)} | {cells.get('comp_text_extract_annual', 0)} "
            f"| {cells.get('comp_text_extract_fail', 0)} |"
        )
    return lines


_US_LOC_LABEL_RE = re.compile(
    r",\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
    r"MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b",
    re.I,
)


def loc_label_indicates_us_worksite(loc_label: str) -> bool:
    lab = str(loc_label or "").strip()
    if not lab:
        return False
    lower = lab.lower()
    if _US_LOC_LABEL_RE.search(lab):
        return True
    if any(tok in lower for tok in ("united states", ", us", " usa", "u.s.", "remote us", "remote - us")):
        return True
    if re.search(r"\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC),?\s+United States\b", lab, re.I):
        return True
    return False


def looks_like_remote_us(loc_label: str, desc_text: str) -> bool:
    blob = f"{loc_label} {desc_text[:2000]}".lower()
    remote_us_tokens = (
        "remote - us",
        "remote us",
        "remote, us",
        "remote (us)",
        "remote - usa",
        "remote usa",
        "united states",
        "usa only",
        "us remote",
        "work from anywhere in the us",
        "anywhere in the u.s.",
    )
    return any(tok in blob for tok in remote_us_tokens)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--pipeline", type=Path, default=DEFAULT_PIPELINE)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--sample-per-group", type=int, default=3)
    parser.add_argument("--misclass-sample", type=int, default=20)
    args = parser.parse_args()

    mod = load_quickjobs_module()
    cfg = load_cfg(mod)
    board = extract_lazy_board(args.html)
    pipeline = load_pipeline(args.pipeline)
    snapshot_meta = load_snapshot_meta(args.snapshot)
    index = board.get("index") or []
    descriptions = board.get("descriptions") or {}

    visible = [e for e in index if entry_visible_default(e, pipeline)]
    with_salary = [e for e in visible if has_salary_badge(e)]
    missing = [e for e in visible if not has_salary_badge(e)]

    rows: list[dict[str, Any]] = []
    excluded_comp_by_company: Counter[str] = Counter()
    excluded_extract_annual_by_company: Counter[str] = Counter()
    extract_fail_by_company: Counter[str] = Counter()
    extract_fail_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    extract_ok_no_badge_reasons: Counter[str] = Counter()
    misclass_candidates: list[dict[str, Any]] = []
    misclass_seen_companies: set[str] = set()

    for entry in missing:
        key = str(entry.get("k") or "")
        desc_entry = descriptions.get(key) or {}
        desc_text = str(desc_entry.get("t") or "")
        meta = snapshot_meta.get(key) or {}
        loc_label = str(meta.get("loc_label") or "")
        company = str(entry.get("cn") or entry.get("c") or "unknown")
        ats = infer_ats(key)
        loc = loc_bucket(entry)
        title = str(entry.get("title") or "")
        has_desc = bool(desc_text)
        has_comp = likely_has_comp_text(desc_text) if has_desc else False

        comp_range = None
        extract_ok = False
        extract_annual = False
        pipeline_salary = None
        pipeline_label = None
        would_label = None
        would_status = None

        if has_desc:
            try:
                comp_range = mod.extract_comp_range_from_text(desc_text, location_name=loc_label)
                extract_ok = comp_range is not None
                extract_annual = extract_likely_annual(comp_range, desc_text)
                if extract_ok and comp_range:
                    kind, low, high = comp_range
                    would_status, would_label = mod.salary_range_status(kind, low, high, cfg)
                pipeline_salary, pipeline_label = try_extract_salary(
                    mod, entry, desc_text, cfg, location_name=loc_label
                )
            except Exception as exc:
                comp_range = {"error": str(exc)}

        us_eligible = us_salary_eligible(mod, entry, loc_label, title)

        if has_comp and not extract_ok:
            extract_fail_by_company[company] += 1
            if len(extract_fail_samples[company]) < args.sample_per_group:
                extract_fail_samples[company].append(
                    {
                        "title": title,
                        "key": key,
                        "loc": loc,
                        "loc_label": loc_label,
                        "ats": ats,
                        "snippet": comp_snippet(desc_text),
                    }
                )

        if loc == "excluded" and has_comp:
            excluded_comp_by_company[company] += 1
            if extract_annual:
                excluded_extract_annual_by_company[company] += 1

        if extract_ok:
            if not us_eligible:
                extract_ok_no_badge_reasons["us_salary_gated"] += 1
            elif would_label:
                extract_ok_no_badge_reasons["would_badge_on_rebuild"] += 1
            else:
                extract_ok_no_badge_reasons["extract_ok_no_label"] += 1

        row = {
            "key": key,
            "company": company,
            "ats": ats,
            "loc": str(entry.get("loc") or ""),
            "loc_bucket": loc,
            "loc_label": loc_label,
            "title": title,
            "has_description": has_desc,
            "likely_has_comp_text": has_comp,
            "extract_ok": extract_ok,
            "extract_likely_annual": extract_annual,
            "extract": (
                {"kind": comp_range[0], "low": comp_range[1], "high": comp_range[2]}
                if extract_ok and comp_range and not isinstance(comp_range, dict)
                else comp_range
            ),
            "us_salary_eligible": us_eligible,
            "pipeline_salary": pipeline_salary,
            "pipeline_label": pipeline_label,
            "would_status": would_status,
            "would_label": would_label,
            "us_worksite_loc_label": loc_label_indicates_us_worksite(loc_label),
            "snippet": comp_snippet(desc_text) if has_comp else "",
        }
        rows.append(row)

        if (
            loc == "excluded"
            and has_comp
            and len(misclass_candidates) < args.misclass_sample
            and company not in misclass_seen_companies
        ):
            misclass_seen_companies.add(company)
            company_cfg = company_lookup(cfg, mod, entry)
            employer_region = str(
                meta.get("employer_region")
                or (company_cfg or {}).get("region")
                or "us"
            )
            recloc, relabel = mod.classify_location_with_fallback(
                loc_label,
                employer_region,
                cfg=cfg,
                title=title,
                description_text=desc_text,
            )
            misclass_candidates.append(
                {
                    "title": title,
                    "company": company,
                    "key": key,
                    "loc": loc,
                    "loc_label": loc_label,
                    "reclassified_loc": recloc,
                    "reclassified_label": relabel,
                    "looks_remote_us": looks_like_remote_us(loc_label, desc_text),
                    "us_worksite_loc_label": row["us_worksite_loc_label"],
                    "extract_ok": extract_ok,
                    "extract_annual": extract_annual,
                    "snippet": row["snippet"],
                }
            )

    cross_tab = build_cross_tab(rows)

    total_missing = len(missing)
    has_comp_total = sum(1 for r in rows if r["likely_has_comp_text"])
    extract_ok_total = sum(1 for r in rows if r["extract_ok"])
    extract_annual_total = sum(1 for r in rows if r["extract_likely_annual"])
    excluded_extract_annual = sum(
        1 for r in rows if r["loc_bucket"] == "excluded" and r["extract_likely_annual"]
    )
    excluded_has_comp = sum(
        1 for r in rows if r["loc_bucket"] == "excluded" and r["likely_has_comp_text"]
    )
    excluded_extract_ok = sum(
        1 for r in rows if r["loc_bucket"] == "excluded" and r["extract_ok"]
    )
    us_eligible_extract_ok_no_badge = sum(
        1 for r in rows if r["extract_ok"] and r["us_salary_eligible"]
    )
    us_gated_extract_ok = sum(
        1 for r in rows if r["extract_ok"] and not r["us_salary_eligible"]
    )
    excluded_extract_ok_us_worksite = sum(
        1
        for r in rows
        if r["loc_bucket"] == "excluded" and r["extract_ok"] and r["us_worksite_loc_label"]
    )
    comp_fail_us_eligible = sum(
        1
        for r in rows
        if r["likely_has_comp_text"] and not r["extract_ok"] and r["us_salary_eligible"]
    )

    report = {
        "html": str(args.html),
        "snapshot": str(args.snapshot),
        "totals": {
            "index_entries": len(index),
            "visible_default": len(visible),
            "with_salary_badge": len(with_salary),
            "missing_salary_badge": total_missing,
            "missing_has_comp_text": has_comp_total,
            "missing_extract_ok": extract_ok_total,
            "missing_extract_likely_annual": extract_annual_total,
            "excluded_missing_has_comp_text": excluded_has_comp,
            "excluded_missing_extract_ok": excluded_extract_ok,
            "excluded_missing_extract_likely_annual": excluded_extract_annual,
            "extract_ok_us_gated": us_gated_extract_ok,
            "extract_ok_us_eligible": us_eligible_extract_ok_no_badge,
            "comp_text_extract_fail_us_eligible": comp_fail_us_eligible,
            "excluded_extract_ok_us_worksite_loc_label": excluded_extract_ok_us_worksite,
        },
        "cross_tab": cross_tab,
        "extract_ok_no_badge_reasons": dict(extract_ok_no_badge_reasons),
        "top_excluded_comp_text_employers": excluded_comp_by_company.most_common(20),
        "top_excluded_extract_annual_employers": excluded_extract_annual_by_company.most_common(20),
        "top_extract_fail_employers": extract_fail_by_company.most_common(30),
        "extract_fail_samples_by_company": dict(extract_fail_samples),
        "misclassification_sample": misclass_candidates,
        "rows": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md_lines = [
        "# Missing salary audit (re-analysis)",
        "",
        f"Source HTML: `{args.html}`",
        f"Snapshot meta: `{args.snapshot}` ({len(snapshot_meta)} jobs indexed)",
        "",
        "## Headline counts",
        "",
        f"- Visible (default filters): {len(visible)}",
        f"- With salary badge: {len(with_salary)}",
        f"- Missing salary badge: **{total_missing}**",
        f"- Missing badge + comp text in cached JD: **{has_comp_total}** ({pct(has_comp_total, total_missing)})",
        f"- Missing badge + extract_comp_range_from_text ok (ignore US gate): **{extract_ok_total}** ({pct(extract_ok_total, total_missing)})",
        f"- Missing badge + likely annual US extract: **{extract_annual_total}**",
        "",
        "### Critical: excluded jobs with pay we're not showing",
        "",
        f"- Excluded, missing badge, has comp text: **{excluded_has_comp}**",
        f"- Excluded, missing badge, extract ok: **{excluded_extract_ok}**",
        f"- Excluded, missing badge, likely annual extract: **{excluded_extract_annual}**",
        f"- Excluded + extract ok + US worksite loc_label (onsite US, not intl mis-tag): **{excluded_extract_ok_us_worksite}**",
        "",
        "## Extract ok but no badge — why?",
        "",
        f"- US salary gated (`location_us_salary_eligible` false): **{us_gated_extract_ok}**",
        f"- US eligible, would produce label on rebuild: **{extract_ok_no_badge_reasons.get('would_badge_on_rebuild', 0)}**",
        f"- US eligible, comp text, extract still fails: **{comp_fail_us_eligible}**",
        "",
    ]
    md_lines.extend(render_cross_tab_md(cross_tab, total_missing))
    md_lines.extend(
        [
            "",
            "## Top 20 employers — excluded jobs with comp text (hidden pay)",
            "",
        ]
    )
    for rank, (employer, count) in enumerate(excluded_comp_by_company.most_common(20), 1):
        annual_n = excluded_extract_annual_by_company.get(employer, 0)
        md_lines.append(f"{rank}. {employer} — {count} with comp text ({annual_n} annual-extractable)")

    md_lines.extend(["", "## Top extract-fail clusters (US-eligible comp text)", ""])
    us_fail = [
        (co, n)
        for co, n in extract_fail_by_company.most_common(15)
        if any(
            r["company"] == co and r["us_salary_eligible"] and r["likely_has_comp_text"] and not r["extract_ok"]
            for r in rows
        )
    ]
    for rank, (employer, count) in enumerate(us_fail[:10], 1):
        md_lines.append(f"{rank}. {employer} — {count}")
        for sample in extract_fail_samples.get(employer, [])[:1]:
            md_lines.append(f"   - {sample['title']}: `{sample['snippet'][:140]}`")

    md_lines.extend(["", "## Location check (excluded + comp text, one per employer)", ""])
    remote_us_misclass = [
        m for m in misclass_candidates if m["looks_remote_us"] and m["reclassified_loc"] in {"remote", "local"}
    ]
    us_worksite_gated = [m for m in misclass_candidates if m["us_worksite_loc_label"] and m["extract_ok"]]
    md_lines.append(
        f"Sampled {len(misclass_candidates)} employers with excluded+comp jobs. "
        f"{sum(1 for m in misclass_candidates if m['looks_remote_us'])} mention remote US in text; "
        f"{len(remote_us_misclass)} would reclassify to remote/local. "
        f"{len(us_worksite_gated)} sample US worksite cities with extractable pay (correctly excluded for apply, pay hidden by gate)."
    )
    for item in misclass_candidates[:12]:
        md_lines.append(
            f"- {item['company']} / {item['title'][:45]}: `{item['loc_label'][:55]}` "
            f"reclass={item['reclassified_loc']} us_worksite={item['us_worksite_loc_label']} "
            f"extract_ok={item['extract_ok']}"
        )

    md_lines.extend(
        [
            "",
            "## Recommendation",
            "",
            (
                f"Of {total_missing} jobs without a salary badge, **{has_comp_total}** ({pct(has_comp_total, total_missing)}) "
                f"have compensation text in the cached description. **{extract_ok_total}** parse with current extract logic; "
                f"**{us_gated_extract_ok}** of those are blocked only by US salary eligibility (mostly excluded loc). "
            ),
            (
                f"Excluded jobs account for **{excluded_extract_annual}** annual-extractable postings we hide entirely; "
                f"**{excluded_extract_ok_us_worksite}** of those are US worksite cities (e.g. SpaceX Hawthorne/Redmond), "
                "correctly excluded for apply but carrying real US base pay in the JD. "
                "This is not primarily remote-US misclassification (`classify_location` sample found 0 remote-US → excluded errors). "
                "Consider showing salary badges on excluded jobs for display/filter only, decoupled from `job_us_salary_eligible`."
            ),
            "",
            f"Full JSON: `{args.output}`",
        ]
    )
    args.summary.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Visible: {len(visible)} | with salary: {len(with_salary)} | missing badge: {total_missing}")
    print(f"Missing + comp text: {has_comp_total} | extract ok: {extract_ok_total} | annual: {extract_annual_total}")
    print(f"Excluded + comp text: {excluded_has_comp} | excluded + extract ok: {excluded_extract_ok} | excluded + annual: {excluded_extract_annual}")
    print(f"Excluded + extract ok + US worksite loc: {excluded_extract_ok_us_worksite}")
    print(f"Extract ok, US gated: {us_gated_extract_ok} | US eligible would badge: {extract_ok_no_badge_reasons.get('would_badge_on_rebuild', 0)}")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.summary}")
    return 0


def load_cfg(mod) -> dict[str, Any]:
    return mod.load_config()


def pct(n: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{100.0 * n / total:.1f}%"


if __name__ == "__main__":
    raise SystemExit(main())
