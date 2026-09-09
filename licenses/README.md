# SPDX and common license texts

This directory contains full license texts for third-party components used by
quickjobs. Package-level attribution lives in `THIRD_PARTY_NOTICES.md`.

| File | Used for |
|------|----------|
| `Apache-2.0.txt` | Playwright and other Apache-2.0 components |
| `MIT.txt` | MIT-licensed Python dependencies |
| `BSD-3-Clause.txt` | BSD-licensed Python dependencies |
| `MPL-2.0.txt` | certifi (Mozilla Public License 2.0) |

Regenerate `THIRD_PARTY_NOTICES.md` after changing `requirements.txt`:

```bash
~/.v/bin/python scripts/_shared/generate_third_party_notices.py
```
