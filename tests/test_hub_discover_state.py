#!/usr/bin/env python3
"""Tests for hub discover checkpoint and network error detection."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

HUBS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "hubs"
sys.path.insert(0, str(HUBS_DIR))

import hub_discover_state as run_state  # noqa: E402
import hub_network  # noqa: E402


class HubDiscoverStateTests(unittest.TestCase):
    def test_checkpoint_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / run_state.STATE_FILENAME
            with mock.patch.object(run_state, "state_path", return_value=path):
                args = Namespace(
                    workers=4,
                    limit=0,
                    offset=0,
                    from_deferred=None,
                    ids="",
                    apply=True,
                    exclude_unresolved=False,
                    sync_hidden=False,
                )
                state = run_state.new_state(args, total_hubs=10, hub_ids=["a", "b"])
                run_state.save_state(state)
                loaded = run_state.load_state()
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded["run_id"], state["run_id"])
                self.assertEqual(loaded["hub_ids"], ["a", "b"])

                class Row:
                    id = "a"
                    name = "A"
                    careers_url = ""
                    method = ""
                    status = ""
                    total_jobs = ""
                    keyword_hits = ""
                    recommended_type = ""
                    apply = "no"
                    config_hint = ""
                    url_tested = ""
                    error = ""
                    notes = ""

                run_state.append_result(loaded, Row())
                run_state.save_state(loaded)
                again = run_state.load_state()
                assert again is not None
                self.assertEqual(again["completed_ids"], ["a"])
                self.assertEqual(len(again["rows"]), 1)
                run_state.clear_state()
                self.assertFalse(path.is_file())

    def test_in_progress_uncomplete_on_pause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / run_state.STATE_FILENAME
            with mock.patch.object(run_state, "state_path", return_value=path):
                args = Namespace(
                    workers=1,
                    limit=0,
                    offset=0,
                    from_deferred=None,
                    ids="",
                    apply=False,
                    exclude_unresolved=False,
                    sync_hidden=False,
                )
                state = run_state.new_state(args, total_hubs=2, hub_ids=["a", "b"])

                class Row:
                    id = "a"
                    name = "A"
                    careers_url = ""
                    method = ""
                    status = ""
                    total_jobs = ""
                    keyword_hits = ""
                    recommended_type = ""
                    apply = "no"
                    config_hint = ""
                    url_tested = ""
                    error = ""
                    notes = ""

                run_state.complete_hub(state, Row())
                run_state.set_in_progress(state, "b")
                self.assertEqual(state["completed_ids"], ["a"])
                self.assertEqual(state["in_progress_hub_id"], "b")
                run_state.uncomplete_hub(state, "b")
                self.assertEqual(state["in_progress_hub_id"], "b")
                self.assertNotIn("b", state["completed_ids"])
                self.assertEqual(run_state.remaining_hub_ids(state), ["b"])

    def test_params_compatible(self) -> None:
        stored = {
            "limit": 0,
            "offset": 0,
            "from_deferred": "",
            "ids": "",
            "apply": True,
        }
        args = Namespace(
            workers=4,
            limit=0,
            offset=0,
            from_deferred=None,
            ids="",
            apply=True,
            exclude_unresolved=False,
            sync_hidden=False,
        )
        self.assertTrue(run_state.params_compatible(stored, args))
        args.apply = False
        self.assertFalse(run_state.params_compatible(stored, args))


class HubNetworkTests(unittest.TestCase):
    def test_network_error_detection(self) -> None:
        self.assertFalse(hub_network.is_network_error(403, "Forbidden"))
        self.assertTrue(hub_network.is_waf_block(403, "Forbidden"))
        self.assertFalse(hub_network.is_network_error(404, "Not Found"))
        self.assertTrue(hub_network.is_network_error(599, "curl: (6) Could not resolve host"))
        self.assertTrue(hub_network.is_network_error(599, "Connection timed out after 35000 ms"))


if __name__ == "__main__":
    unittest.main()
