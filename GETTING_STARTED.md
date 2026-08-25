# Getting started (public clone)

This repository is the shareable quickjobs tree: employer ATS scrapers, company
catalog, and board HTML builder. It ships a placeholder profile (`User`) so
`validate-static-config` and config load work immediately after clone.

LinkedIn job scraping and live Glassdoor rating fetch are disabled here (no
network calls). Other ATS types (Greenhouse, Ashby, Lever, Workday, JSON feeds,
etc.) work as usual.

## 1. Clone and bootstrap

```bash
git clone https://github.com/YOUR_GITHUB_USER/quickjobs_public.git
cd quickjobs_public

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

Or:

```bash
./scripts/_shared/bootstrap_clone.sh
```

## 2. Confirm config loads

```bash
python quickjobs.py validate-static-config --dir .
```

Edit `quickjobs.profile.json` for your name, ZIP, salary floor, and
`jobs_dir` (HTML output directory). Defaults write under `~/Downloads/jobs`.

## 3. First scrape (small)

Full catalog scrapes take a long time. Start with a few API-friendly employers.
With no prior snapshot, `--only` seeds a new one from just these sources:

```bash
python quickjobs.py --only remotive,remoteok,weworkremotely
```

Open the HTML path printed at the end (under `profile.jobs_dir`). Later, run
without `--only` once for a full catalog, or keep using `--only` for smoke checks.

Default title filters in `quickjobs.base.json` are DevOps-oriented; a first
`--only remotive` run may write an empty board (exit 0) until you edit search
keywords / profile. That still proves scrape + HTML write work.

## 4. Optional: portable layout

For a self-contained install directory with its own venv, see
[portable/README.md](portable/README.md) and `build_portable_package.py`.

## Notes

- Do not commit a real personal profile to a public fork; keep secrets local.
- Operator docs in `HOWTO.md` / `README.md` still describe advanced workflows
  (discovery, hubs). Prefer this file for first run.
- Re-sync from a private upstream (if you maintain one) via
  `scripts/_shared/sync_public_repo.sh` on the private side — it re-applies
  stubs and personal scrubbing.
