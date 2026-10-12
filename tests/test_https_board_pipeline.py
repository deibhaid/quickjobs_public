#!/usr/bin/env python3
"""The published board must not fall back to linking the Mac runtime file."""

from __future__ import annotations

import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "quickjobs.py"


class HttpsBoardPipelineTests(unittest.TestCase):
    def test_https_page_skips_runtime_file_link(self) -> None:
        src = SOURCE.read_text(encoding="utf-8")
        refresh_at = src.find("async function refreshPipelineSaveMode() {{")
        init_at = src.find("async function initPipelinePersistence() {{")
        self.assertGreaterEqual(refresh_at, 0)
        self.assertGreaterEqual(init_at, 0)

        refresh = src[refresh_at:refresh_at + 500]
        refresh_head = refresh.split("readPipelineConfig", 1)[0]
        self.assertIn("if (location.protocol === 'https:') {{", refresh_head)
        self.assertIn("return;", refresh_head)

        init = src[init_at:init_at + 1600]
        https_at = init.find("if (location.protocol === 'https:') {{")
        handle_at = init.find("loadSavedRuntimeHandle")
        self.assertGreaterEqual(https_at, 0)
        self.assertGreater(handle_at, https_at)
        self.assertIn("await refreshNasPipeline();", init)
        self.assertIn("await persistNasPipelineRow", src)

        profile = src[src.find("function initProfileEditors() {{"):]
        profile = profile[: profile.find("function scheduleSearchKeywordPersist")]
        self.assertIn("linkProfileConfigFileBtn.hidden = true;", profile)
        self.assertLess(
            profile.find("if (location.protocol === 'https:') return;"),
            profile.find("loadSavedProfileConfigHandle"),
        )
        keywords = src[src.find("function initSearchKeywordEditors() {{"):]
        keywords = keywords[:800]
        self.assertIn("linkBaseConfigFileBtn.hidden = true;", keywords)
        self.assertLess(
            keywords.find("if (location.protocol === 'https:') return;"),
            keywords.find("loadSavedBaseConfigHandle"),
        )


if __name__ == "__main__":
    unittest.main()
