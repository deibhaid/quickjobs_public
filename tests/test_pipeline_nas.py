#!/usr/bin/env python3
"""Tests for the NAS one-row pipeline save checks and backups."""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline_nas as nas  # noqa: E402


class PipelineNasTests(unittest.TestCase):
    def test_token_round_trip_and_rejection(self) -> None:
        token = nas.generate_pipeline_token()
        self.assertTrue(token.endswith("."))
        self.assertGreaterEqual(len(nas.normalize_pipeline_token(token).split()), 8)
        record = nas.hash_pipeline_token(token)
        self.assertNotIn(token, json.dumps(record))
        typed = token.upper().replace(".", "")
        self.assertTrue(nas.verify_pipeline_token(typed, record))
        self.assertFalse(nas.verify_pipeline_token("nope nope nope nope nope", record))

    def test_sentence_agreement(self) -> None:
        girl = next(noun for noun in nas.PIPELINE_NOUNS if noun.singular == "girl")
        dog = next(noun for noun in nas.PIPELINE_NOUNS if noun.singular == "dog")
        carry = next(verb for verb in nas.PIPELINE_VERBS if verb.base == "carry")
        self.assertEqual(nas.subject_pronoun_for(girl, "sg"), "she")
        self.assertEqual(nas.object_pronoun_for(girl, "sg"), "her")
        self.assertEqual(nas.subject_pronoun_for(girl, "pl"), "they")
        self.assertEqual(nas.subject_pronoun_for(dog, "sg"), "it")
        self.assertEqual(nas.object_pronoun_for(dog, "sg"), "it")
        self.assertEqual(nas.finite_form(carry, "sg"), "carries")
        self.assertEqual(nas.finite_form(carry, "pl"), "carry")
        self.assertEqual(nas.aux_not("sg"), "does not")
        self.assertEqual(nas.aux_not("pl"), "do not")
        singular = {noun.singular for noun in nas.PIPELINE_NOUNS}
        plural = {noun.plural for noun in nas.PIPELINE_NOUNS}
        third = {verb.third for verb in nas.PIPELINE_VERBS}
        female = {noun.singular for noun in nas.PIPELINE_NOUNS if noun.gender == "female"}
        male = {noun.singular for noun in nas.PIPELINE_NOUNS if noun.gender == "male"}
        for _ in range(40):
            sentence = nas.build_pipeline_sentence()
            low = nas.normalize_pipeline_token(sentence)
            words = low.split()
            padded = f" {low} "
            self.assertNotIn(" they does ", padded)
            self.assertNotIn(" she do ", padded)
            self.assertNotIn(" he do ", padded)
            self.assertNotIn(" it do ", padded)
            for index, word in enumerate(words[:-1]):
                nxt = words[index + 1]
                if word == "a":
                    self.assertNotIn(nxt[:1], "aeiou")
                if word == "an":
                    self.assertIn(nxt[:1], "aeiou")
            head = low.split(",")[0].split()
            if "and" in head and head[0] in {"the", "a", "an"} and head[3] == "and":
                self.assertNotIn(head[7], third)
            else:
                noun = head[2]
                verb = head[3]
                if noun in plural:
                    self.assertNotIn(verb, third)
                elif noun in singular:
                    self.assertIn(verb, third)
            if " she " in padded:
                self.assertNotEqual(head[3], "and")
                self.assertIn(head[2], female)
            if " he " in padded:
                self.assertNotEqual(head[3], "and")
                self.assertIn(head[2], male)

    def test_plain_http_rejects_a_correct_token(self) -> None:
        token = "apple beach cedar delta eagle"
        record = nas.hash_pipeline_token(token)
        headers = {
            "X-Forwarded-Proto": "http",
            "X-Quickjobs-Token": token,
        }
        decision = nas.classify_pipeline_request(
            "POST",
            "/pipeline",
            headers,
            b'{"key":"https://example.com/a","status":"applied","base_updated":""}',
            token_record=record,
        )
        self.assertEqual(decision.http_status, 403)
        self.assertEqual(decision.action, "")

    def test_untrusted_client_cannot_forge_https(self) -> None:
        token = "apple beach cedar delta eagle"
        record = nas.hash_pipeline_token(token)
        headers = {"X-Forwarded-Proto": "https", "X-Quickjobs-Token": token}
        decision = nas.classify_pipeline_request(
            "POST",
            "/pipeline",
            headers,
            b'{"key":"https://example.com/a","status":"applied","base_updated":""}',
            token_record=record,
            client_ip="192.168.86.28",
            trusted_proxies=("192.168.86.240",),
        )
        self.assertEqual(decision.http_status, 403)
        allowed = nas.classify_pipeline_request(
            "GET",
            "/pipeline",
            headers,
            b"",
            token_record=record,
            client_ip="192.168.86.240",
            trusted_proxies=("192.168.86.240",),
        )
        self.assertEqual(allowed.action, "get")

    def test_https_post_is_one_row(self) -> None:
        token = "apple beach cedar delta eagle"
        record = nas.hash_pipeline_token(token)
        headers = {"X-Forwarded-Proto": "https", "X-Quickjobs-Token": token}
        rejected = nas.classify_pipeline_request(
            "POST",
            "/pipeline",
            headers,
            b'{"store":{},"key":"https://example.com/a"}',
            token_record=record,
        )
        self.assertEqual(rejected.http_status, 400)
        accepted = nas.classify_pipeline_request(
            "POST",
            "/pipeline",
            headers,
            b'{"key":"https://example.com/a","status":"applied","base_updated":"","meta":{"title":"Role"}}',
            token_record=record,
        )
        self.assertEqual(accepted.action, "post")
        self.assertEqual(accepted.meta["title"], "Role")

    def test_drop_guard_allows_one_row(self) -> None:
        self.assertFalse(nas.pipeline_job_drop_is_too_large(100, 99))
        self.assertTrue(nas.pipeline_job_drop_is_too_large(100, 70))

    def test_snapshot_is_one_file_per_minute_and_omits_state(self) -> None:
        moment = datetime(2026, 10, 8, 20, 51, 27, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = {
                "version": 1,
                "updated_at": "2026-10-08T20:51:27+00:00",
                "jobs": {"https://example.com/a": {"status": "applied", "updated": "t"}},
                "applied": [],
                "state": {"urls": ["https://example.com/new"], "run_at": "2026-10-08T00:00:00+00:00"},
            }
            first = nas.snapshot_pipeline_jobs(doc, root, now=moment)
            doc["jobs"]["https://example.com/a"]["status"] = "screen"
            second = nas.snapshot_pipeline_jobs(doc, root, now=moment.replace(second=40))
            self.assertEqual(first, second)
            files = list(root.glob("jobs-*.json.gz"))
            self.assertEqual(len(files), 1)
            with gzip.open(files[0], "rt", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertNotIn("state", saved)
            self.assertEqual(saved["jobs"]["https://example.com/a"]["status"], "screen")

    def test_prune_keeps_tiers_and_the_size_cap(self) -> None:
        now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stamps = [
                now - timedelta(minutes=5),
                now - timedelta(days=2),
                now - timedelta(days=20),
                now - timedelta(days=21),
                now - timedelta(days=200),
                now - timedelta(days=207),
                now - timedelta(days=800),
            ]
            for stamped in stamps:
                name = f"jobs-{stamped.strftime('%Y%m%dT%H%M%S')}Z.json.gz"
                (root / name).write_bytes(b"x" * 100)
            removed = nas.prune_pipeline_row_backups(root, now=now, max_bytes=250)
            kept = sorted(path.name for path in root.glob("jobs-*.json.gz"))
            self.assertIn(f"jobs-{(now - timedelta(minutes=5)).strftime('%Y%m%dT%H%M%S')}Z.json.gz", kept)
            self.assertIn(f"jobs-{(now - timedelta(days=2)).strftime('%Y%m%dT%H%M%S')}Z.json.gz", kept)
            self.assertTrue(any("2026" in name for name in kept))
            self.assertGreaterEqual(len(removed), 1)
            self.assertLessEqual(sum(path.stat().st_size for path in root.glob("jobs-*.json.gz")), 250)

    def test_replace_jobs_leaves_scrape_state(self) -> None:
        live = {
            "jobs": {"https://example.com/old": {"status": "pass"}},
            "state": {"urls": ["https://example.com/new"], "run_at": "2026-10-08T00:00:00+00:00"},
            "ui": {"theme": "dark"},
        }
        source = {
            "jobs": {"https://example.com/from-backup": {"status": "applied"}},
            "state": {"urls": ["https://stale"], "run_at": "2020-01-01T00:00:00+00:00"},
            "ui": {"theme": "light"},
        }
        merged = nas.replace_pipeline_jobs(live, source)
        self.assertEqual(set(merged["jobs"]), {"https://example.com/from-backup"})
        self.assertEqual(merged["state"]["urls"], ["https://example.com/new"])
        self.assertEqual(merged["ui"]["theme"], "dark")


if __name__ == "__main__":
    unittest.main()
