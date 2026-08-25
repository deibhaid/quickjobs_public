#!/usr/bin/env python3
"""Add or update non-military aviation employers with pilot-focused search_keywords.

Idempotent: re-run with --apply to merge into quickjobs.david.base.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import hub_tools

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

OUT_PREVIEW = hub_tools.report_path("quickjobs-aviation-pilot-added.json")

PILOT_SEARCH_KEYWORDS = [
    "pilot",
    "first officer",
    "captain",
    "co-pilot",
    "copilot",
    "flight officer",
    "line pilot",
    "check airman",
    "chief pilot",
    "airline pilot",
    "cargo pilot",
    "corporate pilot",
    "flight crew",
    "aircraft commander",
    "instructor pilot",
    "direct entry captain",
    "direct entry first officer",
    "first officer fo",
    "captain ca",
]

AVIATION_UPDATE_IDS = (
    "united-airlines",
    "southwest",
    "jetblue",
    "alaska-airlines",
    "ups",
    "boeing",
    "fedex",
)

# Not passenger/cargo airlines — drop aviation sector so pilot-only runs skip them.
AVIATION_SECTOR_CLEAR_IDS = ("honeywell",)

ICIMS_DEFAULTS: dict[str, Any] = {
    "section": "matching",
    "sector": "aviation",
    "type": "icims",
    "search_keywords": PILOT_SEARCH_KEYWORDS,
    "default_salary": "maybe",
    "max_details": 12,
    "cache_ttl_hours": 24,
}


def icims_airline(
    company_id: str,
    name: str,
    host: str,
    *,
    label: str | None = None,
    playwright: bool = False,
) -> dict[str, Any]:
    row = deepcopy(ICIMS_DEFAULTS)
    browse = f"https://{host}.icims.com/jobs/search?ss=1&in_iframe=1"
    template = f"https://{host}.icims.com/jobs/search?searchKeyword={{query}}&ss=1&in_iframe=1"
    row.update(
        {
            "id": company_id,
            "name": name,
            "label": label or f"{name} (pilots)",
            "browse_url": browse,
            "search_url_template": template,
        }
    )
    if playwright:
        row["type"] = "playwright"
        row["playwright_kind"] = "icims"
        row.pop("skip_verify", None)
    return row


def workday_airline(
    company_id: str,
    name: str,
    browse_url: str,
    *,
    label: str | None = None,
) -> dict[str, Any]:
    return {
        "id": company_id,
        "name": name,
        "label": label or f"{name} (pilots — Workday)",
        "section": "matching",
        "sector": "aviation",
        "type": "playwright",
        "playwright_kind": "workday",
        "workday_fetch": "playwright",
        "browse_url": browse_url,
        "search_keywords": PILOT_SEARCH_KEYWORDS,
        "default_salary": "maybe",
        "max_details": 12,
        "cache_ttl_hours": 24,
        "skip_verify": True,
    }


def hub_airline(
    company_id: str,
    name: str,
    hub_url: str,
    *,
    label: str | None = None,
    note: str = "Pilot careers — verify URL; OAuth/blocked ATS may need manual apply",
) -> dict[str, Any]:
    return {
        "id": company_id,
        "name": name,
        "label": label or f"{name} (pilots — careers link)",
        "section": "matching",
        "sector": "aviation",
        "type": "hub",
        "hub_url": hub_url,
        "hub_note": note,
        "search_keywords": PILOT_SEARCH_KEYWORDS,
        "default_salary": "maybe",
    }


PILOTSGLOBAL_US_LC = "04dba4cc2f"


def pilotsglobal_us_feed() -> dict[str, Any]:
    """Aggregated US pilot vacancies (478+ listings); complements per-airline scrapers."""
    base = f"https://pilotsglobal.com/jobs?lc%5B%5D={PILOTSGLOBAL_US_LC}"
    lc = f"lc%5B%5D={PILOTSGLOBAL_US_LC}"
    return {
        "id": "pilotsglobal-us",
        "name": "PilotsGlobal",
        "label": "PilotsGlobal (US pilot job board)",
        "section": "matching",
        "sector": "aviation",
        "type": "playwright",
        "playwright_kind": "pilotsglobal",
        "browse_url": base,
        "listing_urls": [
            base,
            f"https://pilotsglobal.com/jobs/first-officer?{lc}",
            f"https://pilotsglobal.com/jobs/captain?{lc}",
            f"https://pilotsglobal.com/jobs/instructor?{lc}",
            f"https://pilotsglobal.com/jobs/airline?{lc}",
        ],
        "scroll_count": 24,
        "scroll_wait_ms": 1000,
        "max_details": 150,
        "remote_card_only": False,
        "search_keywords": PILOT_SEARCH_KEYWORDS
        + [
            "flight instructor",
            "cfi",
            "cfii",
            "instructor",
            "ground instructor",
            "certified flight instructor",
        ],
        "default_salary": "maybe",
        "cache_ttl_hours": 12,
        "skip_verify": True,
        "hub_note": "Aggregated pilot vacancies; scrolls PilotsGlobal US listings",
    }


def new_or_upgraded_companies() -> list[dict[str, Any]]:
    return [
        pilotsglobal_us_feed(),
        workday_airline(
            "american-airlines",
            "American Airlines",
            "https://aa.wd1.myworkdayjobs.com/en-US/External",
        ),
        workday_airline(
            "delta-air-lines",
            "Delta Air Lines",
            "https://delta.wd1.myworkdayjobs.com/en-US/DeltaAirLines",
        ),
        workday_airline(
            "frontier-airlines",
            "Frontier Airlines",
            "https://flyfrontier.wd1.myworkdayjobs.com/en-US/FrontierCareers",
        ),
        workday_airline(
            "hawaiian-airlines",
            "Hawaiian Airlines",
            "https://hawaiianairlines.wd1.myworkdayjobs.com/en-US/External",
        ),
        workday_airline(
            "atlas-air",
            "Atlas Air",
            "https://atlasair.wd1.myworkdayjobs.com/en-US/AtlasAir",
            label="Atlas Air (cargo pilots — Workday)",
        ),
        workday_airline(
            "breeze-airways",
            "Breeze Airways",
            "https://flybreeze.wd1.myworkdayjobs.com/en-US/Breeze",
        ),
        workday_airline(
            "avelo-airlines",
            "Avelo Airlines",
            "https://aveloair.wd1.myworkdayjobs.com/en-US/AveloCareers",
        ),
        workday_airline(
            "sun-country-airlines",
            "Sun Country Airlines",
            "https://suncountry.wd1.myworkdayjobs.com/en-US/SunCountryCareers",
        ),
        icims_airline(
            "spirit-airlines",
            "Spirit Airlines",
            "corporatecareers-spirit",
            playwright=True,
        ),
        icims_airline("envoy-air", "Envoy Air", "careers-envoyair", label="Envoy Air (American Eagle — pilots)"),
        icims_airline("skywest-airlines", "SkyWest Airlines", "careers-skywest", playwright=True),
        {
            "id": "allegiant-air",
            "name": "Allegiant Air",
            "label": "Allegiant Air (pilots)",
            "section": "matching",
            "sector": "aviation",
            "type": "lever",
            "lever_site": "allegiantair",
            "browse_url": "https://www.allegiantair.com/careers",
            "search_keywords": PILOT_SEARCH_KEYWORDS,
            "default_salary": "maybe",
            "max_details": 12,
            "cache_ttl_hours": 24,
            "skip_verify": True,
        },
        {
            "id": "flexjet",
            "name": "Flexjet",
            "label": "Flexjet (corporate pilots)",
            "section": "matching",
            "sector": "aviation",
            "type": "phenom",
            "phenom_base": "https://careers.flexjet.com",
            "phenom_refnum": "OJAOJCUS",
            "browse_url": "https://careers.flexjet.com/us/en",
            "search_keywords": PILOT_SEARCH_KEYWORDS,
            "default_salary": "maybe",
            "max_details": 12,
            "cache_ttl_hours": 24,
        },
        hub_airline(
            "republic-airways",
            "Republic Airways",
            "https://www.rjet.com/careers/",
            label="Republic Airways (regional pilots)",
        ),
        hub_airline(
            "endeavor-air",
            "Endeavor Air",
            "https://www.endeavorair.com/careers/",
            label="Endeavor Air (Delta Connection — pilots)",
        ),
        hub_airline(
            "psa-airlines",
            "PSA Airlines",
            "https://www.psaairlines.com/careers/",
            label="PSA Airlines (American Eagle — pilots)",
        ),
        hub_airline(
            "piedmont-airlines",
            "Piedmont Airlines",
            "https://www.piedmont-airlines.com/careers/",
            label="Piedmont Airlines (American Eagle — pilots)",
        ),
        hub_airline("mesa-airlines", "Mesa Airlines", "https://www.mesa-air.com/careers/"),
        hub_airline("gojet-airlines", "GoJet Airlines", "https://www.gojetairlines.com/careers/"),
        hub_airline("air-wisconsin", "Air Wisconsin", "https://www.airwis.com/careers/"),
        hub_airline(
            "horizon-air",
            "Horizon Air",
            "https://www.horizonair.com/careers/",
            label="Horizon Air (Alaska Horizon — pilots)",
        ),
        hub_airline(
            "netjets",
            "NetJets",
            "https://www.netjets.com/en-us/careers",
            label="NetJets (fractional/corporate pilots)",
        ),
        hub_airline(
            "kalitta-air",
            "Kalitta Air",
            "https://www.kalittaair.com/about-us/careers/",
            label="Kalitta Air (cargo pilots)",
        ),
        hub_airline(
            "abx-air",
            "ABX Air",
            "https://www.abxair.com/careers/",
            label="ABX Air (cargo pilots)",
        ),
        hub_airline(
            "air-transport-international",
            "Air Transport International",
            "https://www.airtransport.cc/careers/",
            label="Air Transport International (cargo pilots)",
        ),
        hub_airline("jsx", "JSX", "https://www.jsx.com/careers", label="JSX (pilots)"),
        hub_airline(
            "ameriflight",
            "Ameriflight",
            "https://www.ameriflight.com/careers/",
            label="Ameriflight (cargo/feeder pilots)",
        ),
        hub_airline("cape-air", "Cape Air", "https://www.capeair.com/careers/pilot/"),
        hub_airline(
            "wheels-up",
            "Wheels Up",
            "https://www.wheelsup.com/careers",
            label="Wheels Up (charter pilots)",
        ),
        hub_airline(
            "southern-airways",
            "Southern Airways Express",
            "https://www.iflysouthern.com/careers",
            label="Southern Airways Express (pilots)",
        ),
        hub_airline(
            "commuteair",
            "CommuteAir",
            "https://www.commuteair.com/careers/",
            label="CommuteAir (regional pilots)",
        ),
        hub_airline(
            "vista-global",
            "Vista Global / XO",
            "https://vistaglobal.com/careers/",
            label="Vista Global (corporate pilots)",
        ),
        hub_airline(
            "plane-sense",
            "PlaneSense",
            "https://www.planesense.com/careers/",
            label="PlaneSense (fractional pilots)",
        ),
        hub_airline(
            "surf-air",
            "Surf Air",
            "https://www.surfair.com/careers",
            label="Surf Air (charter pilots)",
        ),
        # ── Cargo / freight (additional) ─────────────────────────────────────
        hub_airline(
            "omni-air-international",
            "Omni Air International",
            "https://www.omniairintl.com/careers/",
            label="Omni Air International (cargo/charter pilots)",
        ),
        hub_airline(
            "national-airlines",
            "National Airlines",
            "https://www.nationalairlines.com/careers/",
            label="National Airlines (cargo pilots)",
        ),
        hub_airline(
            "amerijet",
            "Amerijet International",
            "https://www.amerijet.com/careers/",
            label="Amerijet (cargo pilots)",
        ),
        hub_airline(
            "northern-air-cargo",
            "Northern Air Cargo",
            "https://www.northernaircargo.com/careers/",
            label="Northern Air Cargo (cargo pilots)",
        ),
        hub_airline(
            "western-global-airlines",
            "Western Global Airlines",
            "https://www.westernglobal.com/careers/",
            label="Western Global Airlines (cargo pilots)",
        ),
        hub_airline(
            "21-air",
            "21 Air",
            "https://www.21air.com/careers/",
            label="21 Air (cargo pilots)",
        ),
        hub_airline(
            "air-cargo-carriers",
            "Air Cargo Carriers",
            "https://www.aircargocarriers.com/careers/",
            label="Air Cargo Carriers (cargo pilots)",
        ),
        hub_airline(
            "empire-airlines",
            "Empire Airlines",
            "https://www.empireairlines.com/careers/",
            label="Empire Airlines (feeder/cargo pilots)",
        ),
        hub_airline(
            "everts-air-cargo",
            "Everts Air Cargo",
            "https://www.evertsair.com/employment/",
            label="Everts Air Cargo (cargo pilots)",
        ),
        hub_airline(
            "lynden-air-cargo",
            "Lynden Air Cargo",
            "https://www.lynden.com/lac/careers/",
            label="Lynden Air Cargo (cargo pilots)",
        ),
        hub_airline(
            "aloha-air-cargo",
            "Aloha Air Cargo",
            "https://www.alohaaircargo.com/careers/",
            label="Aloha Air Cargo (cargo pilots)",
        ),
        hub_airline(
            "miami-air-international",
            "Miami Air International",
            "https://www.miamiair.com/careers/",
            label="Miami Air International (charter/cargo pilots)",
        ),
        hub_airline(
            "southern-air",
            "Southern Air",
            "https://www.southernair.com/careers/",
            label="Southern Air (cargo/ACMI pilots)",
        ),
        hub_airline(
            "castle-aviation",
            "Castle Aviation",
            "https://www.castleaviation.com/careers/",
            label="Castle Aviation (cargo/feeder pilots)",
        ),
        hub_airline(
            "martinaire",
            "Martinaire",
            "https://www.martinaire.com/careers/",
            label="Martinaire (feeder cargo pilots)",
        ),
        hub_airline(
            "baron-aviation",
            "Baron Aviation Services",
            "https://www.baronaviation.com/careers/",
            label="Baron Aviation (feeder/cargo pilots)",
        ),
        hub_airline(
            "wiggins-airways",
            "Wiggins Airways",
            "https://www.wiggins-air.com/careers/",
            label="Wiggins Airways (feeder cargo pilots)",
        ),
        hub_airline(
            "solairus-aviation",
            "Solairus Aviation",
            "https://www.solairus.aero/careers/",
            label="Solairus Aviation (charter/corporate pilots)",
        ),
        hub_airline(
            "amazon-air-ati",
            "Amazon Air",
            "https://www.airtransport.cc/careers/",
            label="Amazon Air contractor — Air Transport International (cargo pilots)",
        ),
        # ── Passenger / regional / charter (additional) ──────────────────────
        hub_airline(
            "silver-airways",
            "Silver Airways",
            "https://www.silverairways.com/careers/",
            label="Silver Airways (regional pilots)",
        ),
        hub_airline(
            "contour-airlines",
            "Contour Aviation",
            "https://www.contourairlines.com/careers/",
            label="Contour Aviation (regional pilots; Contour Airlines careers site)",
        ),
        hub_airline(
            "boutique-air",
            "Boutique Air",
            "https://www.boutiqueair.com/careers/",
            label="Boutique Air (regional pilots)",
        ),
        hub_airline(
            "advanced-air",
            "Advanced Air",
            "https://www.advancedairlines.com/careers/",
            label="Advanced Air (charter/regional pilots)",
        ),
        hub_airline(
            "air-choice-one",
            "Air Choice One",
            "https://www.airchoiceone.com/careers/",
            label="Air Choice One (regional pilots)",
        ),
        hub_airline(
            "new-pacific-airlines",
            "New Pacific Airlines",
            "https://www.flynewpacific.com/careers/",
            label="New Pacific Airlines (pilots)",
        ),
        hub_airline(
            "ravn-alaska",
            "Ravn Alaska",
            "https://www.flyravn.com/careers/",
            label="Ravn Alaska (regional pilots)",
        ),
        hub_airline(
            "grant-aviation",
            "Grant Aviation",
            "https://www.flygrant.com/careers/",
            label="Grant Aviation (Alaska bush/regional pilots)",
        ),
        hub_airline(
            "kenmore-air",
            "Kenmore Air",
            "https://www.kenmoreair.com/careers/",
            label="Kenmore Air (seaplane/regional pilots)",
        ),
        hub_airline(
            "harbour-air",
            "Harbour Air",
            "https://www.harbourair.com/careers/",
            label="Harbour Air (seaplane pilots)",
        ),
        hub_airline(
            "penair",
            "PenAir",
            "https://www.penair.com/careers/",
            label="PenAir (regional pilots)",
        ),
        hub_airline(
            "bering-air",
            "Bering Air",
            "https://www.beringair.com/careers/",
            label="Bering Air (Alaska regional pilots)",
        ),
        hub_airline(
            "gulfstream-international",
            "Gulfstream International Airlines",
            "https://www.gulfstreamair.com/careers/",
            label="Gulfstream International (regional pilots)",
        ),
        hub_airline(
            "mokulele-airlines",
            "Mokulele Airlines",
            "https://www.mokuleleairlines.com/careers/",
            label="Mokulele Airlines (regional pilots)",
        ),
        hub_airline(
            "piedmont-flight-ops",
            "Piedmont Flight Operations",
            "https://www.piedmont-airlines.com/careers/pilots/",
            label="Piedmont Airlines — pilot careers (direct link)",
        ),
        hub_airline(
            "psa-pilot-recruiting",
            "PSA Airlines Pilots",
            "https://www.psaairlines.com/careers/pilots/",
            label="PSA Airlines — pilot careers (direct link)",
        ),
        hub_airline(
            "republic-pilot-recruiting",
            "Republic Airways Pilots",
            "https://www.rjet.com/careers/pilots/",
            label="Republic Airways — pilot careers (direct link)",
        ),
        hub_airline(
            "endeavor-pilot-recruiting",
            "Endeavor Air Pilots",
            "https://www.endeavorair.com/careers/pilots/",
            label="Endeavor Air — pilot careers (direct link)",
        ),
        hub_airline(
            "fedex-pilot-recruiting",
            "FedEx Express Pilots",
            "https://careers.fedex.com/express/pilot",
            label="FedEx Express — pilot careers (direct link)",
        ),
        hub_airline(
            "ups-pilot-recruiting",
            "UPS Airlines Pilots",
            "https://www.jobs-ups.com/global/en/search-results?keywords=pilot",
            label="UPS Airlines — pilot search (direct link)",
        ),
        # ── Medevac / air ambulance ───────────────────────────────────────────
        hub_airline(
            "air-methods",
            "Air Methods",
            "https://www.airmethods.com/careers/",
            label="Air Methods (HEMS pilots)",
        ),
        hub_airline(
            "life-flight-network",
            "Life Flight Network",
            "https://www.lifeflight.org/careers/",
            label="Life Flight Network (Oregon/Washington HEMS pilots)",
        ),
        hub_airline(
            "guardian-flight",
            "Guardian Flight",
            "https://www.guardianflight.com/careers/",
            label="Guardian Flight (air ambulance pilots)",
        ),
        hub_airline(
            "reach-air-medical",
            "REACH Air Medical",
            "https://www.reachair.com/careers/",
            label="REACH Air Medical (HEMS pilots)",
        ),
        hub_airline(
            "classic-air-medical",
            "Classic Air Medical",
            "https://www.classicairmedical.com/careers/",
            label="Classic Air Medical (air ambulance pilots)",
        ),
        hub_airline(
            "airevac-lifeteam",
            "AirEvac Lifeteam",
            "https://www.airevaclifeteam.com/careers/",
            label="AirEvac Lifeteam (HEMS pilots)",
        ),
        hub_airline(
            "med-trans",
            "Med-Trans",
            "https://www.med-trans.com/careers/",
            label="Med-Trans (air ambulance pilots)",
        ),
        # ── Fire / aerial firefighting ────────────────────────────────────────
        hub_airline(
            "coulson-aviation",
            "Coulson Aviation",
            "https://www.coulsonaviation.com/careers/",
            label="Coulson Aviation (firefighting pilots)",
        ),
        hub_airline(
            "erickson-inc",
            "Erickson Inc",
            "https://www.ericksoninc.com/careers/",
            label="Erickson Inc (heavy-lift/fire pilots)",
        ),
        hub_airline(
            "10-tanker",
            "10 Tanker Air Carrier",
            "https://www.10tanker.com/careers/",
            label="10 Tanker (fire bomber pilots)",
        ),
        hub_airline(
            "neptune-aviation",
            "Neptune Aviation Services",
            "https://www.neptuneaviation.com/careers/",
            label="Neptune Aviation (fire tanker pilots)",
        ),
        hub_airline(
            "aero-air",
            "Aero Air / Aero Flite",
            "https://www.aeroair.com/careers/",
            label="Aero Air (fire/utility pilots)",
        ),
        # ── Offshore / utility / EMS helicopter ─────────────────────────────
        hub_airline(
            "bristow-group",
            "Bristow Group",
            "https://www.bristowgroup.com/careers/",
            label="Bristow Group (offshore/utility helicopter pilots)",
        ),
        hub_airline(
            "phi-helicopters",
            "PHI",
            "https://www.phihelico.com/careers/",
            label="PHI (offshore/utility helicopter pilots)",
        ),
        # ── Flightseeing / tourism / Part 135 tour ──────────────────────────
        hub_airline(
            "maverick-helicopters",
            "Maverick Helicopters",
            "https://www.maverickhelicopter.com/careers/",
            label="Maverick Helicopters (Grand Canyon tour pilots)",
        ),
        hub_airline(
            "papillon-grand-canyon",
            "Papillon Grand Canyon Helicopters",
            "https://www.papillon.com/careers/",
            label="Papillon (tour pilots)",
        ),
        hub_airline(
            "grand-canyon-airlines",
            "Grand Canyon Airlines",
            "https://www.grandcanyonairlines.com/careers/",
            label="Grand Canyon Airlines (tour pilots)",
        ),
        hub_airline(
            "talkeetna-air-taxi",
            "Talkeetna Air Taxi",
            "https://www.talkeetnaair.com/careers/",
            label="Talkeetna Air Taxi (Alaska bush/tour pilots)",
        ),
        hub_airline(
            "k2-aviation",
            "K2 Aviation",
            "https://www.flyk2.com/careers/",
            label="K2 Aviation (Alaska glacier/tour pilots)",
        ),
        hub_airline(
            "rusts-flying-service",
            "Rust's Flying Service",
            "https://www.flyrusts.com/careers/",
            label="Rust's Flying Service (Alaska floatplane pilots)",
        ),
        hub_airline(
            "wings-air-helicopters",
            "Wings Air Helicopters",
            "https://www.wingsairhelicopters.com/careers/",
            label="Wings Air Helicopters (Hawaii tour pilots)",
        ),
        hub_airline(
            "blue-hawaiian-helicopters",
            "Blue Hawaiian Helicopters",
            "https://www.bluehawaiian.com/careers/",
            label="Blue Hawaiian Helicopters (tour pilots)",
        ),
        hub_airline(
            "paramount-aviation",
            "Paramount Aviation Resources",
            "https://www.paramountaviation.com/careers/",
            label="Paramount Aviation (tour/utility pilots)",
        ),
        hub_airline(
            "scenic-airlines",
            "Scenic Airlines",
            "https://www.scenic.com/careers/",
            label="Scenic Airlines (tour pilots)",
        ),
        # ── Flight training / instructing ─────────────────────────────────────
        hub_airline(
            "atp-flight-school",
            "ATP Flight School",
            "https://atpflightschool.com/become-a-cfi/careers/",
            label="ATP Flight School (CFI/instructor pilots)",
        ),
        hub_airline(
            "cae",
            "CAE",
            "https://www.cae.com/careers/",
            label="CAE (sim/training pilots and instructors)",
        ),
        hub_airline(
            "flightsafety-international",
            "FlightSafety International",
            "https://www.flightsafety.com/careers/",
            label="FlightSafety International (instructor pilots)",
        ),
        hub_airline(
            "hillsboro-aero-academy",
            "Hillsboro Aero Academy",
            "https://www.hillsboroaviation.com/careers/",
            label="Hillsboro Aero Academy (Portland-area CFI/instructor)",
        ),
        hub_airline(
            "embry-riddle",
            "Embry-Riddle Aeronautical University",
            "https://careers.erau.edu/",
            label="Embry-Riddle (instructor/university pilots)",
        ),
        # ── Charter / corporate (additional) ────────────────────────────────
        hub_airline(
            "jet-aviation",
            "Jet Aviation",
            "https://www.jetaviation.com/careers/",
            label="Jet Aviation (corporate/charter pilots)",
        ),
        hub_airline(
            "duncan-aviation",
            "Duncan Aviation",
            "https://www.duncanaviation.aero/careers/",
            label="Duncan Aviation (corporate pilots/MRO flight ops)",
        ),
        hub_airline(
            "magellan-jets",
            "Magellan Jets",
            "https://www.magellanjets.com/careers/",
            label="Magellan Jets (charter pilots)",
        ),
        hub_airline(
            "flyexclusive",
            "flyExclusive",
            "https://www.flyexclusive.com/careers/",
            label="flyExclusive (charter pilots)",
        ),
        # ── Agricultural / utility / survey ─────────────────────────────────
        hub_airline(
            "aero-agricultural",
            "Aerial Applicators (industry)",
            "https://www.agaviation.org/careers/",
            label="NAAREF / ag aviation (crop-dusting employers — industry hub)",
            note="National ag aviation association — links to operator members",
        ),
        hub_airline(
            "woolpert-aviation",
            "Woolpert",
            "https://woolpert.com/careers/",
            label="Woolpert (survey/mapping aviation pilots)",
        ),
        # ── Government / contract civilian pilots ───────────────────────────
        hub_airline(
            "faa-pilot",
            "FAA",
            "https://www.usajobs.gov/Search?k=faa%20pilot",
            label="FAA (USAJOBS — pilot positions)",
            note="Federal pilot jobs via USAJOBS",
        ),
        hub_airline(
            "dyncorp-international",
            "DynCorp International",
            "https://www.dyn-intl.com/careers/",
            label="DynCorp International (contract pilot positions)",
        ),
        hub_airline(
            "aar-corp",
            "AAR Corp",
            "https://www.aarcorp.com/en/careers/",
            label="AAR Corp (MRO/contract flight ops)",
        ),
        # ── Pilot job boards (aggregators) ──────────────────────────────────
        hub_airline(
            "jsfirm",
            "JSfirm",
            "https://www.jsfirm.com/",
            label="JSfirm (pilot job board)",
            note="Aggregated pilot listings — search manually",
        ),
        hub_airline(
            "climbto350",
            "Climbto350",
            "https://www.climbto350.com/",
            label="Climbto350 (pilot job board)",
            note="Aggregated pilot listings — search manually",
        ),
        hub_airline(
            "aviation-interviews",
            "AviationInterviews.com",
            "https://www.aviationinterviews.com/",
            label="AviationInterviews.com (pilot hiring intel + links)",
            note="Pilot hiring resources and employer links",
        ),
        hub_airline(
            "pilotjobsnetwork",
            "PilotJobsNetwork",
            "https://www.pilotjobsnetwork.com/",
            label="PilotJobsNetwork (pilot job board)",
        ),
        # ── Additional passenger / regional ───────────────────────────────────
        hub_airline(
            "air-canada",
            "Air Canada",
            "https://careers.aircanada.com/",
            label="Air Canada (pilots — verify US work eligibility)",
        ),
        hub_airline(
            "westjet",
            "WestJet",
            "https://careers.westjet.com/",
            label="WestJet (pilots — verify US work eligibility)",
        ),
        hub_airline(
            "lufthansa-group",
            "Lufthansa Group airlines",
            "https://lufthansagroup.careers/en",
            label="Lufthansa Group (international airline pilots)",
        ),
        hub_airline(
            "cathay-pacific",
            "Cathay Pacific",
            "https://careers.cathaypacific.com/",
            label="Cathay Pacific (international airline pilots)",
        ),
    ]


def merge_company(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    merged.update(patch)
    return merged


def apply(base: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    by_id = {c["id"]: c for c in base["companies"]}
    log: list[str] = []

    for company_id in AVIATION_UPDATE_IDS:
        if company_id not in by_id:
            log.append(f"skip update (missing): {company_id}")
            continue
        row = by_id[company_id]
        row["search_keywords"] = list(PILOT_SEARCH_KEYWORDS)
        row["sector"] = "aviation"
        if company_id == "fedex":
            row["section"] = "matching"
            row["label"] = "FedEx (cargo pilots — careers link)"
            row["hub_note"] = "Cargo pilot hiring — verify careers.fedex.com; may need Pilot Credentials"
        log.append(f"updated keywords: {company_id}")

    for company_id in AVIATION_SECTOR_CLEAR_IDS:
        if company_id in by_id:
            by_id[company_id].pop("sector", None)
            log.append(f"cleared aviation sector: {company_id}")

    for patch in new_or_upgraded_companies():
        cid = patch["id"]
        if cid in by_id:
            by_id[cid] = merge_company(by_id[cid], patch)
            log.append(f"upgraded: {cid}")
        else:
            by_id[cid] = patch
            log.append(f"added: {cid}")

    base["companies"] = sorted(by_id.values(), key=lambda c: c["id"])
    return base, log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write quickjobs.david.base.json")
    args = parser.parse_args()

    base = hub_tools.load_base_bundle()
    updated, log = apply(base)

    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    OUT_PREVIEW.write_text(
        json.dumps({"log": log, "count": len(updated["companies"])}, indent=2),
        encoding="utf-8",
    )

    for line in log:
        print(line)
    print(f"companies: {len(base['companies'])} -> {len(updated['companies'])}")

    if args.apply:
        hub_tools.save_base_bundle(updated)
        print(f"wrote {BASE_JSON}")
    else:
        print(f"dry-run preview: {OUT_PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
