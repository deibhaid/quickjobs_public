# HN "Who is hiring?" employer discovery (`scripts/hn/`)

`discover_hn_employers.py` mines the monthly "Ask HN: Who is hiring?" threads via
the public, no-auth **Algolia HN Search API** (`https://hn.algolia.com/api`) to
build a persistent EMPLOYER catalog over time. The goal is cataloging companies
(their careers/ATS site, salary ranges, roles, job types), NOT tracking live
jobs. Scheduled reruns keep widening coverage; each new monthly thread adds
employers.

Why HN is a strong source for this profile: top-level comments are posted by the
hiring companies themselves (founders / engineering leaders), so they are almost
entirely DIRECT employers (not staffing agencies). They frequently include a
salary, a remote flag, and a link to the company's own careers/ATS page — ideal
for a remote senior DevOps/Platform/SRE/Infra search.

Runs with the repo venv (`~/.v/bin/python`). It only READS
`quickjobs.david.base.json` (to flag employers already tracked) and never writes
it. Shared logic (name normalization, agency heuristics, salary parsing, ATS
fingerprinting, catalog IO, reporting) lives in `scripts/_shared/discovery_common.py`.

## What it does per run

1. Enumerates the N most-recent "Who is hiring?" story threads
   (`search_by_date?tags=story,author_whoishiring`), keeping only "Who is
   hiring?" titles (skips "Who wants to be hired?" / "Freelancer?").
2. Fetches each thread's comment tree via `items/<id>` (one JSON document).
3. Keeps top-level comments mentioning the DevOps/Platform/SRE/Infra keyword set
   (`--all-roles` disables the filter); extracts employer name, role, salary,
   job type, remote flag, and a careers URL from the post header.
4. Merges into a persistent catalog keyed by normalized employer name (deduped by
   HN comment id, so reruns never inflate counts). New, non-agency employers are
   ATS-fingerprinted ONCE (reusing `scripts/hubs`; **seeded with the scraped
   careers URL** when present) and cached.
5. Flags agencies, base.json membership, and API-scrapability; writes a dated
   candidates report.

## HN Algolia API notes (verified 2026-07)

- No auth. Documented soft limit ~10,000 requests/hour per IP. This miner makes
  roughly one request per thread plus one `items/<id>` per thread — a tiny
  footprint.
- Threads are enumerable via `tags=story,author_whoishiring`.
- `items/<id>` returns the full nested comment tree in a single response.

## Outputs

| File | Role |
|------|------|
| `~/ws/scriptdir/output/hn-employer-catalog.json` | Persistent employer catalog (accumulates across runs) |
| `~/ws/scriptdir/output/hn-new-candidates-<date>.md` | Per-run "new candidates" report (human-readable) |
| `~/ws/scriptdir/output/hn-new-candidates-<date>.json` | Same report as structured JSON |

Each catalog employer records: canonical name, `cid` slug, `is_agency` + reason,
`in_base_json` + `base_id`, `ats` (type / slug / endpoint / browse_url / method /
confidence / `api_scrapable` / `fingerprinted_at` / `careers_url_seed`), `salary`
(min/max annualized; raw labels; `hourly_seen`), `job_types`, `titles` (roles),
`careers_urls`, `hn_authors`, `keywords`, `postings`, `source_ids`,
`first_seen` / `last_seen`.

## Usage

```bash
# Default: 3 most-recent threads, infra filter on, full ATS fingerprint (uses careers URLs)
~/.v/bin/python scripts/hn/discover_hn_employers.py

# Fast / cron-friendly: 1 thread, API-only fingerprint, cap new fingerprints
~/.v/bin/python scripts/hn/discover_hn_employers.py \
  --threads 1 --fingerprint api --max-fingerprint 40

# Catalog every posting (not just infra), specific threads, snapshot base for dedup
~/.v/bin/python scripts/hn/discover_hn_employers.py \
  --all-roles --thread-ids 48747976,48357725 --base /tmp/base-snapshot.json
```

Key flags: `--threads`, `--thread-ids`, `--all-roles`, `--fingerprint
{full,api,off}`, `--max-fingerprint` (0 = all new; rest done on later runs),
`--refingerprint`, `--catalog`, `--report-dir`, `--base` (READ ONLY; point at a
snapshot to avoid reading a concurrently-edited base.json), `--print-cron`.

Notes:
- `--fingerprint full` also probes careers-HTML (icims/workday/phenom/etc.) and
  can fall back to Playwright (~45s/URL worst case). Cap unattended runs with
  `--max-fingerprint` or use `--fingerprint api` for a fast, Playwright-free pass.
- Idempotent: safe to run repeatedly; the catalog merge dedupes by HN comment id.

## Scheduling (example only — NOT installed)

This script never touches your crontab. Print an example line with `--print-cron`:

```cron
# Monthly HN 'Who is hiring' employer-catalog refresh (7th, 07:20). Uses ~/.v python; no cd needed.
20 7 7 * * cron-exec /Users/deibhaid/.v/bin/python /Users/deibhaid/ws/github/quickjobs/scripts/hn/discover_hn_employers.py --threads 2 --max-fingerprint 40
```
