#!/usr/bin/env python3
"""Verify sidebar company scroll lands on the matching listings block."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _audit_html(html: str) -> list[str]:
    issues: list[str] = []
    buttons = re.findall(
        r'<button[^>]*class="company-filter-name"[^>]*data-company-scroll="([^"]+)"'
        r'(?:[^>]*data-company-scroll-id="([^"]*)")?[^>]*>([^<]+)</button>',
        html,
    )
    body_start = html.find('id="job-listings-body"')
    body_end = html.find('id="excluded-panel"')
    body = html[body_start:body_end] if body_start >= 0 else html
    lazy_match = re.search(
        r'<script type="application/json" id="lazy-board-data">(.*?)</script>',
        html,
        re.S,
    )
    lazy_data = json.loads(lazy_match.group(1)) if lazy_match else {}

    skip_no_group = {"amazon", "apple", "google", "okta"}
    for key, company_id, name in buttons:
        name = name.strip()
        if company_id:
            pat = rf'<div class="company-group[^"]*"[^>]*data-company="{re.escape(company_id)}"'
        else:
            pat = rf'<div class="company-group[^"]*"[^>]*data-company-filter="{re.escape(key)}"'
        if not re.search(pat, body):
            if key not in skip_no_group:
                issues.append(f"no listings group for sidebar {name!r} ({key})")
            continue
        lazy_html = (lazy_data.get("companies") or {}).get(key, "") or (
            lazy_data.get("companiesExcluded") or {}
        ).get(key, "")
        if lazy_html:
            first = re.search(
                r'class="job-title"[^>]*>[\s\S]*?<a[^>]*>([^<]+)',
                lazy_html,
            )
            if not first:
                issues.append(f"lazy block empty for {name!r} ({key})")
    return issues


def _audit_rendered(out_path: Path) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ["playwright not installed"]

    issues: list[str] = []
    file_url = out_path.resolve().as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(file_url, wait_until="networkidle", timeout=120000)
        page.wait_for_selector("#company-filter", timeout=60000)
        page.evaluate(
            """() => {
              document.getElementById('match-good').checked = true;
              document.getElementById('match-strong').checked = true;
              document.querySelectorAll('.company-filter-row-hidden').forEach(row => {
                row.classList.remove('company-filter-row-hidden');
              });
              applyRoleFilter();
            }"""
        )
        page.wait_for_timeout(500)

        samples = page.evaluate(
            """() => {
              const buttons = [...document.querySelectorAll('#company-filter button.company-filter-name')];
              const pick = (label) => buttons.find(b => b.textContent.trim().startsWith(label));
              return ['Salesforce', 'Mercury', 'Meta', 'Rubrik', 'Adobe Inc.']
                .map(label => {
                  const btn = pick(label);
                  if (!btn) return {label, error: 'button missing'};
                  return {
                    label,
                    key: btn.dataset.companyScroll,
                    id: btn.dataset.companyScrollId || '',
                  };
                });
            }"""
        )
        for sample in samples:
            if sample.get("error"):
                issues.append(f"{sample['label']}: {sample['error']}")
                continue
            label = sample["label"]
            page.evaluate(
                """(args) => scrollToCompanySection(args.key, args.id)""",
                {"key": sample["key"], "id": sample["id"]},
            )
            page.wait_for_timeout(900)
            info = page.evaluate(
                """(args) => {
                  const target = findCompanyGroup(args.key, args.id);
                  if (!target) return null;
                  const h = target.querySelector('h3, h4');
                  return {
                    key: target.dataset.companyFilter,
                    id: target.dataset.company,
                    h3: (h?.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
                    scrollY: Math.round(window.scrollY),
                    hTop: h ? Math.round(h.getBoundingClientRect().top) : null,
                    hidden: target.classList.contains('hidden-empty') || target.classList.contains('hidden-company'),
                    jobs: target.querySelectorAll('.job:not(.hidden)').length,
                  };
                }""",
                {"key": sample["key"], "id": sample["id"]},
            )
            if not info:
                issues.append(f"{label}: no company group near viewport after scroll")
                continue
            if info["key"] != sample["key"]:
                issues.append(
                    f"{label}: scroll landed on {info['key']!r} (expected {sample['key']!r}); h3={info['h3']!r}"
                )
            elif info["hidden"]:
                issues.append(f"{label}: target still hidden after scroll")
            elif info["hTop"] is None or abs(info["hTop"]) > 120:
                issues.append(
                    f"{label}: heading not in viewport (hTop={info['hTop']}, scrollY={info['scrollY']})"
                )
        browser.close()
    return issues


def main() -> int:
    out = Path("/Users/deibhaid/Downloads/jobs/job-search-david.html")
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
    if not out.is_file():
        print(f"Missing HTML: {out}", file=sys.stderr)
        return 1
    html = out.read_text(encoding="utf-8")
    issues = _audit_html(html)
    issues.extend(_audit_rendered(out))
    if issues:
        print("Company scroll validation failed:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1
    print(f"Company scroll OK: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
