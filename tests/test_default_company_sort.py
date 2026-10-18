#!/usr/bin/env python3
"""Default listing sort is posting date newest→oldest (Clear resets to same)."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = (REPO_ROOT / "quickjobs.py").read_text(encoding="utf-8")


class DefaultCompanySortTests(unittest.TestCase):
    def test_html_marks_date_sort_active(self) -> None:
        self.assertIn(
            'class="company-sort-btn active" data-company-sort="date"',
            SRC,
        )
        self.assertNotIn(
            'class="company-sort-btn active" data-company-sort="salary"',
            SRC,
        )

    def test_js_default_and_clear_use_date_desc(self) -> None:
        self.assertIn("let activeCompanySort = 'date';", SRC)
        self.assertIn("let companySortAsc = false;", SRC)
        self.assertIn("activeCompanySort = 'date';", SRC)
        # Clear path must not reintroduce salary as the reset default.
        clear_fn = SRC.split("function resetFilterBarToDefaults()", 1)[1].split(
            "function clearLegendFilters()", 1
        )[0]
        self.assertIn("activeCompanySort = 'date';", clear_fn)
        self.assertNotIn("activeCompanySort = 'salary';", clear_fn)

    def test_rating_sort_hides_employer_browse_links(self) -> None:
        self.assertIn("function syncEmployerBrowseLinks(root)", SRC)
        self.assertIn("activeCompanySort === 'rating'", SRC)
        self.assertIn("is-hidden-for-rating-sort", SRC)
        self.assertIn("Browse all .+ remote roles", SRC)

    def test_rating_sort_company_hides_visible_active_jobs(self) -> None:
        self.assertIn("function syncCompanyHideActiveButtons(root)", SRC)
        self.assertIn("function jobCardShowsActive(job)", SRC)
        self.assertIn("function companySortShowsCompanyHide()", SRC)
        self.assertIn("activeCompanySort === 'alphabetically'", SRC)
        hide_fn = SRC.split("async function hideVisibleActiveJobsForCompany(group)", 1)[1].split(
            "function syncCompanyHideActiveButtons(root)", 1
        )[0]
        self.assertNotIn("await commitPipelineStatusChange", hide_fn)
        self.assertIn("job.classList.add('hidden', 'hidden-pass')", hide_fn)
        self.assertIn("writePipeline(store)", hide_fn)
        self.assertEqual(hide_fn.count("void applyRoleFilter()"), 1)
        self.assertIn("company-hide-active-btn", SRC)
        self.assertIn("Hide visible Active listings", SRC)
        self.assertIn(".job:hover > .job-pass-btn", SRC)
        self.assertIn("h3.company-head-with-hide:hover .company-hide-active-btn", SRC)
        self.assertIn("nameText.appendChild(btn)", SRC)
        self.assertIn("function syncListingExpandToggles()", SRC)
        self.assertIn("function shownBoardJobs(root)", SRC)
        self.assertIn('id="listing-expand-all"', SRC)
        self.assertIn("color: #fff;", SRC)
        self.assertIn(".listing-expand-all-row:hover .listing-expand-toggle", SRC)
        self.assertIn(".company-listing-expand-btn", SRC)
        self.assertIn("async function mountVisibleListingShells()", SRC)
        self.assertIn("await mountVisibleListingShells()", SRC)
        self.assertIn(
            '#job-listings-body > .company-group.company-group-lazy[data-lazy-loaded="0"]',
            SRC,
        )

    def test_stability_hide_controls_are_removed(self) -> None:
        self.assertNotIn(">Stability</h2>", SRC)
        self.assertNotIn("Hide layoff-prone employers", SRC)
        self.assertNotIn("Hide applied / screen / rejected / ghosted", SRC)
        self.assertNotIn('id="hide-layoff-prone"', SRC)
        self.assertNotIn('id="hide-applied"', SRC)


if __name__ == "__main__":
    unittest.main()
