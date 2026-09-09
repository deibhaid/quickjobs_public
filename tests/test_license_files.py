#!/usr/bin/env python3
"""License and third-party notice files for quickjobs."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class LicenseFilesTests(unittest.TestCase):
    def test_license_file_present(self) -> None:
        text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Quickjobs License 1.0", text)
        self.assertIn("Personal Use", text)
        self.assertIn("Commercial Use", text)
        self.assertIn("THIRD_PARTY_NOTICES.md", text)

    def test_third_party_notices_present(self) -> None:
        text = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("## Python packages", text)
        self.assertIn("playwright", text.lower())
        self.assertIn("curl_cffi", text)
        self.assertIn("## Browser binaries (Playwright)", text)

    def test_standard_license_texts_present(self) -> None:
        licenses_dir = REPO_ROOT / "licenses"
        for name in ("Apache-2.0.txt", "MIT.txt", "BSD-3-Clause.txt", "MPL-2.0.txt"):
            path = licenses_dir / name
            self.assertTrue(path.is_file(), msg=f"missing {name}")
            self.assertGreater(path.stat().st_size, 100, msg=f"empty {name}")

    def test_generate_third_party_notices_check(self) -> None:
        import subprocess
        import sys

        script = REPO_ROOT / "scripts" / "_shared" / "generate_third_party_notices.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=proc.stdout + proc.stderr,
        )


if __name__ == "__main__":
    unittest.main()
