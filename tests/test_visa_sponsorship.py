#!/usr/bin/env python3
"""Tests for visa sponsorship scrape skip and board filter helpers."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_h1b_module():
    path = REPO_ROOT / "h1b_employer.py"
    spec = importlib.util.spec_from_file_location("h1b_employer_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class VisaSponsorshipNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.h1b = _load_h1b_module()

    def test_negative_phrases_trigger_no_sponsorship(self) -> None:
        mod = self.h1b
        samples = (
            "We are unable to sponsor or take over sponsorship for this role.",
            "Candidates must be authorized to work for any employer without sponsorship.",
            "Not eligible for immigration sponsorship.",
            "This position offers no visa sponsorship.",
            "This role does not offer visa sponsorship.",
            "We will not sponsor work visas.",
            "We cannot sponsor at this time.",
            "We are not able to sponsor candidates.",
            "Must have work authorization without sponsorship.",
            "US citizens only.",
        )
        for text in samples:
            with self.subTest(text=text[:48]):
                self.assertTrue(mod.posting_text_indicates_no_visa_sponsorship(text))

    def test_ambiguous_authorized_any_employer_without_denial(self) -> None:
        mod = self.h1b
        text = "Must be authorized to work for any employer in the United States."
        self.assertFalse(mod.posting_text_indicates_no_visa_sponsorship(text))

    def test_skip_reason_only_for_explicit_denial(self) -> None:
        mod = self.h1b
        no_meta: dict = {}
        self.assertIsNone(
            mod.h1b_job_skip_reason(
                "Platform Engineer",
                "Join our infrastructure team.",
                no_meta,
            )
        )
        self.assertIsNone(
            mod.h1b_job_skip_reason(
                "Platform Engineer",
                "Great benefits and remote work.",
                {"filer": False, "index_loaded": False},
            )
        )
        reason = mod.h1b_job_skip_reason(
            "Platform Engineer",
            "We cannot sponsor work visas for this role.",
            {"filer": True, "index_loaded": True},
        )
        self.assertEqual(reason, "posting explicitly denies visa sponsorship")

    def test_missing_filer_and_missing_positive_jd_not_skipped(self) -> None:
        mod = self.h1b
        self.assertIsNone(
            mod.h1b_job_skip_reason(
                "DevOps Engineer",
                "Build CI/CD pipelines and Kubernetes platforms.",
                {"filer": False, "index_loaded": True},
            )
        )


class VisaSponsorshipPositiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.h1b = _load_h1b_module()

    def test_positive_phrases_for_board_filter(self) -> None:
        mod = self.h1b
        samples = (
            "Visa sponsorship is available for qualified candidates.",
            "We are able to offer visa transfer for qualified candidates.",
            "We offer visa transfer for the right candidate.",
            "We sponsor employment visas and are proud to sponsor talent.",
            "We are willing to facilitate visa transfers.",
            "Visa sponsorship or transfer is available.",
            "H-1B visa sponsorship available.",
        )
        for text in samples:
            with self.subTest(text=text[:48]):
                self.assertTrue(mod.job_has_visa_sponsor_jd_signal("Engineer", text))

    def test_negative_wording_blocks_positive_match(self) -> None:
        mod = self.h1b
        text = "Visa sponsorship is available but we cannot sponsor new applicants."
        self.assertFalse(mod.job_has_visa_sponsor_jd_signal("Engineer", text))

    def test_board_filter_ignores_dol_filer_without_jd_wording(self) -> None:
        mod = self.h1b
        self.assertFalse(
            mod.job_has_visa_sponsor_jd_signal(
                "DevOps Engineer",
                "Standard platform responsibilities.",
            )
        )

    def test_board_signal_from_dol_filer_without_jd_wording(self) -> None:
        mod = self.h1b
        self.assertTrue(
            mod.job_has_visa_sponsor_board_signal(
                "DevOps Engineer",
                "Standard platform responsibilities.",
                {"filer": True},
            )
        )
        self.assertFalse(
            mod.job_has_visa_sponsor_board_signal(
                "DevOps Engineer",
                "Standard platform responsibilities.",
                {"filer": False},
            )
        )


class CompanyBadgeLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.h1b = _load_h1b_module()

    def test_dol_filer_badge_label_uses_visa_wording(self) -> None:
        mod = self.h1b
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            meta = mod.lookup_company_h1b_meta(
                "test-co",
                "Unknown Employer XYZ",
                cache_root=Path(tmp),
            )
        self.assertEqual(meta["label"], "No DOL visa filings")
        badge = mod.h1b_company_badge_html("F", meta["label"])
        self.assertIn("No DOL visa filings", badge)
        self.assertNotIn("H-1B", badge)

    def test_badge_fallback_label_is_visa(self) -> None:
        mod = self.h1b
        badge = mod.h1b_company_badge_html("C", "")
        self.assertIn("Visa", badge)
        self.assertNotIn("H-1B", badge)


class ProfileDefaultTextFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.h1b = _load_h1b_module()

    @staticmethod
    def _job_hidden_by_h1b_default_filters(title: str, description: str, chips: list[dict]) -> bool:
        """Mirror board chip 'not' logic on title + description only."""
        fields = [title, description]
        for chip in chips:
            if chip.get("mode") != "not":
                continue
            term = str(chip.get("text") or "").lower()
            if not term:
                continue
            if any(term in str(field or "").lower() for field in fields):
                return True
        return False

    def test_h1b_board_exclude_terms_match_no_sponsorship_wording(self) -> None:
        mod = self.h1b
        terms = mod.H1B_BOARD_FILTER_EXCLUDE_TERMS
        samples = (
            "This role does not offer visa sponsorship.",
            "We are unable to sponsor or take over sponsorship for this role.",
            "Candidates must be authorized to work for any employer without sponsorship.",
            "Not eligible for immigration sponsorship.",
            "We will not sponsor work visas.",
            "We cannot sponsor at this time.",
            "Must have work authorization without sponsorship.",
            "US citizens only.",
        )
        for text in samples:
            with self.subTest(text=text[:48]):
                matched = any(term in text.lower() for term in terms)
                self.assertTrue(matched, msg=text)

    def test_h1b_board_exclude_terms_avoid_overbroad_terms(self) -> None:
        mod = self.h1b
        terms = set(mod.H1B_BOARD_FILTER_EXCLUDE_TERMS)
        self.assertNotIn("visa", terms)
        self.assertNotIn("sponsorship", terms)
        self.assertNotIn("work authorization", terms)

    def test_h1b_profile_gets_no_sponsorship_exclude_chips(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "h1b"}}
        chips = mod.profile_default_text_filters(cfg)
        self.assertGreaterEqual(len(chips), 10)
        self.assertTrue(all(chip["mode"] == "not" for chip in chips))
        texts = {chip["text"] for chip in chips}
        self.assertIn("does not offer visa sponsorship", texts)
        self.assertIn("no visa sponsorship", texts)
        self.assertIn("unable to sponsor", texts)
        self.assertIn("will not sponsor", texts)
        self.assertIn("cannot sponsor", texts)
        self.assertIn("without sponsorship", texts)
        self.assertIn("not eligible for sponsorship", texts)
        scope = mod.profile_default_filter_scope(cfg)
        self.assertTrue(scope["title"])
        self.assertTrue(scope["description"])

    def test_h1b_default_filters_hide_explicit_no_sponsorship_posting(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "h1b"}}
        chips = mod.profile_default_text_filters(cfg)
        hidden = self._job_hidden_by_h1b_default_filters(
            "Platform Engineer",
            "This role does not offer visa sponsorship.",
            chips,
        )
        self.assertTrue(hidden)

    def test_h1b_default_filters_keep_neutral_posting_visible(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "h1b"}}
        chips = mod.profile_default_text_filters(cfg)
        hidden = self._job_hidden_by_h1b_default_filters(
            "Platform Engineer",
            "Build CI/CD pipelines and Kubernetes platforms.",
            chips,
        )
        self.assertFalse(hidden)

    def test_green_card_profile_gets_citizenship_exclude_chips(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "green_card"}}
        chips = mod.profile_default_text_filters(cfg)
        self.assertGreaterEqual(len(chips), 4)
        self.assertTrue(all(chip["mode"] == "not" for chip in chips))
        texts = {chip["text"] for chip in chips}
        self.assertIn("citizenship is strictly required", texts)
        self.assertIn("us citizens only", texts)
        scope = mod.profile_default_filter_scope(cfg)
        self.assertTrue(scope["title"])
        self.assertTrue(scope["description"])

    def test_citizen_profile_has_no_default_filters(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "citizen"}}
        self.assertEqual(mod.profile_default_text_filters(cfg), [])


class ProfileDefaultCompanyExcludeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.h1b = _load_h1b_module()

    def _reset_h1b_caches(self) -> None:
        mod = self.h1b
        mod._EMPLOYER_INDEX = None
        mod._COMPANY_LOOKUP_CACHE = {}

    def _write_test_index(self, cache_root: Path, employers: dict[str, dict]) -> None:
        mod = self.h1b
        self._reset_h1b_caches()
        cache_root.mkdir(parents=True, exist_ok=True)
        path = mod.employer_index_path(cache_root)
        path.write_text(
            json.dumps({"employers": employers}, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_h1b_profile_gets_non_sponsor_company_excludes(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "h1b"}}
        excludes = mod.profile_default_company_ids_exclude(cfg)
        self.assertIn("chainguard", excludes)
        self.assertIn("airship", excludes)
        self.assertIn("cayuse-holdings-llc", excludes)
        self.assertIn("defense-unicorns", excludes)
        self.assertIn("tria-federal", excludes)

    def test_citizen_profile_has_no_default_company_excludes(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "citizen"}}
        self.assertEqual(mod.profile_default_company_ids_exclude(cfg), [])

    def test_green_card_profile_has_no_default_company_excludes(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "green_card"}}
        self.assertEqual(mod.profile_default_company_ids_exclude(cfg), [])

    def test_h1b_index_present_excludes_non_filer_companies(self) -> None:
        import tempfile

        mod = self.h1b
        cfg = {"profile": {"resident_status": "h1b"}}
        companies = [
            {"id": "acme-corp", "name": "Acme Corp"},
            {"id": "unknown-co", "name": "Unknown Employer XYZ"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            self._write_test_index(
                cache_root,
                {
                    "acme corp": {
                        "display_name": "Acme Corp",
                        "lca_certified": 12,
                        "lca_denied": 0,
                        "grade": "B",
                        "confidence": "high",
                    }
                },
            )
            excludes = mod.profile_default_company_ids_exclude(cfg, companies, cache_root)
        self.assertIn("unknown-co", excludes)
        self.assertNotIn("acme-corp", excludes)
        self.assertIn("chainguard", excludes)

    def test_h1b_index_missing_keeps_static_excludes_only(self) -> None:
        import tempfile

        mod = self.h1b
        cfg = {"profile": {"resident_status": "h1b"}}
        companies = [
            {"id": "acme-corp", "name": "Acme Corp"},
            {"id": "unknown-co", "name": "Unknown Employer XYZ"},
        ]
        warnings: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            self._reset_h1b_caches()
            excludes = mod.profile_default_company_ids_exclude(
                cfg,
                companies,
                cache_root,
                warn=warnings.append,
            )
        self.assertIn("chainguard", excludes)
        self.assertNotIn("unknown-co", excludes)
        self.assertNotIn("acme-corp", excludes)
        self.assertEqual(len(warnings), 1)
        self.assertIn("DOL employer index not built", warnings[0])

    def test_filer_company_not_excluded_by_dol_gate(self) -> None:
        import tempfile

        mod = self.h1b
        companies = [{"id": "visa-filer-co", "name": "Visa Filer Inc"}]
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            self._write_test_index(
                cache_root,
                {
                    "visa filer": {
                        "display_name": "Visa Filer Inc",
                        "lca_certified": 25,
                        "lca_denied": 1,
                        "grade": "B",
                        "confidence": "high",
                    }
                },
            )
            excludes = mod.company_ids_exclude_no_dol_visa_filers(companies, cache_root)
        self.assertEqual(excludes, [])

    def test_scrape_source_merges_profile_default_company_excludes(self) -> None:
        src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")
        self.assertIn("profile_default_company_ids_exclude", src)
        self.assertIn("h1b_cache_root()", src)


    def test_board_source_wires_profile_text_filter_presets(self) -> None:
        src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")
        self.assertNotIn('data-legend-filter="visa-sponsor"', src)
        self.assertNotIn("LEGEND_VISA_KEYS", src)
        self.assertNotIn("visa_legend_filter_button", src)
        self.assertIn("defaultTextFilters", src)
        self.assertIn("applyProfileDefaultTextFilters", src)
        self.assertIn("_h1b_employer.profile_default_text_filters", src)
        self.assertIn("chipSearchTerms", src)


if __name__ == "__main__":
    unittest.main()
