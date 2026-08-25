# quickjobs discover CLI

Dev-machine commands to run employer-catalog miners and sync conservative
add-candidates into `quickjobs.base.json`.

Invoke via the top-level `quickjobs` wrapper or directly:

```bash
~/.v/bin/python /path/to/quickjobs/scripts/discover/discover_cli.py discover dice
quickjobs discover dice
```

## Commands

### `quickjobs discover dice|hn|builtin|all`

Runs the schedulable miners under `scripts/{dice,hn,builtin}/`. Outputs land in
`~/ws/scriptdir/output/` (persistent catalogs + dated `*-new-candidates-*.json`
reports). Does not modify `quickjobs.base.json`.

Default profile (widest net):

| Source | Defaults |
|--------|----------|
| dice | No `--posted-date` (widest window), `--fingerprint api` |
| hn | `--fingerprint api` |
| builtin | `--fingerprint api --pages 5` |

`all` runs dice, then hn, then builtin sequentially.

Extra miner flags can be forwarded after `--`:

```bash
quickjobs discover dice -- --max-fingerprint 20
```

### `quickjobs discover-sync dice|hn|builtin|all`

Reads candidates and appends matching employers to `companies` in base.json.

Candidate source (per source): the newest
`~/ws/scriptdir/output/<source>-new-candidates-*.json`, field
`all_api_scrapable_direct_not_in_base`. If no report exists, falls back to the
persistent `<source>-employer-catalog.json` (API-scrapable, not in base).

Conservative filters (default unless overridden):

- `ats_api_scrapable == true`
- `ats_confidence == "high"` (skip `review`; use `--include-review` to allow)
- `is_agency == false` (`--include-agency` to allow)
- `in_base_json == false` (`--include-in-base` to allow)
- No salary floor (`--min-salary N` optional)

Safety:

- `--dry-run` — print ids/names that would be added; no backup or write
- `--limit N` — max adds per source per run (default 0 = no limit)

Idempotent: skips when company `id` already exists or the same ATS slug+type is
already present.

Before write: timestamped backup under `~/.numbered_backups/` mirroring the
absolute path, suffix `_M.D.Y_H:MM:SS`. For `discover-sync all`, one backup at
the start of the run (before any source writes).

After write: runs `quickjobs validate` and fails with restore instructions if invalid.

### `quickjobs validate`

Checks:

- `quickjobs.base.json` — valid JSON, duplicate ids, required fields per ATS type
- `quickjobs.profile.json` — valid JSON when present
- `quickjobs.py` — `py_compile`
- Delegates to `quickjobs.py validate-static-config` for tier keywords and core rules

## Examples

```bash
quickjobs discover all
quickjobs discover-sync dice --dry-run
quickjobs discover-sync dice --dry-run --limit 5
quickjobs discover-sync hn --limit 10
quickjobs validate
```
