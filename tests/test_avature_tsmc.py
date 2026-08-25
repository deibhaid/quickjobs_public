#!/usr/bin/env python3
"""Avature SearchJobs HTML + JobDetail JSON-LD parsing (TSMC)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_avature", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SAMPLE_SEARCH = """
<article class="article article--result" id="article--1">
  <div class="article__header">
    <h3 class="article__header__text__title title title--03">
      <a class="link" href="https://careers.tsmc.com/en_US/careers/JobDetail?jobId=471&amp;source=External%2BCareer%2BSite">
        IT DevOps Manager
      </a>
    </h3>
    <div class="article__header__text__subtitle">Taiwan</div>
  </div>
</article>
<article class="article article--result" id="article--2">
  <h3 class="article__header__text__title">
    <a class="link" href="/en_US/careers/JobDetail?jobId=5307&source=External+Career+Site">
      Site Reliability Engineer (IMC)
    </a>
  </h3>
</article>
"""

SAMPLE_DETAIL = """
<script type="application/ld+json">
{
  "@context": "http://schema.org",
  "@type": "JobPosting",
  "title": "IT DevOps Manager",
  "description": "<p>Lead DevOps for cloud native platforms</p>",
  "datePosted": "2026-07-01",
  "jobLocation": {
    "@type": "Place",
    "address": {"@type": "PostalAddress", "streetAddress": "Taiwan"}
  }
}
</script>
"""

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title><![CDATA[IT Software Engineer]]></title>
  <link>https://careers.tsmc.com/careers/JobDetail/IT-Software-Engineer/461</link>
</item>
</channel></rss>
"""


class AvatureParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_parse_search_articles(self) -> None:
        rows = self.qj.avature_parse_search_articles(SAMPLE_SEARCH)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["job_id"], "471")
        self.assertEqual(rows[0]["title"], "IT DevOps Manager")
        self.assertEqual(rows[1]["job_id"], "5307")

    def test_parse_job_detail_jsonld(self) -> None:
        detail = self.qj.avature_parse_job_detail(SAMPLE_DETAIL)
        self.assertEqual(detail["title"], "IT DevOps Manager")
        self.assertEqual(detail["location_name"], "Taiwan")
        self.assertIn("DevOps", detail["description_text"])

    def test_parse_rss_and_normalize_url(self) -> None:
        items = self.qj.avature_parse_rss_items(SAMPLE_RSS)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["job_id"], "461")
        url = self.qj.avature_normalize_detail_url(
            items[0]["url"], "https://careers.tsmc.com/en_US/careers/SearchJobs"
        )
        self.assertIn("jobId=461", url)
        self.assertIn("en_US/careers/JobDetail", url)

    def test_fetch_avature_uses_search_and_detail(self) -> None:
        company = {
            "id": "tsmc-test",
            "browse_url": "https://careers.tsmc.com/en_US/careers/SearchJobs",
            "search_keywords": ["devops"],
            "skip_search_keywords_extra": True,
            "max_details": 5,
            "default_loc": "remote",
            "default_salary": "maybe",
            "skip_verify": True,
        }
        cfg = {"search_keywords": ["devops"], "keywords_exclude": []}

        def fake_get(url, timeout=None):
            if "feed" in url:
                return 200, url, SAMPLE_RSS
            if "JobDetail" in url or "jobId=" in url:
                return 200, url, SAMPLE_DETAIL
            return 200, url, SAMPLE_SEARCH

        def fake_post(url, fields, timeout=None, headers=None):
            return 200, url, SAMPLE_SEARCH

        with patch.object(self.qj, "http_get", side_effect=fake_get):
            with patch.object(self.qj, "http_post_form", side_effect=fake_post):
                with patch.object(self.qj, "cache_get", return_value=None):
                    with patch.object(self.qj, "cache_set"):
                        raw, note = self.qj.fetch_avature(company, cfg)
        self.assertTrue(raw)
        self.assertIn("Avature", note or "")
        self.assertTrue(any("DevOps" in p.title or "Software" in p.title for p in raw))


if __name__ == "__main__":
    unittest.main()
