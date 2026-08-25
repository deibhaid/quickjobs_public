# quickjobs

Self-contained job board pipeline: scrape employer ATS sources, merge pipeline
state, and generate a static HTML board.

This README is the primary reference for humans and AI agents working in this
repo. Read it before changing scrape logic, portable packaging, visa filtering,
sync, or board HTML/JS. Operator day-to-day steps (Mac ↔ remote host) live in
[HOWTO.md](HOWTO.md). Portable unzip/run steps live in
[portable/README.md](portable/README.md) and
[portable/ARCHITECTURE.txt](portable/ARCHITECTURE.txt).

---

## Agent orientation (read first)

### What this repo is

| Product | Audience | Entry point |
|---------|----------|-------------|
| David / primary fork | David's Mac + remote scrape host (remote) | `quickjobs.david.py` |
| Portable zip | Any user (e.g. Naiyyar Farooqui test install) | Built `quickjobs.py` via `run.py` |

Development happens in `quickjobs.david.*` sources. The portable package is a
*build artifact* produced by `build_portable_package.py`. Do not treat a portable
install directory (e.g. `~/temp_test/quickjobs/`) as the source of truth, and do
not copy `quickjobs.david.py` into a portable tree.

### Hard invariants — do not change by accident

1. **Source of truth for scraper logic** is `quickjobs.david.py` (+ `h1b_employer.py`,
   `run_log.py`). Portable installs run a *patched copy* named `quickjobs.py`.
   Edit david sources, then rebuild the zip (`quickjobs portable` /
   `build_portable_package.py`). Never “fix” a portable install by dropping
   `quickjobs.david.py` next to `quickjobs.py`.

2. **Three data layers stay separate.** Do not merge pipeline/runtime into
   `base.json`. Do not treat HTML as the source of pipeline state.

   | Layer | Role |
   |-------|------|
   | Static | Python + `quickjobs.david.*.json` in git |
   | Runtime | `$JOB_SEARCH_DIR/job-board-runtime.json` (+ snapshot/digest) |
   | HTML | Generated board under `profile.jobs_dir` (view only) |

3. **Internal `resident_status` value for visa holders is `h1b`.** User-facing
   prompts and docs say `visa` only (never “H-1B” in UI). Input aliases
   `visa` / `work_visa` store as `h1b`. Do not rename the stored value without a
   migration; existing profiles and tests depend on it.

4. **Visa scrape gates (when `resident_status == "h1b"`):**
   - Static excludes: `config/no-visa-sponsor-company-ids.json`
   - DOL non-filers: skipped at scrape when `cache/h1b/employer-index.json` exists
   - JD text: drop only when posting *explicitly denies* sponsorship
   - Board defaults: **Doesn't contain** chips for no-sponsorship phrases (not a
     positive “Contains sponsorship” filter)
   - DOL index also drives company-header badges only (`Visa filer · A` /
     `No DOL visa filings`). Absence from DOL does **not** drop individual jobs
     after a company was scraped; company-level skip is the gate.

5. **If DOL index is missing**, do not mass-exclude every company. Fall back to
   static no-sponsor list + JD filters; log a one-line warning.

6. **Green card** (`resident_status == "green_card"`): scrape drops US
   citizenship-required wording; board defaults are Doesn't-contain citizenship
   phrases. No DOL scrape gate.

7. **Citizen** profile: no visa/DOL scrape gates, no visa badges, no default
   visa/citizenship text chips.

8. **Pipeline server port 8765** is reserved for `quickjobs run --pipeline-server`
   (david autosave). Ad-hoc HTML previews must use another port (e.g. 8768).

9. **Lazy board payload** is split across `json_sidecars/` files
   (`lazy_board_index.json`, `lazy_board_payload.json`,
   `lazy_board_descriptions.json`, `lazy_board_deferred.json`) next to the HTML.
   The browser `fetch`es those first. Portable builds also embed the same JSON in
   `<script id="lazy-board-*">` tags so `file://` still works if fetch fails.
   David/NAS HTTP boards omit the large inline blobs (stubs only). Do not
   re-merge into a single giant `lazy-board-data` inline JSON. Prefer gzip/brotli
   on the sidecar JSON at the HTTP server (precompressed `.gz`/`.br` are written
   next to each sidecar when libraries allow).

10. **Progress status line format** (TTY):
    `N/M sources - (X jobs live) - MM/DD/YYYY HH:MM:SS`
    Stamp uses slashes. `run_log.py` must not double-prefix that line (see
    `line_is_progress_status`). Do not reintroduce mashed dual timestamps.

11. **Python env:** agent shells and pip use `~/.v` (`/path/to/venv/bin/python`).
    Script shebangs stay `#!/usr/bin/env python3`.

12. **Do not modify** user crontab, `~/local/bin/cron-exec`, or install-cron
    wrappers unless the user explicitly asks in that message.

13. **GitHub releases / PRs:** agents must not run `gh release create` or
    `gh pr create` (Cursor attribution). Prepare notes and print commands for
    the user. Versioning: tenths model (`0.0.9` → `0.1.0`), tag `vX.Y.Z`, title
    `X.Y.Z`, drafts unless asked to publish.

14. **Upstream `../job-board/`** is reference only. Do not modify it from this
    tree. Experiments stay in `quickjobs.david.py`.

### Before you edit — decision checklist

| Intent | Edit here | Then |
|--------|-----------|------|
| Scrape / HTML / filters | `quickjobs.david.py`, `h1b_employer.py`, `run_log.py` | Run tests; rebuild portable zip if behavior ships to others |
| Employer list / keywords | `quickjobs.david.base.json` | `validate` then `quickjobs sync` for remote |
| David's personal filters | `quickjobs.david.profile.json` | Sync if remote should match |
| Known non-sponsors (visa) | `config/no-visa-sponsor-company-ids.json` | Rebuild portable |
| Favicon override | `quickjobs.david.favicon-domains.json` (+ `KNOWN_BY_COMPANY_ID` in generator if needed) | Rebuild portable |
| Portable UX / configure prompts | `portable/configure.py`, `portable/*` | Rebuild zip |
| Portable packaging | `build_portable_package.py` | Rebuild zip |
| Remote CLI wrappers | `~/local/bin/quickjobs-server/` (outside this repo) | `quickjobs sync` |
| Update a portable *install* | Rebuild zip → re-extract code into install | Preserve that user's `quickjobs.profile.json`, `cache/`, `output/`, `python_venv/` |

### Validation after code changes

```bash
cd ~/ws/github/quickjobs
~/.v/bin/python -m pytest tests/ -q
~/.v/bin/python quickjobs.david.py validate-static-config
# If portable users need the change:
~/.v/bin/python build_portable_package.py
# Zip: ~/ws/scriptdir/output/quickjobs-portable.zip
```

---

## What quickjobs does (end-to-end)

1. Load static company list (`base.json`) + profile filters (`profile.json`).
2. For each company (minus `company_ids_exclude` and profile/visa defaults), fetch
   live jobs from the configured ATS (Greenhouse, Lever, Ashby, Workday, Oracle
   HCM, Phenom, manual careers, etc.).
3. Apply location, salary, keyword, match scoring, and (for visa/green_card)
   resident-status filters.
4. Merge with prior snapshot (JD text continuity, `--only` merges, checkpoint resume).
5. Merge pipeline statuses from `job-board-runtime.json` (applied / screen / pass).
6. Emit static HTML board + update snapshot / digest / runtime sidecar.
7. Board UI filters, legend, and status writes (File System Access → runtime JSON,
   or localhost pipeline server).

Typical David workflow: edit config on Mac → `quickjobs sync` → `quickjobs run`
(full refresh on remote). Chain: `quickjobs portable,sync,run`.

---

## Repo layout (complete map)

### Core runtime (synced to remote / copied into portable)

| Path | Role |
|------|------|
| `quickjobs.david.py` | Main scraper + HTML builder (david). Portable build → `quickjobs.py` |
| `run_log.py` | Timestamp-prefixed stdout; skips re-stamping progress status lines |
| `h1b_employer.py` | DOL LCA index, visa/green-card filters, badges, default text chips |
| `quickjobs.david.base.json` | ~1100+ employers, ATS type/slug, keywords, sections |
| `quickjobs.david.profile.json` | David profile: salary floor, skills, `jobs_dir`, excludes, overrides |
| `quickjobs.david.favicon-domains.json` | Favicon domain overrides by company/ATS board |
| `quickjobs.david.unconvertible-careers.json` | Manual employers that cannot auto-convert |
| `quickjobs.david.manual-career-meta.json` | Extra metadata for manual careers |
| `config/no-visa-sponsor-company-ids.json` | Curated non-sponsors for visa profiles |

### Portable packaging

| Path | Role |
|------|------|
| `build_portable_package.py` | Builds `~/ws/scriptdir/output/quickjobs/` + `quickjobs-portable.zip` |
| `portable/configure.py` | First-run: venv, Playwright, resume → profile, aviation/visa excludes |
| `portable/run.py` | Invokes `quickjobs.py` with portable env |
| `portable/portable_runtime.py` | `QUICKJOBS_ROOT` / path helpers from `__file__` (not cwd) |
| `portable/aviation_company_ids.py` | Loads aviation IDs from packaged config |
| `portable/no_visa_sponsor_company_ids.py` | Loads static non-sponsor IDs |
| `portable/fetch_glassdoor.py` | Glassdoor rating fetch (portable) |
| `portable/worker_tuning.py` | Worker env defaults for portable runs |
| `portable/ARCHITECTURE.txt` | Portable layout + visa layer summary |
| `portable/README.md` | Portable quick start |

Build copies: patched `quickjobs.py`, `h1b_employer.py`, `run_log.py`, base JSON
(as `quickjobs.base.json`), favicon domains, `hub_tools.py` / hubs when present,
`fetch_h1b_employer_index.py`, icons, `config/aviation-company-ids.json` (emitted
from `sector=aviation` in base), `config/no-visa-sponsor-company-ids.json`.

### Dev-machine-only tooling

| Path | Role |
|------|------|
| `quickjobs_hubs.py` | `quickjobs hubs …` CLI entry |
| `scripts/hubs/` | Convert, discover, probe, add-company helpers |
| `scripts/dice/`, `scripts/hn/`, `scripts/builtin/` | Employer-catalog miners |
| `scripts/discover/` | `quickjobs discover` / `discover-sync` / `validate` |
| `scripts/validate/` | Salary/location/scroll validators |
| `scripts/diagnostics/` | Timing, HTML diff, scrape-phase / step-isolation runbooks |
| `scripts/maintenance/` | Favicons, regional adds, `fetch_h1b_employer_index.py`, ulimits |
| `scripts/_shared/` | Shared discovery helpers |
| `tests/` | Unit/smoke tests (run with `~/.v/bin/python -m pytest`) |
| `data/` | Hub index URLs, reference lists |
| `compare/` | Overlay JSON for external compare harness |

### Outside this repo (connected)

| Path | Role |
|------|------|
| `~/local/bin/quickjobs` | User CLI (`portable`, `sync`, `run`, `hubs`, …) |
| `~/local/bin/quickjobs-server/` | Remote wrappers synced as `quickjobs-run`, etc. |
| `$JOB_SEARCH_DIR` | Runtime sidecar (david default under `~/.job_search/quickjobs/…`) |
| `profile.jobs_dir` | HTML output (david: often `~/Downloads/jobs`) |
| `~/ws/scriptdir/output/quickjobs-portable.zip` | Portable zip output |
| Remote host (remote) | Cron / `quickjobs-run` scrape + published HTML |

---

## Data model: static vs runtime vs HTML

| Layer | What | Typical location | Sync to remote? | Overwritten by scrape? |
|-------|------|------------------|-----------------|------------------------|
| Static | Code + employer/profile JSON | Repo | Yes (listed files) | No |
| Runtime | Pipeline + run state | `$JOB_SEARCH_DIR` | Yes (update-only) | Snapshot/digest yes; jobs merged |
| HTML | Board view | `profile.jobs_dir` | Only with `QUICKJOBS_SYNC_PUSH_DATA=1` | Yes after run |

Canonical runtime file: `$JOB_SEARCH_DIR/job-board-runtime.json`.

```json
{
  "version": 1,
  "updated_at": "…",
  "jobs": { "<apply-key>": { "status": "applied", "at": "…", "title": "…", "company_id": "…" } },
  "applied": [ { "key": "…", "applied_at": "…", "status": "applied", "title": "…" } ],
  "state": { "urls": ["…"], "run_at": "…" }
}
```

On first load, legacy `job-board-pipeline.json` / `job-board-state.json` /
`job-board-applied.json` migrate into runtime. Optional pipeline-shaped JSON
beside HTML is a mirror only — never the source of truth.

Single propagation path for David: `quickjobs portable,sync,run` (or `sync,run`).
No ad-hoc `cp`/`rsync` of david sources into portable installs.

---

## JSON and sidecar files

### Static (repo → validate → sync)

| File | Purpose | Who writes | Sync |
|------|---------|------------|------|
| `quickjobs.david.base.json` | Companies, keywords, scrapers, sections | You / hub / discover | Always |
| `quickjobs.david.profile.json` | Profile, salary floor, overrides, `jobs_dir` | You | Always |
| `quickjobs.david.favicon-domains.json` | Favicon overrides | Generator / audit | Always |
| `quickjobs.david.unconvertible-careers.json` | Unconvertible manuals | Hub tooling | Always |
| `quickjobs.david.manual-career-meta.json` | Manual career meta | Hub tooling | Always |
| `config/no-visa-sponsor-company-ids.json` | Visa static excludes | Manual edit | Via portable build / repo |

Validate before sync:

```bash
~/.v/bin/python quickjobs.david.py validate-static-config
```

Skip: `QUICKJOBS_SYNC_SKIP_VALIDATE=1`.

### Runtime (`$JOB_SEARCH_DIR`)

| File | Purpose |
|------|---------|
| `job-board-runtime.json` | Pipeline + scrape state (canonical) |
| `job-search-david.snapshot.json` | Full scrape snapshot (`--only` / rebuild) |
| `job-board-digest.txt` | Plain-text run summary |

### HTML

| File | Purpose |
|------|---------|
| `<jobs_dir>/job-search-david.html` | David board (name follows profile) |
| Portable: `output/job-search-quickjobs.html` | Typical portable board path |

---

## Resident status, visa, DOL, green card

### Stored values vs user language

| User says / prompt | Stored `profile.resident_status` |
|--------------------|----------------------------------|
| `citizen` | `citizen` |
| `green_card` | `green_card` |
| `visa` (aliases: `work_visa`, `h1b`) | `h1b` |

Configure prompt hint: `citizen, green_card, visa` — never show `h1b` or
“US permanent resident” parentheticals in the prompt.

### Visa profile (`h1b`) — current behavior

Implemented mainly in `h1b_employer.py`, called from `quickjobs.david.py` at
scrape start and HTML build.

1. **Company excludes (scrape skip entire employer)**  
   Union of:
   - Profile `company_ids_exclude`
   - Aviation list when configured (portable configure default: exclude aviation)
   - `config/no-visa-sponsor-company-ids.json` (`airship`, `cayuse-holdings-llc`,
     `chainguard`, `defense-unicorns`, `tria-federal`)
   - All companies with `filer=False` from DOL lookup when
     `employer-index.json` is present (`company_ids_exclude_no_dol_visa_filers`)

2. **Job-level scrape skip**  
   `h1b_job_skip_reason()` — only when JD/title matches
   `posting_text_indicates_no_visa_sponsorship()` (phrases in
   `H1B_NEGATIVE_NO_SPONSOR_PHRASES`). Does **not** use DOL filer status.

3. **Board default text filters**  
   One **Doesn't contain** chip per negative phrase (`profile_default_text_filters`),
   scope title + description. Positive Contains OR-list was removed; do not restore
   it as the default without an explicit product decision.

4. **DOL badges**  
   `lookup_company_h1b_meta` → `Visa filer · {A–D}` or `No DOL visa filings`.
   Shown on company headers when profile wants h1b validation.

5. **DOL data source**  
   Public DOL OFLC LCA disclosure XLSX (default FY2024 Q4 + FY2025 Q4). Aggregates
   certified/denied counts for H-1B / H1B / H-1B1 visa classes. User-facing labels
   say “visa”; underlying data is LCA/H-1B-centric, not all US work visa types.

6. **LCA salary fallback**  
   Same build also writes `lca-wage-index.json` (certified SOC 15-xxxx wages,
   annualized). When a US-workable posting has no salary on the JD and no
   Levels.fyi/`company_salary_label` reference, the board fills a badge from
   LCA p25–p75 for the employer (title needle when enough samples), labeled
   `· DOL LCA` (hover shows full provenance). Attested H-1B wages, not a
   guarantee of the open req’s band.

   Company config can also set `company_salary_label` / `company_salary_by_title`
   from crowd sources (e.g. Levels.fyi). Those badges show `· est.` in the badge
   text so they read as estimates, not posting-disclosed pay. Bands are title-tiered
   where possible (e.g. Weave senior platform ≈ $130K–$165K base). JD text always
   wins when present.

Build index:

```bash
# Portable install:
python_venv/bin/python fetch_h1b_employer_index.py
# Dev:
~/.v/bin/python scripts/maintenance/fetch_h1b_employer_index.py
```

Index paths under `h1b_cache_root()` / portable `cache/h1b/`:
`employer-index.json`, `lca-wage-index.json`.

### Green card

- Scrape: `green_card_job_skip_reason` / citizenship-required phrases.
- Board: Doesn't-contain citizenship chips (`GREEN_CARD_BOARD_FILTER_EXCLUDE_TERMS`).

### Name-matching caveats (DOL)

Fuzzy match via `normalize_employer_name` + prefix rules. Short names (<4 chars)
and legal-name mismatches (e.g. SpaceX vs Space Exploration Technologies) can
false-negative. Prefer curated `no-visa-sponsor-company-ids.json` for known
non-sponsors that DOL would miss or wrongly keep.

---

## Board UI (generated HTML)

Embedded in `quickjobs.david.py` template/JS:

- Legend filters, match tiers, location chips, bottom text-filter bar.
- Profile defaults injected via `#pipeline-config` → `defaultTextFilters` /
  `defaultFilterScope` → `applyProfileDefaultTextFilters()` on load.
- Stale browser `localStorage` can keep old chips after a regenerate — hard-refresh
  or clear site data for the board origin when testing filter defaults.
- Lazy company shells; job bodies from `lazy-board-index` + `lazy-board-payload`
  (legacy `lazy-board-data` still parsed if present).
- Pipeline: File System Access API → `job-board-runtime.json`, or
  `--pipeline-server` on profile port (david **8765**).
- Favicons: Google `www.google.com/s2/favicons?domain={domain}&sz=64` using domains from
  `favicon-domains.json`. Fix bad overrides there (and pin in
  `generate_favicon_domains.py` `KNOWN_BY_COMPANY_ID` so regen does not revert).

Removed on purpose: visa-sponsor **legend** chip. Do not re-add without asking.
Company DOL badges remain for visa profiles.

---

## Commands (David CLI)

CLI install: `~/local/bin/quickjobs` (not in this repo).

| Command | What it does |
|---------|--------------|
| `quickjobs portable` | Build portable zip → scriptdir output |
| `quickjobs sync` | Validate → push code, bins, runtime to remote |
| `quickjobs run [args…]` | Sync then full scrape on remote |
| `quickjobs rebuild [args…]` | Sync then regenerate HTML from snapshot (no scrape) |
| `quickjobs rebuild --local` | Rebuild HTML on Mac from local snapshot |
| `quickjobs stop` / `resume` / `restart` | Mid-run control via checkpoint |
| `quickjobs sync,restart` | Push code mid-run then resume |
| `quickjobs results` / `status` | Tail in-progress or last cron summary |
| `quickjobs shard [args…]` | Workday Playwright shard on remote |
| `quickjobs deploy` | First-time / venv / cron setup on remote |
| `quickjobs hubs …` | Hub convert / discover / probe |
| `quickjobs discover` / `discover-sync` / `validate` | Miner pipeline |
| `quickjobs portable,sync,run` | Chain |
| `quickjobs portable,sync,rebuild` | Ship code + rebuild board (no scrape) |

Local scrape:

```bash
cd ~/ws/github/quickjobs
~/.v/bin/python quickjobs.david.py
# Flags: --only id[,id…], --exclude …, --dry-run, --rebuild-from-snapshot, --resume-scrape, …
```

### Environment knobs

| Variable | Meaning |
|----------|---------|
| `QUICKJOBS_VERBOSE=1` | Detailed sync/scrape timing |
| `QUICKJOBS_SYNC_PUSH_DATA=1` | Also push HTML/snapshot/digest |
| `QUICKJOBS_SYNC_SKIP_VALIDATE=1` | Skip static validate |
| `QUICKJOBS_NO_REMOTE_SYNC=1` | Scrape host skips post-run rsync |
| `JOB_SEARCH_DIR` | Runtime sidecar root |
| `QUICKJOBS_JOBS_DIR` | HTML output on scrape host |
| `QUICKJOBS_HTTP_WORKERS` / `QUICKJOBS_PLAYWRIGHT_WORKERS` / … | Parallelism (see below) |

---

## Sync behavior (dev → remote)

1. `validate-static-config` (unless skipped).
2. Code: `quickjobs.david.py`, static JSON set, `run_log.py`, `README.md`, portable
   icons → remote checkout (`rsync --delete` for included files only).
3. Bins from `~/local/bin/quickjobs-server/` → remote `quickjobs-run`, etc.
4. Runtime from `$JOB_SEARCH_DIR/job-board-runtime.json`.
5. HTML/snapshot only if `QUICKJOBS_SYNC_PUSH_DATA=1`.

Hub tooling, discover, tests, and `build_portable_package.py` stay on the dev machine.

---

## Hub tooling, discover, validators

- Hubs: `quickjobs hubs …` → `quickjobs_hubs.py` + `scripts/hubs/`. Research notes:
  `scripts/hubs/HUB_ATS_RESEARCH.md`.
- Dice / HN / Built In miners: see each `scripts/*/README.md`.
- Discover CLI: `scripts/discover/README.md`.
- Validators: `scripts/validate/*`.
- Diagnostics runbooks: `scripts/diagnostics/scrape-phase-runbook.md`,
  `step-isolation-runbook.md`.

Typical new-company flow: add → convert/discover → `apply-hub-urls --apply` →
`quickjobs sync`.

---

## Portable package

```bash
quickjobs portable
# or: ~/.v/bin/python build_portable_package.py
```

| Output | Contents |
|--------|----------|
| `~/ws/scriptdir/output/quickjobs/` | Extracted tree |
| `~/ws/scriptdir/output/quickjobs-portable.zip` | Zip of that tree |

Portable `run.py` always runs `quickjobs.py`, never `quickjobs.david.py`.

Configure prompts: resume, resident status (`citizen, green_card, visa`), aviation
include (default no), ZIP, salary, name; optional DOL index build for visa.

Refreshing an existing portable install: re-extract **code** from the zip; preserve
that user's `quickjobs.profile.json`, `cache/` (including `cache/h1b/`), `output/`,
and `python_venv/`. Delete any stray `quickjobs.david.py` if present.

---

## Workday, Phenom, parallelism

Workday default is CXS; HTTP 422 falls back to Playwright. Phenom uses `/widgets`
`refineSearch`. HTTP scrape uses fast vs slow queues (Greenhouse/Ashby/Lever/CXS
vs Oracle HCM/Phenom/iCIMS/…).

| Env | Typical |
|-----|---------|
| `QUICKJOBS_HTTP_WORKERS` | 8–16 |
| `QUICKJOBS_PLAYWRIGHT_WORKERS` | 1 (dev) / 4 (remote) |
| `QUICKJOBS_COMPANY_TIMEOUT_SEC` | 600 |
| `QUICKJOBS_ASHBY_*` | Board HTML list + detail window (see code / prior README notes) |

Ashby: prefer board SSR list + capped JD fetches; do not casually switch back to
multi-MB posting-api as default.

Greenhouse: `type: greenhouse` + `board` slug; API
`boards-api.greenhouse.io/v1/boards/{board}/jobs`.

Open-file limit on Linux hosts: `quickjobs-raise-nofile` /
`scripts/maintenance/install-ulimits-remote.sh`.

---

## Pipeline linking (board ↔ runtime)

1. Open board in Chrome/Edge.
2. Link `$JOB_SEARCH_DIR/job-board-runtime.json` (File System Access API).
3. Status changes write to that file; `quickjobs sync` pushes to remote.
4. Safari: use `--pipeline-server` for local `file://` only.
5. Port **8765** = david pipeline autosave — not a free preview port.

---

## Scrape progress and logging

- Status: `N/M sources - (X jobs live) - MM/DD/YYYY HH:MM:SS`
- Company line: `… scrape k/n · company-id (j jobs)`
- `run_log.py` prefixes most lines with `MM-DD-YYYY HH:MM:SS` but **skips** lines
  already carrying the slash-format progress stamp.
- TTY progress uses `\r` / clear-line before incremental scrape lines so stamps
  do not mash together.

---

## Releases

Repo: `YOUR_GITHUB_USER/quickjobs`. Draft releases preferred; tag `vX.Y.Z`, title `X.Y.Z`;
tenths versioning (`0.0.9` → `0.1.0`).

On your Mac (personal `gh` auth):

```bash
quickjobs draft --dry-run   # show next version + notes
quickjobs draft             # create draft at next tenths version
```

Bumps from the highest existing release (published or draft). Agents must not run
`gh release create`; you publish with your own auth. Attach portable zip when publishing.

---

## Artifacts (quick map)

| Location | Role |
|----------|------|
| Repo checkout | Git source |
| `$JOB_SEARCH_DIR` | Runtime sidecar |
| `profile.jobs_dir` | HTML view |
| `~/ws/scriptdir/output/` | Portable zip + reports |
| Host `/tmp/quickjobs/…` | Scrape cache / checkpoint (not synced) |

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Stale pipeline | Prefer `$JOB_SEARCH_DIR/job-board-runtime.json`; sync refreshes from sidecar |
| Dev HTML ≠ remote | Expected until sync/run or pull published HTML |
| Sync validation fail | `validate-static-config --dir .` |
| Visa filter “finds nothing” | Defaults are Doesn't-contain; clear old Contains chips from localStorage; regenerate board |
| No DOL badges | Need `resident_status: h1b` + built `employer-index.json` |
| Portable “still old code” | Re-unzip code; confirm `run.py` → `quickjobs.py`; no david.py shadow |
| Double timestamps in progress | Ensure latest `run_log.py` + progress newline fix |
| Page unresponsive on huge board | Confirm lazy index/payload split, not monolithic `lazy-board-data` |

---

## Related docs

| Doc | Use when |
|-----|----------|
| [HOWTO.md](HOWTO.md) | Daily Mac/remote operator workflow |
| [portable/ARCHITECTURE.txt](portable/ARCHITECTURE.txt) | Portable paths + visa layers |
| [portable/README.md](portable/README.md) | Unzip → configure → run |
| `scripts/*/README.md` | Discover / Dice / HN / hubs |
| `scripts/diagnostics/*-runbook.md` | Scrape isolation debugging |
| `scripts/hubs/HUB_ATS_RESEARCH.md` | ATS probe patterns |

When documentation and code disagree, **code + tests win**; update this README in
the same change set so the next agent does not relearn from chat history alone.
