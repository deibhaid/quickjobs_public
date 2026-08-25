#!/usr/bin/env python3
"""Tests for portable vs dev quickjobs path resolution."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HUBS_DIR = REPO_ROOT / "scripts" / "hubs"


class PortablePathResolutionTests(unittest.TestCase):
    def test_dev_hub_tools_paths(self) -> None:
        sys.modules.pop("hub_tools", None)
        sys.path.insert(0, str(HUBS_DIR))
        import hub_tools

        self.assertFalse(hub_tools.is_portable_layout())
        self.assertEqual(hub_tools.REPO_ROOT.resolve(), REPO_ROOT.resolve())
        self.assertEqual(hub_tools.HUBS_DIR.resolve(), HUBS_DIR.resolve())
        self.assertEqual(
            hub_tools.BASE_JSON.resolve(),
            (REPO_ROOT / "quickjobs.base.json").resolve(),
        )
        self.assertEqual(
            hub_tools.COMPANIES_JSON.resolve(),
            (REPO_ROOT / "quickjobs.companies.json").resolve(),
        )
        self.assertEqual(
            hub_tools.OUTPUT_ROOT.resolve(),
            (Path.home() / "ws/scriptdir/output").resolve(),
        )

    def test_portable_hub_tools_paths_from_arbitrary_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "quickjobs"
            pkg.mkdir()
            shutil.copy2(HUBS_DIR / "hub_tools.py", pkg / "hub_tools.py")
            (pkg / "quickjobs.py").write_text("# portable marker\n", encoding="utf-8")
            (pkg / "quickjobs.base.json").write_text('{"keywords_include_tier1":["a"],"keywords_include_tier2":["b"]}\n', encoding="utf-8")
            (pkg / "quickjobs.companies.json").write_text('{"companies": []}\n', encoding="utf-8")
            (pkg / "portable_runtime.py").write_text(
                (REPO_ROOT / "portable" / "portable_runtime.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            old_cwd = Path.cwd()
            other_cwd = Path(tmp) / "elsewhere"
            other_cwd.mkdir()
            os.chdir(other_cwd)
            try:
                sys.modules.pop("hub_tools", None)
                sys.modules.pop("portable_runtime", None)
                sys.path.insert(0, str(pkg))
                mod = importlib.import_module("hub_tools")
            finally:
                os.chdir(old_cwd)

            self.assertTrue(mod.is_portable_layout())
            self.assertEqual(mod.REPO_ROOT.resolve(), pkg.resolve())
            self.assertEqual(mod.OUTPUT_ROOT.resolve(), (pkg / "output").resolve())
            self.assertEqual(
                mod.REPORTS_DIR.resolve(),
                (pkg / "output" / "quickjobs-reports").resolve(),
            )
            self.assertEqual(
                mod.BASE_JSON.resolve(),
                (pkg / "quickjobs.base.json").resolve(),
            )

    def test_portable_runtime_honors_quickjobs_root_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "pkg-a"
            alt = Path(tmp) / "pkg-b"
            pkg.mkdir()
            alt.mkdir()
            shutil.copy2(REPO_ROOT / "portable" / "portable_runtime.py", pkg / "portable_runtime.py")

            old = os.environ.get("QUICKJOBS_ROOT")
            os.environ["QUICKJOBS_ROOT"] = str(alt)
            try:
                sys.modules.pop("portable_runtime", None)
                if str(pkg) not in sys.path:
                    sys.path.insert(0, str(pkg))
                pr = importlib.import_module("portable_runtime")
                self.assertEqual(pr.get_quickjobs_root().resolve(), alt.resolve())
            finally:
                if old is None:
                    os.environ.pop("QUICKJOBS_ROOT", None)
                else:
                    os.environ["QUICKJOBS_ROOT"] = old

    def test_dev_scrape_lock_path(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "quickjobs_dev_paths",
            REPO_ROOT / "quickjobs.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        expected = (
            Path.home() / "ws/scriptdir/output/quickjobs-reports" / "quickjobs-scrape.lock"
        )
        self.assertEqual(mod.global_scrape_lock_path().resolve(), expected.resolve())

    def test_portable_scrape_lock_path_from_arbitrary_cwd(self) -> None:
        from build_portable_package import patch_quickjobs_py

        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "quickjobs"
            pkg.mkdir()
            src = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")
            (pkg / "quickjobs.py").write_text(patch_quickjobs_py(src), encoding="utf-8")

            old_cwd = Path.cwd()
            other_cwd = Path(tmp) / "elsewhere"
            other_cwd.mkdir()
            os.chdir(other_cwd)
            try:
                import importlib.util

                spec = importlib.util.spec_from_file_location(
                    "quickjobs_portable_paths",
                    pkg / "quickjobs.py",
                )
                assert spec and spec.loader
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
            finally:
                os.chdir(old_cwd)

            expected = pkg / "output" / "quickjobs-reports" / "quickjobs-scrape.lock"
            self.assertEqual(mod.global_scrape_lock_path().resolve(), expected.resolve())
            failures = pkg / "output" / mod.SCRAPE_FAILURES_FILENAME
            self.assertEqual(mod.scrape_failures_log_path().resolve(), failures.resolve())


if __name__ == "__main__":
    unittest.main()
