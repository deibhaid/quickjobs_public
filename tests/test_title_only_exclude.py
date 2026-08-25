#!/usr/bin/env python3
"""Board-wide: keywords_exclude must not drop roles for JD collaborator mentions."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_title_only_ex", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TitleOnlyExcludeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()
        cls.cfg = {
            "keywords_include_tier1": ["architect", "engineer"],
            "keywords_include_tier2": ["solutions architect", "cloud engineer"],
            "keywords_exclude": ["data scientist", "presales", "ads"],
        }

    def test_posting_matches_despite_data_scientist_in_jd(self) -> None:
        title = "Specialist Solutions Architect - GenAI"
        desc = "You will interact with other Data Scientists and Solution Architects."
        self.assertTrue(
            self.qj.posting_matches_title_filters(title, desc, self.cfg)
        )
        self.assertIsNone(
            self.qj.posting_filter_fail_reason(title, desc, self.cfg)
        )

    def test_title_data_scientist_still_excluded(self) -> None:
        title = "Senior Data Scientist"
        desc = "Build ML models."
        self.assertFalse(
            self.qj.posting_matches_title_filters(title, desc, self.cfg)
        )
        self.assertIsNotNone(
            self.qj.posting_filter_fail_reason(title, desc, self.cfg)
        )

    def test_jd_blocks_defaults_to_title_only(self) -> None:
        title = "Cloud Engineer"
        desc = "Partner with data scientists on platforms."
        self.assertIsNone(
            self.qj.jd_blocks_job(
                desc,
                title,
                self.cfg,
                self.cfg["keywords_exclude"],
            )
        )
        self.assertIsNone(
            self.qj.jd_blocks_job(
                desc,
                title,
                self.cfg,
                self.cfg["keywords_exclude"],
                keyword_exclude_title_only=True,
            )
        )
        # Explicit full-description mode still catches collaborator mentions.
        self.assertIsNotNone(
            self.qj.jd_blocks_job(
                desc,
                title,
                self.cfg,
                self.cfg["keywords_exclude"],
                keyword_exclude_title_only=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
