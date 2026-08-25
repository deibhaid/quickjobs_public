# Quickjobs step isolation runbook

Use after a full-board run stalls or fails. Each step runs one pipeline piece with the same
pass/fail signals as production: exit code, log content, and `check_run_timing.py` where a
`quickjobs-run-*.log` is produced.

Runner: `run_step_isolation.sh <step>` (see bottom). Logs:
`<reports-dir>/step-<step>-<UTC-timestamp>.log`

Do not start remote scrape steps while a full-board scrape lock is held unless you have stopped
the stuck run.

---

## Preamble: current run status (2026-06-23)

| Field | Value |
|-------|-------|
| Log | `quickjobs-run-2026-06-23T180936Z.log` |
| Started | 2026-06-23 11:09:36 PDT (example pid on remote host) |
| Last log line | `still scraping (HTTP, 190/406 companies done, 8m elapsed, 16 workers active)` |
| Log mtime | Unchanged since ~11:18 PDT (heartbeat frozen at 190/406) |
| `check_run_timing.py` | overall **WARN** (`scrape_progress` 0.62x); process still alive at high CPU |
| Verdict | **STALLED at HTTP 190/406** — treat as failed for isolation work; do not kill unless you choose to |

Stall zone (HTTP execution pool order, 1-based positions 189–195):

| Pos | Company id | ATS type |
|-----|------------|----------|
| 189 | `at-t` | talentbrew |
| 190 | `autozone` | oracle_hcm (last reported done) |
| 191 | `bae-systems` | phenom |
| 192 | `baker-hughes` | phenom |
| 193 | `baxter-international` | talentbrew |
| 194 | `becton-dickinson` | talentbrew |
| 195 | `blackrock` | talentbrew |

Config-order positions 191–195 among scrape-selected companies (table printed at end of run):
`ibm`, `iex`, `incyte`, `insmed`, `instacart` (config order differs from parallel HTTP pool order).

Company mix (current profile): 406 scrape-selected (381 HTTP + 25 Playwright), 387 hub-link only.

Playwright-only companies (25): `alaska-airlines`, `alaska-airlines-it`, `american-airlines`,
`atlas-air`, `avelo-airlines`, `breeze-airways`, `cisco`, `delta-air-lines`, `frontier-airlines`,
`google`, `hawaiian-airlines`, `ibm`, `meta`, `microsoft`, `nike`, `nvidia`, `ohsu`,
`pilotsglobal-us`, `rivian`, `saic`, `schwab`, `skywest-airlines`, `spirit-airlines`,
`statefarm`, `sun-country-airlines`.

---

## Timing checker reference

Baselines: `timing-baselines.yaml` (anchor 393 companies; scale with `406/393` for full board).

```bash
~/.v/bin/python scripts/diagnostics/check_run_timing.py \
  --baselines scripts/diagnostics/timing-baselines.yaml \
  /path/to/reports/quickjobs-run-YYYY-MM-DDTHHMMSSZ.log
```

Exit codes: `0` OK/RUNNING in bounds, `1` WARN, `2` STALL, `3` in-progress deviation.

On remote host (remote log path):

```bash
ssh user@remote-host \
  '/path/to/venv/bin/python /path/to/quickjobs/scripts/diagnostics/check_run_timing.py \
    --baselines /path/to/quickjobs/scripts/diagnostics/timing-baselines.yaml \
    /path/to/reports/quickjobs-run-YYYY-MM-DDTHHMMSSZ.log'
```

`run_step_isolation.sh` runs this automatically when a step produces a scrape log.

---

## Step 1 — `portable` (Mac, non-destructive)

Build portable zip only; no remote sync, no scrape.

```bash
QUICKJOBS_PORTABLE_QUIET=1 quickjobs portable
```

| | |
|--|--|
| Expected duration | ~30–90s (no baseline entry; build + zip) |
| Pass | Exit 0; portable zip exists in configured output dir and size > 100KB |
| Timing check | N/A |
| Runner | `./run_step_isolation.sh portable` |

---

## Step 2 — `ssh-ping` (non-destructive)

SSH connectivity to remote scrape host only.

```bash
ssh -o ConnectTimeout=10 user@remote-host 'echo OK; hostname; date -u'
```

| | |
|--|--|
| Expected duration | < 5s |
| Pass | Exit 0; output contains `OK` |
| Timing check | N/A |
| Runner | `./run_step_isolation.sh ssh-ping` |

---

## Steps 3–8 — `sync` sub-steps (dev → remote)

Full sync is `quickjobs sync` (via your CLI install's `sync-remote`). Sub-steps mirror
`sync-remote` functions; each is safe while a remote scrape runs (code push can affect in-flight
run — prefer waiting for stall resolution before `sync-code`).

### 3 `sync-validate`

```bash
~/.v/bin/python quickjobs.py validate-static-config -q --dir .
```

| Expected | < 10s | Pass: exit 0 |

### 4 `sync-code`

Rsync static code/config only (`rsync --delete` for listed files). See `sync-remote` `sync_code`.

| Expected | 5–30s | Pass: exit 0; remote `quickjobs.py` mtime updates |

### 5 `sync-bins`

Push `quickjobs-run`, `quickjobs-run-shard`, `quickjobs-raise-nofile` to remote `~/local/bin/`.

| Expected | 5–15s | Pass: exit 0 |

### 6 `sync-pipeline`

Push `job-board-runtime.json` + derived pipeline JSON (no HTML/snapshot).

| Expected | 5–20s | Pass: exit 0; remote runtime file updated |

### 7 `sync-glassdoor`

Push Glassdoor cache from `$JOB_SEARCH_DIR/glassdoor/*.json`.

| Expected | 5–60s (file count) | Pass: exit 0 or skip if no local cache |

### 8 `sync-data`

Requires `QUICKJOBS_SYNC_PUSH_DATA=1` (pushes snapshot, digest, Mac HTML).

```bash
QUICKJOBS_SYNC_PUSH_DATA=1 QUICKJOBS_SYNC_QUIET=1 quickjobs sync
```

| Expected | 10–120s | Pass: exit 0 |

### 9 `sync-full`

Default sync (validate + code + bins + pipeline + glassdoor; skips HTML unless push-data).

```bash
QUICKJOBS_SYNC_QUIET=1 quickjobs sync
```

| Expected | 15–90s | Pass: exit 0 |

Skip HTML on ordinary run: `QUICKJOBS_SYNC_SKIP_DATA=1` (default for `quickjobs run`).

Runner for each: `./run_step_isolation.sh sync-validate` (etc.).

---

## Step 10 — `run-no-sync` (full board, remote)

Same as `quickjobs run` but skips pre-run sync.

```bash
QUICKJOBS_SYNC_BEFORE_RUN=0 quickjobs run
```

| Phase (timing-baselines.yaml) | expected_sec @406 co | warn_sec | stall_sec |
|-------------------------------|----------------------|----------|-----------|
| startup | 5 | 20 | 120 |
| http_scrape_total | ~495 | ~743 | ~1550 |
| playwright_scrape | 120 | 240 | 600 |
| scrape_total | ~632 | ~930 | ~1550 |
| post_scrape | 30 | 60 | 180 |
| html_write | 5 | 15 | 60 |
| total_wall_clock | ~666 | ~992 | ~1860 |

Pass: log contains `Wrote `; `check_run_timing.py` overall OK (not STALL).

Runner: `./run_step_isolation.sh run-no-sync` — refuses if remote scrape already running.

---

## Steps 11–15 — Stall-zone scrape isolation (remote)

Requires prior full-board snapshot on remote. Uses `--only` merge. Wait until the stuck
process ends or is stopped before running.

### 11 Single company (`only-<id>`)

Example position 191:

```bash
QUICKJOBS_SYNC_BEFORE_RUN=0 quickjobs run --only bae-systems
```

Also: `only-baker-hughes`, `only-baxter-international`, `only-becton-dickinson`,
`only-blackrock`, `only-autozone`, `only-at-t`.

| Expected | 5–120s per company (`http_per_company_p95` stall 120s) |
| Pass | Exit 0; log line for company; no timeout note; `Wrote ` at end |
| Timing | `check_run_timing` on resulting log; single-co scrape_total should be ≪ stall |

### 12 `stall-batch`

```bash
QUICKJOBS_SYNC_BEFORE_RUN=0 quickjobs run --only at-t --only autozone --only bae-systems
```

| Expected | 30–300s (3 companies) |
| Pass | All three ids appear in log; exit 0; `Wrote ` |

### 13 `http-w1-batch` / 14 `http-w16-batch`

Same batch with worker count:

```bash
QUICKJOBS_HTTP_WORKERS=1 QUICKJOBS_SYNC_BEFORE_RUN=0 quickjobs run \
  --only bae-systems --only baker-hughes --only baxter-international
```

Repeat with `QUICKJOBS_HTTP_WORKERS=16`. Compare duration and pass/fail to isolate worker-pool issues.

| w1 expected | ~3× p50 (6–45s) + tail |
| w16 expected | ~max(individual tails), often < 60s |

---

## Steps 16–17 — Full HTTP phase proxy (remote)

Scrape all HTTP companies only by excluding Playwright ids (25 companies). Long runs.

```bash
# workers=1 (sequential HTTP — slow; ~381 × ~2s ≈ 13+ min best case)
QUICKJOBS_HTTP_WORKERS=1 QUICKJOBS_SYNC_BEFORE_RUN=0 quickjobs run \
  --exclude alaska-airlines --exclude alaska-airlines-it ...  # all 25 pw ids

# workers=16 (production default)
QUICKJOBS_HTTP_WORKERS=16 QUICKJOBS_SYNC_BEFORE_RUN=0 quickjobs run --exclude ... 
```

| Phase | w16 expected | w1 expected |
|-------|--------------|-------------|
| http_scrape_total | ~495s | ~25–60+ min |
| scrape_total | ~632s (incl. pw skip) | much longer |

Pass: HTTP phase completes; `check_run_timing` http_scrape_total not STALL.

Runner: `./run_step_isolation.sh http-w16-all` / `http-w1-all` (script expands `--exclude` list).

---

## Steps 18–19 — Playwright isolation (remote)

### 18 `playwright-sample` (3 companies)

```bash
QUICKJOBS_SYNC_BEFORE_RUN=0 quickjobs run \
  --only nike --only microsoft --only google
```

| Expected | ~15–90s (`playwright_scrape` scaled for 3 co) |
| Pass | `Playwright scrape:` header; three ids complete; `Wrote ` |

### 19 `playwright-all` (25 companies)

```bash
QUICKJOBS_SYNC_BEFORE_RUN=0 quickjobs run --only <all 25 pw ids>
```

| Expected | ~120s baseline for 25 co (`playwright_scrape` in baselines) |
| Pass | Playwright phase completes; timing playwright_scrape < stall 600s |

---

## Step 20 — `verify-small` (remote)

Force URL verify on a tiny set (default verify is on; this step uses 3 fast HTTP companies).

```bash
QUICKJOBS_VERIFY_ALL=1 QUICKJOBS_VERIFY_WORKERS=4 QUICKJOBS_SYNC_BEFORE_RUN=0 \
  quickjobs run --only affirm --only coupa --only 1password
```

Pass: exit 0; no mass verify failures in log; `Wrote `.

Timing: scrape_total ≪ stall; verify adds modest overhead (not separately baselined).

---

## Step 21 — `post-scrape-rebuild` (remote or dev)

HTML write / post-scrape without live scrape (uses last snapshot).

On remote:

```bash
ssh user@remote-host \
  'cd /path/to/quickjobs && \
   QUICKJOBS_JOBS_DIR=/path/to/html JOB_SEARCH_DIR=/path/to/html \
   /path/to/venv/bin/python quickjobs.py rebuild-snapshot'
```

Or dev machine:

```bash
~/.v/bin/python scripts/diagnostics/rebuild_board_from_snapshot.py
```

| Phase | expected_sec | warn | stall |
|-------|--------------|------|-------|
| post_scrape | 30 | 60 | 180 |
| html_write | 5 | 15 | 60 |

Pass: `Wrote ` + `Validated badge structure` in output; exit 0.

Runner: `./run_step_isolation.sh post-scrape-rebuild`

---

## Step 22 — `check-stalled-log`

Re-check the known stalled run (no new scrape).

```bash
~/.v/bin/python scripts/diagnostics/check_run_timing.py \
  --baselines scripts/diagnostics/timing-baselines.yaml \
  /path/to/reports/quickjobs-run-2026-06-23T180936Z.log
```

Pass criteria for isolation: document result (expect STALL/WARN while frozen at 190/406).

Runner: `./run_step_isolation.sh check-stalled-log`

---

## Recommended isolation order

1. `ssh-ping`, `portable` (safe anytime)
2. `check-stalled-log` (baseline the failure)
3. After stall cleared: `sync-full` or sub-steps if sync suspected
4. `only-bae-systems` … `only-blackrock` (single-co stall zone)
5. `stall-batch`, then `http-w1-batch` vs `http-w16-batch`
6. `playwright-sample` then `playwright-all` if HTTP steps pass
7. `verify-small`, `post-scrape-rebuild`
8. `http-w16-all` vs `http-w1-all` only if needed (long)
9. `run-no-sync` full board last

---

## `run_step_isolation.sh` usage

```bash
cd /path/to/quickjobs/scripts/diagnostics
./run_step_isolation.sh list
./run_step_isolation.sh portable
./run_step_isolation.sh ssh-ping
./run_step_isolation.sh only-bae-systems
./run_step_isolation.sh check-stalled-log
```

Output: step log path, timing report when applicable, final line `RESULT: OK|WARN|FAIL`.

Scrape steps refuse to start if remote host already has `quickjobs.py` running (unless
`QUICKJOBS_ISOLATION_FORCE=1`).
