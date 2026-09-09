#!/usr/bin/env python3
"""State-Remote, United States (Anaplan/Netflix) is state-locked, not Remote US."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_state_dash_remote", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestStateDashRemoteUs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()
        cls.cfg = {
            "profile": {
                "home_zip": "00000",
                "local_radius_miles": 50,
                "name": "User",
            }
        }

    def test_parse_pennsylvania_remote_united_states(self) -> None:
        for loc in (
            "Pennsylvania-Remote, United States",
            "Pennsylvania - Remote, United States",
            "Pennsylvania-Remote,United States",
        ):
            self.assertEqual(self.qj.parse_state_dash_remote_us_segment(loc), "PA")
            self.assertEqual(
                self.qj.netflix_normalize_location(loc),
                "Pennsylvania, USA, Remote",
            )

    def test_pennsylvania_remote_excluded_not_nationwide(self) -> None:
        loc = "Pennsylvania-Remote, United States"
        self.assertFalse(self.qj.location_text_is_remote_us_nationwide(loc))
        self.assertTrue(self.qj.location_text_is_state_locked_us_remote(loc))
        self.assertEqual(
            self.qj.extract_workday_state_locked_remote_states(loc),
            frozenset({"PA"}),
        )
        job_loc, label = self.qj.classify_location_with_fallback(
            loc, "us", "", self.cfg, title="Principal Data Engineer - AI"
        )
        self.assertEqual(job_loc, "excluded")
        self.assertIn("Pennsylvania", label or "")

    def test_oregon_remote_workable_from_home(self) -> None:
        loc = "Oregon-Remote, United States"
        job_loc, _label = self.qj.classify_location_with_fallback(
            loc, "us", "", self.cfg, title="Platform Engineer"
        )
        self.assertEqual(job_loc, "remote")
        self.assertFalse(self.qj.location_text_is_remote_us_nationwide(loc))

    def test_existing_badge_not_nationwide_us(self) -> None:
        """Already-scraped jobs keep loc_label; badge must not claim Remote US."""
        job = self.qj.Job(
            company_id="anaplan",
            company_name="Anaplan",
            title="Principal Data Engineer - AI",
            url="https://example.com/job",
            loc="remote",
            match="good",
            salary="maybe",
            why="",
            meta="",
            description_text="",
            loc_label="Pennsylvania-Remote, United States",
        )
        self.assertFalse(self.qj.job_is_nationwide_us_remote(job, self.cfg))
        self.assertFalse(self.qj.job_is_remote_workable_from_home(job, self.cfg))
        self.assertEqual(self.qj.badge_work_model(job, self.cfg), "")
        self.assertNotIn("Remote US", self.qj.badge_loc(job, "Local"))

    def test_remote_scope_broad_us_ignores_state_dash(self) -> None:
        """``pennsylvania-remote, united states`` must not match remote+US nationwide."""
        blob = "Pennsylvania-Remote, United States\nPrincipal Engineer, AI"
        self.assertFalse(self.qj.location_text_is_remote_us_nationwide(blob))
        self.assertFalse(self.qj.remote_scope_is_broad_us(blob.lower()))

    def test_reclassify_snapshot_job_to_excluded(self) -> None:
        co = self.qj.CompanyResult(
            id="anaplan",
            name="Anaplan",
            label="Anaplan",
            section="matching",
            jobs=[
                self.qj.Job(
                    company_id="anaplan",
                    company_name="Anaplan",
                    title="Principal Engineer, AI",
                    url="https://job-boards.greenhouse.io/anaplan/jobs/8580672002",
                    loc="remote",
                    match="good",
                    salary="maybe",
                    why="",
                    meta="",
                    description_text="",
                    loc_label="Pennsylvania-Remote, United States",
                )
            ],
        )
        n = self.qj.reclassify_results_locations(
            [co],
            {
                **self.cfg,
                "companies": [
                    {"id": "anaplan", "name": "Anaplan", "type": "greenhouse", "section": "matching"}
                ],
            },
        )
        self.assertEqual(n, 1)
        self.assertEqual(co.jobs[0].loc, "excluded")
        self.assertEqual(self.qj.badge_work_model(co.jobs[0], self.cfg), "")

    def test_meta_only_pennsylvania_remote_not_nationwide(self) -> None:
        """Greenhouse snapshot shape: empty loc_label, place only in meta."""
        job = self.qj.Job(
            company_id="anaplan",
            company_name="Anaplan",
            title="Principal Data Engineer - AI",
            url="https://job-boards.greenhouse.io/anaplan/jobs/8580733002",
            loc="remote",
            match="good",
            salary="maybe",
            why="Remote US (auto-discovered).",
            meta="Pennsylvania-Remote, United States · Posted 08/24/2026",
            description_text="",
            loc_label=None,
            work_model="remote",
        )
        self.assertFalse(self.qj.job_is_nationwide_us_remote(job, self.cfg))
        self.assertFalse(self.qj.job_is_remote_workable_from_home(job, self.cfg))
        self.assertEqual(self.qj.badge_work_model(job, self.cfg), "")
        co = self.qj.CompanyResult(
            id="anaplan",
            name="Anaplan",
            label="Anaplan",
            section="matching",
            jobs=[job],
        )
        n = self.qj.reclassify_results_locations(
            [co],
            {
                **self.cfg,
                "companies": [
                    {"id": "anaplan", "name": "Anaplan", "type": "greenhouse", "section": "matching"}
                ],
            },
        )
        self.assertEqual(n, 1)
        self.assertEqual(job.loc, "excluded")
        self.assertIn("Pennsylvania", job.loc_label or "")


if __name__ == "__main__":
    unittest.main()
