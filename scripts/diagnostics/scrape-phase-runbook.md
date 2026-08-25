# Quickjobs scrape-phase isolation runbook

In-run diagnostics for `_run_full_board_scrape` only. Does not cover portable/sync/deploy CLI steps.

Companion runner: `run_scrape_phase.sh`  
Timing checker: `check_run_timing.py` + `timing-baselines.yaml`  
Company order helper: `list_scrape_positions.py`

---

## Pipeline map (`_run_full_board_scrape`)

Source: `quickjobs.david.py` → `_run_full_board_scrape` (≈ line 22916).

| Phase | What runs | Code / handler | Log markers | timing-baselines phase |
|-------|-----------|----------------|-------------|------------------------|
| Startup | Config load, lock, worker banner | `main()` → `_run_full_board_scrape` | `quickjobs worker pid …` then `Scraping N companies (http×W, playwright×P)…` | `startup` (5s) |
| HTTP/API company fetch | Parallel pool per ATS handler (`greenhouse`, `ashby`, `lever`, `workday` CXS, `phenom`, `oracle_hcm`, `talentbrew`, `icims`, `smartrecruiters`, …) | `_run_company_pool(..., phase_label="HTTP/API scrape")` → `prepare_company_result_timed` → `search_company` → `SEARCH_HANDLERS[type]` | `HTTP/API scrape: N companies (×W workers, …)` | `http_scrape_total` (~495s @406 co), `http_per_company_p50` (2s), `http_per_company_p95` (15s) |
| Per-company verify (in HTTP/PW path) | HEAD/GET on posting URLs after fetch | `prepare_company_result` → `verify_jobs` (skip when `QUICKJOBS_VERIFY_ALL=0`) | Per-company rows when `QUICKJOBS_LOG_PROGRESS=1` (default): `  company-id  N  note` | (included in per-company p50/p95) |
| Playwright company fetch | Sequential pool, shared Chromium per worker | `_run_company_pool(..., phase_label="Playwright scrape")` → `_search_playwright` / workday PW / eightfold PW | `Playwright scrape: N companies …` | `playwright_scrape` (120s, not scaled) |
| Hub links | Non-scrape hub entries | `search_company` on `type=hub` after pools | Rows with note `hub link` in progress table | (part of scrape_total) |
| Scrape progress / heartbeats | Idle >60s during parallel pools | `_scrape_heartbeat_loop` → `_emit_scrape_heartbeat` | `… still scraping (HTTP\|Playwright, done/total companies done, Xm elapsed, W workers active)` | `scrape_total`, `scrape_progress`, `http_heartbeat_rate` |
| Scrape table flush | Config-order company table | `flush_company_progress` | `  N/N sources (…)`, `Companies (config order)`, `Elapsed: N min` | `scrape_total` |
| Salary enrichment | Company-level salary hints | `enrich_results_company_salary` (also inside `build_html`) | (no dedicated line) | part of `post_scrape` |
| Visa enrichment | Employer index lookup | `enrich_results_h1b` | (no dedicated line) | part of `post_scrape` |
| Dedupe / normalize | Cross-company posting dedupe | `dedupe_jobs_across_companies` | `Cross-company dedupe: removed N duplicate posting(s)` | `post_scrape` (30s) |
| Glassdoor prefetch | Rating cache before HTML render | `build_html` → `prefetch_glassdoor_for_all_companies` | `Glassdoor prefetch: N companies (×W workers)…` then `Glassdoor prefetch: ok/N cached` | `post_scrape` |
| HTML render / write | Template assembly + atomic write | `build_html`, `atomic_write_text`, `verify_written_file` | `Validated badge structure (N job cards, 4-column grid)` then `Wrote …job-search-david.html` | `html_write` (5s) |
| Snapshot validate / save | Shrink guard vs prior snapshot | `save_run_snapshot` | `Snapshot not saved: …` on failure; silent on success | part of post-scrape |
| Rolling backup | Numbered backups of script + HTML + snapshot | `rolling_backup_on_success` → `numbered_backup_copy` | `Rolling backup: saved N artifacts to ~/.numbered_backups/` (often silent) | `rolling_backup` (10s) |
| Wall clock | Full run | banner → log mtime | (implicit) | `total_wall_clock` (~644s @393, scale @406) |

### Heartbeat counter semantics

- `done/total` uses `_PROGRESS_TOTAL = len(scrape_selected)` (406 today: non-hub, not in `company_ids_exclude`).
- During HTTP phase, `done` is HTTP completions only; `total` stays 406 until Playwright starts.
- Expected progress: `scrape_progress` ratio ≥0.8 OK, ≥0.55 STALL (see `check_run_timing.py`).

### Handler → type field (HTTP pool)

| `type` | Fetch path |
|--------|------------|
| `greenhouse` | Greenhouse boards API |
| `ashby` | Ashby API |
| `lever` | Lever API |
| `workday` (cxs default) | Workday CXS API |
| `phenom` | Phenom search |
| `oracle_hcm` | Oracle HCM |
| `talentbrew` | TalentBrew / HTML |
| `icims` | iCIMS |
| `smartrecruiters` | SmartRecruiters API |
| `successfactors` | SuccessFactors |
| `playwright` / workday PW / eightfold PW | Playwright pool only |

---

## Companies at scrape positions 188–196 (406-company board)

Order: `companies_in_search_order`, minus hubs, minus `company_ids_exclude`.  
Regenerate: `list_scrape_positions.py --start 188 --end 196`

| Pos | id | type | phase |
|-----|-----|------|-------|
| 188 | arm-american | talentbrew | HTTP |
| 189 | at-t | talentbrew | HTTP |
| 190 | autozone | oracle_hcm | HTTP |
| 191 | bae-systems | phenom | HTTP |
| 192 | baker-hughes | phenom | HTTP |
| 193 | baxter-international | talentbrew | HTTP |
| 194 | becton-dickinson | talentbrew | HTTP |
| 195 | blackrock | talentbrew | HTTP |
| 196 | bny-mellon | oracle_hcm | HTTP |

At 190/406 heartbeat lag (Jun 23 180936Z run), position 190 is `autozone` (oracle_hcm). Neighbors mix talentbrew, phenom, and oracle_hcm handlers.

---

## Isolation tests

Run on the remote scrape host:

```bash
ssh user@remote-host
cd /path/to/quickjobs
./scripts/diagnostics/run_scrape_phase.sh <test-name>
```

Or from dev machine (delegates via SSH when configured):

```bash
./scripts/diagnostics/run_scrape_phase.sh --remote <test-name>
```

After each test, timing is checked automatically. Manual check:

```bash
~/.v/bin/python check_run_timing.py --baselines timing-baselines.yaml /path/to/quickjobs-run-*.log
```

### A. Bisection window (188–196)

| Test | Command / env | Pass | expected_sec (phase) |
|------|---------------|------|----------------------|
| `window-188-196-single` | Loop: `QUICKJOBS_VERIFY_ALL=0 quickjobs-run --only <id> --force-snapshot` for each id 188–196 | exit 0 each; per-co ≤30s | `http_per_company_p95` 120 stall |
| `window-188-196-batch` | One run, all nine `--only` flags | exit 0; wall ≤3m | `scrape_total` scaled (~15s × 9 co) |
| `window-autozone` | `QUICKJOBS_VERIFY_ALL=0 quickjobs-run --only autozone --force-snapshot` | exit 0; ≤45s | pos 190 suspect |
| `window-autozone-verify-on` | Default verify: `quickjobs-run --only autozone --force-snapshot` | exit 0; ≤120s | verify adds tail latency |
| `window-autozone-workers-1` | `QUICKJOBS_HTTP_WORKERS=1 QUICKJOBS_VERIFY_ALL=0 quickjobs-run --only autozone --force-snapshot` | exit 0 | isolate pool contention |

### B. Handler-focused (slow ATS types in window)

| Test | Command | Pass | expected_sec |
|------|---------|------|--------------|
| `phenom-pair` | `--only bae-systems --only baker-hughes` + `QUICKJOBS_VERIFY_ALL=0` | exit 0; ≤90s | 2 × p95 |
| `oracle-pair` | `--only autozone --only bny-mellon` + `QUICKJOBS_VERIFY_ALL=0` | exit 0; ≤90s | 2 × p95 |
| `talentbrew-triple` | `--only arm-american --only at-t --only baxter-international` + verify off | exit 0; ≤60s | 3 × p50 |

### C. Playwright phase (61 companies, not in HTTP counter)

| Test | Command | Pass | expected_sec |
|------|---------|------|--------------|
| `playwright-all` | All PW ids: `QUICKJOBS_VERIFY_ALL=0 quickjobs-run $(list_scrape_positions.py --playwright-only --ids-only \| sed 's/^/--only /') --force-snapshot` | exit 0 | `playwright_scrape` 120s warn 240s |
| `playwright-single-cisco` | `QUICKJOBS_VERIFY_ALL=0 quickjobs-run --only cisco --force-snapshot` | exit 0; ≤30s | single PW co |

### D. Verify-only isolation (post-fetch, no re-scrape)

Use a company known to return jobs; compare verify on vs off on same id:

| Test | Command | Pass | expected_sec |
|------|---------|------|--------------|
| `verify-off-openai` | `QUICKJOBS_VERIFY_ALL=0 quickjobs-run --only openai --force-snapshot` | exit 0 | ≤15s |
| `verify-on-openai` | `quickjobs-run --only openai --force-snapshot` | exit 0 | ≤45s |

Override workers: `QUICKJOBS_VERIFY_WORKERS=1` (serial verify).

### E. Post-scrape phases (no live scrape)

| Test | Command | Pass | expected_sec |
|------|---------|------|--------------|
| `post-dedupe-html` | `~/.v/bin/python quickjobs.david.py rebuild-snapshot` then `rebuild_board_from_snapshot.py` | HTML written | `post_scrape` 30s |
| `post-rolling-backup` | `quickjobs.david.py test-rolling-backup` | prints OK | `rolling_backup` 10s |

### F. Full-board timing smoke (short path)

| Test | Command | Pass | expected_sec |
|------|---------|------|--------------|
| `full-verify-off` | `QUICKJOBS_VERIFY_ALL=0 quickjobs-run --force-snapshot` | exit 0 | `scrape_total` ~632s @406, wall ~664s |
| `full-default` | `quickjobs-run` | exit 0 | same + verify overhead |

Do not run `full-*` while a production cron scrape is active unless confirmed stalled.

---

## Monitoring live run (180936Z pattern)

```bash
ssh user@remote-host \
  '/path/to/venv/bin/python /path/to/quickjobs/scripts/diagnostics/check_run_timing.py \
    /path/to/reports/quickjobs-run-2026-06-23T180936Z.log'
```

Exit codes: 0 OK/RUNNING, 1 WARN, 2 STALL, 3 in-progress deviation.

Do not kill a run unless `overall: STALL` (exit 2) or scrape_progress ratio <0.55 for >5 min with zero heartbeat delta.

---

## First bisection when HTTP stalls ~190/406

When `overall: STALL` or sustained WARN with flat heartbeat:

1. `QUICKJOBS_VERIFY_ALL=0 quickjobs-run --only autozone --force-snapshot` (position 190, oracle_hcm)
2. `QUICKJOBS_VERIFY_ALL=0 quickjobs-run --only bae-systems --force-snapshot` (phenom neighbor)
3. `./run_scrape_phase.sh window-188-196-single` (serial isolate all nine window companies)

If (1) hangs >120s: treat oracle_hcm fetch as suspect; retry with `QUICKJOBS_HTTP_WORKERS=1`.  
If (1) passes but full board stalls: run `window-188-196-batch` then bisect batch halves.

---

## Environment reference (in-run only)

| Variable | Effect |
|----------|--------|
| `QUICKJOBS_VERIFY_ALL=0` | Skip posting URL verify in `prepare_company_result` |
| `QUICKJOBS_VERIFY_WORKERS=N` | Parallel verify threads (default 8) |
| `QUICKJOBS_HTTP_WORKERS=N` | HTTP pool size (remote default often 16) |
| `QUICKJOBS_PLAYWRIGHT_WORKERS=N` | Playwright pool size (remote default often 8) |
| `QUICKJOBS_COMPANY_TIMEOUT_SEC` | Per-company wall (default 1200) |
| `QUICKJOBS_LOG_PROGRESS=0` | Suppress per-company log lines |
| `QUICKJOBS_SHARD_DAY=0-6` | Workday PW shard only |

CLI: `--only ID` (repeatable), `--force-snapshot`, `--exclude ID`, `-q`.
