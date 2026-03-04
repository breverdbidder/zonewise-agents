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

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"

PO_EMAIL = os.environ.get("PROPERTYONION_EMAIL", "")
PO_PASSWORD = os.environ.get("PROPERTYONION_PASSWORD", "")

PO_LOGIN_URL = "https://propertyonion.com/login"

COUNTY_PO_URLS = {
    "brevard": "https://propertyonion.com/property_search/Brevard-County",
    "hillsborough": "https://propertyonion.com/property_search/Hillsborough-County",
    "orange": "https://propertyonion.com/property_search/Orange-County",
    "polk": "https://propertyonion.com/property_search/Polk-County",
    "palm_beach": "https://propertyonion.com/property_search/Palm-Beach-County",
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
            "FIRECRAWL_API_KEY": FIRECRAWL_API_KEY,
        })
    return [k for k, v in required.items() if not v]


# ---------------------------------------------------------------------------
# PHASE 1 — PropertyOnion Scraping via Firecrawl
# ---------------------------------------------------------------------------

def _build_po_login_actions(county_url: str) -> list[dict]:
    """Build Firecrawl action chain: login + navigate to county page.

    Embeds login at the START of every call because Firecrawl
    creates a new browser session per call (cookies don't persist).
    Uses executeJavascript for Angular form filling (same pattern as BECA).
    """
    # JS to fill login form and dispatch input events for Angular change detection
    js_fill = (
        "var emailInput = document.querySelector("
        "'input[type=\"email\"], input[name=\"email\"], #email');"
        "var passInput = document.querySelector("
        "'input[type=\"password\"], input[name=\"password\"], #password');"
        "if (emailInput) {"
        f"  emailInput.value = '{PO_EMAIL}';"
        "  emailInput.dispatchEvent(new Event('input', {bubbles: true}));"
        "  emailInput.dispatchEvent(new Event('change', {bubbles: true}));"
        "}"
        "if (passInput) {"
        f"  passInput.value = '{PO_PASSWORD}';"
        "  passInput.dispatchEvent(new Event('input', {bubbles: true}));"
        "  passInput.dispatchEvent(new Event('change', {bubbles: true}));"
        "}"
    )

    return [
        # Wait for page to render
        {"type": "wait", "milliseconds": 5000},
        # Fill credentials via JS (Angular forms need dispatched events)
        {"type": "executeJavascript", "script": js_fill},
        {"type": "wait", "milliseconds": 1000},
        # Click login/submit button
        {"type": "click", "selector": (
            "button[type='submit'], .login-btn, "
            "input[type='submit'], button.btn-primary"
        )},
        {"type": "wait", "milliseconds": 6000},
        # Navigate to county search page
        {"type": "executeJavascript", "script": (
            f"window.location.href = '{county_url}';"
        )},
        {"type": "wait", "milliseconds": 8000},
    ]


def _firecrawl_scrape(county_slug: str, page: int = 1) -> dict:
    """Execute a single Firecrawl scrape call for a PO county page.

    Handles login + navigation + content capture in one action chain.
    Returns raw Firecrawl response dict.
    """
    county_url = COUNTY_PO_URLS[county_slug]
    if page > 1:
        county_url += f"?page={page}"

    actions = _build_po_login_actions(county_url)

    payload = {
        "url": PO_LOGIN_URL,
        "formats": ["markdown", "html"],
        "waitFor": 3000,
        "timeout": 60000,
        "actions": actions,
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"{FIRECRAWL_BASE}/scrape",
            json=payload,
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


def parse_po_markdown(md: str, html: str, county_slug: str) -> list[dict]:
    """Parse PropertyOnion response into listing dicts.

    Tries markdown table parsing first, falls back to HTML regex.
    Excludes Orange County timeshare rows.
    """
    listings = []

    # Try markdown table parsing: look for rows between | delimiters
    lines = md.split("\n")
    header_idx = None
    headers = []

    for i, line in enumerate(lines):
        if "|" in line and any(
            kw in line.lower()
            for kw in ["case", "cert", "address", "sale date", "auction"]
        ):
            headers = [
                h.strip().lower().replace(" ", "_")
                for h in line.split("|")
                if h.strip()
            ]
            header_idx = i
            break

    if header_idx is not None and headers:
        # Skip separator row (---) after header
        data_start = header_idx + 2
        for line in lines[data_start:]:
            if "|" not in line or line.strip().startswith("---"):
                if not line.strip():
                    break
                continue
            cells = [c.strip() for c in line.split("|") if c.strip() != ""]
            if len(cells) < 2:
                continue

            row = {}
            for j, header in enumerate(headers):
                if j < len(cells):
                    row[header] = cells[j] if cells[j] != "-" else None

            listing = _map_po_fields(row)
            if listing.get("identifier"):
                # Orange County: skip timeshares
                if county_slug == "orange" and is_timeshare(listing):
                    continue
                listings.append(listing)

    # Fallback: parse from HTML if markdown yielded nothing
    if not listings and html:
        listings = _parse_po_html(html, county_slug)

    return listings


def _map_po_fields(row: dict) -> dict:
    """Map PropertyOnion field names to our standard fields."""
    def _get(keys: list[str]) -> Optional[str]:
        for k in keys:
            val = row.get(k)
            if val:
                return str(val).strip()
        return None

    def _currency(val: Optional[str]) -> Optional[float]:
        if not val:
            return None
        clean = re.sub(r"[^0-9.]", "", val)
        try:
            return float(clean) if clean else None
        except ValueError:
            return None

    def _int_val(val: Optional[str]) -> Optional[int]:
        if not val:
            return None
        clean = re.sub(r"[^0-9]", "", val)
        try:
            return int(clean) if clean else None
        except ValueError:
            return None

    identifier = _get([
        "case_number", "case_#", "case", "cert_number", "cert_#",
        "certificate", "identifier", "id",
    ])
    sale_type_raw = _get([
        "sale_type", "type", "auction_type", "sale",
    ])

    sale_type = "foreclosure"
    if sale_type_raw:
        if "tax" in sale_type_raw.lower() or "deed" in sale_type_raw.lower():
            sale_type = "tax_deed"

    return {
        "identifier": identifier,
        "address": _get([
            "address", "property_address", "property",
        ]),
        "sale_date": _get([
            "sale_date", "auction_date", "date",
        ]),
        "sale_type": sale_type,
        "judgment_amount": _currency(_get([
            "judgment_amount", "judgment", "final_judgment",
        ])),
        "opening_bid": _currency(_get([
            "opening_bid", "minimum_bid", "bid",
        ])),
        "assessed_value": _currency(_get([
            "assessed_value", "assessed", "appraised_value",
        ])),
        "market_value": _currency(_get([
            "market_value", "market",
        ])),
        "plaintiff": _get([
            "plaintiff", "plaintiff_name",
        ]),
        "cert_holder": _get([
            "cert_holder", "certificate_holder",
        ]),
        "property_type": _get([
            "property_type", "type", "use",
        ]),
        "beds": _int_val(_get(["beds", "bedrooms"])),
        "baths": _int_val(_get(["baths", "bathrooms"])),
        "sqft": _int_val(_get(["sqft", "sq_ft", "square_feet", "living_area"])),
        "year_built": _int_val(_get(["year_built", "built"])),
        "photo_url": _get(["photo_url", "photo", "image"]),
    }


def _parse_po_html(html: str, county_slug: str) -> list[dict]:
    """Fallback HTML parser for PropertyOnion listings.

    Looks for common patterns: .property-card, table rows, data attributes.
    """
    listings = []

    # Pattern 1: Look for table rows with auction data
    row_pattern = re.compile(
        r'<tr[^>]*>(.*?)</tr>',
        re.IGNORECASE | re.DOTALL,
    )
    cell_pattern = re.compile(
        r'<td[^>]*>(.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )

    rows = row_pattern.findall(html)
    for row_html in rows:
        cells = cell_pattern.findall(row_html)
        if len(cells) >= 3:
            # Strip HTML from cells
            clean_cells = [
                re.sub(r'<[^>]+>', '', c).strip()
                for c in cells
            ]

            # Try to identify if this is an auction listing
            has_case = any(
                re.match(r'\d{2,4}-\d{4}-\w{2}', c) for c in clean_cells
            )
            if has_case:
                listing = {
                    "identifier": clean_cells[0] if len(clean_cells) > 0 else None,
                    "address": clean_cells[1] if len(clean_cells) > 1 else None,
                    "sale_date": clean_cells[2] if len(clean_cells) > 2 else None,
                    "sale_type": "foreclosure",
                }
                if county_slug == "orange" and is_timeshare(listing):
                    continue
                listings.append(listing)

    return listings


def extract_po_total_count(md: str) -> Optional[int]:
    """Extract total listing count from paginator text in markdown."""
    patterns = [
        r"(?:Showing|Displaying)\s+\d+\s+(?:to|of)\s+\d+\s+of\s+(\d+)",
        r"(\d+)\s+(?:results?|listings?|properties|records)",
        r"Page\s+\d+\s+of\s+(\d+)",
        r"Total:\s*(\d+)",
    ]
    for p in patterns:
        m = re.search(p, md, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def scrape_po_county(county_slug: str) -> dict:
    """Scrape PropertyOnion for a single county. Returns result dict."""
    result = {
        "county": county_slug,
        "total_count": 0,
        "listings": [],
        "success": False,
        "error": None,
        "pages_scraped": 0,
    }

    for attempt in range(1, MAX_PO_RETRIES + 1):
        try:
            log.info(
                f"[{county_slug.upper()}] PO scrape attempt {attempt}/{MAX_PO_RETRIES}"
            )
            raw = _firecrawl_scrape(county_slug, page=1)

            data = raw.get("data", raw)
            md = data.get("markdown", "")
            html = data.get("html", "")

            # Check if login succeeded
            login_failed = any(
                indicator in md.lower()
                for indicator in [
                    "sign in", "log in", "login", "forgot password",
                    "create account", "register",
                ]
            ) and not any(
                indicator in md.lower()
                for indicator in [
                    "logout", "sign out", "my account", "dashboard",
                    "property search", "results",
                ]
            )

            if login_failed and attempt < MAX_PO_RETRIES:
                log.warning(
                    f"[{county_slug.upper()}] Login appears to have failed, retrying..."
                )
                time.sleep(5)
                continue

            # Log first response for debugging
            if attempt == 1:
                log.info(f"[{county_slug.upper()}] Response markdown preview:")
                log.info(md[:500] if md else "(empty)")

            listings = parse_po_markdown(md, html, county_slug)
            total = extract_po_total_count(md) or len(listings)

            result["listings"] = listings
            result["total_count"] = total
            result["pages_scraped"] = 1
            result["success"] = True

            # Handle pagination if total > listings on page 1
            if total > len(listings) and len(listings) > 0:
                items_per_page = len(listings)
                total_pages = (total + items_per_page - 1) // items_per_page
                total_pages = min(total_pages, 10)  # Safety cap

                for page in range(2, total_pages + 1):
                    time.sleep(INTER_PAGE_DELAY)
                    try:
                        page_raw = _firecrawl_scrape(county_slug, page=page)
                        page_data = page_raw.get("data", page_raw)
                        page_md = page_data.get("markdown", "")
                        page_html = page_data.get("html", "")
                        page_listings = parse_po_markdown(
                            page_md, page_html, county_slug
                        )
                        if not page_listings:
                            break
                        result["listings"].extend(page_listings)
                        result["pages_scraped"] += 1
                        log.info(
                            f"[{county_slug.upper()}] Page {page}: "
                            f"{len(page_listings)} listings"
                        )
                    except Exception as e:
                        log.warning(
                            f"[{county_slug.upper()}] Page {page} failed: {e}"
                        )
                        break

            log.info(
                f"[{county_slug.upper()}] PO scrape complete: "
                f"{len(result['listings'])} listings across "
                f"{result['pages_scraped']} pages"
            )
            return result

        except Exception as e:
            log.warning(
                f"[{county_slug.upper()}] Attempt {attempt} failed: {e}"
            )
            if attempt < MAX_PO_RETRIES:
                time.sleep(5)

    result["error"] = "All PO scrape attempts failed"
    log.error(f"[{county_slug.upper()}] {result['error']}")
    return result


def scrape_all_po_counties(
    counties: Optional[list[str]] = None,
) -> dict[str, dict]:
    """Scrape all counties from PropertyOnion."""
    counties = counties or ACTIVE_COUNTIES
    po_data = {}

    for county in counties:
        po_data[county] = scrape_po_county(county)
        if county != counties[-1]:
            time.sleep(INTER_COUNTY_DELAY)

    return po_data


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
    """Compare PropertyOnion vs ZoneWise per county/sale_type."""
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
            po_ids = {
                normalize_identifier(l["identifier"])
                for l in po_items
                if l.get("identifier")
            }

            zw_key = (county, sale_type)
            zw_info = zw_data.get(zw_key, {})
            zw_count = zw_info.get("count", 0)
            zw_ids = zw_info.get("identifiers", set())

            missing_from_zw = po_ids - zw_ids
            extra_in_zw = zw_ids - po_ids
            gap = po_count - zw_count

            if not po_success:
                status = "PO_UNAVAILABLE"
            elif gap == 0 and len(missing_from_zw) == 0:
                status = "PARITY"
            elif gap < 0:
                status = "AHEAD"
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
                "missing_from_zw": sorted(missing_from_zw),
                "extra_in_zw": sorted(extra_in_zw),
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

        if r["missing_from_zw"]:
            print(f"  MISSING FROM ZONEWISE: {r['missing_from_zw']}")
        if r["extra_in_zw"]:
            extra_display = r["extra_in_zw"][:20]
            print(f"  IN ZONEWISE NOT IN PO: {extra_display}")
            if len(r["extra_in_zw"]) > 20:
                print(f"    ... and {len(r['extra_in_zw']) - 20} more")

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
    """For each gap, re-fetch from RealForeclose source and insert."""
    from scrapers.foreclosure_scraper import scrape_foreclosures
    from scrapers.tax_deed_scraper import scrape_tax_deeds

    gaps = [r for r in report if r["status"] == "GAP" and r["missing_from_zw"]]
    results = {
        "gaps_found": sum(len(r["missing_from_zw"]) for r in gaps),
        "gaps_closed": 0,
        "gaps_failed": 0,
        "details": [],
    }

    if not gaps:
        log.info("No gaps to close")
        return results

    log.info(f"Closing {results['gaps_found']} gaps across {len(gaps)} county/type combos")

    for r in gaps:
        county = r["county"]
        sale_type = r["sale_type"]
        missing = set(r["missing_from_zw"])

        log.info(
            f"Closing gap: {county} | {sale_type} | "
            f"{len(missing)} missing identifiers"
        )

        # Re-scrape the full county from RealForeclose
        try:
            if sale_type == "foreclosure":
                scraped = await scrape_foreclosures(county_slug=county)
            else:
                scraped = await scrape_tax_deeds(county_slug=county)
        except Exception as e:
            log.error(f"Scraper failed for {county}/{sale_type}: {e}")
            results["gaps_failed"] += len(missing)
            for ident in missing:
                results["details"].append({
                    "county": county,
                    "sale_type": sale_type,
                    "identifier": ident,
                    "status": f"scraper_error: {e}",
                })
            continue

        # Filter to only the missing identifiers
        id_field = "case_number" if sale_type == "foreclosure" else "cert_number"
        new_rows = []
        for row in scraped:
            row_id = normalize_identifier(row.get(id_field, "") or "")
            if row_id in missing:
                new_rows.append(row)
                missing.discard(row_id)

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

        # Log any still-missing identifiers
        for ident in missing:
            results["gaps_failed"] += 1
            results["details"].append({
                "county": county,
                "sale_type": sale_type,
                "identifier": ident,
                "status": "not_found_in_source",
            })
            log.warning(f"  NOT FOUND in RealForeclose: {ident}")

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
        "verified_against": "PropertyOnion via Firecrawl",
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
            po_data = scrape_all_po_counties(counties)
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
