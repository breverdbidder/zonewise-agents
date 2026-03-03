"""
ZoneWise.AI — Foreclosure Sale Scraper
Hook Phase: ACTION (data foundation)
TASK-005: AJAX scraper for county RealForeclose portals.

Outputs: multi_county_auctions rows with sale_type='foreclosure'
Every row: sale_type = 'foreclosure' — hardcoded, NEVER dynamic.

Usage:
  # Dry run (print only, no Supabase insert):
  python scrapers/foreclosure_scraper.py --county brevard --dry-run

  # Live insert:
  python scrapers/foreclosure_scraper.py --county brevard
"""

import asyncio
import json
import logging
import os
import random
import re
import time
from datetime import datetime
from typing import Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreclosure_scraper")

# ---------------------------------------------------------------------------
# County configuration
# ---------------------------------------------------------------------------

COUNTY_CONFIG = {
    "brevard": {"name": "Brevard", "subdomain": "brevard"},
    "orange": {"name": "Orange", "subdomain": "myorangeclerk"},
    "polk": {"name": "Polk", "subdomain": "polk"},
    "hillsborough": {"name": "Hillsborough", "subdomain": "hillsborough"},
    "palm_beach": {"name": "Palm Beach", "subdomain": "palmbeach"},
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# @A-@L shorthand expansion (RealForeclose AJAX compression)
# ---------------------------------------------------------------------------

SHORTHAND_CODES = {
    "@A": '<div class="',
    "@B": "</div>",
    "@C": 'class="',
    "@D": "<div>",
    "@E": "AUCTION",
    "@F": "</td><td",
    "@G": "</td></tr>",
    "@H": "<tr><td ",
    "@I": "table",
    "@J": 'p_back="NextCheck=',
    "@K": 'style="Display:none"',
    "@L": "/index.cfm?zaction=auction&zmethod=details&AID=",
}


def expand_shorthand(html: str) -> str:
    """Replace all @A-@L shorthand codes with full HTML."""
    for code, expansion in SHORTHAND_CODES.items():
        html = html.replace(code, expansion)
    return html


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_currency(text: str) -> Optional[float]:
    """Parse '$1,234.56' -> 1234.56"""
    if not text:
        return None
    clean = re.sub(r"[^0-9.]", "", text.strip())
    try:
        return float(clean) if clean else None
    except ValueError:
        return None


def strip_html_tags(text: str) -> str:
    """Remove HTML tags and return clean text."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return clean.strip()


def extract_field(html_block: str, label_pattern: str) -> Optional[str]:
    """Extract value from AD_LBL/AD_DTA table row pair.

    Handles values that contain <a> tags (case numbers, parcel IDs).
    Looks for a label matching `label_pattern` (case-insensitive) and
    returns the corresponding value text with HTML tags stripped.
    """
    # Match label cell, then capture everything in the value cell.
    # Value may contain <a> tags. Closing tag can be </td> or </div>
    # (Hillsborough uses <table>, Orange uses <div>).
    pattern = (
        r'AD_LBL"[^>]*>[^<]*'
        + label_pattern
        + r'[^<]*<'  # match through end of label text
        + r'.*?'  # skip to value cell
        + r'AD_DTA"[^>]*>(.*?)</(?:td|div)>'  # capture value including HTML
    )
    m = re.search(pattern, html_block, re.IGNORECASE | re.DOTALL)
    if m:
        raw_value = m.group(1)
        return strip_html_tags(raw_value).strip()
    return None


def extract_auction_type(html_block: str) -> Optional[str]:
    """Extract the Auction Type field value (FORECLOSURE or TAXDEED)."""
    return extract_field(html_block, r"Auction\s+Type")


def parse_auction_items(expanded_html: str, sale_type_filter: str = "FORECLOSURE") -> list[dict]:
    """Parse expanded HTML into list of auction dicts.

    Only includes items matching sale_type_filter (default: FORECLOSURE).
    """
    items = []

    # Use findall to capture AITEM IDs alongside their content
    aitem_pattern = re.compile(
        r'<div\s+id="AITEM_(\d+)"[^>]*AUCTION_ITEM[^>]*>(.*?)(?=<div\s+id="AITEM_|\Z)',
        re.DOTALL,
    )
    matches = aitem_pattern.findall(expanded_html)

    if not matches:
        # Fallback: split approach for alternate HTML structure
        parts = re.split(r'<div\s+[^>]*AUCTION_ITEM[^>]*', expanded_html)
        matches = [(None, part) for part in parts[1:]]

    for aid, part in matches:
        # Check auction type — skip if not matching filter
        auction_type = extract_auction_type(part)
        if auction_type and auction_type.upper().strip() != sale_type_filter:
            continue

        # Also try to find AID in detail links inside the item
        if not aid:
            aid_match = re.search(r'AID=(\d+)', part, re.IGNORECASE)
            aid = aid_match.group(1) if aid_match else None

        case_number = extract_field(part, r"Case\s*#")
        judgment_raw = extract_field(part, r"(?:Final\s+)?Judgment\s*(?:Amount)?")
        plaintiff_raw = extract_field(part, r"Plaintiff")
        address = extract_field(part, r"(?:Property\s+)?Address")
        parcel_id = extract_field(part, r"Parcel\s*(?:ID)?")
        appraised_raw = extract_field(part, r"Assessed\s*(?:Value)?")
        plaintiff_max_raw = extract_field(part, r"Plaintiff\s+Max\s+Bid")

        # Look for city/state in the row immediately after address
        # (RealForeclose puts city in a row with empty label)
        city_match = re.search(
            r'AD_LBL"\s*scope="row">\s*<'  # empty label
            r'.*?AD_DTA"[^>]*>(.*?)</td>',
            part[part.find("Address"):] if "Address" in part else "",
            re.IGNORECASE | re.DOTALL,
        )
        city = strip_html_tags(city_match.group(1)) if city_match else None

        # Combine address + city
        full_address = address or ""
        if city and city not in (full_address or ""):
            full_address = f"{full_address}, {city}" if full_address else city

        item = {
            "sale_type": "foreclosure",  # HARDCODED — never dynamic
            "case_number": case_number,
            "judgment_amount": parse_currency(judgment_raw),
            "plaintiff": plaintiff_raw,
            "property_address": full_address.strip(", ") or None,
            "parcel_id": parcel_id,
            "appraised_value": parse_currency(appraised_raw),
            "plaintiff_max_bid": (
                parse_currency(plaintiff_max_raw)
                if plaintiff_max_raw and "Hidden" not in plaintiff_max_raw
                else None
            ),
            "auction_id": aid,
        }

        # Only include items with a case number
        if case_number:
            items.append(item)

    return items


# ---------------------------------------------------------------------------
# Core scraper
# ---------------------------------------------------------------------------

async def scrape_foreclosures(
    county_slug: str = "brevard",
    delay_range: tuple[float, float] = (3.0, 7.0),
    max_retries: int = 3,
) -> list[dict]:
    """Scrape foreclosure auctions from RealForeclose for a single county.

    Returns list of dicts ready for Supabase insert.
    Every dict includes sale_type='foreclosure'.
    """
    config = COUNTY_CONFIG.get(county_slug)
    if not config:
        log.error(f"Unknown county: {county_slug}")
        return []

    subdomain = config["subdomain"]
    county_name = config["name"]
    base_url = f"https://{subdomain}.realforeclose.com/index.cfm"

    all_auctions: list[dict] = []
    seen_cases: set[str] = set()

    for attempt in range(1, max_retries + 1):
        try:
            all_auctions, seen_cases = await _scrape_county(
                base_url, county_name, delay_range
            )
            break
        except Exception as e:
            log.warning(
                f"[{county_name}] Attempt {attempt}/{max_retries} failed: {e}"
            )
            if attempt < max_retries:
                backoff = attempt * 5
                log.info(f"[{county_name}] Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
            else:
                log.error(f"[{county_name}] All {max_retries} attempts failed")
                return []

    log.info(
        f"[{county_name}] Scrape complete: "
        f"{len(all_auctions)} unique foreclosure auctions"
    )
    return all_auctions


async def _scrape_county(
    base_url: str,
    county_name: str,
    delay_range: tuple[float, float],
) -> tuple[list[dict], set[str]]:
    """Internal: scrape a single county. Raises on failure."""
    all_auctions: list[dict] = []
    seen_cases: set[str] = set()

    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True, timeout=30.0
    ) as client:

        # Step 1: Get calendar/preview to discover auction dates
        log.info(f"[{county_name}] Fetching foreclosure calendar...")
        preview_url = (
            f"{base_url}?zaction=AUCTION&Zmethod=PREVIEW&AESSION=Foreclosure"
        )
        resp = await client.get(preview_url)
        resp.raise_for_status()
        calendar_html = resp.text

        # Extract all auction dates from navigation links
        date_pattern = r"AuctionDate=(\d{2}/\d{2}/\d{4})"
        raw_dates = sorted(set(re.findall(date_pattern, calendar_html)))

        if not raw_dates:
            log.warning(f"[{county_name}] No auction dates found in calendar")
            return all_auctions, seen_cases

        log.info(f"[{county_name}] Found {len(raw_dates)} auction dates")

        # Step 2: For each date, load auction items via AJAX
        for auction_date_str in raw_dates:
            delay = random.uniform(*delay_range)
            log.info(
                f"[{county_name}] Loading {auction_date_str} "
                f"(delay {delay:.1f}s)..."
            )
            await asyncio.sleep(delay)

            # Hit the preview page to establish session for this date
            date_preview_url = (
                f"{base_url}?zaction=AUCTION&Zmethod=PREVIEW"
                f"&AuctionDate={auction_date_str}"
            )
            try:
                resp = await client.get(date_preview_url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                log.warning(
                    f"[{county_name}] Preview failed for "
                    f"{auction_date_str}: {e}"
                )
                continue

            # Parse the sale_date
            try:
                sale_date = datetime.strptime(
                    auction_date_str, "%m/%d/%Y"
                ).date()
            except ValueError:
                sale_date = None

            # Load waiting (W) and running (R) auctions via AJAX
            for area in ["W", "R"]:
                await asyncio.sleep(random.uniform(1.0, 2.0))

                ajax_url = (
                    f"{base_url}?zaction=AUCTION&Zmethod=UPDATE"
                    f"&FNC=LOAD&AREA={area}"
                    f"&PageDir=0&doR=1&bypassPage=0"
                )
                try:
                    resp = await client.get(ajax_url)
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    log.warning(
                        f"[{county_name}] AJAX failed "
                        f"{auction_date_str} AREA={area}: {e}"
                    )
                    continue

                # Parse AJAX response
                try:
                    data = resp.json()
                    raw_html = data.get("retHTML", "")
                except (json.JSONDecodeError, AttributeError):
                    raw_html = resp.text

                if not raw_html or len(raw_html) < 20:
                    continue

                expanded = expand_shorthand(raw_html)
                items = parse_auction_items(expanded)

                for item in items:
                    case = item.get("case_number", "")
                    if case and case not in seen_cases:
                        seen_cases.add(case)
                        item["county"] = county_name
                        item["sale_date"] = (
                            sale_date.isoformat() if sale_date else None
                        )
                        all_auctions.append(item)

    return all_auctions, seen_cases


# ---------------------------------------------------------------------------
# Supabase insert
# ---------------------------------------------------------------------------

SUPABASE_URL = os.getenv(
    "SUPABASE_URL", "https://mocerqjnksmhcjzxrewo.supabase.co"
)
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")


async def insert_to_supabase(auctions: list[dict]) -> int:
    """Insert foreclosure auctions into multi_county_auctions table.

    Deduplicates against existing rows using case_number + county + sale_date.
    Returns number of rows successfully inserted.
    """
    if not auctions:
        return 0

    if not SUPABASE_SERVICE_KEY:
        log.error(
            "SUPABASE_SERVICE_KEY not set — cannot insert. "
            "Set env var or use --dry-run."
        )
        return 0

    sb_headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }

    # Fetch existing case_numbers for this county to avoid duplicates
    county = auctions[0].get("county", "")
    existing_cases: set[str] = set()
    async with httpx.AsyncClient(timeout=30.0) as client:
        check_url = (
            f"{SUPABASE_URL}/rest/v1/multi_county_auctions"
            f"?sale_type=eq.foreclosure&county=eq.{county}"
            f"&select=case_number"
        )
        resp = await client.get(check_url, headers=sb_headers)
        if resp.status_code == 200:
            for row in resp.json():
                if row.get("case_number"):
                    existing_cases.add(row["case_number"])
            log.info(
                f"Found {len(existing_cases)} existing {county} "
                f"foreclosure rows — will skip duplicates"
            )

    rows = []
    skipped = 0
    for a in auctions:
        case = a.get("case_number", "")
        if case in existing_cases:
            skipped += 1
            continue

        row = {
            "sale_type": "foreclosure",  # HARDCODED
            "county": a["county"],
            "property_address": a.get("property_address"),
            "sale_date": a.get("sale_date"),
            "case_number": a.get("case_number"),
            "judgment_amount": a.get("judgment_amount"),
            "plaintiff": a.get("plaintiff"),
            "bcpao_data": json.dumps({
                "parcel_id": a.get("parcel_id"),
                "appraised_value": a.get("appraised_value"),
                "plaintiff_max_bid": a.get("plaintiff_max_bid"),
                "auction_id": a.get("auction_id"),
            }),
        }
        rows.append(row)

    if skipped:
        log.info(f"Skipped {skipped} duplicate rows")

    if not rows:
        log.info("No new rows to insert (all duplicates)")
        return 0

    url = f"{SUPABASE_URL}/rest/v1/multi_county_auctions"
    sb_headers["Prefer"] = "return=minimal"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=rows, headers=sb_headers)
        if resp.status_code in (200, 201):
            log.info(f"Inserted {len(rows)} rows into multi_county_auctions")
            return len(rows)
        else:
            log.error(
                f"Supabase insert failed: {resp.status_code} — {resp.text}"
            )
            return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def print_dry_run(auctions: list[dict], limit: int = 5):
    """Print first N auctions for dry run verification."""
    print(f"\n{'='*80}")
    print(f"DRY RUN — {len(auctions)} foreclosure auctions scraped")
    print(f"{'='*80}")

    for i, a in enumerate(auctions[:limit]):
        print(f"\n--- Auction {i+1} ---")
        print(f"  sale_type:        {a.get('sale_type')}")
        print(f"  county:           {a.get('county')}")
        print(f"  case_number:      {a.get('case_number')}")
        print(f"  judgment_amount:  {a.get('judgment_amount')}")
        print(f"  plaintiff:        {a.get('plaintiff')}")
        print(f"  property_address: {a.get('property_address')}")
        print(f"  sale_date:        {a.get('sale_date')}")
        print(f"  parcel_id:        {a.get('parcel_id')}")
        print(f"  appraised_value:  {a.get('appraised_value')}")
        print(f"  plaintiff_max:    {a.get('plaintiff_max_bid')}")
        print(f"  auction_id:       {a.get('auction_id')}")

    if len(auctions) > limit:
        print(f"\n... and {len(auctions) - limit} more")
    print(f"\n{'='*80}")


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="ZoneWise Foreclosure Scraper"
    )
    parser.add_argument(
        "--county",
        default="brevard",
        choices=list(COUNTY_CONFIG.keys()),
        help="County to scrape (default: brevard)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without inserting into Supabase",
    )
    args = parser.parse_args()

    log.info(f"Starting foreclosure scraper for {args.county}...")
    start = time.time()

    auctions = await scrape_foreclosures(county_slug=args.county)

    elapsed = time.time() - start
    log.info(f"Scrape took {elapsed:.1f}s")

    if args.dry_run:
        print_dry_run(auctions)
    else:
        if auctions:
            inserted = await insert_to_supabase(auctions)
            log.info(f"Inserted {inserted}/{len(auctions)} rows")
        else:
            log.warning("No auctions found — nothing to insert")


if __name__ == "__main__":
    asyncio.run(main())
