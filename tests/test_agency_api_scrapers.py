#!/usr/bin/env python3
"""Collabera (SmartRecruiters), Cypress HCM (Bullhorn), Jefferson Frank (GraphQL)."""

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
    spec = importlib.util.spec_from_file_location("quickjobs_mod_agency_apis", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class AgencyApiScraperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = {
            "profile": {"salary_min": 150000},
            "title_tier1": ["devops", "site reliability engineer", "platform engineer"],
            "title_tier2": ["software engineer"],
            "title_exclude": [],
        }

    def test_handlers_registered(self) -> None:
        qj = self.qj
        self.assertIn("bullhorn_public", qj.SEARCH_HANDLERS)
        self.assertIn("jeffersonfrank", qj.SEARCH_HANDLERS)
        self.assertIn("smartrecruiters", qj.SEARCH_HANDLERS)

    def test_bullhorn_public_job_url(self) -> None:
        url = self.qj.bullhorn_public_job_url(
            "https://www.cypresshcm.com/career-portal/", 33900
        )
        self.assertEqual(
            url, "https://www.cypresshcm.com/career-portal/#/jobs/33900"
        )
        self.assertEqual(
            self.qj.normalize_job_url(url),
            "https://www.cypresshcm.com/career-portal/#/jobs/33900",
        )

    def test_jeffersonfrank_job_url(self) -> None:
        url = self.qj.jeffersonfrank_job_url(
            "a0MP900000A5A4D.3_1784104941",
            "Azure DevOps Engineer",
        )
        self.assertEqual(
            url,
            "https://www.jeffersonfrank.com/job/a0MP900000A5A4D.3_1784104941/azure-devops-engineer",
        )

    def test_fetch_bullhorn_public_parses_rows(self) -> None:
        qj = self.qj
        company = {
            "id": "cypress-hcm",
            "name": "Cypress HCM",
            "bullhorn_swimlane": "44",
            "bullhorn_corp_token": "D2ULD0",
            "bullhorn_career_portal": "https://www.cypresshcm.com/career-portal",
            "default_loc": "excluded",
        }
        payload = {
            "total": 1,
            "start": 0,
            "count": 1,
            "data": [
                {
                    "id": 33900,
                    "title": "DevOps Engineer",
                    "employmentType": "Contract",
                    "dateLastPublished": 1700000000000,
                    "address": {"city": "Portland", "state": "OR"},
                    "publicDescription": "<p>Kubernetes and Terraform</p>",
                    "salary": 80,
                    "salaryUnit": "per hour",
                }
            ],
        }

        def fake_get(url: str, timeout=None):
            self.assertIn("public-rest44.bullhornstaffing.com", url)
            self.assertIn("D2ULD0", url)
            return 200, url, json.dumps(payload)

        with mock.patch.object(qj, "http_get", side_effect=fake_get):
            with mock.patch.object(
                qj, "title_rejected_by_scrape_filters", return_value=False
            ):
                with mock.patch.object(
                    qj,
                    "classify_location_with_fallback",
                    return_value=("local", "Portland, OR"),
                ):
                    raw, note = qj.fetch_bullhorn_public(company, self.cfg)

        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0].title, "DevOps Engineer")
        self.assertIn("#/jobs/33900", raw[0].url)
        self.assertIn("Kubernetes", raw[0].description_text)
        self.assertIn("Bullhorn Public API", note or "")

    def test_fetch_jeffersonfrank_parses_graphql(self) -> None:
        qj = self.qj
        company = {
            "id": "jefferson-frank",
            "name": "Jefferson Frank",
            "jeffersonfrank_max_queries": 1,
            "jeffersonfrank_max_pages": 1,
            "search_keywords": ["devops"],
            "skip_search_keywords_extra": True,
            "default_loc": "excluded",
        }
        gql_body = {
            "data": {
                "searchJobs": {
                    "pagination": {"value": 1, "relation": "eq"},
                    "items": [
                        {
                            "reference": "a0MP900000A5A4D.3_1784104941",
                            "title": "Azure DevOps Engineer",
                            "remote": True,
                            "type": "Contract",
                            "role": "Engineer",
                            "seniority": "Senior",
                            "description": "AWS and Terraform",
                            "location": {
                                "description": "USA, Oregon",
                                "country": "USA",
                                "region": "Oregon",
                            },
                            "salary": {
                                "from": 150000,
                                "to": 180000,
                                "currency": "USD",
                                "description": None,
                            },
                        }
                    ],
                }
            }
        }

        def fake_post(url, payload, timeout=None, headers=None):
            self.assertIn("appsync-api", url)
            self.assertTrue((headers or {}).get("x-api-key", "").startswith("da2-"))
            return 200, url, json.dumps(gql_body)

        with mock.patch.object(qj, "http_post_json", side_effect=fake_post):
            with mock.patch.object(
                qj, "title_rejected_by_scrape_filters", return_value=False
            ):
                with mock.patch.object(
                    qj,
                    "classify_location_with_fallback",
                    return_value=("remote", "USA, Oregon (Remote)"),
                ):
                    raw, note = qj.fetch_jeffersonfrank(company, self.cfg)

        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0].title, "Azure DevOps Engineer")
        self.assertIn("/job/a0MP900000A5A4D.3_1784104941/", raw[0].url)
        self.assertIn("150000-180000", raw[0].salary_label or "")
        self.assertIn("Jefferson Frank GraphQL", note or "")

    def test_smartrecruiters_keyword_query_uses_q(self) -> None:
        qj = self.qj
        company = {
            "id": "collabera",
            "name": "Collabera",
            "smartrecruiters_id": "Collabera2",
            "smartrecruiters_keyword_query": True,
            "smartrecruiters_max_queries": 1,
            "search_keywords": ["devops"],
            "skip_search_keywords_extra": True,
            "default_loc": "excluded",
        }
        payload = {
            "offset": 0,
            "limit": 100,
            "totalFound": 1,
            "content": [
                {
                    "id": "abc123",
                    "name": "DevOps Engineer",
                    "location": {
                        "city": "Remote",
                        "region": "OR",
                        "country": "us",
                        "remote": True,
                    },
                    "postingUrl": "https://jobs.smartrecruiters.com/Collabera2/abc123",
                    "releasedDate": "2026-07-01T00:00:00.000Z",
                }
            ],
        }
        seen_urls: list[str] = []

        def fake_get(url: str, timeout=None):
            seen_urls.append(url)
            return 200, url, json.dumps(payload)

        with mock.patch.object(qj, "http_get", side_effect=fake_get):
            with mock.patch.object(
                qj, "title_rejected_by_scrape_filters", return_value=False
            ):
                with mock.patch.object(
                    qj,
                    "classify_location_with_fallback",
                    return_value=("remote", "Remote, OR (Remote)"),
                ):
                    raw, note = qj.fetch_smartrecruiters(company, self.cfg)

        self.assertEqual(len(raw), 1)
        self.assertTrue(any("q=devops" in u for u in seen_urls))
        self.assertIn("keyword scan", note or "")


if __name__ == "__main__":
    unittest.main()
