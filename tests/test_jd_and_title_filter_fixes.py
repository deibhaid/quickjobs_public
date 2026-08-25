#!/usr/bin/env python3
"""JD blocklist substring fixes, OTE boilerplate, and title tier normalization."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_filter_fixes", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


TIER_CFG = {
    "keywords_include_tier1": ["engineer", "architect", "devops"],
    "keywords_include_tier2": ["devops engineer", "software engineer", "software developer"],
    "keywords_exclude": [],
    "profile": {"domain_years": {"ad tech": 0}},
}


class JdAndTitleFilterFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_ad_tech_does_not_match_lead_technical(self) -> None:
        blob = "you will lead technical designs and rfcs for our ci platform."
        self.assertFalse(self.qj.phrase_in_job_blob("ad tech", blob))
        skip = self.qj.jd_blocks_job(
            blob,
            "Principal Software Engineer, DevOps and Tools",
            TIER_CFG,
            [],
        )
        self.assertIsNone(skip)

    def test_ad_tech_still_blocks_real_ad_tech_roles(self) -> None:
        blob = "build our ad tech stack and ad serving pipeline."
        self.assertTrue(self.qj.phrase_in_job_blob("ad tech", blob))
        skip = self.qj.jd_blocks_job(blob, "Ad Tech Platform Engineer", TIER_CFG, [])
        self.assertIsNotNone(skip)
        self.assertIn("ad tech", skip)

    def test_dev_ops_title_matches_devops_tier2(self) -> None:
        title = "Dev Ops Engineer II or III (DOE)"
        self.assertIsNone(self.qj.title_filter_fail_reason(title, TIER_CFG))

    def test_software_development_engineer_matches_tier2(self) -> None:
        title = "Software Development Engineer, Amazon Application Recovery Controller"
        self.assertIsNone(self.qj.title_filter_fail_reason(title, TIER_CFG))

    def test_software_dev_engineer_matches_tier2(self) -> None:
        title = "Software Dev Engineer, AWS Resilience Hub"
        self.assertIsNone(self.qj.title_filter_fail_reason(title, TIER_CFG))

    def test_later_ote_boilerplate_does_not_drop_ic_role(self) -> None:
        title = "Staff Engineer (Product)"
        desc = (
            "Build product platforms. Compensation for some roles is structured as "
            "on target earnings (OTE = base + commission/variable) while for others "
            "it is structured as salary only."
        )
        self.assertIsNone(self.qj.sales_commission_jd_hit(desc, title))
        self.assertIsNone(self.qj.jd_blocks_job(desc, title, TIER_CFG, []))

    def test_role_specific_ote_still_drops(self) -> None:
        title = "Senior Solutions Architect"
        desc = "Compensation includes OTE and a 70/30 base/variable split."
        self.assertEqual(self.qj.sales_commission_jd_hit(desc, title), "OTE")

    def test_anthropic_style_comp_disclaimer_does_not_drop_swe(self) -> None:
        title = "Senior Software Engineer, Full-stack"
        desc = (
            "Build platform services. For some sales roles, compensation includes OTE. "
            "Software engineers receive competitive base salary and equity."
        )
        self.assertIsNone(self.qj.sales_commission_jd_hit(desc, title))

    def test_devsecops_ml_jd_block_exempt(self) -> None:
        desc = "Partner with ML teams on model deployment and GPU infrastructure."
        skip = self.qj.jd_blocks_job(
            desc,
            "DevSecOps Engineer (TypeScript & Agentic AI)",
            TIER_CFG,
            [],
        )
        self.assertIsNone(skip)

    def test_marketing_swe_ads_jd_exempt(self) -> None:
        desc = "Improve our ads platform and marketing technology stack."
        skip = self.qj.jd_blocks_job(
            desc,
            "Senior Staff Software Engineer, Marketing Technology",
            TIER_CFG,
            [],
        )
        self.assertIsNone(skip)

    def test_security_engineer_matches_tier2(self) -> None:
        title = "Senior Security Engineer, Detection & Response"
        self.assertIsNone(self.qj.title_filter_fail_reason(title, self.qj.load_config()))

    def test_security_engineer_not_blocked_by_ml_jd_boilerplate(self) -> None:
        desc = (
            "Partner with machine learning and data science teams on detection pipelines. "
            "You will build security tooling and incident response automation."
        )
        skip = self.qj.jd_blocks_job(
            desc,
            "Senior Security Engineer, Incident Response",
            TIER_CFG,
            [],
        )
        self.assertIsNone(skip)

    def test_machine_learning_engineer_title_still_blocked(self) -> None:
        desc = "Build training pipelines and deploy models to production."
        skip = self.qj.jd_blocks_job(
            desc,
            "Senior Machine Learning Engineer",
            TIER_CFG,
            [],
        )
        self.assertIsNotNone(skip)
        self.assertIn("machine learning engineer", skip)


if __name__ == "__main__":
    unittest.main()
