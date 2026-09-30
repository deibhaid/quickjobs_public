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

CLOUDFLARE_SECURITY_PLATFORM_HTML = """
<h2>Available Locations</h2>
<ul>
<li>Atlanta, US</li>
<li>Austin, US</li>
<li>Denver, US</li>
<li>New York, US</li>
<li>San Francisco, US</li>
<li>Seattle, US</li>
<li>Washington DC, US</li>
<li>Canada</li>
</ul>
<h2>About the Role</h2>
<p>The Security Platform team builds infrastructure.</p>
"""

CLOUDFLARE_PORTLAND_OFFICES_HTML = """
<h2>Available Locations</h2>
<ul><li>Austin, US</li><li>Portland, OR</li></ul>
<h2>About the Role</h2>
<p>Office role.</p>
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

    def test_security_platform_city_list_is_not_remote_us(self) -> None:
        loc = self.qj.greenhouse_extract_locations_from_content(CLOUDFLARE_SECURITY_PLATFORM_HTML)
        self.assertIn("Atlanta, US", loc)
        self.assertIn("Seattle, US", loc)
        self.assertNotIn("Security Platform", loc)
        resolved = self.qj.greenhouse_resolve_location(
            "Distributed",
            "https://boards.greenhouse.io/cloudflare/jobs/7053411",
            CLOUDFLARE_SECURITY_PLATFORM_HTML,
            company_name="Cloudflare",
        )
        job_loc, label = self.qj.classify_location_with_fallback(
            resolved,
            "us",
            "",
            self.cfg,
            title="Staff/Principal Software Engineer - Security Platform",
        )
        self.assertNotEqual(job_loc, "remote")
        self.assertEqual(job_loc, "excluded")
        self.assertIn("Atlanta", str(label or ""))

    def test_office_list_with_portland_is_local(self) -> None:
        resolved = self.qj.greenhouse_resolve_location(
            "Distributed",
            "",
            CLOUDFLARE_PORTLAND_OFFICES_HTML,
            company_name="Cloudflare",
        )
        job_loc, _label = self.qj.classify_location_with_fallback(
            resolved, "us", "", self.cfg, title="Software Engineer"
        )
        self.assertEqual(job_loc, "local")

    def test_bare_us_plus_cities_stays_remote(self) -> None:
        job_loc, _label = self.qj.classify_location_with_fallback(
            "Austin, US; New York, US; US",
            "us",
            "",
            self.cfg,
            title="Account Executive",
        )
        self.assertEqual(job_loc, "remote")

    def test_majors_switzerland_is_not_remote_us(self) -> None:
        """7967144 header is Distributed; Available Locations is only Switzerland."""
        html = """
        <h2>About Us</h2><p>We build a better Internet.</p>
        <h2>Available Locations</h2>
        <ul><li>Switzerland</li></ul>
        <h2>Responsibilities</h2>
        <p>The Customer Engineer (CE) is the core driver.</p>
        """
        plain = self.qj.html_to_plain(html)
        self.assertEqual(self.qj.greenhouse_extract_locations_from_content(plain), "Switzerland")
        job = self.qj.Job(
            title="Principal Customer Engineer, Majors",
            company_id="cloudflare",
            url="https://boards.greenhouse.io/cloudflare/jobs/7967144?gh_jid=7967144",
            job_id="7967144",
            loc="remote",
            loc_label=None,
            meta="Distributed · Posted 09/16/2026",
            description_text="",
        )
        prior = {
            "companies": [
                {
                    "id": "cloudflare",
                    "name": "Cloudflare",
                    "label": "Cloudflare",
                    "section": "matching",
                    "jobs": [
                        {
                            "title": job.title,
                            "company_id": "cloudflare",
                            "url": job.url,
                            "job_id": "7967144",
                            "loc": "remote",
                            "description_text": plain,
                        }
                    ],
                }
            ]
        }
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
        merged = self.qj.merge_prior_job_descriptions([co], prior)
        self.assertEqual(merged, 1)
        self.assertEqual(job.loc, "remote")
        n = self.qj.reclassify_after_prior_jd_merge([co], cfg)
        self.assertGreaterEqual(n, 1)
        self.assertEqual(job.loc, "excluded")
        self.assertEqual(job.loc_label, "Switzerland")

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
