#!/usr/bin/env python3
"""Talentbrew search title must match the job-id URL (Jack Henry markup)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

JACK_HENRY_LIST_HTML = """
<section id="search-results-list" class="search-results-list">
<ul>
<li>
  <div class="search-results-list__content">
    <h2 class="headline__extra-small"><a href="/job/united-states/senior-cloud-infrastructure-engineer-core/42859/100621840400" data-job-id="100621840400">Senior Cloud Infrastructure Engineer: Core</a></h2>
    <span class="job-location"><b>Location:</b> United States</span>
    <span class="job-remote"><b>Workplace Type:</b> Remote</span>
  </div>
</li>
<li>
  <div class="search-results-list__content">
    <h2 class="headline__extra-small"><a href="/job/kansas/infrastructure-engineering-manager/42859/100136307824" data-job-id="100136307824">Infrastructure Engineering Manager</a></h2>
    <span class="job-location"><b>Location:</b> Kansas</span>
  </div>
</li>
<li>
  <div class="search-results-list__content">
    <h2 class="headline__extra-small"><a href="/job/united-states/senior-manager-of-software-engineering-observability/42859/99029486928" data-job-id="99029486928">Senior Manager of Software Engineering: Observability</a></h2>
    <span class="job-location"><b>Location:</b> United States</span>
  </div>
</li>
</ul>
</section>
"""


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_talentbrew_titles", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TalentbrewTitleParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_jack_henry_h2_wraps_anchor_title_matches_path(self) -> None:
        rows = self.qj.parse_talentbrew_search(JACK_HENRY_LIST_HTML)
        by_id = {r["job_id"]: r for r in rows}
        self.assertEqual(
            by_id["100621840400"]["title"],
            "Senior Cloud Infrastructure Engineer: Core",
        )
        self.assertIn("senior-cloud-infrastructure-engineer-core", by_id["100621840400"]["path"])
        self.assertEqual(
            by_id["99029486928"]["title"],
            "Senior Manager of Software Engineering: Observability",
        )
        self.assertIn(
            "senior-manager-of-software-engineering-observability",
            by_id["99029486928"]["path"],
        )
        # Regression: old parser grabbed the *next* card's h2.
        self.assertNotEqual(
            by_id["100621840400"]["title"],
            "Infrastructure Engineering Manager",
        )
        # Location spans include <b>Location:</b>; must not leak tags into the card.
        self.assertEqual(by_id["100621840400"]["location"], "United States · Remote")
        self.assertEqual(by_id["100136307824"]["location"], "Kansas")
        self.assertNotIn("<", by_id["100621840400"]["location"])
        self.assertNotRegex(by_id["100621840400"]["location"], r"(?i)location\s*:")

    def test_legacy_h2_inside_anchor_still_works(self) -> None:
        html = (
            '<a href="/job/a" data-job-id="1"><h2>DevOps Engineer</h2></a>'
            '<a href="/job/b" data-job-id="2"><h2>Platform Engineer</h2></a>'
        )
        rows = self.qj.parse_talentbrew_search(html)
        self.assertEqual([r["title"] for r in rows], ["DevOps Engineer", "Platform Engineer"])

    def test_title_from_detail_strips_nav_noise(self) -> None:
        text = (
            "Senior Manager of Software Engineering: Observability at Jack Henry & Associates, Inc "
            "Skip to main content careers Get Connected"
        )
        title = self.qj.talentbrew_title_from_detail(
            text, company_name="Jack Henry & Associates"
        )
        self.assertEqual(title, "Senior Manager of Software Engineering: Observability")

    def test_netapp_detail_prefers_arrow_title_not_marketing_blob(self) -> None:
        blob = (
            "Own-Every-Moment-at-NetApp At-NetApp,-your-ideas-power-innovation.-We-lead-in-"
            "intelligent-data-infrastructure—delivering-unified-storage. Ready-to-innovate "
            "at NetApp is where your journey begins. "
            'custom_fields.PersonalizationFacet-Americas"> --> Senior Software Engineer'
        )
        title = self.qj.talentbrew_title_from_detail(blob, company_name="NetApp")
        self.assertEqual(title, "Senior Software Engineer")
        self.assertTrue(self.qj.talentbrew_title_looks_plausible(title))
        self.assertFalse(
            self.qj.talentbrew_title_looks_plausible(blob[:822].strip(" -·|:;"))
        )

    def test_netapp_arrow_title_strips_company_suffix(self) -> None:
        text = (
            "Own-Every-Moment-at-NetApp fluff custom_fields.x\"> "
            "--> Senior Software Engineer at NetApp, Inc. Skip to main content Careers"
        )
        self.assertEqual(
            self.qj.talentbrew_title_from_detail(text, company_name="NetApp"),
            "Senior Software Engineer",
        )

    def test_html_location_label_classifies_as_remote_us(self) -> None:
        cfg = {"profile": {"home_zip": "00000", "local_radius_miles": 50}}
        for loc in (
            "<b>Location:</b> United States",
            "Location: United States",
            "<b>Location:</b> United States · Remote",
        ):
            job_loc, label = self.qj.classify_location_with_fallback(loc, "", "", cfg)
            self.assertEqual(job_loc, "remote", msg=repr(loc))
            self.assertNotIn("<", str(label or ""))
            self.assertNotRegex(str(label or ""), r"(?i)^location\s*:")

    def test_netapp_bengaluru_path_beats_us_card_location(self) -> None:
        row = {
            "path": "/job/bengaluru/senior-software-engineer/27600/100288851376",
            "title": "Software Engineer Bengaluru, Karnataka, India",
            "location": (
                "Morrisville, North Carolina, United States; San Jose, California, "
                "United States; Waltham, Massachusetts, United States; , United States"
            ),
        }
        loc = self.qj.talentbrew_resolve_listing_location(row)
        self.assertEqual(loc, "Bengaluru, India")
        self.assertTrue(
            self.qj.url_indicates_bengaluru_india(
                "https://careers.netapp.com/job/bengaluru/senior-software-engineer/27600/1"
            )
        )
        cfg = {"profile": {"home_zip": "00000", "local_radius_miles": 50}}
        job_loc, label = self.qj.classify_location_with_fallback(loc, "", "", cfg)
        self.assertEqual(job_loc, "excluded")
        self.assertIn("Bengaluru", str(label or ""))

    def test_reclassify_excludes_netapp_bengaluru_url_despite_us_label(self) -> None:
        mod = self.qj
        job = mod.Job(
            title="Senior Software Engineer",
            company_id="netapp",
            url="https://careers.netapp.com/job/bengaluru/senior-software-engineer/27600/100288851376",
            loc="remote",
            loc_label="US\nMiami, FL\nSanta Clara, CA\nNew York, NY",
            why="Remote US (auto-discovered).",
            meta=", United States; Miami, Florida, United States · Live posting (Talentbrew)",
        )
        co = mod.CompanyResult(
            id="netapp", name="NetApp", label="NetApp", section="hubs", jobs=[job]
        )
        cfg = {
            "profile": {"home_zip": "00000", "local_radius_miles": 50},
            "companies": [{"id": "netapp", "type": "talentbrew", "name": "NetApp"}],
        }
        n = mod.reclassify_results_locations([co], cfg)
        self.assertGreaterEqual(n, 1)
        self.assertEqual(job.loc, "excluded")
        self.assertEqual(job.loc_label, "Bengaluru, India")

    def test_reconcile_fixes_swapped_snapshot_title(self) -> None:
        mod = self.qj
        job = mod.Job(
            title="Senior Cloud Infrastructure Engineer: Core",
            company_id="jack-henry-associates",
            url=(
                "https://careers.jackhenry.com/job/united-states/"
                "senior-manager-of-software-engineering-observability/42859/99029486928"
            ),
            job_id="99029486928",
            description_text=(
                "Senior Manager of Software Engineering: Observability at Jack Henry & Associates, Inc "
                "Skip to main content"
            ),
            meta="United States · Live posting (Talentbrew)",
        )
        co = mod.CompanyResult(
            id="jack-henry-associates",
            name="Jack Henry & Associates",
            label="Jack Henry",
            section="hubs",
            jobs=[job],
        )
        n = mod.reconcile_talentbrew_job_titles(
            [co],
            [{"id": "jack-henry-associates", "type": "talentbrew", "name": "Jack Henry & Associates"}],
        )
        self.assertEqual(n, 1)
        self.assertEqual(
            co.jobs[0].title,
            "Senior Manager of Software Engineering: Observability",
        )

    def test_reconcile_repairs_netapp_marketing_blob_via_path(self) -> None:
        mod = self.qj
        blob = (
            "Own-Every-Moment-at-NetApp At-NetApp,-your-ideas-power-innovation. "
            "at NetApp join us. "
            'custom_fields.PersonalizationFacet-Americas"> --> Senior Software Engineer'
        )
        job = mod.Job(
            title=blob[:200],
            company_id="netapp",
            url="https://careers.netapp.com/job/san-jose/senior-software-engineer/27600/98404834912",
            description_text=blob,
            meta="San Jose · Live posting (Talentbrew)",
        )
        co = mod.CompanyResult(
            id="netapp",
            name="NetApp",
            label="NetApp",
            section="hubs",
            jobs=[job],
        )
        n = mod.reconcile_talentbrew_job_titles(
            [co],
            [{"id": "netapp", "type": "talentbrew", "name": "NetApp"}],
        )
        self.assertEqual(n, 1)
        self.assertEqual(co.jobs[0].title, "Senior Software Engineer")


if __name__ == "__main__":
    unittest.main()
