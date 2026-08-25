#!/usr/bin/env python3
"""Diff expected job-board HTML placement vs actual rendered HTML.

Uses the run snapshot (all ingested jobs) and the same primary/excluded rules as
build_html(). Reports jobs missing from primary, excluded (filtered/hidden panel),
or only present as empty company stubs.
"""
from __future__ import annotations

import argparse
import json
import re
import runpy
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_HTML = Path.home() / "Downloads/jobs/job-search-quickjobs.html"
DEFAULT_SNAPSHOT = Path.home() / ".job_search/quickjobs/quickjobs/job-search-quickjobs.snapshot.json"
SCRIPT = Path(__file__).resolve().parents[2] / "quickjobs.py"


def _html_section_kind(section_id: str) -> str:
    sid = section_id.lower()
    if "excluded" in sid:
        return "excluded"
    if "applied" in sid:
        return "applied"
    return "primary"


def parse_html_jobs(html: str) -> dict[str, dict[str, Any]]:
    """Map apply-key -> placement info parsed from rendered HTML."""
    jobs: dict[str, dict[str, Any]] = {}
    company_empty: set[str] = set()
    article_open_re = re.compile(r'<article class="job"[^>]*>', re.I)
    title_re = re.compile(
        r'<div class="job-title"><a href="([^"]+)"[^>]*>([^<]+)</a>',
        re.I,
    )

    def _article_attrs(open_tag: str) -> dict[str, str]:
        def attr(name: str) -> str:
            match = re.search(rf'data-{re.escape(name)}="([^"]*)"', open_tag, re.I)
            return match.group(1) if match else ""

        return {
            "company_id": attr("company"),
            "apply_key": attr("apply-key"),
            "salary": attr("salary"),
            "loc": attr("loc"),
        }

    parts = re.split(r'<section id="([^"]+)"', html)
    for index in range(1, len(parts), 2):
        section_id = parts[index]
        chunk = parts[index + 1] if index + 1 < len(parts) else ""
        section = _html_section_kind(section_id)
        for match in article_open_re.finditer(chunk):
            attrs = _article_attrs(match.group(0))
            apply_key = attrs["apply_key"]
            if not apply_key:
                continue
            title = ""
            url = ""
            tail = chunk[match.start() : match.start() + 1200]
            tm = title_re.search(tail)
            if tm:
                url, title = tm.group(1), tm.group(2)
            jobs[apply_key] = {
                "company_id": attrs["company_id"],
                "apply_key": apply_key,
                "title": title,
                "url": url,
                "salary": attrs["salary"],
                "loc": attrs["loc"],
                "html_section": section,
            }
        for match in re.finditer(
            r'<div class="company-group"[^>]*data-company="([^"]+)"[^>]*>',
            chunk,
        ):
            cid = match.group(1)
            start = match.start()
            block = chunk[start : start + 4000]
            if "company-empty" in block:
                company_empty.add(cid)

    return {"jobs": jobs, "empty_company_stubs": company_empty}


def expected_placement(
    qj: dict[str, Any],
    snapshot: dict[str, Any],
    pipeline: dict[str, dict[str, str]],
) -> dict[str, Any]:
    cfg = qj["load_config"]()
    results = [
        qj["company_result_from_dict"](row)
        for row in snapshot.get("companies") or []
        if isinstance(row, dict) and row.get("id")
    ]
    qj["mark_jobs_pipeline"](results, pipeline)
    excluded_cos = qj["collect_excluded_company_results"](results, cfg)
    excluded_cos.extend(qj["collect_pass_company_results"](results, pipeline, cfg))

    primary_keys: set[str] = set()
    excluded_keys: set[str] = set()
    applied_keys: set[str] = set()
    by_company_primary: dict[str, int] = defaultdict(int)
    by_company_excluded: dict[str, int] = defaultdict(int)
    ingested_by_company: dict[str, int] = defaultdict(int)

    for co in results:
        ingested_by_company[co.id] = len(co.jobs)
        for job in qj["active_jobs_for_primary_sections"](co):
            key = qj["job_apply_key"](job)
            primary_keys.add(key)
            by_company_primary[co.id] += 1
        for job in qj["collect_applied_history_jobs"]([co], pipeline, cfg):
            applied_keys.add(qj["job_apply_key"](job))

    for co in excluded_cos:
        for job in co.jobs:
            if job.pipeline_applied_at:
                continue
            key = qj["job_apply_key"](job)
            excluded_keys.add(key)
            by_company_excluded[co.id] += 1

    return {
        "primary": primary_keys,
        "excluded": excluded_keys,
        "applied": applied_keys,
        "by_company_primary": dict(by_company_primary),
        "by_company_excluded": dict(by_company_excluded),
        "ingested_by_company": dict(ingested_by_company),
        "cfg": cfg,
        "results": results,
    }


def load_pipeline(html_path: Path, qj: dict[str, Any]) -> dict[str, dict[str, str]]:
    return qj["load_pipeline_store"](html_path)


def job_meta_from_snapshot(
    snapshot: dict[str, Any], apply_key: str, qj: dict[str, Any]
) -> dict[str, Any] | None:
    for row in snapshot.get("companies") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "")
        for job in row.get("jobs") or []:
            if not isinstance(job, dict):
                continue
            url = str(job.get("url") or "")
            job_obj = qj["job_from_dict"](job)
            job_obj.company_id = cid
            key = qj["job_apply_key"](job_obj)
            if key == apply_key or apply_key in url:
                return {
                    "company_id": cid,
                    "title": job.get("title"),
                    "salary": job.get("salary"),
                    "loc": job.get("loc"),
                    "url": url,
                }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--company", action="append", help="Limit report to company id(s)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "ws/scriptdir/output/job-board-html-diff.txt",
    )
    args = parser.parse_args()

    if not args.html.is_file():
        print(f"HTML not found: {args.html}", file=sys.stderr)
        return 1
    if not args.snapshot.is_file():
        print(f"Snapshot not found: {args.snapshot}", file=sys.stderr)
        return 1

    qj = runpy.run_path(str(SCRIPT), run_name="qj_diff")
    html = args.html.read_text(encoding="utf-8", errors="replace")
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    pipeline = load_pipeline(args.html, qj)
    parsed = parse_html_jobs(html)
    html_jobs = parsed["jobs"]
    empty_stubs = parsed["empty_company_stubs"]
    exp = expected_placement(qj, snapshot, pipeline)

    only = {c.strip() for c in (args.company or []) if c.strip()}
    lines: list[str] = []
    lines.append(f"HTML: {args.html}")
    lines.append(f"Snapshot: {args.snapshot} (run_at {snapshot.get('run_at', '?')})")
    lines.append(f"HTML job cards: {len(html_jobs)}")
    lines.append(
        f"Expected primary: {len(exp['primary'])} | excluded panel: {len(exp['excluded'])} | applied: {len(exp['applied'])}"
    )
    lines.append("")

    missing_primary = sorted(exp["primary"] - set(html_jobs.keys()))
    missing_excluded = sorted(exp["excluded"] - set(html_jobs.keys()))
    extra_html = sorted(set(html_jobs.keys()) - exp["primary"] - exp["excluded"] - exp["applied"])

    wrong_section: list[str] = []
    for key, row in html_jobs.items():
        if key in exp["primary"] and row["html_section"] != "primary":
            wrong_section.append(f"  {key} expected primary, html={row['html_section']}")
        if key in exp["excluded"] and row["html_section"] != "excluded":
            wrong_section.append(f"  {key} expected excluded, html={row['html_section']}")

    lines.append(f"=== In snapshot/expected PRIMARY but not in HTML ({len(missing_primary)}) ===")
    for key in missing_primary[:200]:
        meta = job_meta_from_snapshot(snapshot, key, qj) or {}
        cid = meta.get("company_id", "?")
        if only and cid not in only:
            continue
        lines.append(
            f"  [{cid}] {meta.get('title', key)} salary={meta.get('salary')} loc={meta.get('loc')}"
        )
    if len(missing_primary) > 200:
        lines.append(f"  ... and {len(missing_primary) - 200} more")

    lines.append(f"\n=== In snapshot/expected EXCLUDED panel but not in HTML ({len(missing_excluded)}) ===")
    for key in missing_excluded[:200]:
        meta = job_meta_from_snapshot(snapshot, key, qj) or {}
        cid = meta.get("company_id", "?")
        if only and cid not in only:
            continue
        lines.append(
            f"  [{cid}] {meta.get('title', key)} salary={meta.get('salary')} loc={meta.get('loc')}"
        )
    if len(missing_excluded) > 200:
        lines.append(f"  ... and {len(missing_excluded) - 200} more")

    lines.append(f"\n=== In HTML but not in expected primary/excluded/applied ({len(extra_html)}) ===")
    for key in extra_html[:80]:
        row = html_jobs[key]
        lines.append(f"  [{row['company_id']}] {row['title']} html_section={row['html_section']}")

    if wrong_section:
        lines.append(f"\n=== Wrong HTML section ({len(wrong_section)}) ===")
        lines.extend(wrong_section[:80])

    lines.append("\n=== Companies: ingested vs HTML primary vs HTML excluded (snapshot) ===")
    company_names = {str(c["id"]): c.get("name", c["id"]) for c in snapshot.get("companies") or []}
    all_cids = sorted(
        set(exp["ingested_by_company"])
        | set(exp["by_company_primary"])
        | set(exp["by_company_excluded"])
        | empty_stubs,
        key=lambda x: (company_names.get(x, x).lower(), x),
    )
    problem_companies: list[str] = []
    for cid in all_cids:
        if only and cid not in only:
            continue
        ing = exp["ingested_by_company"].get(cid, 0)
        prim = exp["by_company_primary"].get(cid, 0)
        excl = exp["by_company_excluded"].get(cid, 0)
        html_prim = sum(1 for j in html_jobs.values() if j["company_id"] == cid and j["html_section"] == "primary")
        html_excl = sum(1 for j in html_jobs.values() if j["company_id"] == cid and j["html_section"] == "excluded")
        stub = cid in empty_stubs
        mismatch = prim != html_prim or excl != html_excl or (ing > 0 and prim + excl == 0 and not stub)
        if not mismatch and not (only and cid in only):
            continue
        line = (
            f"  {cid}: ingested={ing} expect_primary={prim} html_primary={html_prim} "
            f"expect_excluded={excl} html_excluded={html_excl} empty_stub={stub}"
        )
        if mismatch:
            problem_companies.append(line)
        if only or mismatch:
            lines.append(line)

    lines.append(f"\nCompanies with placement mismatch or empty stub: {len(problem_companies)}")

    # Affirm-specific
    lines.append("\n=== Affirm detail ===")
    aff_keys = [k for k, v in html_jobs.items() if v["company_id"] == "affirm"]
    lines.append(f"  HTML affirm cards: {len(aff_keys)} (primary={sum(1 for k in aff_keys if html_jobs[k]['html_section']=='primary')}, excluded={sum(1 for k in aff_keys if html_jobs[k]['html_section']=='excluded')})")
    lines.append(f"  Expected affirm primary={exp['by_company_primary'].get('affirm', 0)} excluded={exp['by_company_excluded'].get('affirm', 0)} ingested={exp['ingested_by_company'].get('affirm', 0)}")
    lines.append(f"  Empty stub in HTML: {'affirm' in empty_stubs}")
    sample = "7671388003"
    lines.append(f"  CIAM job {sample} in HTML: {any(sample in k for k in aff_keys)}")
    lines.append(f"  CIAM in expected primary: {any(sample in k for k in missing_primary) or any(sample in k for k in exp['primary'])}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = "\n".join(lines) + "\n"
    args.output.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
