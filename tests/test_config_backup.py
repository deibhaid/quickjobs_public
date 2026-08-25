#!/usr/bin/env python3
"""Tests for rolling config backups."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1] / "scripts" / "_shared"
sys.path.insert(0, str(SHARED_DIR))
import config_backup  # noqa: E402


class ConfigBackupTests(unittest.TestCase):
    def test_rolling_backup_and_prune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "quickjobs.david.base.json"
            source.write_text('{"keywords_include_tier1":["a"]}\n', encoding="utf-8")
            old_root = config_backup.BACKUP_ROOT
            backup_root = root / "backups"
            config_backup.BACKUP_ROOT = backup_root
            try:
                dest = config_backup.rolling_backup(source, retention_days=7)
                self.assertTrue(dest.is_file())
                self.assertIn("quickjobs.david.base.json", dest.name)

                stale_stamp = datetime.now() - timedelta(days=10)
                stale = config_backup.backup_dest_for(source, now=stale_stamp)
                stale.parent.mkdir(parents=True, exist_ok=True)
                stale.write_text('{"stale": true}\n', encoding="utf-8")

                removed = config_backup.prune_old_backups(source, retention_days=7)
                self.assertGreaterEqual(removed, 1)
                self.assertFalse(stale.exists())
                self.assertTrue(dest.exists())
            finally:
                config_backup.BACKUP_ROOT = old_root

    def test_rolling_backup_bundle_includes_companies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "quickjobs.david.base.json"
            companies = root / "quickjobs.david.companies.json"
            base.write_text('{"keywords_include_tier1":["a"]}\n', encoding="utf-8")
            companies.write_text('{"companies":[{"id":"acme"}]}\n', encoding="utf-8")
            old_root = config_backup.BACKUP_ROOT
            config_backup.BACKUP_ROOT = root / "backups"
            try:
                saved = config_backup.rolling_backup_bundle(base, retention_days=7)
                self.assertEqual(len(saved), 2)
            finally:
                config_backup.BACKUP_ROOT = old_root


if __name__ == "__main__":
    unittest.main()
