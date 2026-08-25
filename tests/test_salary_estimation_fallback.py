#!/usr/bin/env python3
"""Pay Scale extraction and estimated company salary provenance."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_salary_est", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class PayScaleExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = {"profile": {"salary_floor": 200000}}

    def test_pay_scale_beats_year_range_noise(self) -> None:
        text = (
            "Requirements: 4-6 years of experience. "
            "Pay Scale: $130,000-$145,000 Bonus: eligible under the current plan."
        )
        kind, low, high = self.qj.extract_comp_range_from_text(text)
        self.assertEqual(kind, "base")
        self.assertEqual(low, 130000)
        self.assertEqual(high, 145000)
        salary, label = self.qj.salary_from_detail_text(text, self.cfg, title="SRE II")
        self.assertIn("130", label or "")
        self.assertIn("145", label or "")
        self.assertEqual(salary, "low")

    def test_pay_scale_with_nbsp_noise(self) -> None:
        text = "Pay Scale: $140,000&nbsp;– $166,500 Individual compensation is determined"
        result = self.qj.extract_comp_range_from_text(text)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[1], 140000)
        self.assertEqual(result[2], 166500)


class EstimatedCompanySalaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = cls.qj.load_config()

    def test_mozilla_weave_guidepoint_have_est_labels(self) -> None:
        by_id = {c["id"]: c for c in self.cfg["companies"] if c.get("id")}
        for cid in ("mozilla", "weave", "guidepoint-security", "keeper-security", "yipitdata", "axs"):
            co = by_id[cid]
            label = self.qj.company_salary_label_for_title(co, "Senior Software Engineer")
            self.assertTrue(label, msg=cid)
            self.assertIn("· est.", label, msg=f"{cid}: {label}")

    def test_weave_senior_platform_uses_tight_base_estimate(self) -> None:
        co = next(c for c in self.cfg["companies"] if c["id"] == "weave")
        label = self.qj.company_salary_label_for_title(
            co, "Senior Platform Engineer - Performance"
        )
        self.assertEqual(label, "$130K–$165K · est.")
        amounts = self.qj.salary_amounts_from_label(label)
        self.assertEqual(amounts, (130000, 165000))

    def test_est_visible_on_badge_not_only_tooltip(self) -> None:
        job = self.qj.Job(
            title="Senior Platform Engineer - Performance",
            company_id="weave",
            company_name="Weave",
            url="https://jobs.ashbyhq.com/weave/x",
            loc="remote",
            loc_label="Remote US",
            match="good",
            salary="maybe",
            salary_label=None,
        )
        co = next(c for c in self.cfg["companies"] if c["id"] == "weave")
        self.qj.apply_company_salary_reference(job, co, self.cfg)
        self.assertEqual(job.salary_label, "$130K–$165K · est.")
        self.assertEqual(job.salary, "low")
        visible = self.qj.salary_badge_visible_label(job, self.cfg)
        self.assertEqual(visible, "$130K–$165K · est.")
        badge = self.qj.badge_salary(job, self.cfg)
        # Visible text (not only title=) includes est.
        inner = badge.split(">")[1].split("<")[0]
        self.assertIn("est.", inner)
        self.assertIn("130", inner)
        self.assertIn("165", inner)
        self.assertNotIn("229", inner)

    def test_jd_pay_beats_company_estimate(self) -> None:
        job = self.qj.Job(
            title="Site Reliability Engineer II",
            company_id="axs",
            company_name="AXS",
            url="https://boards.greenhouse.io/axs/jobs/1",
            loc="remote",
            loc_label="Remote US",
            match="good",
            salary="low",
            salary_label="Base $130K-$145K",
        )
        co = next(c for c in self.cfg["companies"] if c["id"] == "axs")
        self.qj.apply_company_salary_reference(job, co, self.cfg)
        self.assertEqual(job.salary_label, "Base $130K-$145K")
        self.assertNotIn("est.", job.salary_label)
        visible = self.qj.salary_badge_visible_label(job, self.cfg)
        self.assertNotIn("est.", visible)


if __name__ == "__main__":
    unittest.main()
