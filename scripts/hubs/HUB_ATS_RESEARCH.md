# Hub ATS discovery — research and probe notes

Reference for `scripts/hubs/` tooling (`discover_hub_ats_paths.py`, `probe_hub_scrape_methods.py`, `fingerprint_hub_ats.py`).

## quickjobs fetchers already supported

| ATS | quickjobs `type` | Public endpoint pattern |
|-----|------------------|-------------------------|
| Greenhouse | `greenhouse` | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` |
| Lever | `lever` | `api.lever.co/v0/postings/{slug}?mode=json` |
| Ashby | `ashby` | `api.ashbyhq.com/posting-api/job-board/{slug}` |
| SmartRecruiters | `smartrecruiters` | `api.smartrecruiters.com/v1/companies/{id}/postings` |
| Phenom | `phenom` | `{origin}/widgets` POST `refineSearch` (refNum from HTML) |
| Oracle HCM CE | `oracle_hcm` | `{fa-host}/hcmRestApi/.../recruitingCEJobRequisitions` |
| SuccessFactors | `successfactors` | HTML `jobTitle-link` on `/search/` or `/go/Search/` |
| Talentbrew/Radancy | `talentbrew` | `/search-jobs/{keyword}` HTML cards |
| iCIMS | `icims` | `{host}.icims.com/jobs/search?ss=1&in_iframe=1` |
| Taleo CWS (modern) | `taleo_cws` | `{tbe-host}/searchResults?org=&cws=&keyword=` |
| Eightfold PCSX | `playwright` + `eightfold_fetch=pcsx` | `{host}/api/pcsx/search?domain=` |
| Workday CXS | `playwright` + `playwright_kind=workday` | POST `{tenant}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` |

## ATS with public-ish endpoints — not yet full fetchers

Probed and fingerprinted; discovery may record `config_hint` but keeps `type=hub` until a fetcher exists.

| ATS | Endpoint / method | F500 usage | Notes |
|-----|-------------------|------------|-------|
| Jobvite | `jobs.jobvite.com/{company}/jobs` HTML; optional authenticated `api.jobvite.com/v1/jobFeed` | Mid-market + enterprise | No universal public JSON API; HostedJobs widget varies by tier |
| Brassring (IBM) | POST `sjobs.brassring.com/TgNewUI/Search/Ajax/MatchedJobs` + `partnerid`/`siteid` | ~7 F500 (Apify census) | Session-based Ajax; needs Referer from Home URL |
| Avature | `{tenant}.avature.net/careers/SearchJobs` HTML | Ally, BofA events, Duke talent communities | JSON-LD on detail pages; search often 403 without browser session |
| ADP Workforce Now | `workforcenow.adp.com/mascsr/default/careersite/{cid}/jobs` | ~3 F500 | OData-style JSON when enabled |
| Taleo legacy (FTL) | POST `{co}.taleo.net/careersection/rest/jobboard/searchjobs` | Declining but still present | Needs career section id + optional portal; X-Requested-With |
| UKG/UltiPro | Tenant-specific; often login wall | Common in HRIS-heavy employers | Fingerprint only |
| Cornerstone | `csod.com` / Cornerstone careers embeds | Learning-heavy employers | Usually login or embed |
| PageUp, SilkRoad, Beamery, Gem, Dover | Mostly marketing embeds or CRM | Niche | Fingerprint patterns added |
| JazzHR, Breezy, Recruitee, Teamtailor, Pinpoint, Workable, BambooHR, Comeet, Personio, Fountain | Well-known SaaS job board URLs | SMB / mid-market | Apify career-site scraper documents JSON/HTML patterns; quickjobs targets F500 hubs first |

## Aggregator / syndication APIs (employer-direct preferred)

- JobsPipe, Jobo, Apify actors: normalize many ATS types; useful for research, not used in quickjobs F500 pipeline.
- Jobvite Job Feed, LinkedIn XML: opt-in per tenant, often disabled.
- SmartRecruiters v1 company postings API is employer-direct and already supported.

## Common probe failure modes (403 / 404 / 599)

| Symptom | Typical cause | Fix in hub tooling |
|---------|---------------|-------------------|
| 403 | Bot User-Agent (`QuickJobsProbe/1.0`), Cloudflare/DataDome | Browser UA + Accept-Language via `hub_http.py`; scan 403 body for ATS embed URLs |
| 404 | Marketing path stale (`/about-us/careers` vs `/our-company/careers`) | `KNOWN_HUB_URL_ALIASES`, redirect following (`curl -sL`) |
| 599 | Wrong guessed subdomain (`careers.{slug}.com` NXDOMAIN), curl timeout | Aliases from blocked TSV + Workday tenant URLs; timeout 35s |
| Login wall in HTML | Workday `/login` links on marketing site | `discover_workday_browse_urls()` skips login paths; probe CXS on job board URL |
| iCIMS empty | `internal-*.icims.com` redirect; missing `in_iframe=1` | Prefer `careers-` / `external-` hosts; `ss=1&in_iframe=1` |
| Oracle miss | Oracle CE URL deep in page (>80k) | Scan 250k HTML in `discover_oracle_from_html` |
| Workday 422 | CXS blocked off-VPN for some tenants | Keep as hub; note in journal |

## Sources consulted

- [OpenPostings ATS extraction guide (GitHub Discussion #16)](https://github.com/Masterjx9/OpenPostings/discussions/16)
- [Apify Career Site Jobs Scraper — 25+ ATS platforms](https://apify.com/santamaria-automations/career-site-jobs-scraper)
- [JobsPipe iCIMS / Jobvite guides](https://jobspipe.dev/guides/icims-jobs-api)
- [Taleo searchjobs reverse-engineering (jobo.world, GitHub gists)](https://jobo.world/ats/taleo)
- Oracle Taleo career section URL docs (`jobsearch.ftl`, REST `searchjobs`)
- Stack Overflow / Reddit threads on iCIMS `in_iframe=1`, Brassring Ajax

## Re-probe sample employers

Use:

```bash
~/.v/bin/python scripts/hubs/discover_hub_ats_paths.py \
  --ids abbvie,marvell-technology,agilent,advanced-micro-devices,howmet-aerospace,cardinal-health,duke-energy,bank-of-america,caterpillar,best-buy \
  --workers 4
```

Add `--apply` to patch `quickjobs.david.base.json` when `apply=yes` in discovery TSV.

## Pause and resume on network loss

Checkpoint file (written after each hub):

`~/ws/scriptdir/output/quickjobs-reports/quickjobs-discover-run-state.json`

When WiFi drops, `hub_network.py` counts consecutive transport failures (599 / curl
connection errors). A global pause triggers only when a connectivity probe also fails
(Google `generate_204` or ping to 1.1.1.1). HTTP 403 WAF blocks do not count as
network loss. Workers block until connectivity returns; the process does not exit.

| Flag | Effect |
|------|--------|
| (default) | Auto-resume when checkpoint file exists |
| `--resume` | Same; explicit resume if state file present |
| `--fresh` | Delete checkpoint and start over |

Full laptop pass:

```bash
~/.v/bin/python quickjobs_hubs.py discover --limit 0 --offset 0 --apply
# same command after WiFi reconnect, or add --resume
```

`--apply` conversions in `quickjobs.david.base.json` are incremental and persist across
pause/resume. Mid-hub pause clears partial progress for that hub and retries it from the
start when connectivity returns.

Optional env: `QUICKJOBS_HUB_NET_FAIL_THRESHOLD` (default 3),
`QUICKJOBS_HUB_NET_POLL_SEC` (default 10), `QUICKJOBS_HUB_PROBE_URL`.
