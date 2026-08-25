#!/usr/bin/env python3
"""Capital One distinguished / lead titles pass title filters."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_capitalone", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class CapitalOneTitleFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = cls.qj.load_config()
        cls.co = next(c for c in cls.cfg["companies"] if c["id"] == "capitalone")

    def test_capitalone_search_and_detail_budget(self) -> None:
        kw = [str(x).lower() for x in (self.co.get("search_keywords") or [])]
        self.assertIn("distinguished engineer", kw)
        self.assertIn("sr lead software engineer", kw)
        self.assertIn("lead software engineer", kw)
        self.assertGreaterEqual(int(self.co.get("max_details") or 0), 120)
        self.assertGreaterEqual(
            int(self.co.get("workday_cxs_max_details_per_query") or 0), 20
        )
        # Targeted titles first so max_details budget is not spent only on devops/SRE.
        self.assertEqual(kw[0], "distinguished engineer")
        self.assertIn("sr lead software engineer", kw)
        self.assertIn("full stack shopping", kw)

    def test_distinguished_engineer_titles_pass_tier2(self) -> None:
        tier2 = self.cfg.get("keywords_include_tier2") or []
        self.assertIn("distinguished engineer", [str(x).lower() for x in tier2])
        for title in (
            "Distinguished Engineer - Bank Tech",
            "Distinguished Engineer - Card Tech",
            "Distinguished Engineer - Technical Lead (Remote-Eligible)",
            "Senior Distinguished Engineer (Remote-Eligible)",
            "Sr Lead Software Engineer, Full Stack - Shopping (Remote-Eligible)",
            "Lead Software Engineer, Full Stack - Shopping (Remote)",
        ):
            reason = self.qj.title_filter_fail_reason(title, self.cfg, company=self.co)
            self.assertIsNone(reason, msg=f"{title!r} failed: {reason}")

    def test_ml_boilerplate_does_not_block_distinguished_engineer(self) -> None:
        title = "Distinguished Engineer , Bank Tech (Remote- Eligible)"
        desc = (
            "You will work alongside our talented team of developers, "
            "machine learning experts, product managers and people leaders."
        )
        skip = self.qj.jd_blocks_job(
            desc,
            title,
            self.cfg,
            self.qj.cfg_keyword_excludes(self.cfg),
            keyword_exclude_title_only=True,
        )
        self.assertIsNone(skip)
        # Capital One IC JDs also use "decisioning" boilerplate.
        skip_dec = self.qj.jd_blocks_job(
            "Own decisioning platforms with partner teams.",
            title,
            self.cfg,
            self.qj.cfg_keyword_excludes(self.cfg),
            keyword_exclude_title_only=True,
        )
        self.assertIsNone(skip_dec)
        # Still block when ML is in the title itself.
        skip_title = self.qj.jd_blocks_job(
            desc,
            "Distinguished Machine Learning Engineer",
            self.cfg,
            self.qj.cfg_keyword_excludes(self.cfg),
            keyword_exclude_title_only=True,
        )
        self.assertIsNotNone(skip_title)

    def test_workday_us_remote_in_meta_counts_as_nationwide(self) -> None:
        """Badge sanitize may drop 'US Remote' from loc_label; meta must still count."""
        job = self.qj.Job(
            title="Distinguished Engineer , Bank Tech (Remote- Eligible)",
            company_id="capitalone",
            url="https://capitalone.wd12.myworkdayjobs.com/example",
            loc="remote",
            loc_label="New York, NY\nMclean, VA",
            work_model="hybrid",
            meta="New York, NY; US Remote; McLean, VA · Posted 30+ Days Ago",
            match="stretch",
        )
        self.assertTrue(self.qj.job_is_nationwide_us_remote(job, self.cfg))
        self.assertTrue(self.qj.job_is_remote_workable_from_home(job, self.cfg))

    def test_base_json_parses(self) -> None:
        base_path = REPO_ROOT / "quickjobs.base.json"
        companies_path = REPO_ROOT / "quickjobs.companies.json"
        base = json.loads(base_path.read_text(encoding="utf-8"))
        companies = json.loads(companies_path.read_text(encoding="utf-8"))
        self.assertNotIn("companies", base)
        self.assertIsInstance(companies.get("companies"), list)


if __name__ == "__main__":
    unittest.main()
