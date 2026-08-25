#!/usr/bin/env python3
"""Tests for portable configure.py profile builder and aviation excludes."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PORTABLE_DIR = REPO_ROOT / "portable"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class AviationCompanyIdsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.aviation_mod = _load_module(
            "aviation_company_ids_test",
            PORTABLE_DIR / "aviation_company_ids.py",
        )
        base_path = REPO_ROOT / "quickjobs.david.base.json"
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "_shared"))
        import config_bundle  # noqa: E402

        cls.base = config_bundle.load_base_bundle(base_path)

    def test_aviation_ids_from_base_match_sector(self) -> None:
        mod = self.aviation_mod
        ids = mod.aviation_company_ids_from_base(self.base)
        self.assertIn("american-airlines", ids)
        self.assertIn("delta-air-lines", ids)
        self.assertIn("united-airlines", ids)
        self.assertNotIn("netflix", ids)
        expected = sorted(
            str(c["id"])
            for c in self.base.get("companies", [])
            if c.get("id") and str(c.get("sector") or "").lower() == "aviation"
        )
        self.assertEqual(ids, expected)

    def test_load_from_config_snippet(self) -> None:
        mod = self.aviation_mod
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            snippet = root / "config" / "aviation-company-ids.json"
            snippet.write_text(
                json.dumps({"company_ids": ["delta-air-lines", "american-airlines"]}),
                encoding="utf-8",
            )
            self.assertEqual(
                mod.load_aviation_company_ids(root),
                ["american-airlines", "delta-air-lines"],
            )


class ConfigureProfileBuilderTests(unittest.TestCase):
    def test_resident_prompt_hint_never_mentions_h1b(self) -> None:
        sys.path.insert(0, str(PORTABLE_DIR))
        try:
            configure = _load_module("configure_prompt_test", PORTABLE_DIR / "configure.py")
            hint = configure.RESIDENT_PROMPT_HINT.lower()
            self.assertNotIn("h1b", hint)
            self.assertNotIn("h-1b", hint)
            self.assertIn("visa", hint)
            prompt_label = f"Resident status ({configure.RESIDENT_PROMPT_HINT})"
            self.assertEqual(
                prompt_label,
                "Resident status (citizen, green_card, visa)",
            )
        finally:
            sys.path.remove(str(PORTABLE_DIR))

    def test_prompt_resident_status_accepts_visa_alias(self) -> None:
        sys.path.insert(0, str(PORTABLE_DIR))
        try:
            configure = _load_module("configure_resident_test", PORTABLE_DIR / "configure.py")
            with unittest.mock.patch.object(configure, "_prompt", return_value="visa"):
                self.assertEqual(configure._prompt_resident_status(), "h1b")
        finally:
            sys.path.remove(str(PORTABLE_DIR))

    def test_prompt_resident_status_accepts_work_visa_alias(self) -> None:
        sys.path.insert(0, str(PORTABLE_DIR))
        try:
            configure = _load_module("configure_work_visa_test", PORTABLE_DIR / "configure.py")
            with unittest.mock.patch.object(configure, "_prompt", return_value="work_visa"):
                self.assertEqual(configure._prompt_resident_status(), "h1b")
        finally:
            sys.path.remove(str(PORTABLE_DIR))

    def test_write_profile_excludes_aviation_when_not_included(self) -> None:
        aviation_mod = _load_module(
            "aviation_company_ids_cfg",
            PORTABLE_DIR / "aviation_company_ids.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp)
            (pkg / "config").mkdir()
            (pkg / "output").mkdir()
            sys.path.insert(0, str(REPO_ROOT / "scripts" / "_shared"))
            import config_bundle  # noqa: E402

            base = config_bundle.load_base_bundle(REPO_ROOT / "quickjobs.david.base.json")
            snippet = pkg / "config" / "aviation-company-ids.json"
            snippet.write_text(
                json.dumps(
                    {"company_ids": aviation_mod.aviation_company_ids_from_base(base)}
                ),
                encoding="utf-8",
            )

            portable_runtime = PORTABLE_DIR / "portable_runtime.py"
            rt_src = portable_runtime.read_text(encoding="utf-8")
            rt_src = rt_src.replace(
                "ROOT = Path(__file__).resolve().parent",
                f"ROOT = Path({str(pkg)!r})",
            )
            (pkg / "portable_runtime.py").write_text(rt_src, encoding="utf-8")

            cfg_src = (PORTABLE_DIR / "configure.py").read_text(encoding="utf-8")
            (pkg / "aviation_company_ids.py").write_text(
                (PORTABLE_DIR / "aviation_company_ids.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (pkg / "configure.py").write_text(cfg_src, encoding="utf-8")

            sys.path.insert(0, str(pkg))
            try:
                configure = _load_module("configure_test", pkg / "configure.py")
                configure.ROOT = pkg
                configure.PROFILE_PATH = pkg / "quickjobs.profile.json"
                configure.SETUP_PATH = pkg / "config" / "setup.json"
                exclude = aviation_mod.load_aviation_company_ids(pkg)
                configure._write_profile(
                    name="Test User",
                    home_zip="97035",
                    resident_status="citizen",
                    salary_floor=150000,
                    skills=["devops"],
                    extra_keywords=[],
                    resume_path=pkg / "resume.pdf",
                    include_aviation=False,
                    aviation_search=False,
                    company_ids_exclude=exclude,
                )
            finally:
                sys.path.remove(str(pkg))

            profile = json.loads((pkg / "quickjobs.profile.json").read_text(encoding="utf-8"))
            self.assertIn("american-airlines", profile["company_ids_exclude"])
            self.assertIn("delta-air-lines", profile["company_ids_exclude"])
            self.assertNotIn("aviation_search", profile.get("profile", {}))

            setup = json.loads((pkg / "config" / "setup.json").read_text(encoding="utf-8"))
            self.assertFalse(setup["include_aviation"])
            self.assertEqual(len(setup["company_ids_exclude"]), len(exclude))


class NoVisaSponsorCompanyIdsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module(
            "no_visa_sponsor_company_ids_test",
            PORTABLE_DIR / "no_visa_sponsor_company_ids.py",
        )

    def test_load_from_repo_config_snippet(self) -> None:
        mod = self.mod
        ids = mod.load_no_visa_sponsor_company_ids(REPO_ROOT)
        self.assertEqual(
            ids,
            [
                "airship",
                "cayuse-holdings-llc",
                "chainguard",
                "defense-unicorns",
                "tria-federal",
            ],
        )

    def test_write_profile_excludes_non_sponsors_for_visa(self) -> None:
        visa_mod = _load_module(
            "no_visa_sponsor_cfg",
            PORTABLE_DIR / "no_visa_sponsor_company_ids.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp)
            (pkg / "config").mkdir()
            (pkg / "output").mkdir()
            shutil.copy2(
                REPO_ROOT / "config" / "no-visa-sponsor-company-ids.json",
                pkg / "config" / "no-visa-sponsor-company-ids.json",
            )
            (pkg / "aviation_company_ids.py").write_text(
                (PORTABLE_DIR / "aviation_company_ids.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (pkg / "no_visa_sponsor_company_ids.py").write_text(
                (PORTABLE_DIR / "no_visa_sponsor_company_ids.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (pkg / "configure.py").write_text(
                (PORTABLE_DIR / "configure.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            rt_src = (PORTABLE_DIR / "portable_runtime.py").read_text(encoding="utf-8")
            rt_src = rt_src.replace(
                "ROOT = Path(__file__).resolve().parent",
                f"ROOT = Path({str(pkg)!r})",
            )
            (pkg / "portable_runtime.py").write_text(rt_src, encoding="utf-8")

            sys.path.insert(0, str(pkg))
            try:
                configure = _load_module("configure_visa_test", pkg / "configure.py")
                configure.ROOT = pkg
                configure.PROFILE_PATH = pkg / "quickjobs.profile.json"
                configure.SETUP_PATH = pkg / "config" / "setup.json"
                visa_excludes = visa_mod.load_no_visa_sponsor_company_ids(pkg)
                configure._write_profile(
                    name="Test User",
                    home_zip="97035",
                    resident_status="h1b",
                    salary_floor=150000,
                    skills=["devops"],
                    extra_keywords=[],
                    resume_path=pkg / "resume.pdf",
                    include_aviation=True,
                    aviation_search=False,
                    company_ids_exclude=visa_excludes,
                )
            finally:
                sys.path.remove(str(pkg))

            profile = json.loads((pkg / "quickjobs.profile.json").read_text(encoding="utf-8"))
            for cid in visa_excludes:
                self.assertIn(cid, profile["company_ids_exclude"])

    def test_citizen_profile_does_not_get_non_sponsor_excludes(self) -> None:
        visa_mod = _load_module(
            "no_visa_sponsor_citizen_cfg",
            PORTABLE_DIR / "no_visa_sponsor_company_ids.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp)
            (pkg / "config").mkdir()
            (pkg / "output").mkdir()
            shutil.copy2(
                REPO_ROOT / "config" / "no-visa-sponsor-company-ids.json",
                pkg / "config" / "no-visa-sponsor-company-ids.json",
            )
            (pkg / "aviation_company_ids.py").write_text(
                (PORTABLE_DIR / "aviation_company_ids.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (pkg / "no_visa_sponsor_company_ids.py").write_text(
                (PORTABLE_DIR / "no_visa_sponsor_company_ids.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (pkg / "configure.py").write_text(
                (PORTABLE_DIR / "configure.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            rt_src = (PORTABLE_DIR / "portable_runtime.py").read_text(encoding="utf-8")
            rt_src = rt_src.replace(
                "ROOT = Path(__file__).resolve().parent",
                f"ROOT = Path({str(pkg)!r})",
            )
            (pkg / "portable_runtime.py").write_text(rt_src, encoding="utf-8")

            sys.path.insert(0, str(pkg))
            try:
                configure = _load_module("configure_citizen_test", pkg / "configure.py")
                configure.ROOT = pkg
                configure.PROFILE_PATH = pkg / "quickjobs.profile.json"
                configure.SETUP_PATH = pkg / "config" / "setup.json"
                configure._write_profile(
                    name="Test User",
                    home_zip="97035",
                    resident_status="citizen",
                    salary_floor=150000,
                    skills=["devops"],
                    extra_keywords=[],
                    resume_path=pkg / "resume.pdf",
                    include_aviation=True,
                    aviation_search=False,
                    company_ids_exclude=[],
                )
            finally:
                sys.path.remove(str(pkg))

            profile = json.loads((pkg / "quickjobs.profile.json").read_text(encoding="utf-8"))
            for cid in visa_mod.load_no_visa_sponsor_company_ids(pkg):
                self.assertNotIn(cid, profile.get("company_ids_exclude") or [])


if __name__ == "__main__":
    unittest.main()
