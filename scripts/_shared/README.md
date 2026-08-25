# Shared employer-discovery helpers (`scripts/_shared/`)

`discovery_common.py` holds the board-agnostic machinery reused by the per-board
employer-discovery miners (`scripts/hn/`, `scripts/builtin/`). It mirrors the
approach and catalog schema of `scripts/dice/discover_dice_employers.py`.

Provides:

- Employer-name normalization + agency / body-shop heuristics (`normalize`,
  `collapse`, `catalog_key`, `slugify`, `is_agency`).
- Salary parsing, annualized and tolerant of the HN shared-suffix form
  `$200-298k` (`parse_salary`).
- A read-only index of `quickjobs.base.json` + membership test
  (`load_base_index`, `base_match`). base.json is never written.
- A persistent employer catalog: `load_catalog`, `save_catalog` (atomic),
  `new_entry`, `merge_common` (idempotent when given a stable per-posting id).
- ATS fingerprinting that **reuses the `scripts/hubs` probe machinery**
  (greenhouse / lever / ashby / workday_cxs / smartrecruiters / icims / phenom /
  oracle_hcm / successfactors / taleo_cws / json_feed), optionally **seeded with
  an employer-provided careers URL** for higher accuracy (`fingerprint_employer`).
- A shared finalize pipeline (`finalize_catalog`) and report writer
  (`write_reports`, `compute_stats`).

Each board miner is responsible only for fetching its source and mapping listings
into `merge_common`; everything downstream (agency flagging, fingerprinting,
base.json dedup, persistence, reporting) is shared here so the boards stay
consistent with each other and with the Dice miner.
