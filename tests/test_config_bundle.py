#!/usr/bin/env python3
"""Tests for split base + companies config loading."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = REPO_ROOT / "scripts" / "_shared"
sys.path.insert(0, str(SHARED_DIR))
import config_bundle  # noqa: E402


class ConfigBundleTests(unittest.TestCase):
    def test_dev_paths_and_round_trip(self) -> None:
        base_path = REPO_ROOT / "quickjobs.david.base.json"
        companies_path = config_bundle.companies_path_for_base(base_path)
        self.assertEqual(companies_path.name, "quickjobs.david.companies.json")
        merged = config_bundle.load_base_bundle(base_path)
        self.assertGreaterEqual(len(merged.get("companies") or []), 1000)
        self.assertIn("keywords_include_tier1", merged)
        base_only = json.loads(base_path.read_text(encoding="utf-8"))
        self.assertNotIn("companies", base_only)

    def test_save_writes_split_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_path = root / "quickjobs.david.base.json"
            base_path.write_text(
                json.dumps(
                    {
                        "keywords_include_tier1": ["devops"],
                        "keywords_include_tier2": ["engineer"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            merged = {
                "keywords_include_tier1": ["devops"],
                "keywords_include_tier2": ["engineer"],
                "companies": [{"id": "acme", "name": "Acme", "type": "greenhouse", "board": "acme"}],
            }
            config_bundle.save_base_bundle(base_path, merged)
            co_path = config_bundle.companies_path_for_base(base_path)
            self.assertTrue(co_path.is_file())
            reloaded = config_bundle.load_base_bundle(base_path)
            self.assertEqual(reloaded["companies"][0]["id"], "acme")
            self.assertNotIn("companies", json.loads(base_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
