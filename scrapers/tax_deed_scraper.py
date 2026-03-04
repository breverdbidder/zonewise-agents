"""
ZoneWise.AI — Tax Deed Sale Scraper
Hook Phase: ACTION (data foundation)
TASK-006: AJAX scraper for county RealForeclose tax deed listings.

Outputs: multi_county_auctions rows with sale_type='tax_deed'
Every row: sale_type = 'tax_deed' — hardcoded, NEVER dynamic.

Uses the same RealForeclose AJAX infrastructure as the foreclosure scraper
but filters for TAXDEED items instead of FORECLOSURE.

Usage:
  # Dry run (print only, no Supabase insert):
  python scrapers/tax_deed_scraper.py --county brevard --dry-run

  # Live insert:
  python scrapers/tax_deed_scraper.py --county brevard
"""

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime

import httpx

from scrapers.shared import (
    HEADERS,
    expand_shorthand,
    parse_auction_items,
    fetch_existing_identifiers,
    insert_rows,
)
from scrapers.source_map import (
    COUNTY_SOURCE_MAP,
    get_tax_deed_config,
    get_county_name,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tax_deed_scraper")


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


# ---------------------------------------------------------------------------
# Core scraper
# ---------------------------------------------------------------------------

async def scrape_tax_deeds(
    county_slug: str = "brevard",
    delay_range: tuple[float, float] = (3.0, 7.0),
    max_retries: int = 3,
) -> list[dict]:
    """Scrape tax deed auctions from RealForeclose for a single county.

    All tax deed sales are online via RealForeclose for all 5 active counties.
    Returns list of dicts ready for Supabase insert.
    """
    config = get_tax_deed_config(county_slug)
    if not config:
        log.error(f"No tax deed config for county: {county_slug}")
        return []

    if config.get("platform") != "realforeclose":
        log.error(
            f"Tax deed platform for {county_slug} is "
            f"{config.get('platform')}, not realforeclose"
        )
        return []

    subdomain = config["subdomain"]
    county_name = get_county_name(county_slug)
    base_url = f"https://{subdomain}.realforeclose.com/index.cfm"

    for attempt in range(1, max_retries + 1):
        try:
            auctions = await _scrape_tax_deeds(
                base_url, county_slug, county_name, subdomain, delay_range
            )
            log.info(
                f"[{county_name}] Scrape complete: "
                f"{len(auctions)} unique tax deed auctions"
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


async def _scrape_tax_deeds(
    base_url: str,
    county_slug: str,
    county_name: str,
    subdomain: str,
    delay_range: tuple[float, float],
) -> list[dict]:
    """Internal: scrape tax deed listings from RealForeclose."""
    all_auctions: list[dict] = []
    seen_certs: set[str] = set()

    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True, timeout=30.0
    ) as client:

        # Step 1: Get calendar/preview for tax deed dates
        log.info(f"[{county_name}] Fetching tax deed calendar...")
        preview_url = (
            f"{base_url}?zaction=AUCTION&Zmethod=PREVIEW&ESSION=TaxDeed"
        )
        resp = await client.get(preview_url)
        resp.raise_for_status()
        calendar_html = resp.text

        # Extract all auction dates from navigation links
        date_pattern = r"AuctionDate=(\d{2}/\d{2}/\d{4})"
        raw_dates = sorted(set(re.findall(date_pattern, calendar_html)))

        if not raw_dates:
            log.warning(
                f"[{county_name}] No tax deed dates found in calendar"
            )
            return all_auctions

        log.info(f"[{county_name}] Found {len(raw_dates)} tax deed dates")

        # Step 2: For each date, load auction items via AJAX
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

            # Load waiting (W) and running (R) areas
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

                # Key difference: filter for TAXDEED instead of FORECLOSURE
                items = parse_auction_items(expanded, "TAXDEED")

                for item in items:
                    # For tax deeds, case_number field holds the cert number
                    cert_number = item.get("case_number")
                    if not cert_number or cert_number in seen_certs:
                        continue
                    seen_certs.add(cert_number)

                    aid = item.get("auction_id")
                    auction_url = None
                    if aid:
                        auction_url = (
                            f"https://{subdomain}.realforeclose.com"
                            f"/index.cfm?zaction=auction&zmethod=details"
                            f"&AID={aid}"
                        )

                    # Field mapping for tax deed rows
                    auction = {
                        "sale_type": "tax_deed",  # HARDCODED — never dynamic
                        "county": county_slug,
                        # Tax deed uses cert_number, not case_number
                        "cert_number": cert_number,
                        "case_number": None,  # Foreclosure-only field
                        # Opening bid = judgment_amount field in RealForeclose
                        "opening_bid": item.get("judgment_amount"),
                        "judgment_amount": None,  # Foreclosure-only field
                        "plaintiff": None,  # Foreclosure-only field
                        # Cert holder if available from listing
                        "cert_holder": item.get("cert_holder"),
                        # Property data from listing
                        "property_address": item.get("property_address"),
                        "parcel_id": item.get("parcel_id"),
                        "assessed_value": item.get("assessed_value"),
                        # Date/venue
                        "auction_date": (
                            auction_date.isoformat()
                            if auction_date
                            else None
                        ),
                        "auction_venue": "online",
                        "auction_url": auction_url,
                        "realforeclose_url": auction_url,
                        "clerk_url": None,
                        "bcpao_enriched": False,
                    }
                    all_auctions.append(auction)

    return all_auctions


# ---------------------------------------------------------------------------
# Supabase insert
# ---------------------------------------------------------------------------

async def insert_to_supabase(auctions: list[dict]) -> int:
    """Insert tax deed auctions into multi_county_auctions table.

    Deduplicates against existing rows using cert_number + county.
    Returns number of rows successfully inserted.
    """
    if not auctions:
        return 0

    county = auctions[0].get("county", "")
    existing_certs = await fetch_existing_identifiers(
        county, "tax_deed", "cert_number"
    )

    rows = []
    skipped = 0
    for a in auctions:
        cert = a.get("cert_number", "")
        if cert in existing_certs:
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
    print(f"DRY RUN — {len(auctions)} tax deed auctions scraped")
    print(f"{'='*80}")

    for i, a in enumerate(auctions[:limit]):
        print(f"\n--- Tax Deed {i+1} ---")
        print(f"  sale_type:         {a.get('sale_type')}")
        print(f"  county:            {a.get('county')}")
        print(f"  cert_number:       {a.get('cert_number')}")
        print(f"  opening_bid:       {a.get('opening_bid')}")
        print(f"  cert_holder:       {a.get('cert_holder')}")
        print(f"  property_address:  {a.get('property_address')}")
        print(f"  parcel_id:         {a.get('parcel_id')}")
        print(f"  assessed_value:    {a.get('assessed_value')}")
        print(f"  auction_date:      {a.get('auction_date')}")
        print(f"  auction_venue:     {a.get('auction_venue')}")
        print(f"  auction_url:       {a.get('auction_url')}")
        print(f"  realforeclose_url: {a.get('realforeclose_url')}")

    if len(auctions) > limit:
        print(f"\n... and {len(auctions) - limit} more")
    print(f"\n{'='*80}")


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="ZoneWise Tax Deed Scraper"
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

    log.info(f"Starting tax deed scraper for {args.county}...")
    start = time.time()

    auctions = await scrape_tax_deeds(county_slug=args.county)

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
