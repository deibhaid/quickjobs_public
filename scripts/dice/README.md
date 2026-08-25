# Dice employer discovery (`scripts/dice/`)

`discover_dice_employers.py` mines Dice.com's official no-auth MCP endpoint
(`https://mcp.dice.com/mcp`, tool `search_jobs`) to build up a persistent
EMPLOYER catalog over time. The goal is cataloging companies (their careers/ATS
site, salary ranges, and job types/titles seen), NOT tracking live jobs.
Recency of a posting does not matter; scheduled reruns keep widening coverage.

Run with the repo's venv (`~/.v/bin/python`). It only READS
`quickjobs.david.base.json` (to flag employers already tracked) and never
writes it.

## What it does per run

1. Queries `search_jobs` across a DevOps/Platform/SRE/Infra keyword set, using
   the widest date window Dice allows (see limits below), paginating to the
   per-query page ceiling.
2. Merges every posting into a persistent catalog keyed by a normalized
   employer name (idempotent: postings are de-duplicated by Dice job GUID, so
   re-running never inflates counts).
3. Fingerprints each NEW, non-agency employer's ATS ONCE (reusing the
   `scripts/hubs` probe machinery) and caches the result; known employers are
   never re-probed.
4. Flags staffing agencies / recruiters (kept in the catalog with `is_agency`,
   not dropped), whether the employer is already in `base.json`, and whether
   its ATS is API-scrapable.
5. Writes a dated "new since last run" candidates report.

## Dice MCP limits (verified 2026-07)

- `posted_date` accepts only `ONE` (1 day), `THREE` (3 days), `SEVEN` (7 days).
  `FOURTEEN` / `THIRTY` / `ALL` are silently treated as no-match (0 rows), not
  an error. Omitting `posted_date` entirely returns the full unfiltered set —
  the widest window — so this miner defaults to NO `posted_date` (e.g. "devops"
  returns ~9,674 results vs ~2,272 for `SEVEN`). Earlier roles are reachable in
  one query by omitting the date; scheduled reruns then accumulate whatever new
  employers/postings enter Dice's index over time.
- `jobs_per_page` max is 100 (values >100 return 0 rows).
- `page_number` is 1-based; paginate up to `meta.pageCount`
  (= `ceil(totalResults / pageSize)`). Pages beyond that return 0 rows. There
  is no date-sort param; default `sortBy` is `relevance`.

## Outputs

| File | Role |
|------|------|
| `~/ws/scriptdir/output/dice-employer-catalog.json` | Persistent employer catalog (accumulates across runs) |
| `~/ws/scriptdir/output/dice-new-candidates-<date>.md` | Per-run "new since last run" report (human-readable) |
| `~/ws/scriptdir/output/dice-new-candidates-<date>.json` | Same report as structured JSON |

Each catalog employer records: canonical name, `cid` slug, `is_agency` +
reason, `in_base_json` + `base_id`, `ats` (type / slug / endpoint / browse_url /
method / confidence / `api_scrapable` / `fingerprinted_at`), `salary`
(min/max seen, annualized; raw labels; `hourly_seen`), `job_types`,
`titles`, `locations`, `employer_types`, `keywords`, `postings`,
`posting_urls_sample`, `first_seen` / `last_seen` / `last_posted_date`.

Fingerprint `confidence` is `high` only when the board's org name (Greenhouse /
SmartRecruiters) or a strict slug match (Lever / Ashby) confirms identity;
generic slug collisions (e.g. Greenhouse board `charles` is literally named
"charles", not Charles Schwab) are downgraded to `review` for manual check.

## Usage

```bash
# Default: full keyword net, widest window, paginate to ceiling, full ATS fingerprint
~/.v/bin/python scripts/dice/discover_dice_employers.py

# Faster / cron-friendly: bound pages, cap new fingerprints per run, API-only probe
~/.v/bin/python scripts/dice/discover_dice_employers.py \
  --max-pages 3 --max-fingerprint 40 --fingerprint api

# Narrow the net (e.g. only remote full-time) or a specific date window
~/.v/bin/python scripts/dice/discover_dice_employers.py \
  --workplace-types Remote --employment-types FULLTIME --posted-date SEVEN
```

Key flags: `--keywords` / `--keywords-file`, `--workplace-types`,
`--employment-types`, `--posted-date` (blank = widest), `--jobs-per-page`
(<=100), `--max-pages` (0 = to ceiling), `--fingerprint {full,api,off}`,
`--max-fingerprint` (0 = all new; remaining get done on later runs),
`--refingerprint`, `--catalog`, `--report-dir`, `--base`, `--print-cron`.

Notes:
- `--fingerprint full` also probes careers-HTML (icims/workday/phenom/oracle/
  etc.) and can fall back to Playwright (~45s/URL worst case). For unattended
  runs cap the work with `--max-fingerprint` (the caps recur across runs since
  fingerprints are cached) or use `--fingerprint api` for a fast, Playwright-free
  pass.
- Safe to run repeatedly; the catalog merge is idempotent.

## Scheduling (example only — NOT installed)

This script never touches your crontab. Print an example line with
`--print-cron`:

```cron
# Weekly Dice employer-catalog refresh (Mondays 07:15). Uses ~/.v python; no cd needed.
15 7 * * 1 cron-exec /path/to/venv/bin/python /path/to/quickjobs/scripts/dice/discover_dice_employers.py --max-fingerprint 40
```
