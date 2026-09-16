#!/usr/bin/env python3
"""Job Sources sidebar: primary-board cards only when hide_zero_yield is on."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_quickjobs_module():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_job_sources", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _job(qj, *, loc: str = "remote", salary: str = "ok", match: str = "good") -> object:
    return qj.Job(
        company_id="acme",
        company_name="Acme",
        title="SRE",
        url="https://example.com/job",
        loc=loc,
        match=match,
        salary=salary,
        job_id="1",
    )


def _co(qj, *, co_id: str, name: str, jobs: list) -> object:
    return qj.CompanyResult(
        id=co_id,
        name=name,
        label=name,
        section="matching",
        jobs=jobs,
    )


class JobSourcesSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_quickjobs_module()

    def test_excluded_only_omitted_when_hide_zero_yield(self) -> None:
        qj = self.qj
        co = _co(qj, co_id="acme", name="Acme", jobs=[_job(qj, loc="excluded")])
        self.assertFalse(qj.include_company_in_sidebar(co, hide_zero_yield=True))
        self.assertTrue(qj.include_company_in_sidebar(co, hide_zero_yield=False))

    def test_primary_jobs_included(self) -> None:
        qj = self.qj
        co = _co(qj, co_id="acme", name="Acme", jobs=[_job(qj, loc="remote")])
        self.assertTrue(qj.include_company_in_sidebar(co, hide_zero_yield=True))

    def test_applied_jobs_excluded_from_sidebar_dot(self) -> None:
        qj = self.qj
        active = _job(qj, loc="remote", match="strong")
        applied = _job(qj, loc="remote", match="strong")
        applied.pipeline_status = "applied"
        co = _co(qj, co_id="amazon", name="Amazon", jobs=[active, applied])
        dots = qj.active_jobs_for_sidebar_dot(co)
        self.assertEqual(len(dots), 1)
        self.assertEqual(dots[0].pipeline_status, "")
        both_applied = _co(
            qj,
            co_id="amazon",
            name="Amazon",
            jobs=[
                qj.Job(
                    company_id="amazon",
                    company_name="Amazon",
                    title="SA 1",
                    url="https://example.com/1",
                    loc="local",
                    match="strong",
                    salary="ok",
                    job_id="1",
                    pipeline_status="applied",
                ),
                qj.Job(
                    company_id="amazon",
                    company_name="Amazon",
                    title="SA 2",
                    url="https://example.com/2",
                    loc="local",
                    match="strong",
                    salary="ok",
                    job_id="2",
                    pipeline_status="applied",
                ),
            ],
        )
        self.assertEqual(qj.active_jobs_for_sidebar_dot(both_applied), [])
        self.assertFalse(qj.include_company_in_sidebar(both_applied, hide_zero_yield=True))

    def test_match_counts_exclude_excluded_and_applied(self) -> None:
        qj = self.qj
        primary = _job(qj, loc="remote", match="good")
        stretch = _job(qj, loc="remote", match="stretch")
        stretch.job_id = "2"
        stretch.url = "https://example.com/stretch"
        low = _job(qj, loc="remote", match="strong", salary="low")
        low.job_id = "3"
        low.url = "https://example.com/low"
        low.salary = "low"
        applied = _job(qj, loc="remote", match="strong")
        applied.job_id = "4"
        applied.url = "https://example.com/applied"
        applied.pipeline_status = "applied"
        loc_ex = _job(qj, loc="excluded", match="good")
        loc_ex.job_id = "5"
        loc_ex.url = "https://example.com/ex"
        co = _co(
            qj,
            co_id="acme",
            name="Acme",
            jobs=[primary, stretch, low, applied, loc_ex],
        )
        self.assertEqual(
            qj.active_job_match_counts(co),
            {"strong": 0, "good": 1, "stretch": 1},
        )
        self.assertEqual(len(qj.active_jobs_for_sidebar_dot(co)), 1)

    def test_checklist_omits_excluded_only_company(self) -> None:
        qj = self.qj
        cfg = {
            "profile": {"board_ui": {"hide_zero_yield_sidebar": True}},
            "companies": [
                {"id": "live", "name": "Live Co", "source_group": "company"},
                {"id": "hidden", "name": "Hidden Co", "source_group": "company"},
            ],
        }
        results = [
            _co(qj, co_id="live", name="Live Co", jobs=[_job(qj, loc="remote")]),
            _co(qj, co_id="hidden", name="Hidden Co", jobs=[_job(qj, loc="excluded")]),
        ]
        html = qj.render_company_checklist(cfg, results, scraped_ids={"live", "hidden"})
        self.assertIn("Job Sources (1)", html)
        self.assertIn(f'data-company-filter="{qj.company_filter_key("Live Co")}"', html)
        self.assertNotIn(f'data-company-filter="{qj.company_filter_key("Hidden Co")}"', html)

    def test_pages_zero_roles_is_suspicious_zero_yield(self) -> None:
        qj = self.qj
        co = _co(qj, co_id="apple", name="Apple", jobs=[])
        co.search_note = "Apple search (20 pages, 0 roles, 0 parsed)"
        self.assertTrue(qj.company_result_suspicious_zero_yield(co))

    def test_checklist_includes_linkedin_employer_when_first_party_excluded(self) -> None:
        """Microsoft ATS excluded-only + LinkedIn Hillsboro local → sidebar checkbox."""
        qj = self.qj
        cfg = {
            "profile": {"board_ui": {"hide_zero_yield_sidebar": True}},
            "companies": [
                {"id": "microsoft", "name": "Microsoft", "source_group": "company"},
                {
                    "id": "linkedin",
                    "name": "LinkedIn",
                    "source_group": "job_sites",
                },
            ],
        }
        ms_ats = _co(
            qj,
            co_id="microsoft",
            name="Microsoft",
            jobs=[_job(qj, loc="excluded")],
        )
        ms_ats.jobs[0].company_id = "microsoft"
        ms_ats.jobs[0].company_name = "Microsoft"
        li_job = qj.Job(
            company_id="linkedin",
            company_name="Microsoft",
            title="Senior Linux SRE",
            url="https://www.linkedin.com/jobs/view/1",
            loc="local",
            loc_label="Hillsboro, OR",
            match="strong",
            salary="ok",
            job_id="li-1",
        )
        linkedin = qj.CompanyResult(
            id="linkedin",
            name="LinkedIn",
            label="LinkedIn",
            section="aggregated",
            source_group="job_sites",
            jobs=[li_job],
        )
        html = qj.render_company_checklist(
            cfg, [ms_ats, linkedin], scraped_ids={"microsoft", "linkedin"}
        )
        self.assertIn(f'data-company-filter="{qj.company_filter_key("Microsoft")}"', html)
        # LinkedIn stays as a job-site row; Microsoft is added via employer remapping.
        self.assertIn("Job Sources (2)", html)
        self.assertIn('data-company-filter="microsoft"', html)

    def test_checklist_adds_orphan_linkedin_employer_not_in_cfg(self) -> None:
        qj = self.qj
        cfg = {
            "profile": {"board_ui": {"hide_zero_yield_sidebar": True}},
            "companies": [
                {
                    "id": "linkedin",
                    "name": "LinkedIn",
                    "source_group": "job_sites",
                },
            ],
        }
        li_job = qj.Job(
            company_id="linkedin",
            company_name="Ampere",
            title="Principal Engineer",
            url="https://www.linkedin.com/jobs/view/2",
            loc="local",
            loc_label="Portland, OR",
            match="good",
            salary="ok",
            job_id="li-2",
        )
        linkedin = qj.CompanyResult(
            id="linkedin",
            name="LinkedIn",
            label="LinkedIn",
            section="aggregated",
            source_group="job_sites",
            jobs=[li_job],
        )
        html = qj.render_company_checklist(cfg, [linkedin], scraped_ids={"linkedin"})
        self.assertIn('data-company-filter="ampere"', html)
        self.assertIn("Ampere", html)

    def test_job_work_model_key_overrides_stale_in_office_when_remote(self) -> None:
        qj = self.qj
        job = qj.Job(
            company_id="oscar",
            company_name="Oscar Health",
            title="Senior Software Engineer, Cloud Infrastructure / SRE",
            url="https://example.com/oscar",
            loc="remote",
            loc_label="Remote US",
            work_model="in-office",
            match="good",
            salary="ok",
            job_id="1",
        )
        self.assertEqual(qj.job_work_model_key(job), "remote")


if __name__ == "__main__":
    unittest.main()
