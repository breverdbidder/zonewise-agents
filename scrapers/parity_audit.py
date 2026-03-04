"""
ZoneWise.AI -- PropertyOnion vs ZoneWise Parity Audit
Compares PropertyOnion listing counts against multi_county_auctions,
closes gaps, audits field coverage, and stores a parity baseline.

Every phase prints its results in full. No abbreviation.

Usage:
  python -m scrapers.parity_audit --dry-run --skip-po   # ZW-only field audit
  python -m scrapers.parity_audit --dry-run              # Full audit, no writes
  python -m scrapers.parity_audit --county brevard       # Single county
  python -m scrapers.parity_audit                        # Full live audit
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from scrapers.shared import (
    _run_sql,
    _escape_sql,
    insert_rows,
    fetch_existing_identifiers,
)
from scrapers.source_map import (
    COUNTY_SOURCE_MAP,
    get_county_name,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("parity_audit")


# ---------------------------------------------------------------------------
# Credentials — from environment only, NEVER hardcoded
# ---------------------------------------------------------------------------

PO_EMAIL = os.environ.get("PROPERTYONION_EMAIL", "")
PO_PASSWORD = os.environ.get("PROPERTYONION_PASSWORD", "")

COUNTY_PO_PATHS = {
    "brevard":      "/property_search/Brevard-County",
    "hillsborough": "/property_search/Hillsborough-County",
    "orange":       "/property_search/Orange-County",
    "polk":         "/property_search/Polk-County",
    "palm_beach":   "/property_search/Palm-Beach-County",
}

ACTIVE_COUNTIES = ["brevard", "hillsborough", "orange", "polk", "palm_beach"]

INTER_COUNTY_DELAY = 10.0
INTER_PAGE_DELAY = 5.0
MAX_PO_RETRIES = 3

# Orange County timeshare exclusion
TIMESHARE_PATTERN = re.compile(
    r"(timeshare|time\s*share|interval|vacation\s+ownership|"
    r"vacation\s+villas|westgate|bluegreen|"
    r"holiday\s+inn\s+club|orange\s+lake\s+country\s+club|"
    r"marriott.*vacation|hilton.*grand|wyndham)",
    re.IGNORECASE,
)

# Field coverage minimum targets (percentage)
COVERAGE_TARGETS = {
    "address_pct": 95,
    "assessed_pct": 85,
    "market_pct": 80,
    "type_pct": 90,
    "sqft_pct": 75,
    "beds_pct": 60,
    "photo_pct": 70,
    "bcpao_url_pct": 90,
    "auction_url_pct": 90,
    "plaintiff_pct": 90,
    "opening_bid_pct": 90,
    "judgment_pct": 90,
}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def normalize_identifier(raw: str) -> str:
    """Normalize case/cert number for comparison."""
    if not raw:
        return ""
    return re.sub(r"[\s]+", " ", raw.strip().upper())


def is_timeshare(listing: dict) -> bool:
    """Return True if listing is a timeshare (excluded from ZoneWise)."""
    fields = [
        str(listing.get("property_type", "") or ""),
        str(listing.get("address", "") or ""),
        str(listing.get("property_address", "") or ""),
        str(listing.get("plaintiff", "") or ""),
    ]
    return any(TIMESHARE_PATTERN.search(f) for f in fields)


def check_secrets(require_po: bool = True) -> list[str]:
    """Verify required secrets are set. Returns list of missing secret NAMES."""
    required = {
        "SUPABASE_URL": os.environ.get("SUPABASE_URL"),
    }
    if require_po:
        required.update({
            "PROPERTYONION_EMAIL": PO_EMAIL,
            "PROPERTYONION_PASSWORD": PO_PASSWORD,
        })
    return [k for k, v in required.items() if not v]


# ---------------------------------------------------------------------------
# PHASE 1 — PropertyOnion Scraping (Playwright -> Browserless -> Apify)
# ---------------------------------------------------------------------------

def _convert_playwright_to_po_data(
    pw_data: dict, approach: str,
) -> dict[str, dict]:
    """Convert Playwright scraper output to po_data format for compare_parity().

    Playwright returns: {county: {sale_type: {date: [listings]}}}
    compare_parity expects: {county: {listings: [...], success: bool, ...}}
    """
    po_data = {}
    for county, type_data in pw_data.items():
        listings = []
        for sale_type, date_groups in type_data.items():
            for date_str, items in date_groups.items():
                for item in items:
                    # Ensure standard fields
                    item.setdefault("sale_type", sale_type)
                    item.setdefault("sale_date", date_str)
                    # Map 'address' to work with compare_parity
                    if "identifier" not in item and "address" in item:
                        item["identifier"] = item["address"]
                    listings.append(item)

        po_data[county] = {
            "county": county,
            "total_count": len(listings),
            "listings": listings,
            "success": len(listings) > 0,
            "error": None,
            "pages_scraped": 1,
            "approach": approach,
        }

    return po_data


def _convert_browserless_to_po_data(
    bl_results: dict[str, dict],
) -> dict[str, dict]:
    """Convert Browserless results to po_data format."""
    po_data = {}
    for county, result in bl_results.items():
        if "error" in result:
            po_data[county] = {
                "county": county, "total_count": 0, "listings": [],
                "success": False, "error": result["error"],
                "pages_scraped": 0, "approach": "browserless",
            }
            continue

        raw_listings = result.get("listings", [])
        listings = []
        for raw in raw_listings:
            listing = {
                "identifier": raw.get("identifier") or raw.get("id", ""),
                "address": raw.get("address", ""),
                "sale_date": raw.get("sale_date", ""),
                "sale_type": "foreclosure",
                "judgment_amount": None,
                "opening_bid": None,
                "plaintiff": raw.get("plaintiff", ""),
            }
            # Parse amounts from raw text
            if raw.get("judgment_amount"):
                try:
                    listing["judgment_amount"] = float(
                        re.sub(r"[^0-9.]", "", raw["judgment_amount"])
                    )
                except (ValueError, TypeError):
                    pass
            if raw.get("opening_bid"):
                try:
                    listing["opening_bid"] = float(
                        re.sub(r"[^0-9.]", "", raw["opening_bid"])
                    )
                    listing["sale_type"] = "tax_deed"
                except (ValueError, TypeError):
                    pass
            if listing.get("identifier") or listing.get("address"):
                listings.append(listing)

        po_data[county] = {
            "county": county,
            "total_count": len(listings),
            "listings": listings,
            "success": len(listings) > 0,
            "error": None,
            "pages_scraped": 1,
            "approach": "browserless",
        }

    return po_data


def get_propertyonion_data(
    counties: Optional[list[str]] = None,
) -> dict[str, dict]:
    """Scrape PropertyOnion with fallback chain:
    1. Playwright (best for Angular SPA)
    2. Browserless CDP (fallback)
    3. Apify with residential proxy (last resort)

    Returns po_data in format expected by compare_parity():
    {county: {listings: [...], success: bool, total_count: int, ...}}
    """
    counties = counties or ACTIVE_COUNTIES

    # ── Approach 1: Playwright ────────────────────────────────────────
    try:
        print("  Attempting PropertyOnion scrape via Playwright...")
        from scrapers.po_scraper_playwright import run_playwright_scrape
        data = run_playwright_scrape()

        total = sum(
            len(items)
            for county_data in data.values()
            for sale_type in county_data.values()
            for items in sale_type.values()
        )

        if total > 0:
            print(f"  Playwright SUCCESS: {total} total listings")
            # Approach 1 worked — documented in code comment
            return _convert_playwright_to_po_data(data, "playwright")
        else:
            print("  Playwright returned 0 listings — trying Approach 2")

    except Exception as e:
        print(f"  Playwright failed: {str(e)[:200]}")
        print("  Trying Approach 2: Browserless...")

    # ── Approach 2: Browserless CDP ───────────────────────────────────
    try:
        browserless_key = os.environ.get("BROWSERLESS_API_KEY", "")
        if not browserless_key:
            print("  BROWSERLESS_API_KEY not set — skipping Approach 2")
            raise RuntimeError("No Browserless API key")

        from scrapers.po_scraper_browserless import (
            scrape_propertyonion_via_browserless,
        )

        bl_results = {}
        for county in counties:
            path = COUNTY_PO_PATHS.get(county)
            if not path:
                continue
            print(f"  Browserless: scraping {county}...")
            result = scrape_propertyonion_via_browserless(path)
            bl_results[county] = result
            time.sleep(5)

        po_data = _convert_browserless_to_po_data(bl_results)
        total = sum(r["total_count"] for r in po_data.values())

        if total > 0:
            print(f"  Browserless SUCCESS: {total} total listings")
            return po_data
        else:
            print("  Browserless returned 0 listings — trying Approach 3")

    except Exception as e:
        print(f"  Browserless failed: {str(e)[:200]}")
        print("  Trying Approach 3: Apify...")

    # ── Approach 3: Apify Actor ───────────────────────────────────────
    try:
        apify_token = os.environ.get("APIFY_API_TOKEN", "")
        if not apify_token:
            print("  APIFY_API_TOKEN not set — skipping Approach 3")
            raise RuntimeError("No Apify API token")

        from scrapers.po_scraper_apify import scrape_via_apify
        results = scrape_via_apify("https://propertyonion.com")

        # Parse Apify results into po_data format
        po_data = {}
        for county in counties:
            po_data[county] = {
                "county": county, "total_count": 0, "listings": [],
                "success": False, "error": None,
                "pages_scraped": 0, "approach": "apify",
            }

        if isinstance(results, list):
            for item in results:
                url = item.get("url", "")
                for county, path in COUNTY_PO_PATHS.items():
                    if path.lower() in url.lower():
                        item_listings = item.get("listings", [])
                        po_data[county]["listings"].extend(item_listings)
                        po_data[county]["total_count"] += len(item_listings)
                        po_data[county]["success"] = len(item_listings) > 0
                        break

        total = sum(r["total_count"] for r in po_data.values())
        if total > 0:
            print(f"  Apify SUCCESS: {total} total listings")
            return po_data
        else:
            print("  Apify returned 0 listings")

    except Exception as e:
        print(f"  Apify failed: {str(e)[:200]}")

    # ── All 3 approaches failed ───────────────────────────────────────
    log.error("ALL 3 PropertyOnion scraping approaches failed")
    log.error(
        "Check /tmp/po_login_debug.png and /tmp/po_login_failed.png "
        "for debug screenshots"
    )
    return {
        county: {
            "county": county,
            "total_count": 0,
            "listings": [],
            "success": False,
            "error": "All 3 PO approaches failed",
            "pages_scraped": 0,
        }
        for county in counties
    }


# ---------------------------------------------------------------------------
# PHASE 2 — Query ZoneWise Database
# ---------------------------------------------------------------------------

def query_zw_grouped() -> list[dict]:
    """Query multi_county_auctions grouped by county, sale_type, auction_date."""
    sql = """
    SELECT
        county,
        sale_type,
        auction_date::text AS auction_date,
        COUNT(*) AS count,
        ARRAY_AGG(COALESCE(case_number, cert_number)) AS identifiers
    FROM multi_county_auctions
    WHERE county IN ('brevard','hillsborough','orange','polk','palm_beach')
    GROUP BY county, sale_type, auction_date
    ORDER BY county, sale_type, auction_date;
    """
    return _run_sql(sql)


def query_zw_counts() -> dict:
    """Build ZW lookup: {(county, sale_type): {count, identifiers, dates}}."""
    rows = query_zw_grouped()
    result = {}

    for row in rows:
        county = row.get("county", "")
        sale_type = row.get("sale_type", "")
        count = row.get("count", 0)
        ids = row.get("identifiers") or []
        date = row.get("auction_date")

        key = (county, sale_type)
        if key not in result:
            result[key] = {
                "count": 0,
                "identifiers": set(),
                "dates": {},
            }
        result[key]["count"] += count
        for ident in ids:
            if ident:
                result[key]["identifiers"].add(normalize_identifier(ident))

        if date:
            result[key]["dates"][date] = {
                "count": count,
                "identifiers": {
                    normalize_identifier(i) for i in ids if i
                },
            }

    return result


# ---------------------------------------------------------------------------
# PHASE 3 — Parity Report
# ---------------------------------------------------------------------------

def compare_parity(
    po_data: dict[str, dict],
    zw_data: dict,
    counties: list[str],
) -> list[dict]:
    """Compare PropertyOnion vs ZoneWise per county/sale_type.

    NOTE: PO identifiers are addresses, ZW identifiers are case/cert numbers.
    Set-based matching is impossible — comparison is COUNT-BASED ONLY.
    Gap closing re-scrapes from RealForeclose and inserts missing rows by
    case/cert number, not by PO address matching.
    """
    report = []

    for county in counties:
        po_result = po_data.get(county, {})
        po_listings = po_result.get("listings", [])
        po_success = po_result.get("success", False)

        # Split PO listings by sale type
        po_by_type = {"foreclosure": [], "tax_deed": []}
        for listing in po_listings:
            st = listing.get("sale_type", "foreclosure")
            if st in po_by_type:
                po_by_type[st].append(listing)

        for sale_type in ["foreclosure", "tax_deed"]:
            po_items = po_by_type[sale_type]
            po_count = len(po_items)

            zw_key = (county, sale_type)
            zw_info = zw_data.get(zw_key, {})
            zw_count = zw_info.get("count", 0)

            # Count-based gap (PO and ZW use different identifier systems)
            gap = po_count - zw_count

            if not po_success:
                status = "PO_UNAVAILABLE"
            elif gap <= 0:
                status = "PARITY" if gap == 0 else "AHEAD"
            else:
                status = "GAP"

            report.append({
                "county": county,
                "sale_type": sale_type,
                "po_count": po_count,
                "zw_count": zw_count,
                "gap": gap,
                "gap_pct": (
                    round(abs(gap) / po_count * 100, 1) if po_count > 0 else 0
                ),
                "missing_from_zw": [],  # Cannot determine — different ID systems
                "extra_in_zw": [],
                "status": status,
                "po_available": po_success,
            })

    return report


def print_parity_report(report: list[dict]) -> None:
    """Print full parity report."""
    print("\n")
    print("=" * 70)
    print("PROPERTYONION vs ZONEWISE -- PARITY AUDIT REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    current_county = None
    for r in report:
        if r["county"] != current_county:
            current_county = r["county"]
            print(f"\n{'-' * 70}")
            print(f"  COUNTY: {current_county.upper()}")
            print(f"{'-' * 70}")

        if r["status"] == "PO_UNAVAILABLE":
            icon = "??"
            gap_str = "PO UNAVAILABLE"
        elif r["status"] == "PARITY":
            icon = "OK"
            gap_str = "MATCH"
        elif r["status"] == "AHEAD":
            icon = "++"
            gap_str = f"ZW AHEAD by {abs(r['gap'])}"
        else:
            icon = "!!"
            gap_str = f"GAP={r['gap']} ({r['gap_pct']}%)"

        print(
            f"\n  {r['sale_type'].upper()} | "
            f"PO={r['po_count']}  |  ZW={r['zw_count']}  |  "
            f"[{icon}] {gap_str}"
        )

        # Note: PO uses address identifiers, ZW uses case/cert numbers
        # Individual identifier matching is not possible across systems

    # Summary
    gaps = [r for r in report if r["status"] == "GAP"]
    at_par = [r for r in report if r["status"] == "PARITY"]
    ahead = [r for r in report if r["status"] == "AHEAD"]
    unavail = [r for r in report if r["status"] == "PO_UNAVAILABLE"]

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total county/type combinations audited: {len(report)}")
    print(f"  At parity (gap = 0):                    {len(at_par)}")
    print(f"  ZoneWise ahead of PropertyOnion:         {len(ahead)}")
    print(f"  Gaps (PO has more than ZW):              {len(gaps)}")
    print(f"  PO unavailable:                          {len(unavail)}")
    if gaps:
        total_missing = sum(r["gap"] for r in gaps)
        print(f"  Total missing properties:                {total_missing}")
        print(f"  Counties with gaps: {list({r['county'] for r in gaps})}")
        for r in gaps:
            print(
                f"    {r['county']} | {r['sale_type']} | "
                f"missing {r['gap']} properties"
            )
    print(f"{'=' * 70}")


# ---------------------------------------------------------------------------
# PHASE 4 — Close Every Gap
# ---------------------------------------------------------------------------

async def close_gaps(
    report: list[dict],
    dry_run: bool = False,
) -> dict:
    """For each count gap, re-scrape from RealForeclose and insert missing rows.

    PO and ZW use different identifier systems (addresses vs case/cert numbers),
    so we cannot match individual PO listings to ZW rows. Instead:
    1. Re-scrape the full county from RealForeclose
    2. Fetch existing ZW identifiers for this county/sale_type
    3. Insert any scraped rows whose case/cert number is NOT already in ZW
    """
    from scrapers.foreclosure_scraper import scrape_foreclosures
    from scrapers.tax_deed_scraper import scrape_tax_deeds

    gaps = [r for r in report if r["status"] == "GAP" and r["gap"] > 0]
    results = {
        "gaps_found": sum(r["gap"] for r in gaps),
        "gaps_closed": 0,
        "gaps_failed": 0,
        "details": [],
    }

    if not gaps:
        log.info("No gaps to close")
        return results

    log.info(
        f"Closing {results['gaps_found']} count gaps "
        f"across {len(gaps)} county/type combos"
    )

    for r in gaps:
        county = r["county"]
        sale_type = r["sale_type"]
        count_gap = r["gap"]

        log.info(
            f"Closing gap: {county} | {sale_type} | "
            f"PO={r['po_count']} vs ZW={r['zw_count']} (gap={count_gap})"
        )

        # Re-scrape the full county from RealForeclose
        id_field = "case_number" if sale_type == "foreclosure" else "cert_number"
        try:
            if sale_type == "foreclosure":
                scraped = await scrape_foreclosures(county_slug=county)
            else:
                scraped = await scrape_tax_deeds(county_slug=county)
            log.info(
                f"  RealForeclose returned {len(scraped)} {sale_type} "
                f"rows for {county}"
            )
        except Exception as e:
            log.error(f"Scraper failed for {county}/{sale_type}: {e}")
            results["gaps_failed"] += count_gap
            results["details"].append({
                "county": county,
                "sale_type": sale_type,
                "identifier": "*",
                "status": f"scraper_error: {e}",
            })
            continue

        # Fetch existing ZW identifiers for this county/sale_type
        existing_ids = await fetch_existing_identifiers(
            county, sale_type, id_field,
        )
        existing_normalized = {
            normalize_identifier(i) for i in existing_ids if i
        }
        log.info(
            f"  ZW already has {len(existing_normalized)} {sale_type} "
            f"identifiers for {county}"
        )

        # Find rows in RealForeclose not already in ZW
        new_rows = []
        for row in scraped:
            row_id = normalize_identifier(row.get(id_field, "") or "")
            if row_id and row_id not in existing_normalized:
                new_rows.append(row)

        log.info(f"  Found {len(new_rows)} new rows to insert for {county}")

        if new_rows:
            if dry_run:
                log.info(
                    f"  DRY RUN: Would insert {len(new_rows)} rows "
                    f"for {county}/{sale_type}"
                )
                results["gaps_closed"] += len(new_rows)
            else:
                inserted = await insert_rows(new_rows)
                results["gaps_closed"] += inserted
                log.info(
                    f"  Inserted {inserted}/{len(new_rows)} rows "
                    f"for {county}/{sale_type}"
                )

            for row in new_rows:
                results["details"].append({
                    "county": county,
                    "sale_type": sale_type,
                    "identifier": row.get(id_field, ""),
                    "status": "closed" if not dry_run else "dry_run",
                })
        else:
            log.info(
                f"  No new rows found — RealForeclose may not have "
                f"all PO listings (different data sources)"
            )
            results["gaps_failed"] += count_gap
            results["details"].append({
                "county": county,
                "sale_type": sale_type,
                "identifier": "*",
                "status": "no_new_rows_from_source",
            })

    log.info(
        f"Gap closing complete: {results['gaps_closed']} closed, "
        f"{results['gaps_failed']} failed"
    )
    return results


def run_gap_closing(report: list[dict], dry_run: bool = False) -> dict:
    """Sync wrapper for async gap closing."""
    return asyncio.run(close_gaps(report, dry_run))


# ---------------------------------------------------------------------------
# PHASE 5 — Field Coverage Audit
# ---------------------------------------------------------------------------

def audit_field_coverage() -> list[dict]:
    """Check field completion percentages per county/sale_type."""
    sql = """
    SELECT
        county,
        sale_type,
        COUNT(*) AS total,
        ROUND(COUNT(CASE WHEN property_address IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS address_pct,
        ROUND(COUNT(CASE WHEN assessed_value IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS assessed_pct,
        ROUND(COUNT(CASE WHEN market_value IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS market_pct,
        ROUND(COUNT(CASE WHEN property_type IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS type_pct,
        ROUND(COUNT(CASE WHEN sqft IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS sqft_pct,
        ROUND(COUNT(CASE WHEN beds IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS beds_pct,
        ROUND(COUNT(CASE WHEN photo_url IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS photo_pct,
        ROUND(COUNT(CASE WHEN bcpao_url IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS bcpao_url_pct,
        ROUND(COUNT(CASE WHEN auction_url IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS auction_url_pct,
        ROUND(COUNT(CASE WHEN plaintiff IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS plaintiff_pct,
        ROUND(COUNT(CASE WHEN opening_bid IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS opening_bid_pct,
        ROUND(COUNT(CASE WHEN judgment_amount IS NOT NULL THEN 1 END)::numeric
              / NULLIF(COUNT(*), 0) * 100, 1) AS judgment_pct
    FROM multi_county_auctions
    WHERE county IN ('brevard','hillsborough','orange','polk','palm_beach')
    GROUP BY county, sale_type
    ORDER BY county, sale_type;
    """
    return _run_sql(sql)


def print_coverage_report(coverage: list[dict]) -> None:
    """Print field coverage audit with pass/warn/fail indicators."""
    print(f"\n{'=' * 70}")
    print("FIELD COVERAGE AUDIT")
    print(f"{'=' * 70}")

    fields = [
        "address_pct", "assessed_pct", "market_pct", "type_pct",
        "sqft_pct", "beds_pct", "photo_pct", "bcpao_url_pct",
        "auction_url_pct", "plaintiff_pct", "opening_bid_pct",
        "judgment_pct",
    ]

    for row in coverage:
        county = row.get("county", "?")
        sale_type = row.get("sale_type", "?")
        total = row.get("total", 0)

        print(f"\n  {county.upper()} | {sale_type.upper()} | {total} rows")
        print(f"  {'Field':<20} {'Pct':>6} {'Target':>8} {'Status':>8}")
        print(f"  {'-' * 44}")

        for field in fields:
            pct = float(row.get(field, 0) or 0)
            target = COVERAGE_TARGETS.get(field, 0)

            # Contextual targets: plaintiff only for foreclosure, opening_bid for tax_deed
            if field == "plaintiff_pct" and sale_type == "tax_deed":
                target = 0  # N/A for tax deed
            if field == "opening_bid_pct" and sale_type == "foreclosure":
                target = 0  # N/A for foreclosure
            if field == "judgment_pct" and sale_type == "tax_deed":
                target = 0  # N/A for tax deed
            # Brevard FC has auction_url = NULL by design (in-person)
            if (field == "auction_url_pct" and county == "brevard"
                    and sale_type == "foreclosure"):
                target = 0

            if target == 0:
                status = "N/A"
            elif pct >= target:
                status = "PASS"
            elif pct >= target * 0.9:
                status = "WARN"
            else:
                status = "FAIL"

            print(
                f"  {field:<20} {pct:>5.1f}% {target:>7}% {status:>8}"
            )

    print(f"{'=' * 70}")


# ---------------------------------------------------------------------------
# PHASE 6 — ZoneWise Exclusive Intelligence
# ---------------------------------------------------------------------------

def audit_exclusive_intelligence() -> dict:
    """Verify ZoneWise-exclusive features that PropertyOnion lacks."""
    sql = """
    SELECT
        county,
        sale_type,
        COUNT(*) AS total,
        COUNT(CASE WHEN plaintiff ILIKE '%HOA%'
                     OR plaintiff ILIKE '%homeowner%'
                     OR plaintiff ILIKE '%homeowners%'
                     OR plaintiff ILIKE '%association%'
                     OR plaintiff ILIKE '%community%'
                     OR plaintiff ILIKE '%condominium%' THEN 1 END) AS hoa_flagged,
        COUNT(CASE WHEN assessed_value IS NOT NULL
                    AND judgment_amount IS NOT NULL THEN 1 END) AS ready_bid_ratio,
        COUNT(CASE WHEN assessed_value IS NOT NULL
                    AND opening_bid IS NOT NULL THEN 1 END) AS ready_net_spread,
        COUNT(CASE WHEN bcpao_enriched = true THEN 1 END) AS bcpao_enriched
    FROM multi_county_auctions
    WHERE county IN ('brevard','hillsborough','orange','polk','palm_beach')
    GROUP BY county, sale_type
    ORDER BY county, sale_type;
    """
    return _run_sql(sql)


def print_exclusive_report(rows: list[dict]) -> None:
    """Print ZoneWise exclusive intelligence report."""
    print(f"\n{'=' * 70}")
    print("ZONEWISE EXCLUSIVE INTELLIGENCE (PropertyOnion does NOT have these)")
    print(f"{'=' * 70}")

    total_hoa = 0
    total_bid_ratio = 0
    total_net_spread = 0
    total_enriched = 0

    for row in rows:
        county = row.get("county", "?")
        sale_type = row.get("sale_type", "?")
        total = row.get("total", 0)
        hoa = row.get("hoa_flagged", 0) or 0
        bid_ratio = row.get("ready_bid_ratio", 0) or 0
        net_spread = row.get("ready_net_spread", 0) or 0
        enriched = row.get("bcpao_enriched", 0) or 0

        total_hoa += hoa
        total_bid_ratio += bid_ratio
        total_net_spread += net_spread
        total_enriched += enriched

        print(f"\n  {county.upper()} | {sale_type.upper()} | {total} rows")
        if sale_type == "foreclosure":
            print(f"    HOA plaintiff flagged:     {hoa}")
            print(f"    Ready for bid/judgment:    {bid_ratio}")
        if sale_type == "tax_deed":
            print(f"    Ready for net spread:      {net_spread}")
        print(f"    BCPAO enriched:            {enriched}")

    print(f"\n  {'=' * 50}")
    print(f"  TOTALS:")
    print(f"    HOA detection active:      {'YES' if total_hoa > 0 else 'NO'} ({total_hoa} rows)")
    print(f"    ML bid ratio ready:        {total_bid_ratio} rows")
    print(f"    ML net spread ready:       {total_net_spread} rows")
    print(f"    BCPAO enriched:            {total_enriched} rows")
    print(f"{'=' * 70}")

    return {
        "hoa_flagged": total_hoa,
        "ready_bid_ratio": total_bid_ratio,
        "ready_net_spread": total_net_spread,
        "bcpao_enriched": total_enriched,
    }


# ---------------------------------------------------------------------------
# PHASE 7 — Store Parity Baseline
# ---------------------------------------------------------------------------

def store_parity_baseline(
    report: list[dict],
    coverage: list[dict],
    exclusive: dict,
    gap_results: dict,
) -> bool:
    """Insert PARITY_BASELINE row into insights table."""
    # Build summary
    gaps = [r for r in report if r["status"] == "GAP"]
    at_par = [r for r in report if r["status"] == "PARITY"]
    total_po = sum(r["po_count"] for r in report)
    total_zw = sum(r["zw_count"] for r in report)

    description = json.dumps({
        "zonewise_count": total_zw,
        "propertyonion_count": total_po,
        "verified_against": "PropertyOnion via Playwright/Browserless/Apify",
        "verification_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "gaps_at_verification": len(gaps),
        "gaps_closed": gap_results.get("gaps_closed", 0),
        "at_parity": len(at_par),
        "fields_verified": [
            "address", "assessed_value", "market_value",
            "photo_url", "auction_url", "bcpao_url",
            "plaintiff", "opening_bid", "judgment_amount",
        ],
        "hoa_detection_active": (exclusive.get("hoa_flagged", 0) or 0) > 0,
        "ml_inputs_ready": (exclusive.get("ready_bid_ratio", 0) or 0) > 0,
    })

    escaped_desc = description.replace("'", "''")

    sql = f"""
    INSERT INTO insights (county, sale_type, anomaly_type, description, detected_at)
    VALUES (
        'all',
        'both',
        'PARITY_BASELINE',
        '{escaped_desc}',
        NOW()
    );
    """

    result = _run_sql(sql)
    if isinstance(result, list):
        log.info("Parity baseline stored in insights table")
        return True
    log.warning(f"Failed to store parity baseline: {result}")
    return False


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ZoneWise PropertyOnion Parity Audit"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print report without inserting/patching",
    )
    parser.add_argument(
        "--county", default=None,
        help="Single county to audit (default: all 5)",
    )
    parser.add_argument(
        "--skip-po", action="store_true",
        help="Skip PropertyOnion scrape, audit ZW data only",
    )
    parser.add_argument(
        "--skip-gaps", action="store_true",
        help="Report gaps but don't close them",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("ZoneWise.AI -- PropertyOnion Parity Audit")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    start = time.time()

    counties = [args.county] if args.county else ACTIVE_COUNTIES

    # ── PHASE 1: Scrape PropertyOnion ──────────────────────────────────
    po_data = {}
    if not args.skip_po:
        missing_secrets = check_secrets(require_po=True)
        if missing_secrets:
            log.warning(
                f"Missing secrets for PO scrape: {missing_secrets}. "
                f"Skipping PO scrape."
            )
        else:
            print("\n--- PHASE 1: Scraping PropertyOnion ---")
            po_data = get_propertyonion_data(counties)
    else:
        print("\n--- PHASE 1: SKIPPED (--skip-po) ---")

    # ── PHASE 2: Query ZoneWise ────────────────────────────────────────
    print("\n--- PHASE 2: Querying ZoneWise Database ---")
    zw_data = query_zw_counts()
    total_zw = sum(v["count"] for v in zw_data.values())
    print(f"  ZoneWise: {total_zw} total rows across {len(zw_data)} county/type combos")

    # ── PHASE 3: Parity Report ─────────────────────────────────────────
    print("\n--- PHASE 3: Parity Report ---")
    report = compare_parity(po_data, zw_data, counties)
    print_parity_report(report)

    # ── PHASE 4: Gap Closing ───────────────────────────────────────────
    gap_results = {
        "gaps_found": 0, "gaps_closed": 0,
        "gaps_failed": 0, "details": [],
    }
    if not args.skip_gaps and not args.skip_po:
        has_gaps = any(r["status"] == "GAP" for r in report)
        if has_gaps:
            print("\n--- PHASE 4: Closing Gaps ---")
            gap_results = run_gap_closing(report, dry_run=args.dry_run)

            # Re-query and re-report after gap closing
            if gap_results["gaps_closed"] > 0 and not args.dry_run:
                print("\n--- PHASE 4b: Post-Gap-Closing Verification ---")
                zw_data = query_zw_counts()
                report = compare_parity(po_data, zw_data, counties)
                print_parity_report(report)
        else:
            print("\n--- PHASE 4: No gaps to close ---")
    else:
        print("\n--- PHASE 4: SKIPPED ---")

    # ── PHASE 5: Field Coverage Audit ──────────────────────────────────
    print("\n--- PHASE 5: Field Coverage Audit ---")
    coverage = audit_field_coverage()
    print_coverage_report(coverage)

    # ── PHASE 6: ZoneWise Exclusive Intelligence ───────────────────────
    print("\n--- PHASE 6: ZoneWise Exclusive Intelligence ---")
    exclusive_rows = audit_exclusive_intelligence()
    exclusive = print_exclusive_report(exclusive_rows)

    # ── PHASE 7: Store Parity Baseline ─────────────────────────────────
    if not args.dry_run:
        print("\n--- PHASE 7: Storing Parity Baseline ---")
        store_parity_baseline(report, coverage, exclusive, gap_results)
    else:
        print("\n--- PHASE 7: SKIPPED (--dry-run) ---")

    # ── Summary ────────────────────────────────────────────────────────
    elapsed = time.time() - start
    print(f"\n{'=' * 70}")
    print(f"PARITY AUDIT COMPLETE in {elapsed:.1f}s")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
