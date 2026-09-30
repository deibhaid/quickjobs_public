#!/usr/bin/env python3
"""Show listing frames the job URL except hosts that refuse framing."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_listing_frame", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class JobListingFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_greenhouse_and_ashby_frame(self) -> None:
        gh = "https://job-boards.greenhouse.io/cloudflare/jobs/7053411"
        ash = "https://jobs.ashbyhq.com/docker/5119e349-09a6-43fd-91de-db7decfa5ff9"
        self.assertEqual(self.qj.job_listing_frame_url(gh), gh)
        self.assertEqual(self.qj.job_listing_frame_url(ash), ash)

    def test_workday_and_linkedin_fall_back(self) -> None:
        self.assertEqual(
            self.qj.job_listing_frame_url(
                "https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/Principal-Engineer"
            ),
            "",
        )
        self.assertEqual(
            self.qj.job_listing_frame_url("https://wd1.myworkdaysite.com/recruiting/acme/jobs"),
            "",
        )
        self.assertEqual(
            self.qj.job_listing_frame_url("https://www.linkedin.com/jobs/view/123"),
            "",
        )

    def test_company_landing_pages_fall_back(self) -> None:
        self.assertEqual(
            self.qj.job_listing_frame_url(
                "https://www.bill.com/job?6107864004&gh_jid=6107864004"
            ),
            "",
        )
        self.assertEqual(
            self.qj.job_listing_frame_url(
                "https://www.amazon.jobs/en/jobs/10558083/senior-solutions-architect"
            ),
            "",
        )
        self.assertEqual(
            self.qj.job_listing_frame_url(
                "https://weworkremotely.com/remote-jobs/zoominfo-technologies-llc-principal"
            ),
            "",
        )

    def test_show_listing_markup(self) -> None:
        html = self.qj.render_show_listing_block(
            "https://job-boards.greenhouse.io/acme/jobs/1",
            description_html="<p>Platform work.</p>",
        )
        self.assertIn("Show listing", html)
        self.assertIn("data-listing-url=", html)
        self.assertIn("data-listing-sandbox", html)
        self.assertIn("job-listing-frame", html)
        self.assertIn("Saved description", html)
        self.assertNotIn("Expand description", html)
        ash = self.qj.render_show_listing_block(
            "https://jobs.ashbyhq.com/docker/5119e349-09a6-43fd-91de-db7decfa5ff9"
        )
        self.assertNotIn("data-listing-sandbox", ash)

    def test_blocked_host_keeps_stored_description(self) -> None:
        html = self.qj.render_job_description_block(
            "Build the platform.\n\nRequirements: Kubernetes.",
            "https://www.linkedin.com/jobs/view/123",
        )
        self.assertIn("Expand description", html)
        self.assertIn("job-description", html)
        self.assertNotIn("Show listing", html)


if __name__ == "__main__":
    unittest.main()
