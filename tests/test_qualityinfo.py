#!/usr/bin/env python3
"""QualityInfo Oregon LMI job openings scraper."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_qualityinfo", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class QualityInfoScraperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_oed_url_from_ord_id(self) -> None:
        url = self.qj.qualityinfo_oed_job_url("4535578")
        self.assertIn("ord=4535578", url)
        self.assertTrue(url.startswith("https://secure.emp.state.or.us/jobs/"))

    def test_oed_apply_key_keeps_ord_query(self) -> None:
        """OED postings share index.cfm; ord= must survive normalize_job_url."""
        qj = self.qj
        url = qj.qualityinfo_oed_job_url("4535578")
        self.assertEqual(qj.normalize_job_url(url), url.rstrip("/"))
        self.assertIn("ord=4535578", qj.normalize_job_url(url))
        job = qj.Job(
            company_id="qualityinfo",
            company_name="QualityInfo.org",
            title="Cloud Engineer",
            url=url,
            loc="local",
            match="good",
            salary="maybe",
            why="",
            meta="",
            description_text="",
            job_id="4535578",
        )
        self.assertIn("ord=4535578", qj.job_apply_key(job))

    def test_normalize_oregon_city(self) -> None:
        qj = self.qj
        self.assertEqual(qj.qualityinfo_normalize_location("Portland"), "Portland, OR")
        self.assertEqual(qj.qualityinfo_normalize_location("Hillsboro, OR"), "Hillsboro, OR")
        self.assertEqual(qj.qualityinfo_normalize_location("Remote"), "Remote")

    def test_title_allowlist(self) -> None:
        qj = self.qj
        self.assertTrue(qj.qualityinfo_title_acceptable("Site Reliability Engineering Architect"))
        self.assertTrue(qj.qualityinfo_title_acceptable("DevOps Infrastructure Engineers"))
        self.assertTrue(qj.qualityinfo_title_acceptable("Cloud Solutions Architect"))
        self.assertTrue(qj.qualityinfo_title_acceptable("Platform Engineers"))
        self.assertFalse(qj.qualityinfo_title_acceptable("Principal Thermal Engineer"))
        self.assertFalse(qj.qualityinfo_title_acceptable("Industrial Engineer - Foundry Quality and Reliability Labs"))
        self.assertFalse(qj.qualityinfo_title_acceptable("3D Memory Chip Architect and Design, Principal Engineer"))

    def test_opening_to_raw_rejects_noise_titles(self) -> None:
        qj = self.qj
        cfg = {"profile": {"salary_min": 150000}}
        noise = qj.qualityinfo_opening_to_raw(
            {
                "ordID": "x",
                "source": "OED",
                "jobTitle": "Principal Thermal Engineer",
                "date": "2026-07-20T00:00:00Z",
                "locationText": "Hillsboro",
                "url": "",
                "summary": "Thermal work.",
            },
            cfg,
        )
        self.assertIsNone(noise)

    def test_opening_to_raw_hwol_and_oed(self) -> None:
        qj = self.qj
        cfg = {"profile": {"salary_min": 150000}}
        hwol = qj.qualityinfo_opening_to_raw(
            {
                "ordID": "abc123",
                "source": "HWOL",
                "jobTitle": "DevOps Engineer",
                "date": "2026-07-20T00:00:00Z",
                "locationText": "Portland",
                "wageText": "$160,000/yr to $200,000/yr",
                "url": "https://example.com/job/1",
                "occTitle": "Software Developers",
                "summary": "Acme Corp\nBuild reliable platforms.",
            },
            cfg,
        )
        assert hwol is not None
        self.assertEqual(hwol.title, "DevOps Engineer")
        self.assertEqual(hwol.url, "https://example.com/job/1")
        self.assertEqual(hwol.location_name, "Portland, OR")
        self.assertEqual(hwol.company_name, "Acme Corp")
        self.assertFalse(hwol.skip_verify)
        self.assertTrue(hwol.force_url_verify)

        oed = qj.qualityinfo_opening_to_raw(
            {
                "ordID": "4535578",
                "source": "OED",
                "jobTitle": "Cloud Engineer",
                "date": "2026-07-20T00:00:00Z",
                "locationText": "Hillsboro",
                "wageText": "",
                "url": "",
                "occTitle": "Network Engineers",
                "summary": "Deploy cloud infrastructure.",
            },
            cfg,
        )
        assert oed is not None
        self.assertIn("ord=4535578", oed.url)
        self.assertEqual(oed.job_id, "4535578")
        self.assertEqual(oed.location_name, "Hillsboro, OR")
        self.assertTrue(oed.skip_verify)
        self.assertFalse(oed.force_url_verify)

    def test_hwol_workday_force_verify_drops_dead_cxs(self) -> None:
        qj = self.qj
        dead = (
            "https://intel.wd1.myworkdayjobs.com/en-us/external/job/"
            "senior-infrastructure-and-devops-engineer_jr0285653"
        )
        self.assertFalse(qj.workday_aggregator_url_is_live(dead))
        self.assertFalse(qj.url_is_live(dead, force=True))
        # Without force, ATS host skip still treats Workday as live.
        self.assertTrue(qj.url_is_live(dead, force=False))

        job = qj.Job(
            title="DevOps Infrastructure Engineers",
            company_id="qualityinfo",
            url=dead,
            skip_verify=False,
            force_url_verify=True,
            loc="local",
            match="good",
            salary="ok",
        )
        removed: list[str] = []
        live = qj.verify_jobs([job], removed, out_path=None)
        self.assertEqual(live, [])
        self.assertEqual(len(removed), 1)

    def test_fetch_qualityinfo_paginates_and_dedupes(self) -> None:
        qj = self.qj
        page1 = {
            "openingCount": "2",
            "JobOpening": [
                {
                    "ordID": "1",
                    "source": "HWOL",
                    "jobTitle": "SRE",
                    "date": "2026-07-20T00:00:00Z",
                    "locationText": "Portland",
                    "wageText": "",
                    "url": "https://example.com/a",
                    "occTitle": "SRE",
                    "summary": "Acme\nKeep systems up.",
                },
                {
                    "ordID": "2",
                    "source": "OED",
                    "jobTitle": "Platform Engineer",
                    "date": "2026-07-19T00:00:00Z",
                    "locationText": "Salem",
                    "wageText": "$90,000/yr to $120,000/yr",
                    "url": "",
                    "occTitle": "Software",
                    "summary": "Platform work.",
                },
            ],
        }
        page_dup = {
            "openingCount": "2",
            "JobOpening": [page1["JobOpening"][0]],
        }

        responses = [
            (200, "https://qi", json.dumps(page1)),
            (200, "https://qi", json.dumps(page_dup)),
        ]

        def fake_http_get(url: str, timeout: int | None = None):
            return responses.pop(0) if responses else (200, url, json.dumps({"openingCount": 0, "JobOpening": []}))

        company = {
            "id": "qualityinfo",
            "name": "QualityInfo",
            "qualityinfo_searches": ["devops"],
            "qualityinfo_sources": ["all"],
            "qualityinfo_max_pages": 2,
            "qualityinfo_maxrows": 50,
        }
        with mock.patch.object(qj, "http_get", side_effect=fake_http_get):
            raw, note = qj.fetch_qualityinfo(company, {"profile": {}})
        self.assertEqual(len(raw), 2)
        self.assertIn("2 title-matched", note or "")
        self.assertTrue(any(r.job_id == "1" for r in raw))
        self.assertTrue(any(r.job_id == "2" for r in raw))

    def test_search_handler_registered(self) -> None:
        self.assertIn("qualityinfo", self.qj.SEARCH_HANDLERS)


if __name__ == "__main__":
    unittest.main()
