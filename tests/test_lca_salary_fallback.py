#!/usr/bin/env python3
"""DOL LCA wage index: annualize, lookup, and salary badge fallback."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_h1b():
    path = REPO_ROOT / "h1b_employer.py"
    spec = importlib.util.spec_from_file_location("h1b_employer_lca_wage_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_qj():
    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david_lca_salary", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class LcaWageUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.h1b = _load_h1b()

    def test_annualize_hour_week_month(self) -> None:
        h1b = self.h1b
        self.assertEqual(h1b.annualize_lca_wage(100.0, "Hour"), 208000.0)
        self.assertEqual(h1b.annualize_lca_wage(2000.0, "Week"), 104000.0)
        self.assertEqual(h1b.annualize_lca_wage(10000.0, "Month"), 120000.0)
        self.assertEqual(h1b.annualize_lca_wage(180000.0, "Year"), 180000.0)
        self.assertIsNone(h1b.annualize_lca_wage(0, "Year"))
        self.assertIsNone(h1b.annualize_lca_wage(50, "Day"))

    def test_row_midpoint_annual(self) -> None:
        h1b = self.h1b
        self.assertEqual(h1b.lca_row_annual_wage(100000, 120000, "Year"), 110000.0)
        self.assertEqual(h1b.lca_row_annual_wage("90.00", None, "Hour"), 187200.0)

    def test_format_label(self) -> None:
        label = self.h1b.format_lca_salary_label(180_000, 320_000)
        self.assertEqual(label, "$180K–$320K · DOL LCA")

    def test_lookup_prefers_title_bucket(self) -> None:
        h1b = self.h1b
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            idx_dir = root / "index"
            idx_dir.mkdir(parents=True)
            key = h1b.normalize_employer_name("Example Corp Inc")
            payload = {
                "source": "dol_lca_disclosure_wages",
                "employer_count": 1,
                "employers": {
                    key: {
                        "display_name": "Example Corp Inc",
                        "overall": {
                            "n": 20,
                            "p25": 150000,
                            "p50": 170000,
                            "p75": 190000,
                        },
                        "by_title": {
                            "devops engineer": {
                                "n": 5,
                                "p25": 200000,
                                "p50": 220000,
                                "p75": 250000,
                            }
                        },
                    }
                },
            }
            h1b.wage_index_path(root).write_text(
                json.dumps(payload) + "\n", encoding="utf-8"
            )
            h1b._WAGE_INDEX = None
            hit = h1b.lookup_lca_salary_range(
                "Example Corp",
                "Senior DevOps Engineer",
                cache_root=root,
            )
            self.assertIsNotNone(hit)
            assert hit is not None
            self.assertEqual(hit["matched_title"], "devops engineer")
            self.assertEqual(hit["p25"], 200000)
            self.assertEqual(hit["p75"], 250000)
            self.assertIn("DOL LCA", hit["label"])

            overall = h1b.lookup_lca_salary_range(
                "Example Corp Inc",
                "Product Manager",
                cache_root=root,
            )
            self.assertIsNotNone(overall)
            assert overall is not None
            self.assertEqual(overall["matched_title"], "")
            self.assertEqual(overall["p25"], 150000)

    def test_finalize_requires_min_samples(self) -> None:
        h1b = self.h1b
        buckets = {
            "tiny co": {
                "display_name": "Tiny Co",
                "wages": [100000.0, 110000.0],
                "wage_counts": {"all": 2},
                "by_title": {},
            },
            "big co": {
                "display_name": "Big Co",
                "wages": [100000.0, 120000.0, 140000.0, 160000.0, 180000.0],
                "wage_counts": {"all": 5},
                "by_title": {},
            },
        }
        out = h1b._finalize_wage_index(buckets)
        self.assertNotIn("tiny co", out)
        self.assertIn("big co", out)
        self.assertEqual(out["big co"]["overall"]["n"], 5)


class LcaSalaryApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qj = _load_qj()
        cls.h1b = cls.qj._h1b_employer
        assert cls.h1b is not None

    def _write_wage_index(self, root: Path, display_name: str = "Netflix Inc") -> str:
        h1b = self.h1b
        key = h1b.normalize_employer_name(display_name)
        (root / "index").mkdir(parents=True, exist_ok=True)
        payload = {
            "source": "test",
            "employer_count": 1,
            "employers": {
                key: {
                    "display_name": display_name,
                    "overall": {
                        "n": 12,
                        "p25": 180000,
                        "p50": 220000,
                        "p75": 320000,
                    },
                    "by_title": {},
                }
            },
        }
        h1b.wage_index_path(root).write_text(json.dumps(payload) + "\n", encoding="utf-8")
        h1b._WAGE_INDEX = None
        return key

    def test_apply_lca_when_jd_and_levels_missing(self) -> None:
        qj = self.qj
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wage_index(root)
            orig = qj.h1b_cache_root
            qj.h1b_cache_root = lambda: root  # type: ignore[method-assign]
            try:
                job = qj.Job(
                    title="Senior Software Engineer",
                    company_id="netflix",
                    company_name="Netflix",
                    url="https://example.com/jobs/1",
                    loc="remote",
                    loc_label="Remote US",
                    match="good",
                    salary="maybe",
                    salary_label=None,
                )
                company = {"id": "netflix", "name": "Netflix", "label": "Netflix"}
                cfg = {"profile": {"salary_floor": 200000}}
                qj.apply_company_salary_reference(job, company, cfg)
                self.assertTrue(job.salary_label)
                self.assertIn("180", job.salary_label or "")
                self.assertIn("DOL LCA", job.salary_label or "")
                badge = qj.badge_salary(job, cfg)
                self.assertIn("$180K", badge)
                self.assertIn("title=", badge)
                self.assertIn("DOL LCA", badge)
            finally:
                qj.h1b_cache_root = orig  # type: ignore[method-assign]
                self.h1b._WAGE_INDEX = None

    def test_levels_beats_lca(self) -> None:
        qj = self.qj
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wage_index(root)
            orig = qj.h1b_cache_root
            qj.h1b_cache_root = lambda: root  # type: ignore[method-assign]
            try:
                job = qj.Job(
                    title="Software Engineer",
                    company_id="netflix",
                    company_name="Netflix",
                    url="https://example.com/jobs/2",
                    loc="remote",
                    loc_label="Remote US",
                    match="good",
                    salary="maybe",
                    salary_label=None,
                )
                company = {
                    "id": "netflix",
                    "name": "Netflix",
                    "company_salary_label": "$250K–$400K · Levels.fyi",
                    "company_salary": "ok",
                }
                qj.apply_company_salary_reference(
                    job, company, {"profile": {"salary_floor": 200000}}
                )
                self.assertNotIn("DOL LCA", job.salary_label or "")
                self.assertIn("250", job.salary_label or "")
            finally:
                qj.h1b_cache_root = orig  # type: ignore[method-assign]
                self.h1b._WAGE_INDEX = None

    def test_existing_jd_salary_not_overwritten(self) -> None:
        qj = self.qj
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_wage_index(root)
            orig = qj.h1b_cache_root
            qj.h1b_cache_root = lambda: root  # type: ignore[method-assign]
            try:
                job = qj.Job(
                    title="Software Engineer",
                    company_id="netflix",
                    company_name="Netflix",
                    url="https://example.com/jobs/3",
                    loc="remote",
                    loc_label="Remote US",
                    match="good",
                    salary="ok",
                    salary_label="$210K–$240K",
                )
                qj.apply_company_salary_reference(
                    job,
                    {"id": "netflix", "name": "Netflix"},
                    {"profile": {"salary_floor": 200000}},
                )
                self.assertEqual(job.salary_label, "$210K–$240K")
            finally:
                qj.h1b_cache_root = orig  # type: ignore[method-assign]
                self.h1b._WAGE_INDEX = None


if __name__ == "__main__":
    unittest.main()
