#!/usr/bin/env python3
"""Tests for split lazy-board index/payload/deferred HTML emission."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_quickjobs_module():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_lazy_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class LazyBoardSplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_quickjobs_module()

    def test_collector_emits_separate_index_payload_descriptions_and_deferred(self) -> None:
        mod = self.qj
        collector = mod.LazyBoardCollector({"profile": {"resident_status": "h1b"}})
        collector.index.append({"k": "job-1", "c": "acme", "vs": True, "pool": "listings"})
        collector.descriptions["job-1"] = {"h": "<p>Visa sponsorship is available.</p>"}
        collector.descriptions_deferred["job-x"] = {"h": "<p>Hidden role body</p>"}
        collector.companies["acme"] = '<article class="job" data-apply-key="job-1"></article>'
        collector.companies_excluded["hidden-co"] = (
            '<article class="job" data-apply-key="job-x"></article>'
        )
        collector.sections["applied"] = "<p>applied</p>"
        collector.sections["excluded"] = "<p>excluded</p>"

        index = json.loads(collector.to_index_json())
        payload = json.loads(collector.to_payload_json())
        descriptions = json.loads(collector.to_descriptions_json())
        deferred = json.loads(collector.to_deferred_payload_json())

        self.assertEqual(index[0]["k"], "job-1")
        self.assertEqual(payload["companies"]["acme"], collector.companies["acme"])
        self.assertEqual(payload["companiesExcluded"], {})
        self.assertEqual(payload["descriptions"], {})
        self.assertIn("applied", payload["sections"])
        self.assertNotIn("excluded", payload["sections"])
        self.assertEqual(
            descriptions["descriptions"]["job-1"]["h"],
            "<p>Visa sponsorship is available.</p>",
        )
        self.assertNotIn("t", descriptions["descriptions"]["job-1"])
        self.assertEqual(deferred["companiesExcluded"]["hidden-co"], collector.companies_excluded["hidden-co"])
        self.assertEqual(deferred["descriptions"]["job-x"]["h"], "<p>Hidden role body</p>")
        self.assertIn("excluded", deferred["sections"])

    def test_register_job_routes_excluded_descriptions_to_deferred(self) -> None:
        mod = self.qj
        collector = mod.LazyBoardCollector({})
        co = mod.CompanyResult(
            id="acme",
            name="Acme",
            label="Acme",
            section="matching",
            jobs=[],
        )
        job = mod.Job(
            title="SRE",
            company_id="acme",
            company_name="Acme",
            url="https://example.com/job",
            loc="Remote",
            match="good",
            description_text="Job Summary\n\nBuild reliable platforms.",
            posted_ts=1700000000,
            job_id="1",
        )
        apply_key = collector.register_job(job, co, pool="excluded")
        self.assertTrue(apply_key)
        self.assertEqual(collector.descriptions, {})
        self.assertIn(apply_key, collector.descriptions_deferred)
        entry = collector.descriptions_deferred[apply_key]
        self.assertIn("h", entry)
        self.assertNotIn("t", entry)
        self.assertIn("Build reliable platforms", entry["h"])
        self.assertEqual(collector.index[-1]["pt"], 1700000000)

    def test_parse_lazy_board_data_merges_split_scripts(self) -> None:
        mod = self.qj
        html = """
        <html><body>
        <script type="application/json" id="lazy-board-index">[{"k":"job-1","vs":true}]</script>
        <script type="application/json" id="lazy-board-payload">{"companies":{"acme":"<article></article>"},"descriptions":{},"companiesExcluded":{},"companiesApplied":{},"sections":{}}</script>
        <script type="application/json" id="lazy-board-descriptions">{"descriptions":{"job-1":{"h":"<p>hello</p>"}}}</script>
        <script type="application/json" id="lazy-board-deferred">{"descriptions":{"job-x":{"h":"<p>hidden</p>"}},"companiesExcluded":{"x":"<article></article>"},"sections":{"excluded":"<p>x</p>"}}</script>
        </body></html>
        """
        data = mod._parse_lazy_board_data(html)
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(len(data["index"]), 1)
        self.assertEqual(data["index"][0]["k"], "job-1")
        self.assertIn("acme", data["companies"])
        self.assertEqual(data["descriptions"]["job-1"]["h"], "<p>hello</p>")
        self.assertEqual(data["descriptions"]["job-x"]["h"], "<p>hidden</p>")
        self.assertIn("x", data["companiesExcluded"])
        self.assertEqual(data["sections"]["excluded"], "<p>x</p>")

    def test_write_lazy_board_sidecars_and_parse_from_disk(self) -> None:
        import tempfile

        mod = self.qj
        collector = mod.LazyBoardCollector({})
        collector.index.append({"k": "job-1", "c": "acme", "pool": "listings"})
        collector.descriptions["job-1"] = {"h": "<p>body</p>"}
        collector.companies["acme"] = '<article class="job" data-apply-key="job-1"></article>'
        collector.descriptions_deferred["job-x"] = {"h": "<p>hidden</p>"}
        collector.companies_excluded["x"] = '<article class="job"></article>'
        collector.sections["excluded"] = "<p>excluded</p>"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "job-search-david.html"
            out.write_text(
                '<script type="application/json" id="lazy-board-index">[]</script>'
                '<script type="application/json" id="lazy-board-payload">{}</script>'
                '<script type="application/json" id="lazy-board-descriptions">{}</script>'
                '<script type="application/json" id="lazy-board-deferred">{}</script>',
                encoding="utf-8",
            )
            side_dir = mod.write_lazy_board_sidecars(out, collector)
            self.assertTrue((side_dir / "lazy_board_index.json").is_file())
            self.assertTrue((side_dir / "lazy_board_payload.json").is_file())
            self.assertTrue((side_dir / "lazy_board_descriptions.json").is_file())
            self.assertTrue((side_dir / "lazy_board_deferred.json").is_file())
            self.assertTrue((side_dir / "lazy_board_index.json.gz").is_file())
            data = mod._parse_lazy_board_data(out.read_text(encoding="utf-8"), html_path=out)
            self.assertIsNotNone(data)
            assert data is not None
            self.assertEqual(data["index"][0]["k"], "job-1")
            self.assertIn("acme", data["companies"])
            self.assertEqual(data["descriptions"]["job-1"]["h"], "<p>body</p>")
            self.assertEqual(data["descriptions"]["job-x"]["h"], "<p>hidden</p>")

    def test_embed_lazy_board_in_html_respects_env(self) -> None:
        mod = self.qj
        import os

        prev = os.environ.get("QUICKJOBS_EMBED_LAZY_BOARD")
        try:
            os.environ["QUICKJOBS_EMBED_LAZY_BOARD"] = "1"
            self.assertTrue(mod.embed_lazy_board_in_html())
            os.environ["QUICKJOBS_EMBED_LAZY_BOARD"] = "0"
            self.assertFalse(mod.embed_lazy_board_in_html())
        finally:
            if prev is None:
                os.environ.pop("QUICKJOBS_EMBED_LAZY_BOARD", None)
            else:
                os.environ["QUICKJOBS_EMBED_LAZY_BOARD"] = prev

    def test_client_bootstrap_guards_empty_stub_poison(self) -> None:
        """Stub embeds are [] / {}; early getJobBoardIndex must not block fetch."""
        mod = self.qj
        src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")
        self.assertIn("lazyBoardIndexFetchDone", src)
        self.assertIn("lazyBoardPayloadFetchDone", src)
        self.assertIn(
            "Do not parse stub embeds before bootstrap",
            src,
        )
        # initBoardUiStateSync must run after bootstrapLazyBoard in the boot IIFE
        boot_start = src.find("await bootstrapLazyBoard();")
        self.assertGreater(boot_start, 0)
        boot_chunk = src[boot_start : boot_start + 400]
        sync_pos = boot_chunk.find("initBoardUiStateSync();")
        self.assertGreater(sync_pos, 0, "initBoardUiStateSync must follow bootstrap")
        # No pre-bootstrap initBoardUiStateSync immediately before the IIFE
        pre = src[boot_start - 120 : boot_start]
        self.assertNotIn("initBoardUiStateSync();", pre)

    def test_client_guards_flat_sort_empty_payload_trap(self) -> None:
        """Salary/date flat-sort must not hide shells when sidecar payload is empty."""
        src = (REPO_ROOT / "quickjobs.david.py").read_text(encoding="utf-8")
        self.assertIn("resetEmptyLazyCompanyShells", src)
        self.assertIn("cache: 'no-cache'", src)
        self.assertNotIn("cache: 'force-cache'", src)
        self.assertIn(
            "Keep company layout visible; adding flat-sort with zero jobs hides every",
            src,
        )
        # Must not remount shells emptied by flat-sort (that duplicated every card).
        self.assertIn('data-lazy-mount-pending="1"', src)
        self.assertIn(
            "those shells look empty but must",
            src,
        )
        self.assertIn(
            "Replace prior job nodes (do not append)",
            src,
        )
        # First-load salary/date sort must not mount every company shell at once.
        self.assertIn("companyKeysOrderedForFlatSort", src)
        self.assertIn("yieldToMainThread", src)
        self.assertIn("applyFlatListingNodes", src)
        self.assertIn(
            "Paint after the first chunk so Chrome stays responsive during the rest.",
            src,
        )
        self.assertIn(
            "if (listingsBody?.classList.contains('listings-flat-sort')) return;",
            src,
        )
        # Job Sources collapsed by default (large checkbox grid on first paint).
        self.assertIn("'companies',\n      false,", src)
        self.assertIn('aria-expanded="false" ', src)
        self.assertIn(
            'id="job-sources-filter-panel" class="section-collapse-panel is-collapsed"',
            src,
        )
        self.assertIn("toggle-job-sources-filter", src)

    def test_html_uses_lazy_board_stubs(self) -> None:
        mod = self.qj
        stub = (
            '<script type="application/json" id="lazy-board-index">[]</script>'
            '<script type="application/json" id="lazy-board-payload">{}</script>'
        )
        embedded = (
            '<script type="application/json" id="lazy-board-index">'
            '[{"k":"job-1"}]</script>'
            '<script type="application/json" id="lazy-board-payload">'
            '{"companies":{"acme":"<article></article>"}}</script>'
        )
        self.assertTrue(mod.html_uses_lazy_board_stubs(stub))
        self.assertFalse(mod.html_uses_lazy_board_stubs(embedded))

    def test_validate_lazy_board_sidecars_fails_without_files(self) -> None:
        import tempfile

        mod = self.qj
        stub_html = (
            '<script type="application/json" id="lazy-board-index">[]</script>'
            '<script type="application/json" id="lazy-board-payload">{}</script>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "job-search-david.html"
            out.write_text(stub_html, encoding="utf-8")
            issues = mod.validate_lazy_board_sidecars(
                out, stub_html, expect_listing_jobs=True
            )
            self.assertTrue(any("Missing lazy-board index" in i for i in issues))
            self.assertTrue(any("Missing lazy-board payload" in i for i in issues))

    def test_validate_lazy_board_sidecars_fails_empty_companies_with_listings(self) -> None:
        import tempfile

        mod = self.qj
        stub_html = (
            '<script type="application/json" id="lazy-board-index">[]</script>'
            '<script type="application/json" id="lazy-board-payload">{}</script>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "job-search-david.html"
            out.write_text(stub_html, encoding="utf-8")
            side = mod.lazy_board_sidecars_dir(out)
            side.mkdir(parents=True, exist_ok=True)
            (side / "lazy_board_index.json").write_text(
                json.dumps([{"k": "job-1", "c": "acme", "pool": "listings"}]),
                encoding="utf-8",
            )
            (side / "lazy_board_payload.json").write_text(
                json.dumps(
                    {
                        "companies": {},
                        "descriptions": {},
                        "companiesExcluded": {},
                        "companiesApplied": {},
                        "sections": {},
                    }
                ),
                encoding="utf-8",
            )
            issues = mod.validate_lazy_board_sidecars(
                out, stub_html, expect_listing_jobs=True
            )
            self.assertTrue(any("companies is empty" in i for i in issues))

    def test_validate_lazy_board_sidecars_passes_with_payload_companies(self) -> None:
        import tempfile

        mod = self.qj
        stub_html = (
            '<script type="application/json" id="lazy-board-index">[]</script>'
            '<script type="application/json" id="lazy-board-payload">{}</script>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "job-search-david.html"
            out.write_text(stub_html, encoding="utf-8")
            side = mod.lazy_board_sidecars_dir(out)
            side.mkdir(parents=True, exist_ok=True)
            (side / "lazy_board_index.json").write_text(
                json.dumps([{"k": "job-1", "c": "acme", "pool": "listings"}]),
                encoding="utf-8",
            )
            (side / "lazy_board_payload.json").write_text(
                json.dumps(
                    {
                        "companies": {
                            "acme": '<article class="job" data-company-filter="acme"></article>'
                        },
                        "descriptions": {},
                        "companiesExcluded": {},
                        "companiesApplied": {},
                        "sections": {},
                    }
                ),
                encoding="utf-8",
            )
            issues = mod.validate_lazy_board_sidecars(
                out, stub_html, expect_listing_jobs=True
            )
            self.assertEqual(issues, [])
            self.assertEqual(
                mod.count_lazy_board_job_articles(stub_html, html_path=out),
                1,
            )

    def test_format_job_description_html_stable_sample(self) -> None:
        mod = self.qj
        text = "Job Summary\n\nBuild systems.\n\nRequirements:\nPython\nBash"
        html = mod.format_job_description_html(text)
        self.assertIn("job-description", html.lower() + "job-description")
        self.assertTrue(html.startswith("<") or "<p" in html or "<ul" in html)


if __name__ == "__main__":
    unittest.main()
