#!/usr/bin/env python3
"""Add S&P 500 and Nasdaq-100 companies as hub entries in quickjobs.david.base.json.

Sources:
  - S&P 500: Wikipedia table (saved markdown or live fetch)
  - Nasdaq-100: slickcharts.com table

Skips symbols/names already in quickjobs.david.base.json. New rows use type=hub
(section=hubs) with a best-guess careers URL (verify via probe later).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import hub_tools

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

DEFAULT_SP500_MD = (
    Path.home()
    / ".cursor/projects/Users-example-ws-github/uploads/List_of_S_P_500_companies-1.md"
)
DEFAULT_NASDAQ_MD = hub_tools.REPO_ROOT / "data" / "nasdaq100-slickcharts.md"
NASDAQ_URL = "https://www.slickcharts.com/nasdaq100"
USER_AGENT = "Mozilla/5.0 (compatible; QuickJobsIndexHub/1.0)"

SEARCH_KEYWORDS = [
    "devops",
    "site reliability engineer",
    "platform engineer",
    "cloud engineer",
    "infrastructure engineer",
    "systems engineer",
    "principal engineer",
    "staff engineer",
    "software engineer",
]

# Tickers mapped to existing quickjobs company ids (skip adding duplicates).
TICKER_TO_EXISTING_ID: dict[str, str] = {
    "AAPL": "apple",
    "MSFT": "microsoft",
    "GOOGL": "google",
    "GOOG": "google",
    "AMZN": "amazon-jobs",
    "META": "meta",
    "NFLX": "netflix",
    "NVDA": "nvidia",
    "INTC": "intel",
    "CSCO": "cisco",
    "ORCL": "oracle",
    "CRM": "salesforce",
    "ADBE": "adobe",
    "PYPL": "paypal",
    "BKNG": "booking",
    "ABNB": "airbnb",
    "UBER": "uber",
    "LYFT": "lyft",
    "SHOP": "shopify",
    "SNOW": "snowflake",
    "PLTR": "palantir",
    "ZS": "zscaler",
    "DDOG": "datadog",
    "CRWD": "crowdstrike",
    "PANW": "palo-alto-networks",
    "FTNT": "fortinet",
    "WDAY": "workday",
    "NOW": "servicenow",
    "IBM": "ibm",
    "V": "visa",
    "MA": "mastercard",
    "JPM": "jpmorgan",
    "BAC": "bank-of-america",
    "WMT": "walmart",
    "TGT": "target",
    "COST": "costco",
    "HD": "home-depot",
    "LOW": "lowes",
    "TSLA": "tesla",
    "F": "ford",
    "GM": "gm",
    "BA": "boeing",
    "LMT": "lockheed-martin",
    "RTX": "rtx",
    "NOC": "northrop-grumman",
    "HON": "honeywell",
    "UPS": "ups",
    "FDX": "fedex",
    "UNH": "unitedhealth",
    "CVS": "cvs-health",
    "HUM": "humana",
    "PFE": "pfizer",
    "MRK": "merck",
    "ABBV": "abbvie",
    "JNJ": "jnj",
    "LLY": "lilly",
    "BMY": "bristol-myers-squibb",
    "AMGN": "amgen",
    "GILD": "gilead",
    "ISRG": "intuitive-surgical",
    "VRTX": "vertex",
    "REGN": "regeneron",
    "BIIB": "biogen",
    "SYK": "stryker",
    "MDT": "medtronic",
    "DHR": "danaher",
    "TXN": "texas-instruments",
    "QCOM": "qualcomm",
    "AVGO": "broadcom",
    "MU": "micron",
    "AMAT": "applied-materials",
    "LRCX": "lam-research",
    "KLAC": "kla",
    "ADI": "analog-devices",
    "SNPS": "synopsys",
    "CDNS": "cadence",
    "ADSK": "autodesk",
    "INTU": "intuit",
    "ADP": "adp",
    "BLK": "blackrock",
    "BX": "blackstone",
    "GS": "goldman-sachs",
    "MS": "morgan-stanley",
    "AXP": "american-express",
    "C": "citi",
    "WFC": "wellsfargo",
    "USB": "us-bancorp",
    "PNC": "pnc",
    "TFC": "truist",
    "COF": "capitalone",
    "SCHW": "schwab",
    "ICE": "ice",
    "CME": "cme-group",
    "SPGI": "sp-global",
    "MCO": "moodys",
    "MMC": "marsh-mclennan",
    "AON": "aon",
    "CB": "chubb",
    "PGR": "progressive",
    "ALL": "allstate",
    "TRV": "travelers",
    "MET": "metlife",
    "PRU": "prudential",
    "AIG": "aig",
    "BK": "bank-of-new-york-mellon",
    "STT": "state-street",
    "NKE": "nike",
    "SBUX": "starbucks",
    "MCD": "mcdonalds",
    "PEP": "pepsi",
    "KO": "coca-cola",
    "PG": "procter-gamble",
    "CL": "colgate-palmolive",
    "EL": "estee-lauder",
    "MDLZ": "mondelez",
    "KHC": "kraft-heinz",
    "GIS": "general-mills",
    "K": "kellanova",
    "HSY": "hershey",
    "PM": "philip-morris",
    "MO": "altria",
    "T": "att",
    "TMUS": "t-mobile",
    "VZ": "verizon",
    "CMCSA": "comcast",
    "CHTR": "charter",
    "DIS": "disney",
    "EA": "electronic-arts",
    "TTWO": "take-two",
    "ATVI": "activision-blizzard",
    "MAR": "marriott",
    "HLT": "hilton",
    "DAL": "delta-airlines",
    "UAL": "united-airlines",
    "LUV": "southwest",
    "AAL": "american-airlines",
    "JBLU": "jetblue",
    "ALK": "alaska-airlines",
    "DE": "deere",
    "CAT": "caterpillar",
    "GE": "ge-aerospace",
    "GEHC": "ge-healthcare",
    "MMM": "3m",
    "HCA": "hca-healthcare",
    "CI": "cigna",
    "ELV": "elevance",
    "CNC": "centene",
    "MOH": "molina-healthcare",
    "DASH": "doordash",
    "ABT": "abbott",
    "TMO": "thermo-fisher",
    "ZBH": "zimmer-biomet",
    "BSX": "boston-scientific",
    "EW": "edwards-lifesciences",
    "DXCM": "dexcom",
    "IDXX": "idexx",
    "ROP": "roper",
    "ETN": "eaton",
    "EMR": "emerson",
    "ITW": "illinois-tool-works",
    "PH": "parker-hannifin",
    "ROK": "rockwell-automation",
    "CMI": "cummins",
    "PCAR": "paccar",
    "CSX": "csx",
    "UNP": "union-pacific",
    "NSC": "norfolk-southern",
    "FDX": "fedex",
    "UPS": "ups",
    "LHX": "l3harris",
    "GD": "general-dynamics",
    "LMT": "lockheed-martin",
    "NOC": "northrop-grumman",
    "RTX": "rtx",
    "BA": "boeing",
    "GDIT": "gdit",
    "ACN": "accenture",
    "IBM": "ibm",
    "CTSH": "cognizant",
    "EPAM": "epam",
    "GDDY": "godaddy",
    "AKAM": "akamai",
    "GEN": "gen-digital",
    "HPQ": "hp",
    "HPE": "hewlett-packard-enterprise",
    "DELL": "dell",
    "STX": "seagate",
    "WDC": "western-digital",
    "NTAP": "netapp",
    "ANET": "arista-networks",
    "MPWR": "monolithic-power",
    "NXPI": "nxp",
    "MCHP": "microchip",
    "ON": "on-semiconductor",
    "SWKS": "skyworks",
    "QRVO": "qorvo",
    "TER": "teradyne",
    "ENPH": "enphase",
    "FSLR": "first-solar",
    "CEG": "constellation-energy",
    "NEE": "nextera-energy",
    "DUK": "duke-energy",
    "SO": "southern-company",
    "D": "dominion-energy",
    "AEP": "american-electric-power",
    "EXC": "exelon",
    "XEL": "xcel-energy",
    "WEC": "wec-energy",
    "ES": "eversource",
    "ED": "consolidated-edison",
    "PEG": "public-service-enterprise",
    "EIX": "edison-international",
    "SRE": "sempra",
    "WMB": "williams",
    "KMI": "kinder-morgan",
    "OXY": "occidental",
    "COP": "conocophillips",
    "EOG": "eog-resources",
    "SLB": "schlumberger",
    "HAL": "halliburton",
    "BKR": "baker-hughes",
    "FANG": "diamondback-energy",
    "DVN": "devon-energy",
    "PXD": "pioneer-natural-resources",
    "VLO": "valero",
    "MPC": "marathon-petroleum",
    "PSX": "phillips-66",
    "LIN": "linde",
    "APD": "air-products",
    "ECL": "ecolab",
    "SHW": "sherwin-williams",
    "FCX": "freeport-mcmoran",
    "NEM": "newmont",
    "NUE": "nucor",
    "STLD": "steel-dynamics",
    "VMC": "vulcan-materials",
    "MLM": "martin-marietta",
    "AMT": "american-tower",
    "PLD": "prologis",
    "EQIX": "equinix",
    "CCI": "crown-castle",
    "SPG": "simon-property",
    "O": "realty-income",
    "PSA": "public-storage",
    "WELL": "welltower",
    "AVB": "avalonbay",
    "EQR": "equity-residential",
    "DLR": "digital-realty",
    "IRM": "iron-mountain",
    "VTR": "ventas",
    "ARE": "alexandria-real-estate",
    "WY": "weyerhaeuser",
    "IP": "international-paper",
    "PKG": "packaging-corp",
    "AMCR": "amcor",
    "BALL": "ball-corp",
}

# Extra symbol → careers URL when slug guess is wrong.
CAREERS_URL_OVERRIDES: dict[str, str] = {
    "BRK.B": "https://www.berkshirehathaway.com/",
    "BF.B": "https://www.brown-forman.com/careers",
    "GOOGL": "https://careers.google.com/",
    "GOOG": "https://careers.google.com/",
    "META": "https://www.metacareers.com/",
    "JPM": "https://careers.jpmorgan.com/",
    "BAC": "https://careers.bankofamerica.com/",
    "WMT": "https://careers.walmart.com/",
    "HD": "https://careers.homedepot.com/",
    "UNH": "https://careers.unitedhealthgroup.com/",
    "LLY": "https://careers.lilly.com/",
    "MRK": "https://jobs.merck.com/",
    "PFE": "https://www.pfizer.com/about/careers",
    "T": "https://www.att.jobs/",
    "TMUS": "https://careers.t-mobile.com/",
    "VZ": "https://www.verizon.com/about/work",
    "DIS": "https://www.disneycareers.com/",
    "NKE": "https://careers.nike.com/",
    "MCD": "https://careers.mcdonalds.com/",
    "KO": "https://careers.coca-colacompany.com/",
    "PEP": "https://www.pepsicojobs.com/",
    "PG": "https://www.pgcareers.com/",
    "XOM": "https://jobs.exxonmobil.com/",
    "CVX": "https://careers.chevron.com/",
    "ABBV": "https://careers.abbvie.com/",
    "ABT": "https://www.abbott.com/careers.html",
    "TMO": "https://jobs.thermofisher.com/",
    "ACN": "https://www.accenture.com/us-en/careers",
    "TXN": "https://careers.ti.com/",
    "QCOM": "https://careers.qualcomm.com/",
    "AVGO": "https://www.broadcom.com/company/careers",
    "LRCX": "https://careers.lamresearch.com/",
    "AMAT": "https://careers.appliedmaterials.com/",
    "KLAC": "https://www.kla.com/careers",
    "SNPS": "https://careers.synopsys.com/",
    "CDNS": "https://careers.cadence.com/",
    "INTU": "https://www.intuit.com/careers/",
    "ADP": "https://jobs.adp.com/",
    "BLK": "https://careers.blackrock.com/",
    "GS": "https://www.goldmansachs.com/careers/",
    "MS": "https://www.morganstanley.com/careers",
    "AXP": "https://jobs.americanexpress.com/",
    "C": "https://jobs.citi.com/",
    "WFC": "https://www.wellsfargojobs.com/",
    "COF": "https://www.capitalonecareers.com/",
    "SCHW": "https://www.schwabjobs.com/",
    "DE": "https://www.deere.com/en/our-company/john-deere-careers/",
    "CAT": "https://careers.caterpillar.com/",
    "GE": "https://careers.geaerospace.com/",
    "MMM": "https://www.3m.com/3M/en_US/careers-us/",
    "HON": "https://careers.honeywell.com/",
    "LMT": "https://www.lockheedmartinjobs.com/",
    "RTX": "https://careers.rtx.com/",
    "NOC": "https://jobs.northropgrumman.com/",
    "BA": "https://jobs.boeing.com/",
    "DAL": "https://careers.delta.com/",
    "UAL": "https://careers.united.com/",
    "LUV": "https://careers.southwest.com/",
    "FDX": "https://careers.fedex.com/",
    "UPS": "https://about.ups.com/us/en/our-company/careers",
    "ARM": "https://careers.arm.com/",
    "ASML": "https://www.asml.com/en/careers",
    "SHOP": "https://www.shopify.com/careers",
    "MELI": "https://careers.mercadolibre.com/",
    "PDD": "https://careers.pinduoduo.com/",
    "APP": "https://www.applovin.com/en/careers",
    "MSTR": "https://www.strategy.com/careers",
    "ZS": "https://www.zscaler.com/careers",
    "WDAY": "https://www.workday.com/en-us/company/careers.html",
    "NOW": "https://careers.servicenow.com/",
    "DDOG": "https://careers.datadoghq.com/",
    "CRWD": "https://www.crowdstrike.com/en-us/careers/",
    "PANW": "https://jobs.paloaltonetworks.com/",
    "FTNT": "https://www.fortinet.com/corporate/careers",
    "PLTR": "https://jobs.lever.co/palantir",
    "ABNB": "https://careers.airbnb.com/",
    "UBER": "https://www.uber.com/us/en/careers/",
    "LYFT": "https://www.lyft.com/careers",
    "DASH": "https://careers.doordash.com/",
    "COIN": "https://www.coinbase.com/careers",
    "SQ": "https://block.xyz/careers",
    "XYZ": "https://block.xyz/careers",
}

SKIP_SYMBOLS = frozenset({"SPY", "QQQ", "DIA"})

DUAL_CLASS_SKIP = frozenset(
    {
        ("GOOG", "GOOGL"),
        ("FOX", "FOXA"),
        ("NWS", "NWSA"),
        ("BRK.B", "BRK.A"),
        ("BF.B", "BF.A"),
    }
)


def normalize_name(text: str) -> str:
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    stop = {
        "inc",
        "corp",
        "corporation",
        "company",
        "common",
        "stock",
        "class",
        "capital",
        "plc",
        "ltd",
        "limited",
        "holdings",
        "holding",
        "the",
        "co",
        "com",
        "depositary",
        "shares",
        "share",
        "ordinary",
        "subordinate",
        "voting",
        "ireland",
        "del",
        "de",
    }
    return " ".join(w for w in text.split() if w not in stop).strip()


def company_id_from_name(name: str, symbol: str = "") -> str:
    base = normalize_name(name) or symbol.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    if symbol and symbol.lower() in {"a", "b", "c", "d", "e", "f", "g", "h"}:
        slug = f"{slug}-{symbol.lower()}" if slug else symbol.lower()
    return slug[:48] or "unknown"


def guess_careers_url(name: str, symbol: str) -> str:
    sym = symbol.upper().strip()
    if sym in CAREERS_URL_OVERRIDES:
        return CAREERS_URL_OVERRIDES[sym]
    slug = company_id_from_name(name, sym)
    if not slug:
        return ""
    if sym in CAREERS_URL_OVERRIDES:
        return CAREERS_URL_OVERRIDES[sym]
    brand = slug.replace("-", "")
    for url in (
        f"https://careers.{slug}.com",
        f"https://jobs.{slug}.com",
        f"https://www.{slug}.com/careers",
        f"https://www.{brand}.com/careers",
    ):
        return url
    return ""


def parse_sp500_md(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rows: list[tuple[str, str]] = []
    row_re = re.compile(
        r"^\|\s*\[([A-Z0-9.]+)\]\([^)]+\)\s*\|\s*\[([^\]]+)\]\(/wiki/",
        re.MULTILINE,
    )
    for sym, name in row_re.findall(text):
        sym = sym.strip().upper()
        name = re.sub(r"\s+", " ", name).strip()
        if sym and name:
            rows.append((sym, name))
    return rows


def fetch_nasdaq100() -> str:
    req = urllib.request.Request(NASDAQ_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_nasdaq_md(path: Path) -> list[tuple[str, str]]:
    return parse_nasdaq_table(path.read_text(encoding="utf-8", errors="replace"))


def parse_nasdaq_table(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    row_re = re.compile(
        r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*([A-Z][A-Z0-9.]*)\s*\|",
        re.MULTILINE,
    )
    for name, sym in row_re.findall(text):
        name = re.sub(r"\s+", " ", name).strip()
        sym = sym.strip().upper()
        if sym in SKIP_SYMBOLS or not name:
            continue
        rows.append((sym, name))
    return rows


def load_existing_index(base: dict) -> tuple[set[str], set[str], dict[str, str]]:
    ids: set[str] = set()
    names: set[str] = set()
    norm_to_id: dict[str, str] = {}
    for co in base.get("companies") or []:
        if not isinstance(co, dict):
            continue
        cid = str(co.get("id") or "").strip()
        name = str(co.get("name") or "").strip()
        if cid:
            ids.add(cid)
        if name:
            names.add(name.lower())
            norm = normalize_name(name)
            if norm:
                norm_to_id[norm] = cid
    return ids, names, norm_to_id


def should_skip_symbol(sym: str, seen_syms: set[str]) -> bool:
    if sym in SKIP_SYMBOLS:
        return True
    for a, b in DUAL_CLASS_SKIP:
        if sym == b and a in seen_syms:
            return True
        if sym == a and b in seen_syms:
            return True
    return False


def ticker_map_for_ids(ids: set[str]) -> dict[str, str]:
    return {sym: cid for sym, cid in TICKER_TO_EXISTING_ID.items() if cid in ids}


def match_existing(
    sym: str,
    name: str,
    ids: set[str],
    names: set[str],
    norm_to_id: dict[str, str],
    ticker_map: dict[str, str],
) -> str | None:
    sym = sym.upper()
    if sym in ticker_map:
        return ticker_map[sym]
    norm = normalize_name(name)
    if norm in norm_to_id:
        return norm_to_id[norm]
    slug = company_id_from_name(name, sym)
    if slug in ids:
        return slug
    if name.lower() in names:
        return name.lower()
    for existing_norm, cid in norm_to_id.items():
        if norm and (norm in existing_norm or existing_norm in norm):
            if len(norm) >= 4 and len(existing_norm) >= 4:
                return cid
    return None


def hub_entry(sym: str, name: str, index_tag: str) -> dict:
    cid = company_id_from_name(name, sym)
    url = guess_careers_url(name, sym)
    _ = index_tag  # source list only; labels are generic manual hubs
    label = f"{name} (manual careers hub)"
    return {
        "id": cid,
        "name": name,
        "label": label,
        "section": "hubs",
        "type": "hub",
        "hub_url": url,
        "hub_note": "Manual careers link — verify careers URL; probe for ATS conversion",
        "search_keywords": list(SEARCH_KEYWORDS),
        "default_salary": "maybe",
    }


def merge_indices(
    sp500: list[tuple[str, str]],
    nasdaq: list[tuple[str, str]],
    base: dict,
) -> tuple[list[dict], dict[str, int]]:
    ids, names, norm_to_id = load_existing_index(base)
    ticker_map = ticker_map_for_ids(ids)
    seen_syms: set[str] = set()
    new_rows: list[dict] = []
    stats = {
        "sp500_rows": len(sp500),
        "nasdaq_rows": len(nasdaq),
        "added": 0,
        "skipped_existing": 0,
        "skipped_dup": 0,
        "skipped_dual": 0,
    }

    def ingest(rows: list[tuple[str, str]], tag: str) -> None:
        for sym, name in rows:
            sym = sym.upper()
            if should_skip_symbol(sym, seen_syms):
                stats["skipped_dual"] += 1
                continue
            if sym in seen_syms:
                stats["skipped_dup"] += 1
                continue
            seen_syms.add(sym)
            existing = match_existing(sym, name, ids, names, norm_to_id, ticker_map)
            if existing:
                stats["skipped_existing"] += 1
                continue
            entry = hub_entry(sym, name, tag)
            cid = entry["id"]
            suffix = 2
            while cid in ids:
                cid = f"{entry['id']}-{suffix}"
                suffix += 1
            entry["id"] = cid
            ids.add(cid)
            names.add(name.lower())
            norm = normalize_name(name)
            if norm:
                norm_to_id[norm] = cid
            new_rows.append(entry)
            stats["added"] += 1

    ingest(sp500, "S&P 500")
    ingest(nasdaq, "Nasdaq-100")
    return new_rows, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sp500-md", type=Path, default=DEFAULT_SP500_MD)
    parser.add_argument("--nasdaq-md", type=Path, default=DEFAULT_NASDAQ_MD)
    parser.add_argument("--apply", action="store_true", help="Write new hubs to base.json")
    parser.add_argument(
        "--out",
        type=Path,
        default=hub_tools.report_path("quickjobs-index-hubs-added.json"),
    )
    args = parser.parse_args()

    if not BASE_JSON.is_file():
        print(f"Missing {BASE_JSON}", file=sys.stderr)
        return 1
    if not args.sp500_md.is_file():
        print(f"Missing S&P 500 markdown: {args.sp500_md}", file=sys.stderr)
        return 1

    sp500 = parse_sp500_md(args.sp500_md)
    if not sp500:
        print("No S&P 500 rows parsed", file=sys.stderr)
        return 1

    nasdaq: list[tuple[str, str]] = []
    if args.nasdaq_md.is_file():
        nasdaq = parse_nasdaq_md(args.nasdaq_md)
    if not nasdaq:
        try:
            nasdaq = parse_nasdaq_table(fetch_nasdaq100())
        except OSError as exc:
            print(f"Nasdaq-100 fetch failed: {exc}", file=sys.stderr)
    if not nasdaq:
        print("No Nasdaq-100 rows parsed (use --nasdaq-md or fix fetch)", file=sys.stderr)
        return 1

    base = hub_tools.load_base_bundle()
    new_rows, stats = merge_indices(sp500, nasdaq, base)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(new_rows, indent=2) + "\n", encoding="utf-8")

    print(
        f"S&P 500 parsed: {stats['sp500_rows']} · Nasdaq-100 parsed: {stats['nasdaq_rows']}\n"
        f"New hub entries: {stats['added']} · already in board: {stats['skipped_existing']} · "
        f"dup symbol: {stats['skipped_dup']} · dual-class skip: {stats['skipped_dual']}\n"
        f"Wrote preview: {args.out}"
    )

    if args.apply:
        base["companies"].extend(new_rows)
        hub_tools.save_base_bundle(base)
        print(f"Appended {stats['added']} companies to {BASE_JSON}")
        print(f"Total companies now: {len(base['companies'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
