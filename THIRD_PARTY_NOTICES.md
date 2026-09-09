# Third-party notices

quickjobs depends on the open-source components below. Each component
is licensed on its own terms. This file satisfies attribution and
notice requirements for source distributions. See also the `licenses/`
directory for full license texts commonly required at distribution time.

Regenerate this file after changing `requirements.txt`:

```bash
~/.v/bin/python scripts/_shared/generate_third_party_notices.py
```

## Python packages

| Package | Version | License | Source |
|---------|---------|---------|--------|
| attrs | 26.1.0 | MIT |  |
| brotli | 1.2.0 | MIT |  |
| certifi | 2026.4.22 | Mozilla Public License 2.0 (MPL 2.0) |  |
| cffi | 2.0.0 | MIT |  |
| curl_cffi | 0.15.0 | MIT |  |
| et_xmlfile | 2.0.0 | MIT License |  |
| greenlet | 3.5.1 | MIT AND PSF-2.0 |  |
| idna | 3.15 | BSD-3-Clause |  |
| markdown-it-py | 4.2.0 | MIT License |  |
| mdurl | 0.1.2 | MIT License |  |
| openpyxl | 3.1.5 | MIT License |  |
| outcome | 1.3.0.post0 | Apache Software License; MIT License |  |
| playwright | 1.60.0 | Apache-2.0 |  |
| pycparser | 3.0 | BSD-3-Clause |  |
| pyee | 13.0.1 | MIT License |  |
| Pygments | 2.20.0 | BSD-2-Clause |  |
| pypdf | 6.12.1 | BSD-3-Clause |  |
| PyYAML | 6.0.3 | MIT License |  |
| rich | 15.0.0 | MIT License |  |
| sniffio | 1.3.1 | Apache Software License; MIT License |  |
| sortedcontainers | 2.4.0 | Apache Software License |  |
| trio | 0.33.0 | MIT OR Apache-2.0 |  |
| typing_extensions | 4.15.0 | PSF-2.0 |  |

## Browser binaries (Playwright)

`playwright install chromium` downloads browser binaries that are not part of
this repository. Chromium and other Playwright-managed browsers are distributed
under their own licenses. See:

- https://github.com/microsoft/playwright-python/blob/main/LICENSE
- https://playwright.dev/docs/browsers

When you distribute a product that bundles or installs Playwright browsers,
include the applicable browser license notices.

## DOL and employer data

The optional H-1B employer index uses public U.S. Department of Labor LCA
disclosure files. Those files are government data with their own publication
terms. quickjobs does not claim ownership of DOL data or employer job postings
retrieved from third-party sites.

## Your responsibilities

- Install dependencies with `pip install -r requirements.txt` (and optional
  `brotli` for smaller lazy-board sidecars).
- Run `playwright install chromium` before using Playwright scrapers.
- Ship this file and the `licenses/` directory with any binary or source
  distribution you provide to others.
- Do not remove copyright or license notices from third-party components.
