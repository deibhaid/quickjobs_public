#!/usr/bin/env python3
"""Docker Ashby country pay lines + typo '$245,00' must still yield US band."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DOCKER_COMP = (
    "Docker does not offer visa sponsorship for this role. "
    "Compensation & Equity Canada: CA$238,000– CA$340,000 + equity "
    "United States: $171,500 – $245,00 + equity "
    "Posting Information Open vacancy: This posting is for an existing open role."
)


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_docker_salary", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class DockerAshbySalaryTests(unittest.TestCase):
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

    def test_normalize_repairs_truncated_thousand_typo(self) -> None:
        fixed = self.qj._normalize_comp_detail_text(
            "United States: $171,500 – $245,00 + equity"
        )
        self.assertIn("$245,000", fixed)
        self.assertNotIn("$245,00 ", fixed + " ")

    def test_extracts_us_band_not_canada_cad(self) -> None:
        kind, low, high = self.qj.extract_comp_range_from_text(
            DOCKER_COMP, location_name="Remote US"
        )
        self.assertEqual(kind, "base")
        self.assertEqual(low, 171500)
        self.assertEqual(high, 245000)

    def test_salary_badge_label_present(self) -> None:
        salary, label = self.qj.salary_from_detail_text(
            DOCKER_COMP,
            self.cfg,
            location_name="Remote US",
            title="Principal Solutions Architect, Professional Services",
        )
        self.assertEqual(salary, "maybe")  # floor $200k; low is $171.5k
        self.assertIsNotNone(label)
        self.assertIn("171.5K", label or "")
        self.assertIn("245K", label or "")
        self.assertNotIn("238", label or "")
        self.assertNotIn("340", label or "")

    def test_recompute_fills_docker_salary_from_stored_jd(self) -> None:
        job = self.qj.Job(
            title="Principal Solutions Architect, Professional Services (West Coast Preferred)",
            company_id="docker",
            url="https://jobs.ashbyhq.com/docker/5119e349-09a6-43fd-91de-db7decfa5ff9",
            loc="remote",
            loc_label="CAN\nUS",
            match="good",
            salary="maybe",
            salary_label=None,
            description_text=DOCKER_COMP,
        )
        co = self.qj.CompanyResult(
            id="docker",
            name="Docker",
            label="Docker",
            section="matching",
            jobs=[job],
        )
        company = {"id": "docker", "type": "ashby", "name": "Docker"}

        def boom(url: str, cache_ttl_hours: float = 24.0) -> str:
            raise AssertionError(f"should not fetch {url}")

        with mock.patch.object(self.qj, "ashby_fetch_posting_html", boom):
            n = self.qj.recompute_results_salaries(
                [co], self.cfg, [company], only_missing=False
            )
        self.assertEqual(n, 1)
        self.assertIn("171.5K", job.salary_label or "")
        self.assertIn("245K", job.salary_label or "")

    def test_rebuild_snapshot_always_recomputes_salaries(self) -> None:
        src = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")
        start = src.index("def cmd_rebuild_snapshot")
        chunk = src[start : start + 4500]
        self.assertIn("Always refresh salary badges from stored JDs", chunk)
        # salary recompute must not be gated solely on --recompute-matches
        salary_idx = chunk.index("salary_n = recompute_results_salaries")
        # Find the nearest preceding 'if recompute_matches:' that still owns this call.
        # The salary call should sit at the same indent as that if (module body of the fn).
        salary_line = [
            line for line in chunk.splitlines() if "salary_n = recompute_results_salaries" in line
        ][0]
        self.assertTrue(salary_line.startswith("    salary_n ="))


if __name__ == "__main__":
    unittest.main()
