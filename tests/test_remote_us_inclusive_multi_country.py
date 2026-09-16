#!/usr/bin/env python3
"""Remote US legend is inclusive of US+Canada (and similar) multi-country remote."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("qj_remote_us_inclusive", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class RemoteUsInclusiveMultiCountryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()
        cls.cfg = {"profile": {"home_zip": "00000", "local_radius_miles": 50}}

    def test_canada_united_states_remote_is_remote_us(self) -> None:
        mod = self.qj
        job = mod.Job(
            title="Staff Software Engineer, Infrastructure",
            company_id="docker",
            url="https://jobs.ashbyhq.com/docker/9bbe3ad7-f4be-4efa-8889-b93e9d62c1ed",
            loc="remote",
            match="strong",
            salary="maybe",
            loc_label="CAN\nUS",
            meta="Canada, United States, Remote · FullTime · Posted 06/08/2026",
        )
        self.assertTrue(mod.location_is_multi_country_us_eligible("Canada, United States, Remote"))
        self.assertTrue(mod.location_is_multi_country_us_eligible("CAN\nUS"))
        self.assertTrue(mod.location_is_multi_country_us_eligible("CA\nUS"))
        self.assertTrue(mod._label_is_abbreviated_canada_us_remote("CAN\nUS"))
        self.assertTrue(mod._label_is_abbreviated_canada_us_remote("CA\nUS"))
        self.assertTrue(mod.job_is_nationwide_us_remote(job, self.cfg))

    def test_canada_abbreviates_as_can_not_ca(self) -> None:
        mod = self.qj
        self.assertEqual(mod.abbreviate_location_label("Canada"), "CAN")
        self.assertEqual(mod.abbreviate_location_label("United States / Canada"), "US\nCAN")
        self.assertEqual(mod.abbreviate_location_label("United States, Canada"), "US\nCAN")
        # Legacy CA+US country badges rewrite to CAN (not California).
        self.assertEqual(mod.stacked_location_lines("CA\nUS"), ["CAN", "US"])
        # California state code stays CA when paired with a US city.
        self.assertEqual(
            mod.abbreviate_location_label("San Francisco, CA, United States"),
            "San Francisco, CA",
        )

    def test_canada_only_remote_still_not_remote_us(self) -> None:
        mod = self.qj
        job = mod.Job(
            title="Engineer",
            company_id="x",
            url="https://example.com/1",
            loc="remote",
            loc_label="Canada - Remote",
        )
        self.assertFalse(mod.job_is_nationwide_us_remote(job, self.cfg))

    def test_state_locked_remote_still_not_remote_us(self) -> None:
        mod = self.qj
        job = mod.Job(
            title="Engineer",
            company_id="x",
            url="https://example.com/2",
            loc="excluded",
            loc_label="Pennsylvania-Remote, United States",
            meta="Pennsylvania-Remote, United States",
        )
        self.assertFalse(mod.job_is_nationwide_us_remote(job, self.cfg))

    def test_gitlab_canada_us_sanitize_keeps_remote_us(self) -> None:
        mod = self.qj
        raw = "Remote, Canada; Remote, US"
        self.assertEqual(
            mod.strip_geo_or_remote_hybrid_location(raw),
            "CAN; US",
        )
        self.assertEqual(mod.sanitize_loc_label_for_badge(raw), "CAN\nUS")
        self.assertFalse(mod.location_text_is_remote_us_nationwide(raw))
        loc, label = mod.classify_location_with_fallback(
            raw, "us", cfg=self.cfg, title="Site Reliability Engineer (AMER)"
        )
        self.assertEqual(loc, "remote")
        job = mod.Job(
            title="Site Reliability Engineer (AMER)",
            company_id="gitlab",
            url="https://job-boards.greenhouse.io/gitlab/jobs/8623389002",
            loc=loc or "remote",
            loc_label=mod.sanitize_loc_label_for_badge(raw),
            meta=raw,
        )
        self.assertTrue(mod.job_is_nationwide_us_remote(job, self.cfg))

    def test_gitlab_apac_emea_us_sanitize_keeps_remote_us(self) -> None:
        mod = self.qj
        raw = "Remote, APAC; Remote, EMEA; Remote, US"
        self.assertTrue(mod.location_is_multi_remote_locale_with_us(raw))
        self.assertFalse(mod.location_text_is_remote_us_nationwide(raw))
        self.assertEqual(
            mod.strip_geo_or_remote_hybrid_location(raw),
            "APAC; EMEA; US",
        )
        self.assertEqual(mod.sanitize_loc_label_for_badge(raw), "APAC\nEMEA\nUS")
        loc, _ = mod.classify_location_with_fallback(
            raw,
            "us",
            cfg=self.cfg,
            title="Staff Infrastructure Security Engineer (APAC, EMEA, or US)",
        )
        self.assertEqual(loc, "remote")
        job = mod.Job(
            title="Staff Infrastructure Security Engineer (APAC, EMEA, or US)",
            company_id="gitlab",
            url="https://job-boards.greenhouse.io/gitlab/jobs/8514960002",
            loc="remote",
            loc_label="APAC\nEMEA\nUS",
            meta=raw,
        )
        self.assertTrue(mod.job_is_nationwide_us_remote(job, self.cfg))

    def test_canada_only_location_not_upgraded_from_jd_or_amer_title(self) -> None:
        mod = self.qj
        jd = "Open to candidates based in the United States and Canada."
        for raw in ("Canada", "Canada - Remote", "Remote, Canada"):
            loc, label = mod.classify_location_with_fallback(
                raw,
                "us",
                cfg=self.cfg,
                title="Staff Software Engineer (AMER)",
                description_text=jd,
            )
            self.assertEqual(loc, "excluded", raw)
            self.assertNotIn("US", (label or "").upper())
            self.assertFalse(
                "US" in mod.sanitize_loc_label_for_badge(raw, description_text=jd)
            )

    def test_cohere_canada_united_states_location_is_remote_us(self) -> None:
        mod = self.qj
        raw = "Canada; United States"
        loc, label = mod.classify_location_with_fallback(
            raw,
            "us",
            cfg=self.cfg,
            title="Senior Software Engineer, GPU Infrastructure (HPC)",
        )
        self.assertEqual(loc, "remote")
        self.assertTrue(mod.location_is_multi_country_us_eligible(label or raw))

    def test_reclassify_prefers_canada_only_meta_over_can_us_badge(self) -> None:
        mod = self.qj
        job = mod.Job(
            title="Staff Software Engineer",
            company_id="babylist",
            url="https://job-boards.greenhouse.io/babylist/jobs/1",
            loc="remote",
            loc_label="CAN\nUS",
            meta="Canada · FullTime · Posted 09/03/2026",
            description_text="Open to candidates based in the United States and Canada.",
        )
        src = mod._job_primary_location_text(job)
        self.assertEqual(src, "Canada")
        loc, _ = mod.classify_location_with_fallback(
            src,
            "us",
            cfg=self.cfg,
            title=job.title,
            description_text=job.description_text,
        )
        self.assertEqual(loc, "excluded")

    def test_source_us_country_slots_classify_alike(self) -> None:
        """Greenhouse/Lever/Ashby/Workday/Eightfold country-wide US strings → Remote US."""
        mod = self.qj
        remote_us = (
            ("United States", "greenhouse"),
            ("USA", "greenhouse"),
            ("US", "flexjet"),
            ("United States of America", "workday"),
            ("Virtual US", "workday"),
            ("Virtual, US", "workday"),
            ("United States and Canada", "ashby"),
            ("Canada and United States", "ashby"),
            ("US and Canada", "ashby"),
            ("Continental United States", "greenhouse"),
            ("US - Various", "greenhouse"),
        )
        for raw, source in remote_us:
            loc, _ = mod.classify_location_with_fallback(
                raw, "us", cfg=self.cfg, title="Staff Software Engineer"
            )
            self.assertEqual(loc, "remote", f"{source}: {raw}")
            job = mod.Job(
                title="Staff Software Engineer",
                company_id=source,
                url=f"https://example.com/{source}",
                loc="remote",
                loc_label=raw,
                meta=f"{raw} · Posted 09/03/2026",
            )
            self.assertTrue(
                mod.job_is_nationwide_us_remote(job, self.cfg),
                f"{source}: {raw}",
            )
        stay_excluded = (
            ("Canada", "greenhouse"),
            ("Northeast - United States", "databricks"),
            ("US-Tx-Houston", "icims"),
            ("USA.VA.Reston", "workday"),
            (
                "Ashburn, Virginia, United States; Washington, District of Columbia, United States",
                "roblox",
            ),
            ("San Mateo, CA, United States", "roblox"),
        )
        for raw, source in stay_excluded:
            loc, _ = mod.classify_location_with_fallback(
                raw, "us", cfg=self.cfg, title="Staff Software Engineer"
            )
            self.assertEqual(loc, "excluded", f"{source}: {raw}")

    def test_bare_united_states_location_is_remote_us(self) -> None:
        mod = self.qj
        for raw in ("United States", "US", "USA", "United States of America"):
            loc, label = mod.classify_location_with_fallback(
                raw, "us", cfg=self.cfg, title="Staff Software Engineer"
            )
            self.assertEqual(loc, "remote", raw)
            self.assertEqual(label, raw)
        job = mod.Job(
            title="Staff Software Engineer",
            company_id="babylist",
            url="https://job-boards.greenhouse.io/babylist/jobs/2",
            loc="remote",
            loc_label="United States",
            meta="United States · Posted 09/03/2026",
        )
        self.assertTrue(mod.job_is_nationwide_us_remote(job, self.cfg))
        # Canada-only twin stays excluded.
        loc_ca, _ = mod.classify_location_with_fallback(
            "Canada", "us", cfg=self.cfg, title="Staff Software Engineer"
        )
        self.assertEqual(loc_ca, "excluded")

    def test_office_only_us_elsewhere_stays_excluded(self) -> None:
        """Anduril / Postman / Waymo / Roblox / HP-style offices are not Remote US."""
        office_only = (
            "Costa Mesa, California, United States",
            "San Francisco, California, United States",
            "Mountain View, CA, USA",
            "San Mateo, CA, United States",
            "Ashburn, Virginia, United States; Washington, District of Columbia, United States",
            "McLean, Virginia, United States",
            "Office - Chicago; Office - NYC",
            "Houston, Texas, United States",
            "Fridley, Minnesota, United States",
        )
        for raw in office_only:
            loc, _ = self.qj.classify_location_with_fallback(
                raw, "us", cfg=self.cfg, title="Staff Software Engineer"
            )
            self.assertEqual(loc, "excluded", raw)

    def test_axon_united_states_is_remote_us_offices_are_not(self) -> None:
        loc, _ = self.qj.classify_location_with_fallback(
            "United States",
            "us",
            cfg=self.cfg,
            title="Principal Systems Architect, Communications Hardware (Remote Eligible | Relocation Assistance Available)",
        )
        self.assertEqual(loc, "remote")
        job = self.qj.Job(
            title="Principal Systems Architect, Communications Hardware (Remote Eligible | Relocation Assistance Available)",
            company_id="axon-enterprise",
            url="https://job-boards.greenhouse.io/axon/jobs/1",
            loc="remote",
            loc_label="United States",
            meta="United States",
        )
        self.assertTrue(self.qj.job_is_nationwide_us_remote(job, self.cfg))
        loc_city, _ = self.qj.classify_location_with_fallback(
            "Scottsdale, Arizona, United States",
            "us",
            cfg=self.cfg,
            title="Principal Systems Architect, Communications Hardware (Remote Eligible | Relocation Assistance Available)",
        )
        self.assertEqual(loc_city, "excluded")

    def test_gm_offices_plus_wfh_united_states_is_remote_us(self) -> None:
        raw = (
            "Milford, Michigan, United States of America; "
            "Work From Home - United States; "
            "Austin, Texas, United States of America; "
            "Mountain View, California, United States of America; "
            "Warren, Michigan, United States of America"
        )
        self.assertTrue(self.qj.location_is_geo_plus_us_nationwide_remote(raw))
        loc, _ = self.qj.classify_location_with_fallback(
            raw, "us", cfg=self.cfg, title="Senior Software Engineer"
        )
        self.assertEqual(loc, "remote")
        job = self.qj.Job(
            title="Senior Software Engineer",
            company_id="gm",
            url="https://example.com/gm/1",
            loc="remote",
            loc_label=raw,
            meta=raw,
        )
        self.assertTrue(self.qj.job_is_nationwide_us_remote(job, self.cfg))
        loc_offices, _ = self.qj.classify_location_with_fallback(
            "Milford, Michigan, United States of America; Austin, Texas, United States of America",
            "us",
            cfg=self.cfg,
            title="Senior Software Engineer",
        )
        self.assertEqual(loc_offices, "excluded")

    def test_drivewealth_amer_us_remote_plus_offices_is_remote_us(self) -> None:
        raw = (
            "AMER-US-Remote; Austin, Texas, United States; Dallas, Texas, United States; "
            "Denver, Colorado, United States; Miami, Florida, United States; "
            "Office - Chicago; Office - NYC; San Francisco, California, United States; "
            "Seattle, Washington, United States"
        )
        self.assertTrue(self.qj.location_is_geo_plus_us_nationwide_remote(raw))
        loc, _ = self.qj.classify_location_with_fallback(
            raw, "us", cfg=self.cfg, title="Staff Software Engineer"
        )
        self.assertEqual(loc, "remote")

    def test_exiger_united_states_remote_segment_is_remote_us(self) -> None:
        raw = (
            "Jersey City, New Jersey, United States; McLean, Virginia, United States; "
            "Richmond, Virginia, United States; United States (Remote)"
        )
        self.assertTrue(self.qj.location_is_geo_plus_us_nationwide_remote(raw))
        loc, _ = self.qj.classify_location_with_fallback(
            raw, "us", cfg=self.cfg, title="Staff Software Engineer"
        )
        self.assertEqual(loc, "remote")

    def test_recover_truncated_apac_remote_from_title_paren(self) -> None:
        mod = self.qj
        loc, label = mod.classify_location_with_fallback(
            "Remote, APAC",
            "us",
            cfg=self.cfg,
            title="Staff Infrastructure Security Engineer (APAC, EMEA, or US)",
        )
        self.assertEqual(loc, "remote")
        self.assertTrue(mod.location_is_multi_remote_locale_with_us(label or ""))


if __name__ == "__main__":
    unittest.main()
