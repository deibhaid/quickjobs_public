#!/usr/bin/env python3
"""Validate extract_comp_range_from_text against known salary prose samples."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

BLACKROCK_NY_SALARY_TEXT = (
    "For New York, NY Only the salary range for this position is "
    "USD$137,500.00 - USD$194,000.00 . Additionally, employees are eligible for an annual discretionary bonus."
)

SAMPLES: dict[str, tuple[str, int, int]] = {
    "chime": (
        "The base salary offered for this role and level of experience will begin at "
        "$138,000.00 and up to $190,000.00.",
        138_000,
        190_000,
    ),
    "cigna": (
        "For this position, we anticipate offering an annual salary of "
        "79,000 - 131,600 USD / yearly",
        79_000,
        131_600,
    ),
    "discord": (
        "The US base salary range for this full-time position is "
        "$196,000 to $220,500 + equity + benefits.",
        196_000,
        220_500,
    ),
    "gm": (
        "The salary range for this position is $160,200 to $290,700 (good faith estimate)",
        160_200,
        290_700,
    ),
    "kentik": (
        "The compensation range for this position is: $190,000— $225,000",
        190_000,
        225_000,
    ),
    "lattice": (
        "The estimated annual cash salary for this role is $187,500- $234,500.",
        187_500,
        234_500,
    ),
    "marqeta": (
        "The new-hire base salary range for this position is: National: $198,100 - $247,600",
        198_100,
        247_600,
    ),
    "nextdoor": (
        "The starting salary for this role is expected to range from $ 165,000 to $250,000 on an annualized basis.",
        165_000,
        250_000,
    ),
    "ohsu": (
        "Salary Range $103,980 - $157,453 per year, with offer based on experience.",
        103_980,
        157_453,
    ),
    "ohsu_biaa": (
        "Salary Range $114,635 - $173,593 Department Overview OHSU Business Intelligence.",
        114_635,
        173_593,
    ),
    "automattic": (
        "Salary range: $70,000-$170,000 USD",
        70_000,
        170_000,
    ),
    "bosch_smartrecruiters": (
        "The base salary range for this position is $80,000-$100,000. "
        "Within the range, individual pay is determined based on several factors.",
        80_000,
        100_000,
    ),
    "aflac_successfactors": (
        "Salary Range: $88,000 - $140,000",
        88_000,
        140_000,
    ),
    "blackrock_ny": (
        BLACKROCK_NY_SALARY_TEXT,
        137_500,
        194_000,
    ),
    "ametek_successfactors": (
        "Compensation Employee Type: Salaried Currency: USD Salary Minimum: 90,000 "
        "Salary Maximum: 120,000 Disclaimer: Where a specific pay range is noted",
        90_000,
        120_000,
    ),
    "bae_phenom_full_time_salary_range": (
        "Pay Information Full-Time Salary Range: $118095 - $200762 "
        "Please note: This range is based on our market pay structures.",
        118_095,
        200_762,
    ),
    "apple_base_pay_between": (
        "The base pay range for this role is between $139,500 and $210,100, and your base pay will depend on your skills.",
        139_500,
        210_100,
    ),
    "apple_base_pay_between_dash": (
        "The base pay range for this role is between $139,500 - $210,100/yr and your base pay will depend on your skills.",
        139_500,
        210_100,
    ),
    "automattic_local_currency": (
        "Salary range: $70,000-$170,000 USD. Please note that salary ranges are global, "
        "regardless of location, and we pay in local currency.",
        70_000,
        170_000,
    ),
    "automattic_trailing_plus": (
        "Salary range: $120,000-$180,000+ USD. We have interview steps that take 2-3 weeks.",
        120_000,
        180_000,
    ),
    "aws_elemental": (
        "Salary Range $153,600/year to $207,800/year",
        153_600,
        207_800,
    ),
    "cboe": (
        "The anticipated base salary range for this role is $119,000 – $154,000.",
        119_000,
        154_000,
    ),
    "cboe_r4498": (
        "The anticipated base salary range for this role is $148,750–$192,500, with actual compensation determined by job-related factors.",
        148_750,
        192_500,
    ),
    "cboe_r4498_nb_hyphen": (
        "The anticipated base salary range for this role is $148,750‑$192,500, with actual compensation determined by job-related factors.",
        148_750,
        192_500,
    ),
    "schwab": (
        "USD $129,000.00 - $200,000.00 / Year",
        129_000,
        200_000,
    ),
    "chipotle": (
        "PAY TRANSPARENCY $182,000.00–$264,500.00 for this role.",
        182_000,
        264_500,
    ),
    "collins": (
        "The annual base salary range is 86,800 USD - 165,200 USD.",
        86_800,
        165_200,
    ),
    "conagra": (
        "Pay Range: $109,000-$159,000",
        109_000,
        159_000,
    ),
    "databricks": (
        "Local Pay Range $135,500—$186,350 USD",
        135_500,
        186_350,
    ),
    "disney": (
        "The hiring range for this position in Glendale, CA & Bristol, CT is $117,500 - $157,500.",
        117_500,
        157_500,
    ),
    "costco_levels": (
        "Level 1: $109,000 - $131,000\nLevel 2: $131,000 - $159,000\nLevel 3: $159,000 - $182,000",
        109_000,
        182_000,
    ),
    "ebay_workday": (
        "The base pay range for this position is expected in the range below:\n$98,000 - $130,800",
        98_000,
        130_800,
    ),
    "adobe_workday_us": (
        "Expected Pay Range: The U.S. pay range for this position is $139,000 -- $257,550 annually.",
        139_000,
        257_550,
    ),
    "adobe_workday_california": (
        "In California, the pay range for this position is $177,900 - $257,550",
        177_900,
        257_550,
    ),
    "adobe_workday_phone_guard": (
        "email accommodations@adobe.com or call +1 408-536-3015. "
        "The U.S. pay range for this position is $139,000 -- $257,550 annually.",
        139_000,
        257_550,
    ),
    "ecolab_workday": (
        "Annual or Hourly Compensation Range:\nThe pay range for this role is $100,000-$130,000",
        100_000,
        130_000,
    ),
    "eversource": (
        "The annual salary range for this position is:\n$151,650.00-$168,500.00",
        151_650,
        168_500,
    ),
    "google_usd": (
        "US: $116000 - $166000 (USD) + 15% bonus target + equity + benefits",
        116_000,
        166_000,
    ),
    "google_k": (
        "expected, full-time, annual base pay scale $169K - $224K",
        169_000,
        224_000,
    ),
    "grail_lever": (
        "Pay Range\n$142,300 - $195,700 per year",
        142_300,
        195_700,
    ),
    "humana_workday": (
        "Pay Range\nThe pay range for this role is $120,000 - $160,000 per year",
        120_000,
        160_000,
    ),
    "spacex_level": (
        "compensation and benefits: Pay Range: Level I: $125,000.00 - $150,000.00/per year "
        "Level II: $145,000.00 - $175,000.00/per year",
        125_000,
        175_000,
    ),
    "spacex_title": (
        "Pay Range: Software Engineer/Senior: $160,000.00 - $225,000.00/per year",
        160_000,
        225_000,
    ),
    "spacex_per_year_space": (
        "Pay Range: Level I: $100,000.00 - $115,000.00 per/year "
        "Level II: $110,000.00 - $135,000.00 per/year",
        100_000,
        135_000,
    ),
    "ford_grade": (
        "This position is a salary grade 5 and ranges from $56,400-$94,900. "
        "This position is a salary grade 6 and ranges from $74,300-$124,500.",
        56_400,
        124_500,
    ),
    "asana_between": (
        "For this role, the estimated base salary range is between $202,000 - $230,000.",
        202_000,
        230_000,
    ),
    "oracle_hiring_range": (
        "US: Hiring Range in USD from: $99,600 to $223,400 per annum.",
        99_600,
        223_400,
    ),
    "elastic_starting": (
        "The typical starting salary range for this role is: $133,100 — $210,600 USD",
        133_100,
        210_600,
    ),
    "lyft_geo": (
        "The base pay range for this position in the San Francisco area is $118,000 - $147,500",
        118_000,
        147_500,
    ),
    "gusto_targeted": (
        "Our cash compensation amount for this role is targeted at $180,000/yr to $200,000/yr "
        "in Denver & most remote locations",
        180_000,
        200_000,
    ),
    "temporal_dash": (
        "Compensation Base salary range - $212,000 to $237,000, depending on qualifications",
        212_000,
        237_000,
    ),
    "twilio_estimated": (
        "The estimated pay ranges for this role are as follows: $171,120.00 to $213,900.00",
        171_120,
        213_900,
    ),
    "pge_min_max": (
        "Bay Area Minimum:$136,000 Bay Area Maximum: $232,000",
        136_000,
        232_000,
    ),
    "anduril_us_range": (
        "US Salary Range $166,000 — $220,000 USD",
        166_000,
        220_000,
    ),
    "reddit_greenhouse": (
        'The base salary range for this position is:</div><div class="pay-range">'
        '<span>$190,800</span><span class="divider">&mdash;</span><span>$267,100 USD</span>',
        190_800,
        267_100,
    ),
    "sourcegraph_zones": (
        "The start of the IC2 pay band for each zone is listed below: "
        "Zone 1: $160,000 Zone 2: $128,000 Zone 3: $96,000 Zone 4: $64,000 "
        "Please speak with a recruiter. Interview process [30m] Recruiter Screen "
        "[45m] Hiring Manager [60m] Technical Interview",
        160_000,
        160_000,
    ),
    "stripe_pay_and_benefits": (
        "Pay and benefits\nThe annual US base salary range for this role is "
        "$214,600 - $321,800. For sales roles, the range provided is the role's "
        "On Target Earnings (OTE) range.",
        214_600,
        321_800,
    ),
    "render_ashby_k_range": (
        "$255K – $295K • Offers Equity",
        255_000,
        295_000,
    ),
    "wwr_k_annum": (
        "Salary: $100K - $150K / Annum\nLocation: 100% Remote (Continental United States)",
        100_000,
        150_000,
    ),
}

AFFIRM_USA_BASE_PAY_TEXT = (
    "USA base pay range (CA, WA, NY, NJ, CT) per year: $165,000 - 225,000 USD "
    "USA base pay range (all other U.S. states) per year: $146,000 - 206 ,000 USD"
)

AFFIRM_TIER_EXPECTATIONS: dict[str, tuple[str, int, int]] = {
    "affirm_or_remote": ("Remote US", 146_000, 206_000),
    "affirm_ca_onsite": ("San Francisco, CA", 165_000, 225_000),
}

BLOCK_ZONE_PAY_TEXT = (
    "Block takes a market-based approach to pay. U.S. locations are categorized into one of four zones "
    "based on a cost of labor index for that geographic area. "
    "Zone A: USD $189,000 - USD $283,600 "
    "Zone B: USD $179,600 - USD $269,400 "
    "Zone C: USD $170,100 - USD $255,100 "
    "Zone D: USD $160,700 - USD $241,100"
)

BLOCK_TIER_EXPECTATIONS: dict[str, tuple[str, int, int]] = {
    "block_or_remote": ("Remote US", 179_600, 269_400),
    "block_portland": ("Portland, OR", 179_600, 269_400),
    "block_nyc": ("New York, NY", 189_000, 283_600),
    "block_atlanta": ("Atlanta, GA", 170_100, 255_100),
    "block_unknown_remote": ("Remote - United States", 160_700, 241_100),
}

BLACKROCK_MULTI_LOCATION_TEXT = (
    "For Portland, OR Only the salary range for this position is USD$120,000.00 - USD$160,000.00 . "
    "For New York, NY Only the salary range for this position is USD$137,500.00 - USD$194,000.00 ."
)

BLACKROCK_LOCATION_EXPECTATIONS: dict[str, tuple[str, int, int]] = {
    "blackrock_ny_listing": ("New York, NY", 137_500, 194_000),
    "blackrock_or_profile_remote": ("Remote US", 120_000, 160_000),
    "blackrock_ny_only_remote": ("Remote US", 137_500, 194_000),
}

# US-only gating: comp prose may mention USD even for non-US postings.
US_SALARY_TEXT = (
    "The US base salary range for this full-time position is "
    "$196,000 to $220,500 + equity + benefits."
)

US_GATING_EXTRACT: dict[str, tuple[str, str, tuple[str, int, int] | None]] = {
    "us_location_parses": ("Remote - US", US_SALARY_TEXT, ("base", 196_000, 220_500)),
    "canada_location_skips": ("Toronto, ON, Canada", US_SALARY_TEXT, None),
}

US_GATING_DETAIL: dict[str, tuple[str, str, str, tuple[str, str | None]]] = {
    "uk_excluded_job_loc_skips": (
        "London, United Kingdom",
        "excluded",
        US_SALARY_TEXT,
        ("maybe", None),
    ),
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_playwright_icims_salary_checks(mod, cfg: dict) -> list[str]:
    """Playwright iCIMS path must extract JD salary (HTTP fetch_icims already did)."""
    failures: list[str] = []
    company = {
        "id": "ohsu",
        "default_loc": "local",
        "skip_profile_jd_blocklist": True,
    }
    records = [
        {
            "title": "BIAA Senior Applications Engineer (Application Engineer, Sr.)",
            "url": "https://externalcareers-ohsu.icims.com/jobs/38784/biaa-senior-applications-engineer/job",
            "location": "US-Remote",
            "description_text": (
                "Salary Range $114,635 - $173,593 Department Overview "
                "OHSU Business Intelligence team is seeking a Senior Application Engineer."
            ),
        }
    ]
    raw = mod.playwright_records_to_raw(records, company, cfg, kind="icims")
    if len(raw) != 1:
        failures.append(f"icims_playwright_ohsu: expected 1 RawPosting, got {len(raw)}")
        return failures
    posting = raw[0]
    if posting.salary in (None, "maybe") or not posting.salary_label:
        failures.append(
            "icims_playwright_ohsu: expected salary label from JD, "
            f"got salary={posting.salary!r} label={posting.salary_label!r}"
        )
    return failures


def run_affirm_tier_checks(mod, cfg: dict) -> list[str]:
    failures: list[str] = []
    high, oregon, other = mod.extract_usa_base_pay_geo_bands(AFFIRM_USA_BASE_PAY_TEXT)
    if other != (146_000, 206_000):
        failures.append(
            f"affirm_tier/bands: expected other (146000, 206000), got {other!r}"
        )
    if high != (165_000, 225_000):
        failures.append(
            f"affirm_tier/bands: expected high (165000, 225000), got {high!r}"
        )
    for name, (location_name, exp_low, exp_high) in AFFIRM_TIER_EXPECTATIONS.items():
        band = mod.pick_usa_base_pay_geo_band(
            high,
            other,
            oregon=oregon,
            location_name=location_name,
            cfg=cfg,
        )
        if band != (exp_low, exp_high):
            failures.append(
                f"affirm_tier/{name}: expected ({exp_low}, {exp_high}), got {band!r}"
            )
        result = mod.affirm_salary_from_detail(
            AFFIRM_USA_BASE_PAY_TEXT, cfg, location_name=location_name
        )
        if result[1] is None:
            failures.append(f"affirm_tier/{name}: expected salary label, got {result!r}")
    return failures


def run_blackrock_location_checks(mod, cfg: dict) -> list[str]:
    failures: list[str] = []
    bands = mod.extract_for_location_only_salary_bands(BLACKROCK_MULTI_LOCATION_TEXT)
    if len(bands) != 2:
        failures.append(f"blackrock_location/bands: expected 2 bands, got {bands!r}")
    for name, (location_name, exp_low, exp_high) in BLACKROCK_LOCATION_EXPECTATIONS.items():
        text = (
            BLACKROCK_MULTI_LOCATION_TEXT
            if name == "blackrock_or_profile_remote"
            else BLACKROCK_NY_SALARY_TEXT
        )
        result = mod.extract_comp_range_from_text(
            text, location_name=location_name, cfg=cfg
        )
        if result != ("base", exp_low, exp_high):
            failures.append(
                f"blackrock_location/{name}: expected ('base', {exp_low}, {exp_high}), got {result!r}"
            )
    return failures


def run_block_tier_checks(mod, cfg: dict) -> list[str]:
    failures: list[str] = []
    bands = mod.extract_letter_zone_bands(BLOCK_ZONE_PAY_TEXT)
    expected_bands = [
        ("A", 189_000, 283_600),
        ("B", 179_600, 269_400),
        ("C", 170_100, 255_100),
        ("D", 160_700, 241_100),
    ]
    if bands != expected_bands:
        failures.append(f"block_tier/bands: expected {expected_bands!r}, got {bands!r}")
    cfg_or = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "home_state": "OR"}}
    for name, (location_name, exp_low, exp_high) in BLOCK_TIER_EXPECTATIONS.items():
        use_cfg = cfg if name != "block_unknown_remote" else {
            "profile": {"salary_floor": 200_000, "home_zip": "73301", "home_state": "TX"},
        }
        band = mod.block_pick_zone_band(bands, location_name, use_cfg)
        if band != (exp_low, exp_high):
            failures.append(
                f"block_tier/{name}: expected ({exp_low}, {exp_high}), got {band!r}"
            )
        result = mod.block_salary_from_detail(
            BLOCK_ZONE_PAY_TEXT, use_cfg, location_name=location_name
        )
        if result[1] is None:
            failures.append(f"block_tier/{name}: expected salary label, got {result!r}")
    return failures


def run_checks(module_path: Path, label: str) -> list[str]:
    mod = load_module(f"salary_mod_{label}", module_path)
    failures: list[str] = []
    for name, (text, exp_low, exp_high) in SAMPLES.items():
        result = mod.extract_comp_range_from_text(text)
        if result != ("base", exp_low, exp_high):
            failures.append(f"{label}/{name}: expected ('base', {exp_low}, {exp_high}), got {result!r}")
    if label != "quickjobs":
        return failures
    for name, (location_name, text, expected) in US_GATING_EXTRACT.items():
        result = mod.extract_comp_range_from_text(text, location_name=location_name)
        if result != expected:
            failures.append(f"{label}/{name}: expected {expected!r}, got {result!r}")
    cfg: dict = {}
    for name, (location_name, job_loc, text, expected) in US_GATING_DETAIL.items():
        fn = getattr(mod, "salary_from_detail_text", None)
        if fn is None:
            failures.append(f"{label}/{name}: salary_from_detail_text missing")
            continue
        try:
            result = fn(text, cfg, location_name=location_name, job_loc=job_loc)
        except TypeError as exc:
            failures.append(f"{label}/{name}: salary_from_detail_text rejected job_loc ({exc})")
            continue
        if result != expected:
            failures.append(f"{label}/{name}: expected {expected!r}, got {result!r}")
    cfg = {"profile": {"salary_floor": 200_000, "home_zip": "97035", "home_state": "OR"}}
    failures.extend(run_playwright_icims_salary_checks(mod, cfg))
    failures.extend(run_affirm_tier_checks(mod, cfg))
    failures.extend(run_blackrock_location_checks(mod, cfg))
    failures.extend(run_block_tier_checks(mod, cfg))
    wwr_text = SAMPLES.get("wwr_k_annum")
    if wwr_text:
        text, exp_low, exp_high = wwr_text
        wwr_result = mod.wwr_extract_salary(text, cfg)
        if wwr_result[0] == "maybe" or not wwr_result[1]:
            failures.append(f"{label}/wwr_k_annum: wwr_extract_salary expected label, got {wwr_result!r}")
        else:
            comp = mod.extract_comp_range_from_text(text)
            if comp != ("base", exp_low, exp_high):
                failures.append(f"{label}/wwr_k_annum: extract_comp mismatch {comp!r}")
    return failures


def main() -> int:
    targets = (
        ("quickjobs", REPO_ROOT / "quickjobs.david.py"),
        ("job_board", REPO_ROOT.parent / "job-board" / "job_board.david.py"),
    )
    quickjobs_failures: list[str] = []
    job_board_failures: list[str] = []
    for label, path in targets:
        if not path.is_file():
            msg = f"{label}: missing module at {path}"
            if label == "quickjobs":
                quickjobs_failures.append(msg)
            else:
                job_board_failures.append(msg)
            continue
        failures = run_checks(path, label)
        if label == "quickjobs":
            quickjobs_failures.extend(failures)
        else:
            job_board_failures.extend(failures)

    if quickjobs_failures:
        print("FAIL (quickjobs)")
        for line in quickjobs_failures:
            print(f"  {line}")
        return 1

    print("PASS: quickjobs salary extraction and US gating samples")
    for name, (_, low, high) in SAMPLES.items():
        print(f"  {name}: base ${low:,}-${high:,}")
    for name in US_GATING_EXTRACT:
        print(f"  {name}")
    for name in US_GATING_DETAIL:
        print(f"  {name}")
    if job_board_failures:
        print(f"WARN: job_board fork had {len(job_board_failures)} sample mismatch(es) (ignored)")
        for line in job_board_failures[:5]:
            print(f"  {line}")
        if len(job_board_failures) > 5:
            print(f"  ... and {len(job_board_failures) - 5} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
