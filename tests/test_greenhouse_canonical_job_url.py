#!/usr/bin/env python3
"""Greenhouse career-index ?gh_jid= URLs rewrite to job-boards.greenhouse.io."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("qj_gh_canonical_url", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class GreenhouseCanonicalJobUrlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_motional_open_positions_index_rewrites(self) -> None:
        for raw in (
            "https://motional.com/open-positions?gh_jid=6354724003#/",
            "https://motional.com/open-positions/?gh_jid=7869390003#/7869390003",
        ):
            self.assertEqual(
                self.qj.greenhouse_canonical_job_url(raw, "motional"),
                "https://job-boards.greenhouse.io/motional/jobs/"
                + self.qj.greenhouse_job_id_from_url(raw),
            )

    def test_direct_greenhouse_url_unchanged(self) -> None:
        url = "https://job-boards.greenhouse.io/motional/jobs/6354724003"
        self.assertEqual(self.qj.greenhouse_canonical_job_url(url, "motional"), url)

    def test_company_jobs_id_embed_unchanged(self) -> None:
        url = "https://careers.roblox.com/jobs/7350081?gh_jid=7350081"
        self.assertEqual(self.qj.greenhouse_canonical_job_url(url, "roblox"), url)

    def test_stripe_search_pay_page_unchanged(self) -> None:
        url = "https://stripe.com/jobs/search?gh_jid=123456"
        self.assertEqual(self.qj.greenhouse_canonical_job_url(url, "stripe"), url)

    def test_waymo_jobs_index_rewrites(self) -> None:
        raw = "https://careers.withwaymo.com/jobs?gh_jid=8177651"
        self.assertEqual(
            self.qj.greenhouse_canonical_job_url(raw, "waymo"),
            "https://job-boards.greenhouse.io/waymo/jobs/8177651",
        )

    def test_rebuild_rewrites_motional_snapshot_urls(self) -> None:
        job = self.qj.Job(
            title="Software Engineer",
            company_id="motional",
            url="https://motional.com/open-positions?gh_jid=6354724003#/",
            job_id="6354724003",
        )
        results = [
            self.qj.CompanyResult(
                id="motional",
                name="Motional",
                label="Motional",
                section="matching",
                jobs=[job],
            )
        ]
        cfg = {
            "companies": [
                {"id": "motional", "type": "greenhouse", "board": "motional"},
            ]
        }
        n = self.qj.rewrite_greenhouse_embed_job_urls(results, cfg)
        self.assertEqual(n, 1)
        self.assertEqual(
            job.url,
            "https://job-boards.greenhouse.io/motional/jobs/6354724003",
        )


if __name__ == "__main__":
    unittest.main()
