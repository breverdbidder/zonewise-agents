"""
ZoneWise.AI — Foreclosure Sale Scraper
Hook Phase: ACTION (data foundation)
TASK-005: AJAX scraper for county RealForeclose portals + Brevard Clerk.

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
import random
import re
import time
from datetime import datetime
from typing import Optional

import httpx

from scrapers.shared import (
    HEADERS,
    expand_shorthand,
    extract_field,
    extract_auction_type,
    parse_currency,
    strip_html_tags,
    parse_auction_items,
    fetch_existing_identifiers,
    insert_rows,
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
)
from scrapers.source_map import (
    COUNTY_SOURCE_MAP,
    get_foreclosure_config,
    get_county_name,
    get_clerk_url,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreclosure_scraper")


# ---------------------------------------------------------------------------
# Brevard Clerk scraper
# ---------------------------------------------------------------------------

# BREVARD COUNTY SPECIAL CASE:
# Foreclosure sales = IN-PERSON at Titusville courthouse
#   Source: brevardclerk.us/foreclosure-sales-list
#   auction_venue = 'in_person'
#   auction_url = NULL (no online bidding link)
#
# Tax deed sales = ONLINE via RealAuction
#   Source: brevard.realforeclose.com (TAXDEED filter)
#   auction_venue = 'online'
#   auction_url = direct link to listing on brevard.realforeclose.com

BREVARD_CLERK_URL = (
    "http://www.brevardclerk.us/Foreclosures/foreclosure_sales.html"
)


async def scrape_brevard_clerk(
    max_retries: int = 3,
) -> list[dict]:
    """Scrape Brevard County foreclosure list from brevardclerk.us.

    The clerk page is a static HTML table with 4 columns:
      case_number | case_title | comment | foreclosure_sale_date

    case_title is "PLAINTIFF VS DEFENDANT" — split on " VS ".
    Rows with comment="CANCELLED" are skipped.
    Auction time is fixed at 11:00 AM (from page header).

    Fields NOT on this page (set to NULL, enriched later via BECA/BCPAO):
      property_address, judgment_amount, parcel_id
    """
    # BREVARD COUNTY SPECIAL CASE:
    # Foreclosure sales = IN-PERSON at Titusville courthouse
    #   Source: brevardclerk.us/foreclosure-sales-list
    #   auction_venue = 'in_person'
    #   auction_url = NULL (no online bidding link)

    for attempt in range(1, max_retries + 1):
        try:
            return await _fetch_brevard_clerk()
        except Exception as e:
            log.warning(
                f"[Brevard Clerk] Attempt {attempt}/{max_retries} failed: {e}"
            )
            if attempt < max_retries:
                backoff = attempt * 5
                log.info(f"[Brevard Clerk] Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
            else:
                log.error(
                    f"[Brevard Clerk] All {max_retries} attempts failed"
                )
                return []


async def _fetch_brevard_clerk() -> list[dict]:
    """Internal: fetch and parse the Brevard clerk foreclosure page."""
    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True, timeout=30.0
    ) as client:
        log.info("[Brevard Clerk] Fetching foreclosure sales list...")
        resp = await client.get(BREVARD_CLERK_URL)
        resp.raise_for_status()
        html = resp.text

    # Parse the HTML table rows
    # Pattern: <tr> with <td> cells containing case data
    row_pattern = re.compile(
        r'<tr[^>]*>\s*'
        r'<td[^>]*>(.*?)</td>\s*'   # case_number
        r'<td[^>]*>(.*?)</td>\s*'   # case_title
        r'<td[^>]*>(.*?)</td>\s*'   # comment
        r'<td[^>]*>(.*?)</td>\s*'   # foreclosure_sale_date
        r'</tr>',
        re.IGNORECASE | re.DOTALL,
    )

    matches = row_pattern.findall(html)
    auctions: list[dict] = []

    for case_number_raw, case_title_raw, comment_raw, date_raw in matches:
        case_number = strip_html_tags(case_number_raw).strip()
        case_title = strip_html_tags(case_title_raw).strip()
        comment = strip_html_tags(comment_raw).strip().upper()
        date_str = strip_html_tags(date_raw).strip()

        # Skip header row
        if case_number.lower() == "case_number" or not case_number:
            continue

        # Skip cancelled sales
        if comment == "CANCELLED":
            continue

        # Split case_title on " VS " to get plaintiff and defendant
        plaintiff = None
        defendant = None
        if " VS " in case_title.upper():
            parts = case_title.split(" VS ", 1)
            plaintiff = parts[0].strip()
            defendant = parts[1].strip() if len(parts) > 1 else None
        elif " V " in case_title.upper():
            parts = case_title.split(" V ", 1)
            plaintiff = parts[0].strip()
            defendant = parts[1].strip() if len(parts) > 1 else None
        else:
            plaintiff = case_title

        # Parse date (format: MM-DD-YYYY)
        auction_date = None
        try:
            auction_date = datetime.strptime(date_str, "%m-%d-%Y").date()
        except ValueError:
            try:
                auction_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            except ValueError:
                log.warning(
                    f"[Brevard Clerk] Could not parse date: {date_str}"
                )

        auction = {
            "sale_type": "foreclosure",  # HARDCODED — never dynamic
            "county": "brevard",
            "case_number": case_number,
            "plaintiff": plaintiff,
            "defendant": defendant,
            "property_address": None,  # Not on clerk page — enriched via BECA
            "judgment_amount": None,   # Not on clerk page — enriched via BECA
            "parcel_id": None,         # Not on clerk page — enriched via BCPAO
            "auction_date": (
                auction_date.isoformat() if auction_date else None
            ),
            "auction_time": "11:00:00",  # Fixed — from page header
            "auction_venue": "in_person",
            "auction_url": None,  # No online bidding for in-person sales
            "clerk_url": "https://www.brevardclerk.us/foreclosure-sales-list",
            "realforeclose_url": None,
            "bcpao_enriched": False,
        }
        auctions.append(auction)

    log.info(
        f"[Brevard Clerk] Parsed {len(auctions)} active foreclosures "
        f"(skipped cancelled)"
    )
    return auctions


# ---------------------------------------------------------------------------
# RealForeclose AJAX scraper (non-Brevard counties)
# ---------------------------------------------------------------------------

async def scrape_realforeclose_foreclosures(
    county_slug: str,
    delay_range: tuple[float, float] = (3.0, 7.0),
    max_retries: int = 3,
) -> list[dict]:
    """Scrape foreclosure auctions from RealForeclose for a single county.

    Returns list of dicts ready for Supabase insert.
    Every dict includes sale_type='foreclosure'.
    """
    config = get_foreclosure_config(county_slug)
    if not config:
        log.error(f"Unknown county: {county_slug}")
        return []

    subdomain = config["subdomain"]
    county_name = get_county_name(county_slug)
    base_url = f"https://{subdomain}.realforeclose.com/index.cfm"

    for attempt in range(1, max_retries + 1):
        try:
            auctions = await _scrape_realforeclose(
                base_url, county_slug, county_name, subdomain, delay_range
            )
            log.info(
                f"[{county_name}] Scrape complete: "
                f"{len(auctions)} unique foreclosure auctions"
            )
            return auctions
        except Exception as e:
            log.warning(
                f"[{county_name}] Attempt {attempt}/{max_retries} failed: {e}"
            )
            if attempt < max_retries:
                backoff = attempt * 5
                log.info(f"[{county_name}] Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
            else:
                log.error(
                    f"[{county_name}] All {max_retries} attempts failed"
                )
                return []


async def _scrape_realforeclose(
    base_url: str,
    county_slug: str,
    county_name: str,
    subdomain: str,
    delay_range: tuple[float, float],
) -> list[dict]:
    """Internal: scrape a single county from RealForeclose. Raises on failure."""
    all_auctions: list[dict] = []
    seen_cases: set[str] = set()

    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True, timeout=30.0
    ) as client:

        log.info(f"[{county_name}] Fetching foreclosure calendar...")
        preview_url = (
            f"{base_url}?zaction=AUCTION&Zmethod=PREVIEW&AESSION=Foreclosure"
        )
        resp = await client.get(preview_url)
        resp.raise_for_status()
        calendar_html = resp.text

        date_pattern = r"AuctionDate=(\d{2}/\d{2}/\d{4})"
        raw_dates = sorted(set(re.findall(date_pattern, calendar_html)))

        if not raw_dates:
            log.warning(f"[{county_name}] No auction dates found in calendar")
            return all_auctions

        log.info(f"[{county_name}] Found {len(raw_dates)} auction dates")

        for auction_date_str in raw_dates:
            delay = random.uniform(*delay_range)
            log.info(
                f"[{county_name}] Loading {auction_date_str} "
                f"(delay {delay:.1f}s)..."
            )
            await asyncio.sleep(delay)

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

            try:
                auction_date = datetime.strptime(
                    auction_date_str, "%m/%d/%Y"
                ).date()
            except ValueError:
                auction_date = None

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

                try:
                    data = resp.json()
                    raw_html = data.get("retHTML", "")
                except (json.JSONDecodeError, AttributeError):
                    raw_html = resp.text

                if not raw_html or len(raw_html) < 20:
                    continue

                expanded = expand_shorthand(raw_html)
                items = parse_auction_items(expanded, "FORECLOSURE")

                for item in items:
                    case = item.get("case_number", "")
                    if case and case not in seen_cases:
                        seen_cases.add(case)

                        aid = item.get("auction_id")
                        auction_url = None
                        if aid:
                            auction_url = (
                                f"https://{subdomain}.realforeclose.com"
                                f"/index.cfm?zaction=auction&zmethod=details"
                                f"&AID={aid}"
                            )

                        auction = {
                            "sale_type": "foreclosure",
                            "county": county_slug,
                            "case_number": case,
                            "judgment_amount": item.get("judgment_amount"),
                            "plaintiff": item.get("plaintiff"),
                            "property_address": item.get("property_address"),
                            "parcel_id": item.get("parcel_id"),
                            "assessed_value": item.get("assessed_value"),
                            "auction_date": (
                                auction_date.isoformat()
                                if auction_date
                                else None
                            ),
                            "auction_time": "09:00:00",  # Default RealForeclose start time
                            "auction_venue": "online",
                            "auction_url": auction_url,
                            "realforeclose_url": auction_url,
                            "clerk_url": get_clerk_url(county_slug),
                            "bcpao_enriched": False,
                        }
                        all_auctions.append(auction)

    return all_auctions


# ---------------------------------------------------------------------------
# Main entry point — routes to correct scraper per source map
# ---------------------------------------------------------------------------

async def scrape_foreclosures(
    county_slug: str = "brevard",
    delay_range: tuple[float, float] = (3.0, 7.0),
    max_retries: int = 3,
) -> list[dict]:
    """Scrape foreclosure auctions for a single county.

    Routes to the correct source based on COUNTY_SOURCE_MAP:
    - Brevard → brevardclerk.us (in-person sales)
    - All others → RealForeclose AJAX
    """
    config = get_foreclosure_config(county_slug)
    if not config:
        log.error(f"No foreclosure config for county: {county_slug}")
        return []

    if config.get("platform") == "brevard_clerk":
        return await scrape_brevard_clerk(max_retries=max_retries)
    else:
        return await scrape_realforeclose_foreclosures(
            county_slug, delay_range, max_retries
        )


# ---------------------------------------------------------------------------
# Supabase insert
# ---------------------------------------------------------------------------

async def insert_to_supabase(auctions: list[dict]) -> int:
    """Insert foreclosure auctions into multi_county_auctions table.

    Deduplicates against existing rows using case_number + county.
    Returns number of rows successfully inserted.
    """
    if not auctions:
        return 0

    county = auctions[0].get("county", "")
    existing_cases = await fetch_existing_identifiers(
        county, "foreclosure", "case_number"
    )

    rows = []
    skipped = 0
    for a in auctions:
        case = a.get("case_number", "")
        if case in existing_cases:
            skipped += 1
            continue
        rows.append(a)

    if skipped:
        log.info(f"Skipped {skipped} duplicate rows")

    if not rows:
        log.info("No new rows to insert (all duplicates)")
        return 0

    return await insert_rows(rows)


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
        print(f"  plaintiff:        {a.get('plaintiff')}")
        print(f"  property_address: {a.get('property_address')}")
        print(f"  judgment_amount:  {a.get('judgment_amount')}")
        print(f"  auction_date:     {a.get('auction_date')}")
        print(f"  auction_time:     {a.get('auction_time')}")
        print(f"  auction_venue:    {a.get('auction_venue')}")
        print(f"  auction_url:      {a.get('auction_url')}")
        print(f"  clerk_url:        {a.get('clerk_url')}")
        print(f"  realforeclose_url:{a.get('realforeclose_url')}")

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
        choices=list(COUNTY_SOURCE_MAP.keys()),
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
