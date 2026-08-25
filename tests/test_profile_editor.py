#!/usr/bin/env python3
"""Editable profile fields in Search Parameters panel."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_profile_editor", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ProfileEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")
        cls.cfg = cls.qj.load_config_raw()

    def test_board_profile_fields(self) -> None:
        fields = self.qj.board_profile_fields(self.cfg)
        self.assertIn("devops", fields["skills"])
        self.assertGreaterEqual(fields["salary_floor"], 100000)
        self.assertIn(fields["resident_status"], self.qj.PROFILE_RESIDENT_CHOICES)
        self.assertIn("american-airlines", fields["company_ids_exclude"])

    def test_pipeline_config_embeds_profile_fields(self) -> None:
        out = self.qj._board_pipeline_config(
            self.cfg,
            pipeline_server=False,
            default_runtime_path=Path("/tmp/job-board-runtime.json"),
        )
        self.assertIn("profileFields", out)
        self.assertIn("profileConfigFilePickerId", out)
        self.assertIn("profileConfigPath", out)
        self.assertIn("skills", out["profileFields"])

    def test_search_params_panel_profile_editors(self) -> None:
        panel = self.qj.render_search_parameters_panel(self.cfg)
        self.assertIn('id="profile-salary-floor"', panel)
        self.assertIn('id="profile-resident-status"', panel)
        self.assertIn('data-profile-list="skills"', panel)
        self.assertIn('data-profile-list="company_ids_exclude"', panel)
        self.assertIn("link-profile-config-file", panel)
        self.assertIn("initProfileEditors", self.src)


if __name__ == "__main__":
    unittest.main()
