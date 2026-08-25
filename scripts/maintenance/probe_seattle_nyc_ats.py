#!/usr/bin/env python3
"""Probe Greenhouse/Lever slugs for Seattle and NYC metro employers."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path.home() / "ws/scriptdir/output/quickjobs-reports/probe-seattle-nyc-2026-06-15.json"
BASE = Path(__file__).resolve().parents[2] / "quickjobs.david.base.json"

PLATFORM_RE = re.compile(
    r"sre|site reliability|platform|infrastructure|devops|kubernetes|terraform|"
    r"production engineer|observability|cloud engineer|developer productivity|"
    r"reliability engineer|systems engineer|release engineer|build engineer",
    re.I,
)
REMOTE_RE = re.compile(r"remote|#LI-Remote|work from home|WFH|anywhere", re.I)

# (company_id, display_name, slug, ats, region)
CANDIDATES: list[tuple[str, str, str, str, str]] = [
    # Seattle metro — Greenhouse
    ("remitly", "Remitly", "remitly", "gh", "seattle"),
    ("outreach", "Outreach", "outreach", "gh", "seattle"),
    ("smartsheet", "Smartsheet", "smartsheet", "gh", "seattle"),
    ("docusign", "DocuSign", "docusign", "gh", "seattle"),
    ("expedia", "Expedia Group", "expediagroup", "gh", "seattle"),
    ("expedia", "Expedia Group", "expedia", "gh", "seattle"),
    ("zillow", "Zillow", "zillow", "gh", "seattle"),
    ("zillow", "Zillow", "zillowgroup", "gh", "seattle"),
    ("tableau", "Tableau", "tableau", "gh", "seattle"),
    ("pagerduty", "PagerDuty", "pagerduty", "gh", "seattle"),
    ("auth0", "Auth0", "auth0", "gh", "seattle"),
    ("extrahop", "ExtraHop", "extrahop", "gh", "seattle"),
    ("apptio", "Apptio", "apptio", "gh", "seattle"),
    ("convoy", "Convoy", "convoy", "gh", "seattle"),
    ("offerup", "OfferUp", "offerup", "gh", "seattle"),
    ("rover", "Rover", "rover", "gh", "seattle"),
    ("qualtrics", "Qualtrics", "qualtrics", "gh", "seattle"),
    ("bigpanda", "BigPanda", "bigpanda", "gh", "seattle"),
    ("impinj", "Impinj", "impinj", "gh", "seattle"),
    ("chewy", "Chewy", "chewy", "gh", "seattle"),
    ("nordstrom", "Nordstrom", "nordstrom", "gh", "seattle"),
    ("skytap", "Skytap", "skytap", "gh", "seattle"),
    ("inrix", "INRIX", "inrix", "gh", "seattle"),
    ("chef", "Chef", "chef", "gh", "seattle"),
    ("highspot", "Highspot", "highspot", "gh", "seattle"),
    ("pluralsight", "Pluralsight", "pluralsight", "gh", "seattle"),
    ("domo", "Domo", "domo", "gh", "seattle"),
    ("avalara", "Avalara", "avalara", "gh", "seattle"),
    ("recroom", "Rec Room", "recroom", "gh", "seattle"),
    ("waabi", "Waabi", "waabi", "gh", "seattle"),
    ("anduril", "Anduril", "andurilindustries", "gh", "seattle"),
    ("skydio", "Skydio", "skydio", "gh", "seattle"),
    ("flexe", "Flexe", "flexe", "gh", "seattle"),
    ("pax8", "Pax8", "pax8", "gh", "seattle"),
    ("zipwhip", "Zipwhip", "zipwhip", "gh", "seattle"),
    ("formidable", "Formidable", "formidable", "gh", "seattle"),
    ("viz-ai", "Viz.ai", "vizai", "gh", "seattle"),
    ("blue-origin", "Blue Origin", "blueorigin", "gh", "seattle"),
    ("valve", "Valve", "valvesoftware", "gh", "seattle"),
    ("t-mobile", "T-Mobile", "tmobile", "gh", "seattle"),
    ("realnetworks", "RealNetworks", "realnetworks", "gh", "seattle"),
    ("f5", "F5", "f5networks", "gh", "seattle"),
    ("f5", "F5", "f5", "gh", "seattle"),
    ("unity", "Unity", "unity3d", "gh", "seattle"),
    ("temporal", "Temporal", "temporaltechnologies", "gh", "seattle"),
    ("snowflake", "Snowflake", "snowflake", "gh", "seattle"),
    ("databricks", "Databricks", "databricks", "gh", "seattle"),
    ("atlassian", "Atlassian", "atlassian", "gh", "seattle"),
    ("okta", "Okta", "okta", "gh", "seattle"),
    ("splunk", "Splunk", "splunk", "gh", "seattle"),
    ("nutanix", "Nutanix", "nutanix", "gh", "seattle"),
    ("zoominfo", "ZoomInfo", "zoominfo", "gh", "seattle"),
    ("articulate", "Articulate", "articulate", "gh", "seattle"),
    ("pitchbook", "PitchBook", "pitchbook", "gh", "seattle"),
    ("pitchbook", "PitchBook", "pitchbookdata", "gh", "seattle"),
    ("egencia", "Egencia", "egencia", "gh", "seattle"),
    ("vulcan", "Vulcan", "vulcan", "gh", "seattle"),
    ("getty-images", "Getty Images", "gettyimages", "gh", "seattle"),
    ("getty-images", "Getty Images", "getty", "gh", "seattle"),
    ("sap-concur", "SAP Concur", "concur", "gh", "seattle"),
    ("sap-concur", "SAP Concur", "sapconcur", "gh", "seattle"),
    ("sap", "SAP", "sap", "gh", "seattle"),
    ("starbucks", "Starbucks", "starbucks", "gh", "seattle"),
    ("costco", "Costco", "costco", "gh", "seattle"),
    ("alaska-air", "Alaska Airlines", "alaskaair", "gh", "seattle"),
    ("alaska-air", "Alaska Airlines", "alaskaairlines", "gh", "seattle"),
    ("boeing", "Boeing", "boeing", "gh", "seattle"),
    ("f5-networks", "F5 Networks", "f5", "gh", "seattle"),
    ("extrahop-networks", "ExtraHop", "extrahopnetworks", "gh", "seattle"),
    ("extrahop", "ExtraHop", "extrahopnetworks", "gh", "seattle"),
    ("smartsheet", "Smartsheet", "smartsheetinc", "gh", "seattle"),
    ("docusign", "DocuSign", "docusigninc", "gh", "seattle"),
    ("remitly", "Remitly", "remitlyinc", "gh", "seattle"),
    ("zillow", "Zillow", "zillowinc", "gh", "seattle"),
    ("outreach", "Outreach", "outreachcorporation", "gh", "seattle"),
    ("convoy", "Convoy", "convoyinc", "gh", "seattle"),
    ("rover", "Rover", "roverdotcom", "gh", "seattle"),
    ("chewy", "Chewy", "chewycom", "gh", "seattle"),
    ("qualtrics", "Qualtrics", "qualtricsxm", "gh", "seattle"),
    ("nordstrom", "Nordstrom", "nordstrominc", "gh", "seattle"),
    ("impinj", "Impinj", "impinjinc", "gh", "seattle"),
    ("inrix", "INRIX", "inrixinc", "gh", "seattle"),
    ("domo", "Domo", "domoinc", "gh", "seattle"),
    ("avalara", "Avalara", "avalarainc", "gh", "seattle"),
    ("pluralsight", "Pluralsight", "pluralsightinc", "gh", "seattle"),
    ("highspot", "Highspot", "highspotinc", "gh", "seattle"),
    ("skytap", "Skytap", "skytapinc", "gh", "seattle"),
    ("chef-software", "Chef Software", "chefsoftware", "gh", "seattle"),
    ("chef", "Chef", "chefsoftware", "gh", "seattle"),
    ("bigpanda", "BigPanda", "bigpandainc", "gh", "seattle"),
    ("apptio", "Apptio", "apptioinc", "gh", "seattle"),
    ("auth0", "Auth0", "auth0inc", "gh", "seattle"),
    ("extrahop", "ExtraHop", "extrahopinc", "gh", "seattle"),
    ("tableau", "Tableau", "tableausoftware", "gh", "seattle"),
    ("expedia", "Expedia", "expediacareers", "gh", "seattle"),
    ("expedia", "Expedia", "expediagroupinc", "gh", "seattle"),
    ("zillow", "Zillow", "zillowcareers", "gh", "seattle"),
    ("remitly", "Remitly", "remitlycareers", "gh", "seattle"),
    ("outreach", "Outreach", "outreachio", "gh", "seattle"),
    ("smartsheet", "Smartsheet", "smartsheetcareers", "gh", "seattle"),
    ("docusign", "DocuSign", "docusigncareers", "gh", "seattle"),
    ("convoy", "Convoy", "convoylogistics", "gh", "seattle"),
    ("offerup", "OfferUp", "offerupinc", "gh", "seattle"),
    ("rover", "Rover", "roverinc", "gh", "seattle"),
    ("chewy", "Chewy", "chewyinc", "gh", "seattle"),
    ("qualtrics", "Qualtrics", "qualtricscareers", "gh", "seattle"),
    ("nordstrom", "Nordstrom", "nordstromcareers", "gh", "seattle"),
    ("impinj", "Impinj", "impinjcareers", "gh", "seattle"),
    ("inrix", "INRIX", "inrixcareers", "gh", "seattle"),
    ("domo", "Domo", "domocareers", "gh", "seattle"),
    ("avalara", "Avalara", "avalaracareers", "gh", "seattle"),
    ("pluralsight", "Pluralsight", "pluralsightcareers", "gh", "seattle"),
    ("highspot", "Highspot", "highspotcareers", "gh", "seattle"),
    ("skytap", "Skytap", "skytapcareers", "gh", "seattle"),
    ("chef", "Chef", "chefcareers", "gh", "seattle"),
    ("bigpanda", "BigPanda", "bigpandacareers", "gh", "seattle"),
    ("apptio", "Apptio", "apptiocareers", "gh", "seattle"),
    ("auth0", "Auth0", "auth0careers", "gh", "seattle"),
    ("extrahop", "ExtraHop", "extrahopcareers", "gh", "seattle"),
    ("tableau", "Tableau", "tableaucareers", "gh", "seattle"),
    ("expedia", "Expedia", "expediacareers", "gh", "seattle"),
    ("zillow", "Zillow", "zillowcareers", "gh", "seattle"),
    ("remitly", "Remitly", "remitlycareers", "gh", "seattle"),
    ("outreach", "Outreach", "outreachcareers", "gh", "seattle"),
    ("smartsheet", "Smartsheet", "smartsheetcareers", "gh", "seattle"),
    ("docusign", "DocuSign", "docusigncareers", "gh", "seattle"),
    # NYC metro — Greenhouse
    ("etsy", "Etsy", "etsy", "gh", "nyc"),
    ("etsy", "Etsy", "etsyinc", "gh", "nyc"),
    ("squarespace", "Squarespace", "squarespace", "gh", "nyc"),
    ("yext", "Yext", "yext", "gh", "nyc"),
    ("peloton", "Peloton", "onepeloton", "gh", "nyc"),
    ("peloton", "Peloton", "peloton", "gh", "nyc"),
    ("warby-parker", "Warby Parker", "warbyparker", "gh", "nyc"),
    ("vercel", "Vercel", "vercel", "gh", "nyc"),
    ("flatiron-health", "Flatiron Health", "flatironhealth", "gh", "nyc"),
    ("better", "Better.com", "better", "gh", "nyc"),
    ("better", "Better.com", "betterdotcom", "gh", "nyc"),
    ("better", "Better.com", "bettercom", "gh", "nyc"),
    ("bloomberg", "Bloomberg", "bloomberg", "gh", "nyc"),
    ("bloomberg", "Bloomberg", "bloombergindustry", "gh", "nyc"),
    ("sp-global", "S&P Global", "spglobal", "gh", "nyc"),
    ("factset", "FactSet", "factset", "gh", "nyc"),
    ("broadridge", "Broadridge", "broadridge", "gh", "nyc"),
    ("mastercard", "Mastercard", "mastercard", "gh", "nyc"),
    ("american-express", "American Express", "americanexpress", "gh", "nyc"),
    ("amex", "Amex", "amex", "gh", "nyc"),
    ("ramp", "Ramp", "ramp", "gh", "nyc"),
    ("notion", "Notion", "notion", "gh", "nyc"),
    ("retool", "Retool", "retool", "gh", "nyc"),
    ("miro", "Miro", "miro", "gh", "nyc"),
    ("grammarly", "Grammarly", "grammarly", "gh", "nyc"),
    ("zoom", "Zoom", "zoom", "gh", "nyc"),
    ("datadog", "Datadog", "datadog", "gh", "nyc"),
    ("confluent", "Confluent", "confluent", "gh", "nyc"),
    ("hashicorp", "HashiCorp", "hashicorp", "gh", "nyc"),
    ("cockroach-labs", "Cockroach Labs", "cockroachlabs", "gh", "nyc"),
    ("mongodb", "MongoDB", "mongodb", "gh", "nyc"),
    ("two-sigma", "Two Sigma", "twosigma", "gh", "nyc"),
    ("jane-street", "Jane Street", "janestreet", "gh", "nyc"),
    ("citadel", "Citadel", "citadel", "gh", "nyc"),
    ("bny-mellon", "BNY Mellon", "bnymellon", "gh", "nyc"),
    ("iex", "IEX", "iex", "gh", "nyc"),
    ("oscar-health", "Oscar Health", "oscarhealth", "gh", "nyc"),
    ("dataminr", "Dataminr", "dataminr", "gh", "nyc"),
    ("block", "Block", "block", "gh", "nyc"),
    ("block", "Block", "square", "gh", "nyc"),
    ("block", "Block", "blocksquare", "gh", "nyc"),
    ("robinhood", "Robinhood", "robinhood", "gh", "nyc"),
    ("twilio", "Twilio", "twilio", "gh", "nyc"),
    ("stripe", "Stripe", "stripe", "gh", "nyc"),
    ("doordash", "DoorDash", "doordash", "gh", "nyc"),
    ("affirm", "Affirm", "affirm", "gh", "nyc"),
    ("spotify", "Spotify", "spotify", "gh", "nyc"),
    ("mongodb", "MongoDB", "mongodbinc", "gh", "nyc"),
    ("etsy", "Etsy", "etsycareers", "gh", "nyc"),
    ("squarespace", "Squarespace", "squarespacecareers", "gh", "nyc"),
    ("yext", "Yext", "yextinc", "gh", "nyc"),
    ("peloton", "Peloton", "pelotoncareers", "gh", "nyc"),
    ("warby-parker", "Warby Parker", "warbyparkercareers", "gh", "nyc"),
    ("vercel", "Vercel", "vercelcareers", "gh", "nyc"),
    ("flatiron-health", "Flatiron Health", "flatironhealthcareers", "gh", "nyc"),
    ("better", "Better.com", "bettercareers", "gh", "nyc"),
    ("bloomberg", "Bloomberg", "bloombergcareers", "gh", "nyc"),
    ("sp-global", "S&P Global", "spglobalcareers", "gh", "nyc"),
    ("factset", "FactSet", "factsetcareers", "gh", "nyc"),
    ("broadridge", "Broadridge", "broadridgecareers", "gh", "nyc"),
    ("mastercard", "Mastercard", "mastercardcareers", "gh", "nyc"),
    ("american-express", "American Express", "amexcareers", "gh", "nyc"),
    ("ramp", "Ramp", "rampcareers", "gh", "nyc"),
    ("notion", "Notion", "notioncareers", "gh", "nyc"),
    ("retool", "Retool", "retoolcareers", "gh", "nyc"),
    ("miro", "Miro", "mirocareers", "gh", "nyc"),
    ("grammarly", "Grammarly", "grammarlycareers", "gh", "nyc"),
    ("zoom", "Zoom", "zoomcareers", "gh", "nyc"),
    ("oscar-health", "Oscar Health", "oscar", "gh", "nyc"),
    ("dataminr", "Dataminr", "dataminrcareers", "gh", "nyc"),
    ("block", "Block", "blockcareers", "gh", "nyc"),
    ("robinhood", "Robinhood", "robinhoodcareers", "gh", "nyc"),
    ("twilio", "Twilio", "twiliocareers", "gh", "nyc"),
    ("stripe", "Stripe", "stripecareers", "gh", "nyc"),
    ("doordash", "DoorDash", "doordashcareers", "gh", "nyc"),
    ("affirm", "Affirm", "affirmcareers", "gh", "nyc"),
    ("spotify", "Spotify", "spotifycareers", "gh", "nyc"),
    ("mongodb", "MongoDB", "mongodbcareers", "gh", "nyc"),
    ("etsy", "Etsy", "etsycareers", "gh", "nyc"),
    ("squarespace", "Squarespace", "squarespacecareers", "gh", "nyc"),
    ("yext", "Yext", "yextcareers", "gh", "nyc"),
    ("peloton", "Peloton", "pelotoncareers", "gh", "nyc"),
    ("warby-parker", "Warby Parker", "warbyparkercareers", "gh", "nyc"),
    ("vercel", "Vercel", "vercelcareers", "gh", "nyc"),
    ("flatiron-health", "Flatiron Health", "flatironhealthcareers", "gh", "nyc"),
    ("better", "Better.com", "bettercareers", "gh", "nyc"),
    ("bloomberg", "Bloomberg", "bloombergcareers", "gh", "nyc"),
    ("sp-global", "S&P Global", "spglobalcareers", "gh", "nyc"),
    ("factset", "FactSet", "factsetcareers", "gh", "nyc"),
    ("broadridge", "Broadridge", "broadridgecareers", "gh", "nyc"),
    ("mastercard", "Mastercard", "mastercardcareers", "gh", "nyc"),
    ("american-express", "American Express", "amexcareers", "gh", "nyc"),
    ("ramp", "Ramp", "rampcareers", "gh", "nyc"),
    ("notion", "Notion", "notioncareers", "gh", "nyc"),
    ("retool", "Retool", "retoolcareers", "gh", "nyc"),
    ("miro", "Miro", "mirocareers", "gh", "nyc"),
    ("grammarly", "Grammarly", "grammarlycareers", "gh", "nyc"),
    ("zoom", "Zoom", "zoomcareers", "gh", "nyc"),
    ("oscar-health", "Oscar Health", "oscar", "gh", "nyc"),
    ("dataminr", "Dataminr", "dataminrcareers", "gh", "nyc"),
    ("block", "Block", "blockcareers", "gh", "nyc"),
    ("robinhood", "Robinhood", "robinhoodcareers", "gh", "nyc"),
    ("twilio", "Twilio", "twiliocareers", "gh", "nyc"),
    ("stripe", "Stripe", "stripecareers", "gh", "nyc"),
    ("doordash", "DoorDash", "doordashcareers", "gh", "nyc"),
    ("affirm", "Affirm", "affirmcareers", "gh", "nyc"),
    ("spotify", "Spotify", "spotifycareers", "gh", "nyc"),
    ("mongodb", "MongoDB", "mongodbcareers", "gh", "nyc"),
    # Lever
    ("flatiron-health", "Flatiron Health", "flatiron", "lever", "nyc"),
    ("oscar-health", "Oscar Health", "oscar", "lever", "nyc"),
    ("dataminr", "Dataminr", "dataminr", "lever", "nyc"),
    ("blockfi", "BlockFi", "blockfi", "lever", "nyc"),
    ("cockroach-labs", "Cockroach Labs", "cockroachlabs", "lever", "nyc"),
    ("grail", "Grail", "grailbio", "lever", "nyc"),
    ("outreach", "Outreach", "outreach", "lever", "seattle"),
    ("convoy", "Convoy", "convoy", "lever", "seattle"),
    ("rover", "Rover", "rover", "lever", "seattle"),
    ("chewy", "Chewy", "chewy", "lever", "seattle"),
    ("qualtrics", "Qualtrics", "qualtrics", "lever", "seattle"),
    ("nordstrom", "Nordstrom", "nordstrom", "lever", "seattle"),
    ("impinj", "Impinj", "impinj", "lever", "seattle"),
    ("inrix", "INRIX", "inrix", "lever", "seattle"),
    ("domo", "Domo", "domo", "lever", "seattle"),
    ("avalara", "Avalara", "avalara", "lever", "seattle"),
    ("pluralsight", "Pluralsight", "pluralsight", "lever", "seattle"),
    ("highspot", "Highspot", "highspot", "lever", "seattle"),
    ("skytap", "Skytap", "skytap", "lever", "seattle"),
    ("chef", "Chef", "chef", "lever", "seattle"),
    ("bigpanda", "BigPanda", "bigpanda", "lever", "seattle"),
    ("apptio", "Apptio", "apptio", "lever", "seattle"),
    ("auth0", "Auth0", "auth0", "lever", "seattle"),
    ("extrahop", "ExtraHop", "extrahop", "lever", "seattle"),
    ("tableau", "Tableau", "tableau", "lever", "seattle"),
    ("expedia", "Expedia", "expedia", "lever", "seattle"),
    ("zillow", "Zillow", "zillow", "lever", "seattle"),
    ("remitly", "Remitly", "remitly", "lever", "seattle"),
    ("outreach", "Outreach", "outreach", "lever", "seattle"),
    ("smartsheet", "Smartsheet", "smartsheet", "lever", "seattle"),
    ("docusign", "DocuSign", "docusign", "lever", "seattle"),
    ("etsy", "Etsy", "etsy", "lever", "nyc"),
    ("squarespace", "Squarespace", "squarespace", "lever", "nyc"),
    ("yext", "Yext", "yext", "lever", "nyc"),
    ("peloton", "Peloton", "peloton", "lever", "nyc"),
    ("warby-parker", "Warby Parker", "warbyparker", "lever", "nyc"),
    ("vercel", "Vercel", "vercel", "lever", "nyc"),
    ("flatiron-health", "Flatiron Health", "flatiron", "lever", "nyc"),
    ("better", "Better.com", "better", "lever", "nyc"),
    ("bloomberg", "Bloomberg", "bloomberg", "lever", "nyc"),
    ("sp-global", "S&P Global", "spglobal", "lever", "nyc"),
    ("factset", "FactSet", "factset", "lever", "nyc"),
    ("broadridge", "Broadridge", "broadridge", "lever", "nyc"),
    ("mastercard", "Mastercard", "mastercard", "lever", "nyc"),
    ("american-express", "American Express", "americanexpress", "lever", "nyc"),
    ("ramp", "Ramp", "ramp", "lever", "nyc"),
    ("notion", "Notion", "notion", "lever", "nyc"),
    ("retool", "Retool", "retool", "lever", "nyc"),
    ("miro", "Miro", "miro", "lever", "nyc"),
    ("grammarly", "Grammarly", "grammarly", "lever", "nyc"),
    ("zoom", "Zoom", "zoom", "lever", "nyc"),
    ("oscar-health", "Oscar Health", "oscar", "lever", "nyc"),
    ("dataminr", "Dataminr", "dataminr", "lever", "nyc"),
    ("block", "Block", "block", "lever", "nyc"),
    ("robinhood", "Robinhood", "robinhood", "lever", "nyc"),
    ("twilio", "Twilio", "twilio", "lever", "nyc"),
    ("stripe", "Stripe", "stripe", "lever", "nyc"),
    ("doordash", "DoorDash", "doordash", "lever", "nyc"),
    ("affirm", "Affirm", "affirm", "lever", "nyc"),
    ("spotify", "Spotify", "spotify", "lever", "nyc"),
    ("mongodb", "MongoDB", "mongodb", "lever", "nyc"),
]


def fetch_json(url: str) -> tuple[int, list | str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "quickjobs-probe/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        if isinstance(data, dict) and "jobs" in data:
            return len(data["jobs"]), data["jobs"]
        if isinstance(data, list):
            return len(data), data
        return 0, []
    except Exception as exc:
        return -1, str(exc)


def analyze_jobs(jobs: list, *, greenhouse: bool) -> tuple[int, int, list[str]]:
    plat = remote_plat = 0
    samples: list[str] = []
    for job in jobs:
        if greenhouse:
            title = job.get("title", "")
            loc = job.get("location", {})
            loc_name = loc.get("name", "") if isinstance(loc, dict) else str(loc)
            content = job.get("content", "") or ""
        else:
            title = job.get("text", "")
            loc_name = (job.get("categories") or {}).get("location", "")
            content = (job.get("descriptionPlain") or "") + (job.get("description") or "")
        text = f"{title} {loc_name} {content}"
        if PLATFORM_RE.search(title):
            plat += 1
            if REMOTE_RE.search(text):
                remote_plat += 1
                if len(samples) < 3:
                    samples.append(title[:70])
    return plat, remote_plat, samples


def main() -> int:
    base = hub_tools.load_base_bundle()
    by_id = {c["id"]: c for c in base["companies"]}
    boards = {c.get("board") for c in base["companies"] if c.get("board")}
    levers = {c.get("lever_site") for c in base["companies"] if c.get("lever_site")}

    seen_slugs: set[tuple[str, str]] = set()
    results: list[dict] = []
    best_by_id: dict[str, dict] = {}

    for cid, name, slug, ats, region in CANDIDATES:
        key = (ats, slug)
        if key in seen_slugs:
            continue
        seen_slugs.add(key)

        if ats == "gh":
            n, data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
            greenhouse = True
        else:
            n, data = fetch_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
            greenhouse = False

        if n < 0:
            continue

        plat, remote_plat, samples = analyze_jobs(data, greenhouse=greenhouse)
        on_board = cid in by_id or slug in boards or slug in levers
        row = {
            "id": cid,
            "name": name,
            "slug": slug,
            "ats": ats,
            "region": region,
            "jobs": n,
            "platform_jobs": plat,
            "remote_platform_jobs": remote_plat,
            "on_board": on_board,
            "samples": samples,
        }
        results.append(row)

        prev = best_by_id.get(cid)
        if not prev or (n, remote_plat, plat) > (prev["jobs"], prev["remote_platform_jobs"], prev["platform_jobs"]):
            best_by_id[cid] = row

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"all": results, "best_by_id": list(best_by_id.values())}, indent=2), encoding="utf-8")

    for region in ("seattle", "nyc"):
        print(f"\n=== {region.upper()} BEST HITS ===")
        hits = [r for r in best_by_id.values() if r["region"] == region and r["jobs"] > 0]
        hits.sort(key=lambda r: (-r["remote_platform_jobs"], -r["platform_jobs"], -r["jobs"]))
        for r in hits[:25]:
            flag = "ON" if r["on_board"] else "ADD"
            print(
                f"{flag:3} {r['name']:22} {r['ats']}:{r['slug']:22} "
                f"jobs={r['jobs']:4} plat={r['platform_jobs']:3} rplat={r['remote_platform_jobs']:3} {r['samples']}"
            )
    print(f"\nWrote {OUT} ({len(results)} probe hits, {len(best_by_id)} companies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
