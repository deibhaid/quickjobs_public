#!/usr/bin/env python3
"""Applied section is a flat date-sorted list with company brand column."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_applied", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestAppliedFlatLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_render_pipeline_section_is_flat_date_sorted(self) -> None:
        mod = self.qj
        cfg = {"companies": [], "profile": {"home_zip": "00000"}}
        jobs = [
            mod.Job(
                title="Older Role",
                company_id="acme",
                company_name="Acme",
                url="https://example.com/a",
                pipeline_status="applied",
                pipeline_applied_at="2026-05-01",
            ),
            mod.Job(
                title="Newer Role",
                company_id="beta",
                company_name="Beta",
                url="https://example.com/b",
                pipeline_status="applied",
                pipeline_applied_at="2026-07-20",
            ),
        ]
        results = [
            mod.CompanyResult(id="acme", name="Acme", label="Acme", section="matching", jobs=[]),
            mod.CompanyResult(id="beta", name="Beta", label="Beta", section="matching", jobs=[]),
        ]
        html = "\n".join(
            mod.render_pipeline_section(jobs, results, "≤50 mi from 00000", cfg, lazy=None)
        )
        self.assertNotIn("<h3>", html)
        self.assertNotIn("company-group", html)
        self.assertIn("job-applied-row", html)
        self.assertIn("job-applied-company-col", html)
        self.assertIn("job-company-brand", html)
        # Newer applied date appears before older.
        newer = html.find("Newer Role")
        older = html.find("Older Role")
        self.assertGreater(newer, 0)
        self.assertGreater(older, newer)

    def test_client_sorts_applied_panel_by_date(self) -> None:
        src = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")
        self.assertIn("function sortAppliedPanelByDate()", src)
        self.assertIn("job-applied-company-col", src)
        self.assertIn("grid-template-columns: 4.5rem 4.75rem minmax(0, 1fr)", src)
        self.assertNotIn(
            ".job.job-applied .job-company-brand {{ display: none; }}",
            src,
        )
        # Flat Applied must not hide the section for lack of company-group shells.
        self.assertIn("lazyPending", src)
        self.assertIn(".job-applied-row, .job.job-applied", src)
        self.assertIn(".job.job-applied .badge-col-loc {{ display: none !important; }}", src)

    def test_applied_section_preview_limit(self) -> None:
        src = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")
        for needle in (
            "applied-section-limit-note",
            "APPLIED_SECTION_PREVIEW_LIMIT = 10",
            "function applyAppliedSectionLimit",
            "Displaying first 10 entries.",
            "applied-section-expand-link",
            "hidden-applied-limit",
        ):
            self.assertIn(needle, src)

    def test_applied_cards_omit_location_badge(self) -> None:
        mod = self.qj
        job = mod.Job(
            title="Applied Role",
            company_id="acme",
            company_name="Acme",
            url="https://example.com/a",
            loc="remote",
            loc_label="Remote - US",
            pipeline_status="applied",
            pipeline_applied_at="2026-07-20",
        )
        html = mod.render_job(
            job,
            "≤50 mi from 00000",
            {"companies": [], "profile": {"home_zip": "00000"}},
            lazy=None,
            pool="applied",
            company=mod.CompanyResult(
                id="acme", name="Acme", label="Acme", section="matching", jobs=[]
            ),
        )
        self.assertIn("job-applied", html)
        self.assertNotIn("badge-loc", html)
        self.assertIn('<div class="badge-cell badge-col-loc"></div>', html)


if __name__ == "__main__":
    unittest.main()
