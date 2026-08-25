#!/usr/bin/env python3
"""Tests for green-card US citizenship required scrape skip helpers."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_h1b_module():
    path = REPO_ROOT / "h1b_employer.py"
    spec = importlib.util.spec_from_file_location("h1b_employer_gc_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class GreenCardCitizenshipRequiredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.h1b = _load_h1b_module()

    def test_citizenship_required_phrases_match(self) -> None:
        mod = self.h1b
        samples = (
            "U.S. citizenship is strictly required for this role.",
            "US citizenship strictly required.",
            "Citizenship is strictly required due to export control access.",
            "Applicants for this position must be U.S. citizens.",
            "Applicants for this position must be US citizens.",
            "Must be a U.S. citizen.",
            "Must be a US citizen.",
            "Must be U.S. citizens.",
            "U.S. citizenship is required.",
            "US citizenship required for government contract work.",
            "U.S. citizens only.",
        )
        for text in samples:
            with self.subTest(text=text[:56]):
                self.assertTrue(mod.posting_text_indicates_us_citizenship_required(text))

    def test_citizenship_required_with_us_context(self) -> None:
        mod = self.h1b
        text = (
            "Due to program access requirements, U.S. citizenship is required "
            "for employment in this position."
        )
        self.assertTrue(mod.posting_text_indicates_us_citizenship_required(text))

    def test_work_authorization_without_citizenship_not_matched(self) -> None:
        mod = self.h1b
        samples = (
            "Must be authorized to work in the United States.",
            "Candidates must be legally authorized to work in the US.",
            "Must be authorized to work for any employer in the United States.",
        )
        for text in samples:
            with self.subTest(text=text[:56]):
                self.assertFalse(mod.posting_text_indicates_us_citizenship_required(text))

    def test_skip_reason_for_citizenship_required(self) -> None:
        mod = self.h1b
        self.assertIsNone(
            mod.green_card_job_skip_reason(
                "Platform Engineer",
                "Build CI/CD pipelines and Kubernetes platforms.",
            )
        )
        reason = mod.green_card_job_skip_reason(
            "Systems Engineer",
            "U.S. citizenship is strictly required.",
        )
        self.assertEqual(reason, "US citizenship required")

    def test_profile_wants_green_card_validation(self) -> None:
        mod = self.h1b
        self.assertTrue(
            mod.profile_wants_green_card_validation({"profile": {"resident_status": "green_card"}})
        )
        self.assertFalse(
            mod.profile_wants_green_card_validation({"profile": {"resident_status": "citizen"}})
        )
        self.assertFalse(
            mod.profile_wants_green_card_validation({"profile": {"resident_status": "h1b"}})
        )

    def test_green_card_profile_default_excludes_citizenship_phrases(self) -> None:
        mod = self.h1b
        cfg = {"profile": {"resident_status": "green_card"}}
        filters = mod.profile_default_text_filters(cfg)
        self.assertGreaterEqual(len(filters), 3)
        self.assertTrue(all(chip["mode"] == "not" for chip in filters))
        texts = {chip["text"] for chip in filters}
        self.assertIn("must be a us citizen", texts)
        self.assertIn("us citizens only", texts)
        scope = mod.profile_default_filter_scope(cfg)
        self.assertTrue(scope["title"])
        self.assertTrue(scope["description"])


if __name__ == "__main__":
    unittest.main()
