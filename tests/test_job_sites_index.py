#!/usr/bin/env python3
"""Job Sites footer: scraped boards + manual hubs."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_quickjobs_module():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_job_sites", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class JobSitesIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["QUICKJOBS_GLASSDOOR_NO_FETCH"] = "1"
        cls.qj = _load_quickjobs_module()

    def test_includes_scraped_and_hub(self) -> None:
        qj = self.qj
        cfg = {
            "companies": [
                {
                    "id": "acme",
                    "name": "Acme",
                    "type": "greenhouse",
                    "section": "matching",
                    "browse_url": "https://boards.greenhouse.io/acme",
                },
                {
                    "id": "beta-hub",
                    "name": "Beta",
                    "type": "hub",
                    "section": "hubs",
                    "hub_url": "https://beta.example/careers",
                    "hub_note": "Search manually",
                },
            ],
            "sections": {
                "hubs": {
                    "title": "Job Sites",
                    "intro": "Public careers and jobs boards for every tracked employer.",
                }
            },
        }
        entries = qj.collect_manual_career_index_entries(cfg)
        by_id = {e.id: e for e in entries}
        self.assertIn("acme", by_id)
        self.assertIn("beta-hub", by_id)
        self.assertEqual(by_id["acme"].url, "https://boards.greenhouse.io/acme")
        self.assertIn("Live scrape", by_id["acme"].how_to_search)
        self.assertEqual(by_id["beta-hub"].url, "https://beta.example/careers")

    def test_skips_workday_and_excluded(self) -> None:
        qj = self.qj
        cfg = {
            "companies": [
                {
                    "id": "wd",
                    "name": "Workday Co",
                    "type": "playwright",
                    "section": "matching",
                    "browse_url": "https://company.myworkdayjobs.com/en-US/careers",
                },
                {
                    "id": "gone",
                    "name": "Gone Co",
                    "type": "greenhouse",
                    "section": "excluded",
                    "browse_url": "https://boards.greenhouse.io/gone",
                },
                {
                    "id": "ok",
                    "name": "Ok Co",
                    "type": "ashby",
                    "section": "matching",
                    "browse_url": "https://jobs.ashbyhq.com/ok",
                },
            ],
        }
        ids = {e.id for e in qj.collect_manual_career_index_entries(cfg)}
        self.assertEqual(ids, {"ok"})

    def test_footer_labels_job_sites(self) -> None:
        qj = self.qj
        cfg = {
            "companies": [
                {
                    "id": "acme",
                    "name": "Acme",
                    "type": "greenhouse",
                    "section": "matching",
                    "browse_url": "https://boards.greenhouse.io/acme",
                }
            ],
            "sections": {
                "hubs": {
                    "title": "Manual career search (no live scrape)",
                    "intro": "Public careers sites only, not Workday. "
                    "List is hidden by default; use Show manual career links below.",
                }
            },
        }
        panel = qj.render_manual_career_footer_panel(cfg)
        self.assertIn("Job Sites", panel)
        self.assertNotIn("Manual career search", panel)
        self.assertIn('data-manual-career="1"', panel)
        self.assertIn("acme", panel)


if __name__ == "__main__":
    unittest.main()
