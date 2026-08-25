# Quickjobs (portable)

Self-contained job board scraper and HTML builder. Everything except your resume file lives inside this quickjobs/ folder.

## Quick start

1. Unzip so you have a quickjobs/ directory.

2. From inside that directory:
python3 configure.py

   Setup asks for your resume, resident status (citizen, green_card, or visa), whether to include aviation/airline/pilot jobs (default: no, excludes those employers for faster runs), ZIP, salary, and name.

3. Run a board refresh (full scrape; takes several minutes):
python_venv/bin/python run.py

4. Open `output/job-search-quickjobs.html` in a browser.

   Portable boards embed lazy-board JSON for `file://` opens. The same data is
   also written under `output/json_sidecars/` (for HTTP serving). If you open the
   HTML via a local server, the page prefers those sidecar files and falls back
   to the embedded scripts when fetch is unavailable.

More detail: see ARCHITECTURE.txt.
