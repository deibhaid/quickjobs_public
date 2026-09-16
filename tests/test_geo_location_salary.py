#!/usr/bin/env python3
"""Location-specific posted pay: Cohere geo bands, Dragos point, GM and-range, OpenAI Ashby."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COHERE_COMP = """
Compensation
Canada
Base Salary CA$285K – CA$340K • Offers Equity
USA - California, New York and Washington
Base Salary $235K – $285K • Offers Equity
USA - All Other States
Base Salary $200K – $240K • Offers Equity
"""

DRAGOS_COMP = (
    "if knowledgeable in cybersecurity threat detections, threat intelligence, "
    "or ICS/OT operations. Compensation : Salary: $225,000 Competitive Equity "
    "Package Comprehensive Benefits Plan #LI-NH1 #LI-REMOTE"
)

GM_COMP = (
    "The salary range for this role is 226,000 and 407,100. The actual base "
    "salary a successful candidate will be offered within this range will vary "
    "based on factors relevant to the position."
)

OPENAI_APP = {
    "posting": {
        "compensationTiers": [
            {
                "id": "ab62e9d0-eea4-4443-ad3e-6d8c22528491",
                "title": "ab62e9d0-eea4-4443-ad3e-6d8c22528491",
                "tierSummary": "Base Salary $401K – $510K • Offers Equity",
            }
        ],
        "scrapeableCompensationSalarySummary": "$401K - $510K",
        "compensationTierSummary": "$401K – $510K • Offers Equity",
    }
}

COHERE_APP = {
    "posting": {
        "compensationTiers": [
            {
                "id": "1",
                "title": "Canada",
                "tierSummary": "Base Salary CA$285K – CA$340K • Offers Equity",
            },
            {
                "id": "2",
                "title": "USA - California, New York and Washington",
                "tierSummary": "Base Salary $235K – $285K • Offers Equity",
            },
            {
                "id": "3",
                "title": "USA - All Other States",
                "tierSummary": "Base Salary $200K – $240K • Offers Equity",
            },
        ],
        "scrapeableCompensationSalarySummary": "CA$285K - CA$340K",
        "compensationTierSummary": "CA$285K – CA$340K • Offers Equity • Multiple Ranges",
    }
}


def _load():
    path = ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("qj_geo_salary", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _app_html(payload: dict) -> str:
    return "window.__appData = " + json.dumps(payload) + ";\n"


class GeoLocationSalaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()
        cls.cfg = {
            "profile": {
                "salary_floor": 200000,
                "home_zip": "00000",
                "home_state": "OR",
            }
        }

    def test_cohere_oregon_zip_picks_all_other_states(self) -> None:
        self.assertEqual(self.qj.profile_home_us_state(self.cfg), "OR")
        salary, label = self.qj.salary_from_detail_text(
            COHERE_COMP,
            self.cfg,
            location_name="Canada; United States",
            title="Senior Software Engineer, GPU Infrastructure (HPC)",
        )
        self.assertIn("200K", label or "")
        self.assertIn("240K", label or "")
        self.assertNotIn("235K", label or "")
        self.assertNotIn("285K", label or "")
        self.assertNotIn("340K", label or "")
        self.assertEqual(salary, "ok")

    def test_cohere_ashby_app_data_uses_all_other_states(self) -> None:
        body = _app_html(COHERE_APP)
        kind, low, high = self.qj.ashby_comp_range_from_app_data(
            body, cfg=self.cfg, location_name="Canada; United States"
        )
        self.assertEqual(kind, "base")
        self.assertEqual(low, 200000)
        self.assertEqual(high, 240000)
        salary, label = self.qj.ashby_salary_from_posting_html(
            body,
            self.cfg,
            title="Senior Software Engineer, GPU Infrastructure (HPC)",
            location_name="Canada; United States",
        )
        self.assertEqual(salary, "ok")
        self.assertIn("200K", label or "")
        self.assertIn("240K", label or "")

    def test_dragos_single_posted_salary(self) -> None:
        salary, label = self.qj.greenhouse_salary_from_detail(
            {"id": "dragos-inc", "type": "greenhouse"},
            "Principal Data Engineer",
            DRAGOS_COMP,
            self.cfg,
            location_name="United States",
        )
        self.assertEqual(salary, "ok")
        self.assertEqual(label, "Base $225K")

    def test_gm_salary_range_with_and(self) -> None:
        salary, label = self.qj.workday_salary_from_detail(
            GM_COMP, self.cfg, location_name="Milford, Michigan"
        )
        self.assertEqual(salary, "ok")
        self.assertIn("226K", label or "")
        self.assertIn("407.1K", label or "")

    def test_openai_ashby_sidebar_range(self) -> None:
        body = _app_html(OPENAI_APP)
        salary, label = self.qj.ashby_salary_from_posting_html(
            body,
            self.cfg,
            title="Principal Security Engineer, Infrastructure Security",
            location_name="San Francisco, CA",
        )
        self.assertEqual(salary, "ok")
        self.assertIn("401K", label or "")
        self.assertIn("510K", label or "")

    def test_recompute_dragos_from_stored_jd(self) -> None:
        job = self.qj.Job(
            title="Principal Data Engineer",
            company_id="dragos-inc",
            url="https://job-boards.greenhouse.io/dragos/jobs/5364899008",
            loc="remote",
            loc_label="United States",
            salary="maybe",
            salary_label=None,
            description_text=DRAGOS_COMP,
        )
        co = self.qj.CompanyResult(
            id="dragos-inc",
            name="Dragos, Inc.",
            label="Dragos",
            section="matching",
            jobs=[job],
        )
        company = {"id": "dragos-inc", "type": "greenhouse"}
        n = self.qj.recompute_results_salaries(
            [co], self.cfg, [company], only_missing=False
        )
        self.assertEqual(n, 1)
        self.assertEqual(job.salary_label, "Base $225K")


    def test_recompute_fetches_ashby_page_when_jd_has_no_pay(self) -> None:
        job = self.qj.Job(
            title="Senior Software Engineer, GPU Infrastructure (HPC)",
            company_id="cohere",
            url="https://jobs.ashbyhq.com/cohere/ef9b939d-da66-464c-a878-ef45616c0473",
            loc="remote",
            loc_label="Canada; United States",
            match="good",
            salary="maybe",
            salary_label=None,
            description_text="Build GPU training clusters. No pay in this JD.",
        )
        co = self.qj.CompanyResult(
            id="cohere",
            name="Cohere",
            label="Cohere",
            section="matching",
            jobs=[job],
        )
        company = {"id": "cohere", "type": "ashby", "ashby_board": "cohere"}
        body = _app_html(COHERE_APP)

        def fake_fetch(url: str, cache_ttl_hours: float = 24.0) -> str:
            self.assertIn("cohere", url)
            return body

        with mock.patch.object(self.qj, "ashby_fetch_posting_html", fake_fetch):
            n = self.qj.recompute_results_salaries(
                [co], self.cfg, [company], only_missing=False
            )
        self.assertGreaterEqual(n, 1)
        self.assertIn("200K", job.salary_label or "")
        self.assertIn("240K", job.salary_label or "")
        self.assertNotIn("235K", job.salary_label or "")

    def test_recompute_fetches_openai_ashby_sidebar_pay(self) -> None:
        job = self.qj.Job(
            title="Principal Security Engineer, Infrastructure Security",
            company_id="openai",
            url="https://jobs.ashbyhq.com/openai/8f1b8c6b-b414-4026-a434-6ca32c3b3e0d",
            loc="remote",
            loc_label="United States and Canada",
            match="strong",
            salary="maybe",
            salary_label=None,
            description_text="Secure production infrastructure. No pay in this JD.",
        )
        co = self.qj.CompanyResult(
            id="openai",
            name="OpenAI",
            label="OpenAI",
            section="matching",
            jobs=[job],
        )
        company = {"id": "openai", "type": "ashby", "ashby_board": "openai"}
        body = _app_html(OPENAI_APP)

        def fake_fetch(url: str, cache_ttl_hours: float = 24.0) -> str:
            self.assertIn("openai", url)
            return body

        with mock.patch.object(self.qj, "ashby_fetch_posting_html", fake_fetch):
            n = self.qj.recompute_results_salaries(
                [co], self.cfg, [company], only_missing=False
            )
        self.assertGreaterEqual(n, 1)
        self.assertIn("401K", job.salary_label or "")
        self.assertIn("510K", job.salary_label or "")

    def test_recompute_skips_ashby_fetch_when_jd_already_has_pay(self) -> None:
        job = self.qj.Job(
            title="Principal Data Engineer",
            company_id="dragos-inc",
            url="https://jobs.ashbyhq.com/dragos/not-a-real-posting",
            loc="remote",
            loc_label="United States",
            salary="maybe",
            salary_label=None,
            description_text=DRAGOS_COMP,
        )
        co = self.qj.CompanyResult(
            id="dragos-inc",
            name="Dragos, Inc.",
            label="Dragos",
            section="matching",
            jobs=[job],
        )
        company = {"id": "dragos-inc", "type": "ashby"}

        def boom(url: str, cache_ttl_hours: float = 24.0) -> str:
            raise AssertionError(f"should not fetch {url}")

        with mock.patch.object(self.qj, "ashby_fetch_posting_html", boom):
            n = self.qj.recompute_results_salaries(
                [co], self.cfg, [company], only_missing=False
            )
        self.assertEqual(n, 1)
        self.assertEqual(job.salary_label, "Base $225K")


if __name__ == "__main__":
    unittest.main()
