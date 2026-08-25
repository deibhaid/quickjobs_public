#!/usr/bin/env python3
"""Audit job board loc_label values for title/JD/work-model mislabels."""

from __future__ import annotations

import argparse
import json
import sys
import types
from collections import Counter, defaultdict
from pathlib import Path


def _load_module(path: Path, name: str):
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    sys.modules[name] = mod
    with path.open(encoding="utf-8") as handle:
        exec(compile(handle.read(), str(path), "exec"), mod.__dict__)
    return mod


def loc_label_is_bad(mod, title: str, loc_label: str, meta: str = "") -> tuple[bool, str]:
    ll = str(loc_label or "").strip()
    if not ll:
        return False, ""
    if ll.lower() == str(title or "").strip().lower():
        return True, "equals_title"
    if mod.location_text_is_work_model_only(ll):
        return True, "work_model_only"
    if mod.location_text_looks_like_jd_prose(ll):
        return True, "jd_prose"
    if getattr(mod, "location_text_looks_like_non_geographic_label", lambda _t: False)(ll):
        return True, "non_geographic"
    if len(ll) > 80:
        return True, "too_long"
    cleaned = mod.sanitize_loc_label_for_badge(
        ll,
        title=title,
        meta_parts=[p.strip() for p in meta.split(" · ") if p.strip()],
    )
    if not cleaned and ll:
        return True, "sanitize_empty"
    return False, ""


def audit_jobs(mod, jobs: list[dict], company_id: str) -> list[dict]:
    rows: list[dict] = []
    for job in jobs:
        title = str(job.get("title") or "")
        loc_label = str(job.get("loc_label") or "")
        meta = str(job.get("meta") or "")
        bad, reason = loc_label_is_bad(mod, title, loc_label, meta)
        if not bad:
            continue
        rows.append(
            {
                "company_id": company_id,
                "title": title,
                "loc_label": loc_label[:200],
                "meta": meta[:200],
                "reason": reason,
                "sanitized": mod.sanitize_loc_label_for_badge(
                    loc_label,
                    title=title,
                    meta_parts=[p.strip() for p in meta.split(" · ") if p.strip()],
                ),
            }
        )
    return rows


def load_snapshot(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    companies = data.get("companies") or []
    if not companies and data.get("sections"):
        for section in data["sections"]:
            companies.extend(section.get("companies") or [])
    return companies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path.home() / ".job_search/quickjobs/quickjobs/job-search-quickjobs.snapshot.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "ws/scriptdir/output/loc-label-qc-audit.json",
    )
    parser.add_argument("--resanitize", action="store_true", help="Audit sanitized labels only")
    parser.add_argument(
        "--apply-sanitize",
        action="store_true",
        help="Evaluate loc_label after sanitize_loc_label_for_badge (simulated after-fix)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    mod = _load_module(root / "quickjobs.py", "audit_loc_labels_qj")
    companies = load_snapshot(args.snapshot)

    bad_rows: list[dict] = []
    for co in companies:
        cid = str(co.get("id") or "")
        jobs = co.get("jobs") or []
        if args.apply_sanitize:
            adjusted = []
            for job in jobs:
                job = dict(job)
                meta = str(job.get("meta") or "")
                cleaned = mod.sanitize_loc_label_for_badge(
                    str(job.get("loc_label") or ""),
                    title=str(job.get("title") or ""),
                    description_text=str(job.get("description_text") or ""),
                    meta_parts=[p.strip() for p in meta.split(" · ") if p.strip()],
                )
                if cleaned:
                    job["loc_label"] = cleaned
                adjusted.append(job)
            jobs = adjusted
        bad_rows.extend(audit_jobs(mod, jobs, cid))

    if args.resanitize:
        resanitized: list[dict] = []
        for row in bad_rows:
            cleaned = row.get("sanitized") or ""
            bad, reason = loc_label_is_bad(
                mod,
                row["title"],
                cleaned,
                row.get("meta") or "",
            )
            if bad:
                resanitized.append({**row, "loc_label": cleaned, "reason": reason})
        bad_rows = resanitized

    by_company = Counter(row["company_id"] for row in bad_rows)
    by_reason = Counter(row["reason"] for row in bad_rows)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in bad_rows:
        grouped[row["company_id"]].append(row)

    payload = {
        "snapshot": str(args.snapshot),
        "bad_count": len(bad_rows),
        "by_company": dict(by_company.most_common()),
        "by_reason": dict(by_reason.most_common()),
        "by_company_samples": {
            cid: items[:5] for cid, items in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
        },
        "rows": bad_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Bad loc_label count: {len(bad_rows)}")
    print("Top employers:")
    for cid, count in by_company.most_common(20):
        print(f"  {count:4d}  {cid}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
