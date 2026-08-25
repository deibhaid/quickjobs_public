#!/usr/bin/env python3
"""Sales/commission JD language is dropped, not shown as a match."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_sales_drop", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SKILL_CFG = {
    "keywords_include_tier1": ["architect", "engineer"],
    "keywords_include_tier2": ["solutions architect", "platform engineer"],
    "keywords_exclude": ["presales", "pre-sales"],
    "profile": {
        "skills": [
            "aws",
            "terraform",
            "kubernetes",
            "eks",
            "jenkins",
            "devops",
            "sre",
            "linux",
        ]
    },
}


PLATFORM_JD = (
    "Build AWS EKS platforms with Terraform, Jenkins, and SRE practices on Linux."
)


class SalesCommissionDropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_internal_platform_sa_not_dropped(self) -> None:
        title = "Solutions Architect"
        self.assertIsNone(self.qj.sales_commission_jd_hit(PLATFORM_JD, title))
        self.assertIsNone(
            self.qj.posting_filter_fail_reason(title, PLATFORM_JD, SKILL_CFG)
        )
        self.assertIsNone(
            self.qj.jd_blocks_job(
                PLATFORM_JD, title, SKILL_CFG, SKILL_CFG["keywords_exclude"]
            )
        )
        match = self.qj.infer_match_from_skills(PLATFORM_JD, title, SKILL_CFG)
        self.assertIn(match, ("good", "strong"))

    def test_ote_jd_is_dropped(self) -> None:
        title = "Senior Solutions Architect"
        desc = PLATFORM_JD + " Compensation includes OTE and a 70/30 base/variable split."
        self.assertEqual(self.qj.sales_commission_jd_hit(desc, title), "OTE")
        self.assertEqual(
            self.qj.posting_filter_fail_reason(title, desc, SKILL_CFG),
            "sales",
        )
        skip = self.qj.jd_blocks_job(
            desc, title, SKILL_CFG, SKILL_CFG["keywords_exclude"]
        )
        self.assertIsNotNone(skip)
        self.assertIn("sales/commission JD", skip)
        self.assertIn("OTE", skip)

    def test_sales_title_still_dropped(self) -> None:
        title = "Territory Sales Manager"
        self.assertEqual(
            self.qj.title_filter_fail_reason(title, SKILL_CFG),
            "sales",
        )

    def test_k8s_quota_is_not_dropped(self) -> None:
        title = "Staff Platform Engineer"
        desc = PLATFORM_JD + " Tune Kubernetes resource quotas and LimitRanges."
        self.assertIsNone(self.qj.sales_commission_jd_hit(desc, title))
        self.assertIsNone(
            self.qj.posting_filter_fail_reason(title, desc, SKILL_CFG)
        )
        self.assertIsNone(
            self.qj.jd_blocks_job(
                desc, title, SKILL_CFG, SKILL_CFG["keywords_exclude"]
            )
        )

    def test_reports_to_sales_is_dropped(self) -> None:
        title = "Solutions Architect"
        desc = PLATFORM_JD + " This role reports to the VP of Sales."
        self.assertEqual(
            self.qj.sales_commission_jd_hit(desc, title),
            "reports to sales",
        )
        self.assertEqual(
            self.qj.posting_filter_fail_reason(title, desc, SKILL_CFG),
            "sales",
        )

    def test_record_jd_filter_maps_sales_reason(self) -> None:
        self.qj.clear_filter_rejects()
        self.qj.record_jd_filter_reject(
            "acme",
            "Solutions Architect",
            "sales/commission JD (OTE)",
            url="https://example.com/sa",
        )
        self.assertEqual(self.qj.FILTER_REJECT_COUNTS.get("sales"), 1)


if __name__ == "__main__":
    unittest.main()
