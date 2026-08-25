#!/usr/bin/env python3
"""Editable search keyword lists in Search Parameters panel."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_search_kw", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class SearchKeywordEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.src = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")

    def test_board_keyword_lists_from_cfg(self) -> None:
        qj = self.qj
        cfg = {
            "keywords_include_tier1": ["Engineer", "devops"],
            "keywords_include_tier2": ["platform engineer"],
            "search_keywords_extra": ["distinguished engineer"],
            "keywords_exclude": ["presales"],
        }
        lists = qj.board_keyword_lists(cfg)
        self.assertEqual(lists["keywords_include_tier1"], ["Engineer", "devops"])
        self.assertEqual(lists["search_keywords_extra"], ["distinguished engineer"])

    def test_pipeline_config_embeds_keyword_lists(self) -> None:
        qj = self.qj
        cfg = {
            "keywords_include_tier1": ["engineer"],
            "keywords_include_tier2": ["devops engineer"],
            "search_keywords_extra": ["staff engineer"],
            "keywords_exclude": ["ads"],
            "profile": {"resident_status": "citizen"},
        }
        out = qj._board_pipeline_config(
            cfg,
            pipeline_server=False,
            default_runtime_path=Path("/tmp/job-board-runtime.json"),
        )
        self.assertIn("keywordLists", out)
        self.assertEqual(out["keywordLists"]["keywords_include_tier1"], ["engineer"])
        self.assertIn("baseConfigFilePickerId", out)

    def test_search_params_panel_has_editable_sections(self) -> None:
        qj = self.qj
        cfg = json.loads((REPO_ROOT / "quickjobs.base.json").read_text(encoding="utf-8"))
        cfg.setdefault("profile", {"name": "Test", "home_zip": "00000", "resident_status": "citizen"})
        panel = qj.render_search_parameters_panel(cfg)
        for key in qj.SEARCH_KEYWORD_LIST_KEYS:
            self.assertIn(f'data-search-keyword-list="{key}"', panel)
        self.assertIn("search_keywords_extra", panel)
        self.assertIn("link-base-config-file", panel)
        self.assertIn("link-profile-config-file", panel)
        self.assertIn("initSearchKeywordEditors", self.src)
        self.assertIn("initProfileEditors", self.src)


if __name__ == "__main__":
    unittest.main()
