#!/usr/bin/env python3
"""Jibe CMS careers API (AMD-style /api/jobs) fetch."""

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
    spec = importlib.util.spec_from_file_location("quickjobs_david_jibe", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _cfg() -> dict:
    return mod.load_config()


class JibeFetchTests(unittest.TestCase):
    def test_jibe_job_url(self) -> None:
        company = {
            "browse_url": "https://careers.amd.com/careers-home/jobs",
            "jibe_job_path": "/careers-home/jobs/{slug}",
        }
        self.assertEqual(
            mod.jibe_job_url(company, "84916"),
            "https://careers.amd.com/careers-home/jobs/84916",
        )

    def test_fetch_jibe_parses_api_jobs(self) -> None:
        company = {
            "id": "amd-test",
            "browse_url": "https://careers.amd.com/careers-home/jobs",
            "jibe_api_url": "https://careers.amd.com/api/jobs",
            "search_keywords": ["devops"],
            "skip_search_keywords_extra": True,
            "max_details": 5,
            "default_loc": "remote",
            "skip_verify": True,
        }
        payload = {
            "totalCount": 1,
            "jobs": [
                {
                    "data": {
                        "title": "Staff DevOps Engineer",
                        "slug": "84916",
                        "req_id": "84916",
                        "full_location": "Austin, Texas",
                        "posted_date": "2026-07-16T10:00:00+0000",
                        "description": "<p>Kubernetes Terraform CI/CD</p>",
                        "salary_min_value": 140000,
                        "salary_max_value": 200000,
                    }
                }
            ],
        }

        with patch.object(mod, "cache_get", return_value=None):
            with patch.object(mod, "cache_set"):
                with patch.object(
                    mod, "http_get", return_value=(200, "", json.dumps(payload))
                ):
                    raw, note = mod.fetch_jibe(company, _cfg())
        self.assertEqual(len(raw), 1)
        self.assertIn("84916", raw[0].url)
        self.assertEqual(raw[0].title, "Staff DevOps Engineer")
        self.assertIn("1 parsed", note)


if __name__ == "__main__":
    unittest.main()
