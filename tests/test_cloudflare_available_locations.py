#!/usr/bin/env python3
"""Cloudflare Available Locations must beat Distributed API labels."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_cf_locs", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CLOUDFLARE_GERMANY_HTML = """
<div><p>About Us</p><p>We build a better Internet.</p>
<h2>Available Locations</h2>
<ul><li>Germany</li></ul>
<h2>Responsibilities</h2>
<p>The Customer Engineer (CE) is the core driver...</p></div>
"""

CLOUDFLARE_US_CITIES_HTML = """
<p><strong>Available Locations: Los Angeles, CA OR Seattle, WA</strong></p>
<p>About the Role: We are seeking an entrepreneurial Sales Director</p>
"""


class CloudflareAvailableLocationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.cfg = {"profile": {"home_zip": "00000", "local_radius_miles": 50}}

    def test_extract_germany_heading_without_colon(self) -> None:
        loc = self.qj.greenhouse_extract_locations_from_content(CLOUDFLARE_GERMANY_HTML)
        self.assertEqual(loc, "Germany")

    def test_extract_colon_form_stops_at_about(self) -> None:
        loc = self.qj.greenhouse_extract_locations_from_content(CLOUDFLARE_US_CITIES_HTML)
        self.assertEqual(loc, "Los Angeles, CA OR Seattle, WA")

    def test_distributed_plus_germany_resolves_and_excludes(self) -> None:
        resolved = self.qj.greenhouse_resolve_location(
            "Distributed",
            "https://boards.greenhouse.io/cloudflare/jobs/1",
            CLOUDFLARE_GERMANY_HTML,
            company_name="Cloudflare",
        )
        self.assertEqual(resolved, "Germany")
        job_loc, label = self.qj.classify_location_with_fallback(
            resolved, "us", "", self.cfg, title="Principal Customer Engineer, Digital Natives"
        )
        self.assertEqual(job_loc, "excluded")
        self.assertIn("Germany", str(label or ""))

    def test_reclassify_distributed_from_stored_jd(self) -> None:
        plain = self.qj.html_to_plain(CLOUDFLARE_GERMANY_HTML)
        job = self.qj.Job(
            title="Principal Customer Engineer, Digital Natives",
            company_id="cloudflare",
            url="https://boards.greenhouse.io/cloudflare/jobs/1",
            loc="remote",
            loc_label="Distributed",
            meta="Distributed · Live posting (Greenhouse)",
            description_text=plain,
        )
        co = self.qj.CompanyResult(
            id="cloudflare",
            name="Cloudflare",
            label="Cloudflare",
            section="matching",
            jobs=[job],
        )
        cfg = {
            "profile": self.cfg["profile"],
            "companies": [{"id": "cloudflare", "type": "greenhouse", "name": "Cloudflare"}],
        }
        n = self.qj.reclassify_results_locations([co], cfg)
        self.assertGreaterEqual(n, 1)
        self.assertEqual(job.loc, "excluded")
        self.assertIn("Germany", str(job.loc_label or ""))

    def test_escaped_greenhouse_content_germany(self) -> None:
        escaped = (
            "About Us&lt;/p&gt;&lt;h2&gt;Available Locations&lt;/h2&gt;\n"
            "&lt;ul&gt;\n&lt;li&gt;Germany&lt;/li&gt;\n&lt;/ul&gt;\n"
            "&lt;h2&gt;Responsibilities&lt;/h2&gt;\n&lt;p&gt;The Customer Engineer"
        )
        loc = self.qj.greenhouse_extract_locations_from_content(escaped)
        self.assertEqual(loc, "Germany")
        resolved = self.qj.greenhouse_resolve_location(
            "Distributed", "", escaped, company_name="Cloudflare"
        )
        self.assertEqual(resolved, "Germany")


if __name__ == "__main__":
    unittest.main()
