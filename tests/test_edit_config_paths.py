#!/usr/bin/env python3
"""Config file paths shown for linking are Mac edit paths when HTML is built on remote."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qj():
    path = REPO_ROOT / "quickjobs.py"
    spec = importlib.util.spec_from_file_location("quickjobs_mod_edit_paths", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class EditConfigPathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()

    def test_wulf_script_dir_maps_to_mac_edit_root(self) -> None:
        qj = self.qj
        with mock.patch.object(qj, "SCRIPT_DIR", Path("/home/user/ws/github/quickjobs")):
            root = qj.edit_config_root_for_board()
        self.assertEqual(root, Path("/path/to/quickjobs"))

    def test_display_paths_on_wulf_use_mac(self) -> None:
        qj = self.qj
        with mock.patch.object(qj, "SCRIPT_DIR", Path("/home/user/ws/github/quickjobs")):
            paths = dict(qj.resolve_config_display_paths())
        self.assertEqual(
            paths["Base config"],
            "/path/to/quickjobs/quickjobs.base.json",
        )
        self.assertEqual(
            paths["Companies"],
            "/path/to/quickjobs/quickjobs.companies.json",
        )
        self.assertEqual(
            paths["Profile"],
            "/path/to/quickjobs/quickjobs.profile.json",
        )

    def test_env_override(self) -> None:
        qj = self.qj
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {"QUICKJOBS_EDIT_CONFIG_ROOT": str(root)}):
                self.assertEqual(qj.edit_config_root_for_board(), root)

    def test_pipeline_config_embeds_edit_root(self) -> None:
        qj = self.qj
        cfg = qj.load_config_base()
        cfg.setdefault("profile", {"resident_status": "citizen", "name": "T", "jobs_dir": "~/x"})
        with mock.patch.object(qj, "SCRIPT_DIR", Path("/home/user/ws/github/quickjobs")):
            out = qj._board_pipeline_config(
                cfg,
                pipeline_server=False,
                default_runtime_path=Path("/tmp/job-board-runtime.json"),
            )
        self.assertEqual(out["editConfigRoot"], "/path/to/quickjobs")
        self.assertTrue(out["baseConfigPath"].startswith("/Users/example/"))
        self.assertTrue(out["profileConfigPath"].startswith("/Users/example/"))
        self.assertEqual(out["editConfigFilePickerId"], "quickjobs-quickjobs-runtime")
        self.assertEqual(out["editConfigFilePickerId"], out["runtimeFilePickerId"])

    def test_ensure_picker_symlinks(self) -> None:
        qj = self.qj
        with tempfile.TemporaryDirectory() as tmp:
            edit_root = Path(tmp) / "repo"
            picker_dir = Path(tmp) / "jobs"
            edit_root.mkdir()
            picker_dir.mkdir()
            for name in (
                "quickjobs.base.json",
                "quickjobs.companies.json",
                "quickjobs.profile.json",
            ):
                (edit_root / name).write_text("{}\n", encoding="utf-8")
            linked = qj.ensure_edit_config_picker_symlinks(
                edit_root=edit_root,
                picker_dir=picker_dir,
            )
            self.assertEqual(len(linked), 3)
            for link in linked:
                self.assertTrue(link.is_symlink())
                self.assertTrue(link.resolve().is_file())
            # Idempotent
            linked2 = qj.ensure_edit_config_picker_symlinks(
                edit_root=edit_root,
                picker_dir=picker_dir,
            )
            self.assertEqual(len(linked2), 3)

    def test_ensure_picker_symlinks_jobs_dir_only(self) -> None:
        qj = self.qj
        with tempfile.TemporaryDirectory() as tmp:
            edit_root = Path(tmp) / "repo"
            jobs_dir = Path(tmp) / "jobs"
            runtime_dir = Path(tmp) / "runtime"
            edit_root.mkdir()
            runtime_dir.mkdir()
            for name in (
                "quickjobs.base.json",
                "quickjobs.companies.json",
                "quickjobs.profile.json",
            ):
                (edit_root / name).write_text("{}\n", encoding="utf-8")
            (edit_root / "quickjobs.profile.json").write_text(
                json.dumps({"profile": {"jobs_dir": str(jobs_dir), "name": "T"}}),
                encoding="utf-8",
            )
            with mock.patch.object(qj, "edit_config_picker_dir", return_value=runtime_dir):
                linked = qj.ensure_edit_config_picker_symlinks(edit_root=edit_root)
                removed = qj.remove_stale_edit_config_picker_symlinks(edit_root=edit_root)
            self.assertEqual(len(linked), 3)
            self.assertTrue((jobs_dir / "quickjobs.base.json").is_symlink())
            self.assertFalse((runtime_dir / "quickjobs.base.json").exists())
            self.assertEqual(removed, [])
            # Stale runtime-dir links are removed
            (runtime_dir / "quickjobs.base.json").symlink_to(
                edit_root / "quickjobs.base.json"
            )
            with mock.patch.object(qj, "edit_config_picker_dir", return_value=runtime_dir):
                removed2 = qj.remove_stale_edit_config_picker_symlinks(edit_root=edit_root)
            self.assertEqual(len(removed2), 1)
            self.assertFalse((runtime_dir / "quickjobs.base.json").exists())


if __name__ == "__main__":
    unittest.main()
