#!/usr/bin/env python3
"""Amazon.jobs multi-query search + Portland multi-site location preference."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_amazon_multi", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _loc(city: str, state: str, code: str) -> str:
    return json.dumps(
        {
            "city": city,
            "region": code,
            "normalizedStateName": state,
            "normalizedCountryCode": "USA",
            "countryIso2a": "US",
            "countryIso3a": "USA",
            "normalizedCountryName": "United States",
            "normalizedLocation": f"{city}, {state}, USA",
            "location": f"US, {code}, {city}",
            "type": "ONSITE",
        }
    )


class AmazonMultiSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_location_context_prefers_portland_over_primary(self) -> None:
        job = {
            "location": "US, TX, Austin",
            "normalized_location": "Austin, Texas, USA",
            "locations": [
                _loc("Austin", "Texas", "TX"),
                _loc("Seattle", "Washington", "WA"),
                _loc("Portland", "Oregon", "OR"),
            ],
        }
        name, blob, codes = self.qj.amazon_job_location_context(job, {})
        self.assertEqual(name, "Portland, Oregon, USA")
        self.assertIn("Austin", blob)
        self.assertIn("Portland", blob)
        self.assertIn("USA", codes)

    def test_search_urls_cover_sa_and_locations(self) -> None:
        company = {
            "id": "amazon-jobs",
            "search_keywords": ["solutions architect", "devops"],
            "skip_search_keywords_extra": True,
            "amazon_loc_queries": ["Remote", "United States"],
            "amazon_result_limit": 50,
            "amazon_max_pages_per_query": 1,
            "amazon_max_queries": 10,
        }
        urls = self.qj.amazon_jobs_search_urls(company, {})
        joined = "\n".join(urls)
        self.assertIn("solutions+architect", joined.replace("%20", "+"))
        self.assertIn("loc_query=Remote", joined)
        self.assertIn("United+States", joined.replace("%20", "+"))
        self.assertGreaterEqual(len(urls), 4)

    def test_fetch_amazon_jobs_keeps_portland_multi_site(self) -> None:
        company = {
            "id": "amazon-test",
            "json_variant": "amazon_jobs",
            "search_keywords": ["solutions architect"],
            "skip_search_keywords_extra": True,
            "amazon_loc_queries": ["United States"],
            "amazon_result_limit": 50,
            "amazon_max_pages_per_query": 1,
            "amazon_max_queries": 2,
            "max_details": 12,
            "default_loc": "remote",
            "default_salary": "maybe",
            "skip_verify": True,
        }
        payload = {
            "jobs": [
                {
                    "title": "Senior Solutions Architect, AWS Certification",
                    "job_path": "/en/jobs/10418561/senior-solutions-architect-aws-certification",
                    "company_name": "Amazon Web Services, Inc.",
                    "location": "US, TX, Austin",
                    "normalized_location": "Austin, Texas, USA",
                    "description": "Build certification platforms on AWS.",
                    "locations": [
                        _loc("Austin", "Texas", "TX"),
                        _loc("Portland", "Oregon", "OR"),
                    ],
                }
            ]
        }

        def fake_get(url, timeout=None):
            return 200, url, json.dumps(payload)

        with patch.object(self.qj, "http_get", side_effect=fake_get):
            with patch.object(self.qj, "cache_get", return_value=None):
                with patch.object(self.qj, "cache_set"):
                    with patch.object(
                        self.qj, "amazon_jobs_fetch_page_salary", return_value=("ok", None)
                    ):
                        raw, note = self.qj.fetch_amazon_jobs(company, {"keywords_exclude": []})
        self.assertTrue(raw, note)
        self.assertEqual(raw[0].force_loc, "local")
        self.assertIn("Portland", raw[0].force_loc_label or raw[0].location_name or "")

    def test_description_includes_qualifications(self) -> None:
        job = {
            "description": "Build certification platforms on AWS.",
            "basic_qualifications": (
                "<p>7+ years of cloud computing, systems engineering, "
                "infrastructure, security, networking experience</p>"
            ),
            "preferred_qualifications": (
                "<p>5+ years of infrastructure architecture and networking</p>"
            ),
        }
        text = self.qj.amazon_job_description_text(job)
        self.assertIn("Build certification platforms on AWS", text)
        self.assertIn("cloud computing", text)
        self.assertIn("systems engineering", text)
        self.assertIn("infrastructure architecture", text)

    def test_sa_quals_raise_match_with_profile_skills(self) -> None:
        cfg = {
            "profile": {
                "skills": [
                    "aws",
                    "cloud computing",
                    "systems engineering",
                    "infrastructure architecture",
                    "networking",
                    "solutions architect",
                ]
            }
        }
        title = "Senior Solutions Architect, AWS Certification"
        desc = self.qj.amazon_job_description_text(
            {
                "description": "AWS Solutions Architect for certification exams.",
                "basic_qualifications": (
                    "7+ years of cloud computing, systems engineering, "
                    "infrastructure, security, networking"
                ),
                "preferred_qualifications": "5+ years of infrastructure architecture",
            }
        )
        match = self.qj.infer_match_from_skills(desc, title, cfg)
        self.assertIn(match, ("good", "strong"))


if __name__ == "__main__":
    unittest.main()
