#!/usr/bin/env python3
"""Tests for Mac/wulf runtime merge used by quickjobs sync."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_merge_runtime", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class MergeRuntimeSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load()

    def test_prefers_newer_remote_scrape_state(self) -> None:
        qj = self.qj
        local = {
            "jobs": {"https://example.com/a": {"status": "applied", "at": "2026-08-04"}},
            "state": {
                "urls": ["https://old.example/1"],
                "run_at": "2026-07-02T13:50:37+00:00",
            },
        }
        remote = {
            "jobs": {"https://example.com/b": {"status": "screen", "at": "2026-08-03"}},
            "state": {
                "urls": ["https://new.example/1", "https://new.example/2"],
                "run_at": "2026-08-04T22:35:40+00:00",
            },
        }
        merged = qj.merge_runtime_documents_for_sync(local, remote)
        self.assertEqual(merged["state"]["run_at"], remote["state"]["run_at"])
        self.assertEqual(merged["state"]["urls"], remote["state"]["urls"])
        self.assertIn("https://example.com/a", merged["jobs"])
        self.assertIn("https://example.com/b", merged["jobs"])

    def test_keeps_local_state_when_newer(self) -> None:
        qj = self.qj
        local = {
            "jobs": {},
            "state": {
                "urls": ["https://local/1"],
                "run_at": "2026-08-05T06:00:00+00:00",
            },
        }
        remote = {
            "jobs": {},
            "state": {
                "urls": ["https://remote/1"],
                "run_at": "2026-08-04T22:00:00+00:00",
            },
        }
        merged = qj.merge_runtime_documents_for_sync(local, remote)
        self.assertEqual(merged["state"]["run_at"], local["state"]["run_at"])
        self.assertEqual(merged["state"]["urls"], local["state"]["urls"])

    def test_cli_merge_writes_out(self) -> None:
        qj = self.qj
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "local.json"
            remote = root / "remote.json"
            out = root / "out.json"
            local.write_text(
                '{"jobs":{"https://x":{"status":"applied","at":"2026-08-01"}},'
                '"state":{"urls":["u1"],"run_at":"2026-07-02T00:00:00+00:00"}}\n',
                encoding="utf-8",
            )
            remote.write_text(
                '{"jobs":{},"state":{"urls":["u2","u3"],'
                '"run_at":"2026-08-04T22:35:40+00:00"}}\n',
                encoding="utf-8",
            )
            rc = qj.cmd_merge_runtime_sync([str(local), str(remote), str(out)])
            self.assertEqual(rc, 0)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(doc["state"]["run_at"], "2026-08-04T22:35:40+00:00")
            self.assertEqual(doc["state"]["urls"], ["u2", "u3"])

    def test_also_pipeline_keeps_downloads_applied_history(self) -> None:
        """Stale ~/.job_search runtime must not drop Downloads applied_at rows."""
        qj = self.qj
        local = {
            "jobs": {
                "https://example.com/old": {
                    "status": "applied",
                    "at": "2026-07-20",
                    "applied_at": "2026-07-20",
                    "title": "Old",
                    "company_name": "Acme",
                }
            },
            "state": {"urls": ["u-old"], "run_at": "2026-07-02T00:00:00+00:00"},
        }
        remote = {
            "jobs": {
                "https://example.com/old": {
                    "status": "applied",
                    "at": "2026-07-20",
                    "applied_at": "2026-07-20",
                    "title": "Old",
                    "company_name": "Acme",
                }
            },
            "state": {"urls": ["u-new"], "run_at": "2026-08-04T22:00:00+00:00"},
        }
        downloads = {
            "version": 2,
            "jobs": {
                "https://example.com/ford": {
                    "status": "applied",
                    "at": "2026-08-08",
                    "applied_at": "2026-08-08",
                    "title": "Senior Software Engineer",
                    "company_name": "Ford",
                }
            },
        }
        merged = qj.merge_runtime_documents_for_sync(
            local, remote, also_pipeline_docs=[downloads]
        )
        self.assertIn("https://example.com/ford", merged["jobs"])
        self.assertEqual(merged["jobs"]["https://example.com/ford"]["applied_at"], "2026-08-08")
        applied_keys = {row["key"] for row in merged.get("applied") or []}
        self.assertIn("https://example.com/ford", applied_keys)
        self.assertEqual(merged["state"]["run_at"], remote["state"]["run_at"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_p = root / "local.json"
            remote_p = root / "remote.json"
            dl_p = root / "downloads-pipeline.json"
            out_p = root / "out.json"
            local_p.write_text(json.dumps(local) + "\n", encoding="utf-8")
            remote_p.write_text(json.dumps(remote) + "\n", encoding="utf-8")
            dl_p.write_text(json.dumps(downloads) + "\n", encoding="utf-8")
            rc = qj.cmd_merge_runtime_sync(
                [str(local_p), str(remote_p), str(out_p), "--also-pipeline", str(dl_p)]
            )
            self.assertEqual(rc, 0)
            doc = json.loads(out_p.read_text(encoding="utf-8"))
            self.assertIn("https://example.com/ford", doc["jobs"])


if __name__ == "__main__":
    unittest.main()
