# Built In employer discovery (`scripts/builtin/`)

`discover_builtin_employers.py` mines Built In's (`builtin.com`) public remote job
board to build a persistent EMPLOYER catalog over time. The goal is cataloging
companies (their careers/ATS site, salary ranges, seniority, skills), NOT tracking
live jobs. Scheduled reruns keep widening coverage.

There is **no open Built In JSON API** (the frontend's `api.builtin.com` backend
is not openly queryable — cookieless calls return 404/405, and its `/graphql` is
undocumented/unstable). Built In is server-rendered HTML, so this miner parses
the job cards, restricting itself to paths that **robots.txt ALLOWS**:
`/jobs/<category>/remote?page=N`. Built In `Allow`s `/jobs*?page=` and
`Disallow`s `/jobs*?search=`, so this miner uses category pagination and **never**
`?search=`.

Built In links each card to its own `/company/<slug>` page (it does not expose the
employer's ATS), so — exactly like the Dice miner — each new, non-agency employer
is ATS-fingerprinted by name (reusing `scripts/hubs`) and cached. Built In carries
meaningful staffing/agency volume; agencies are kept in the catalog with
`is_agency` (not dropped) and excluded from the add-candidates list.

Runs with the repo venv (`~/.v/bin/python`). It only READS
`quickjobs.david.base.json` and never writes it. Shared logic lives in
`scripts/_shared/discovery_common.py`.

## What it does per run

1. Fetches N pages of each configured remote category
   (default `dev-engineering/remote`) via `?page=N`.
2. Parses job cards: employer display name + slug, job title, salary range
   (e.g. `62K-111K Annually`, annualized), seniority level, top skills, remote.
3. Keeps DevOps/Platform/SRE/Infra roles (matched on title + skills;
   `--all-roles` disables the filter).
4. Merges into a persistent catalog keyed by normalized employer name (deduped by
   Built In job id). New, non-agency employers are ATS-fingerprinted ONCE and
   cached.
5. Flags agencies, base.json membership, and API-scrapability; writes a dated
   candidates report.

## robots.txt posture (verified 2026-07)

- `Allow: /jobs*?page=` — category pagination is permitted (what this miner uses).
- `Disallow: /jobs*?search=`, `Disallow: /search`, `Disallow: *?region_id=` — this
  miner never uses these.
- No login required for the public job board. Be polite: default 1s delay between
  page fetches, modest page counts.

## Outputs

| File | Role |
|------|------|
| `~/ws/scriptdir/output/builtin-employer-catalog.json` | Persistent employer catalog (accumulates across runs) |
| `~/ws/scriptdir/output/builtin-new-candidates-<date>.md` | Per-run "new candidates" report (human-readable) |
| `~/ws/scriptdir/output/builtin-new-candidates-<date>.json` | Same report as structured JSON |

Each catalog employer records: canonical name, `cid` slug, `company_slugs`,
`is_agency` + reason, `in_base_json` + `base_id`, `ats` (type / slug / endpoint /
browse_url / method / confidence / `api_scrapable` / `fingerprinted_at`), `salary`
(min/max annualized; raw labels), `job_types`, `titles`, `seniority_levels`,
`skills_seen`, `keywords`, `postings`, `source_ids`, `first_seen` / `last_seen`.

## Usage

```bash
# Default: dev-engineering/remote, 3 pages, infra filter on, full ATS fingerprint
~/.v/bin/python scripts/builtin/discover_builtin_employers.py

# Fast / cron-friendly: more pages, API-only fingerprint, cap new fingerprints
~/.v/bin/python scripts/builtin/discover_builtin_employers.py \
  --pages 5 --fingerprint api --max-fingerprint 40

# Multiple remote categories, snapshot base for dedup
~/.v/bin/python scripts/builtin/discover_builtin_employers.py \
  --categories dev-engineering/remote,data-analytics/remote --base /tmp/base-snapshot.json
```

Key flags: `--categories` (robots-allowed `/jobs/<category>` paths),
`--pages`, `--start-page`, `--all-roles`, `--fingerprint {full,api,off}`,
`--max-fingerprint`, `--refingerprint`, `--catalog`, `--report-dir`, `--base`
(READ ONLY; point at a snapshot), `--delay`, `--print-cron`.

Notes:
- Company display names come from the card; ATS is resolved by name (Built In does
  not link to the employer's ATS). Verify `review`-confidence slugs before adding.
- Idempotent: safe to run repeatedly; the catalog merge dedupes by Built In job id.

## Scheduling (example only — NOT installed)

```cron
# Weekly Built In remote employer-catalog refresh (Tuesdays 07:25). Uses ~/.v python; no cd needed.
25 7 * * 2 cron-exec /path/to/venv/bin/python /path/to/quickjobs/scripts/builtin/discover_builtin_employers.py --pages 5 --max-fingerprint 40 --fingerprint api
```
