"""
ZoneWise.AI — BCPAO Enrichment Pass
Enriches Brevard County auction rows with property data from BCPAO GIS.

This is what makes ZoneWise match PropertyOnion: every property card shows
sqft, assessed value, property type, lot size — all from BCPAO GIS Layer 5.

Note: BCPAO GIS Layer 5 (Parcel Property) does NOT have beds/baths/year_built.
Those fields require the bcpao.us building detail API (Cloudflare-blocked) or
a separate browser-based enrichment pass. This enricher fills everything that
GIS provides: valuation, sqft (LIV_AREA), use code → property_type, lot_size,
address components, city/zip, parcel links.

BCPAO = Brevard County Property Appraiser Office.
Only works for county='brevard'. Non-Brevard counties use different PA sources.

Usage:
  python scrapers/bcpao_enricher.py --dry-run
  python scrapers/bcpao_enricher.py
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bcpao_enricher")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BCPAO_GIS_LAYER5 = (
    "https://gis.brevardfl.gov/gissrv/rest/services/"
    "Base_Map/Parcel_New_WKID2881/MapServer/5/query"
)

GIS_OUT_FIELDS = (
    "TaxAcct,PARCEL_ID,OWNER_NAME1,OWNER_NAME2,"
    "STREET_NUMBER,STREET_DIRECTION_PREFIX,STREET_NAME,STREET_TYPE,"
    "CITY,STATE,ZIP_CODE,"
    "LIV_AREA,BLDG_VALUE,LAND_VALUE,ACRES,USE_CODE,USE_CODE_DESCRIPTION,"
    "SUBDIVISION_NAME,HOMESTEAD_VALUE"
)

# BCPAO photo URL pattern — prefix = first 4 digits of account number
BCPAO_PHOTO_TEMPLATE = "https://www.bcpao.us/photos/{prefix}/{account}011.jpg"

SUPABASE_URL = os.getenv(
    "SUPABASE_URL", "https://mocerqjnksmhcjzxrewo.supabase.co"
)
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Management API for SQL queries (alternative to REST API)
MGMT_TOKEN = os.environ.get("SUPABASE_MGMT_TOKEN", "")

GIS_DELAY = 1.5  # seconds between GIS requests


# ---------------------------------------------------------------------------
# BCPAO use code → property_type mapping
# ---------------------------------------------------------------------------

USE_CODE_MAP = {
    "0001": "SFR",       # Single family residential (improved)
    "0009": "Land",      # Vacant residential (unplatted)
    "0100": "SFR",       # Single family residential
    "0200": "Multi",     # Mobile home
    "0400": "Condo",     # Condominium
    "0500": "Multi",     # Cooperatives
    "0700": "Multi",     # Multi-family (2-9 units)
    "0800": "Multi",     # Multi-family (10+ units)
    "0900": "Land",      # Vacant residential
    "1000": "Land",      # Vacant commercial
    "1100": "Commercial", # Stores
    "1200": "Commercial", # Mixed use
    "1400": "Commercial", # Supermarkets
    "1600": "Commercial", # Community shopping centers
    "1700": "Commercial", # Office buildings
    "1900": "Commercial", # Professional service buildings
    "2100": "Commercial", # Restaurants
    "2300": "Commercial", # Financial institutions
    "2700": "Commercial", # Auto sales
    "3900": "Commercial", # Hotels
    "4800": "Commercial", # Warehouses
}


def map_property_type(use_code: str) -> str:
    """Map BCPAO use code to property type."""
    if not use_code:
        return "Unknown"
    # Try exact match first, then prefix match
    code = str(use_code).zfill(4)
    if code in USE_CODE_MAP:
        return USE_CODE_MAP[code]
    prefix = code[:2]
    if prefix == "00":
        return "Land"       # 0001-0099: Vacant residential
    if prefix == "01":
        return "SFR"        # 0100-0199: Single family
    if prefix in ("02", "03"):
        return "Multi"      # 0200-0399: Mobile/manufactured homes
    if prefix in ("04", "05"):
        return "Condo"      # 0400-0599: Condos/cooperatives
    if prefix == "06":
        return "Multi"      # 0600-0699: Retirement homes
    if prefix in ("07", "08"):
        return "Multi"      # 0700-0899: Multi-family
    if prefix in ("09", "10"):
        return "Land"       # 0900-1099: Vacant land
    try:
        if int(prefix) >= 11:
            return "Commercial"
    except ValueError:
        pass
    return "Unknown"


# ---------------------------------------------------------------------------
# BCPAO GIS query
# ---------------------------------------------------------------------------

async def query_bcpao_by_taxacct(
    tax_acct: str,
    client: httpx.AsyncClient,
) -> Optional[dict]:
    """Query BCPAO GIS Layer 5 by TaxAcct (parcel number)."""
    params = {
        "where": f"TaxAcct={tax_acct}",
        "outFields": GIS_OUT_FIELDS,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    try:
        resp = await client.get(BCPAO_GIS_LAYER5, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if features:
            return features[0].get("attributes")
    except Exception as e:
        log.warning(f"GIS query failed for TaxAcct={tax_acct}: {e}")
    return None


async def query_bcpao_by_address(
    address: str,
    client: httpx.AsyncClient,
) -> Optional[dict]:
    """Query BCPAO GIS Layer 5 by property address.

    BCPAO GIS stores address components separately:
      STREET_NUMBER, STREET_DIRECTION_PREFIX, STREET_NAME, STREET_TYPE
    Split the input address and query those fields individually.
    """
    if not address or address.strip() in ("0 UNKNOWN", "UNKNOWN", ""):
        return None

    clean = address.upper().strip()
    # Remove city/state/zip after comma
    clean = clean.split(",")[0].strip()
    # Remove FL suffix and zip
    clean = re.sub(r'\s+FL[-\s]*\d*$', '', clean).strip()

    # Split into street number and rest
    parts = clean.split(None, 1)
    if len(parts) < 2:
        return None

    street_number = parts[0]
    street_rest = parts[1]

    # Remove direction suffixes/prefixes (stored in STREET_DIRECTION_PREFIX)
    street_rest = re.sub(r'\b(NE|NW|SE|SW|N|S|E|W)\b', '', street_rest).strip()
    # Remove street type suffixes (stored in STREET_TYPE)
    street_rest = re.sub(
        r'\b(ST|AVE|AVENUE|DR|DRIVE|BLVD|BOULEVARD|CT|COURT|CIR|CIRCLE|'
        r'LN|LANE|RD|ROAD|WAY|PL|PLACE|TRL|TRAIL|PKWY|PARKWAY|'
        r'TER|TERRACE|HWY|HIGHWAY)\b$',
        '', street_rest
    ).strip()

    if not street_number.isdigit() or not street_rest:
        return None

    # STREET_NUMBER is esriFieldTypeString — must be quoted
    where = (
        f"STREET_NUMBER='{street_number}' "
        f"AND STREET_NAME LIKE '%{street_rest}%'"
    )

    params = {
        "where": where,
        "outFields": GIS_OUT_FIELDS,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    try:
        resp = await client.get(BCPAO_GIS_LAYER5, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if features:
            return features[0].get("attributes")
    except Exception as e:
        log.warning(f"GIS query failed for address={address}: {e}")
    return None


# ---------------------------------------------------------------------------
# Build enrichment payload from GIS attributes
# ---------------------------------------------------------------------------

def build_enrichment(attrs: dict) -> dict:
    """Extract PropertyOnion-equivalent fields from BCPAO GIS attributes.

    Layer 5 provides: valuation, sqft (LIV_AREA), use code, lot_size (ACRES),
    address components, city/zip. Does NOT have beds/baths/year_built.
    """
    tax_acct = attrs.get("TaxAcct")
    use_code = attrs.get("USE_CODE")

    # Build full address from components if not already set
    street_parts = [
        str(attrs.get("STREET_NUMBER", "") or "").strip(),
        str(attrs.get("STREET_DIRECTION_PREFIX", "") or "").strip(),
        str(attrs.get("STREET_NAME", "") or "").strip(),
        str(attrs.get("STREET_TYPE", "") or "").strip(),
    ]
    full_address = " ".join(p for p in street_parts if p).strip()
    # Skip "UNKNOWN" pseudo-addresses (vacant land with no real address)
    if full_address in ("UNKNOWN", ""):
        full_address = None

    bldg_val = attrs.get("BLDG_VALUE") or 0
    land_val = attrs.get("LAND_VALUE") or 0
    total_val = bldg_val + land_val

    # Construct photo URL from account number
    photo_url = None
    if tax_acct and bldg_val > 0:
        acct_str = str(tax_acct)
        prefix = acct_str[:4] if len(acct_str) >= 4 else acct_str
        photo_url = BCPAO_PHOTO_TEMPLATE.format(
            prefix=prefix, account=acct_str
        )

    city = (attrs.get("CITY") or "").strip() or None
    zip_code = (str(attrs.get("ZIP_CODE", "") or "")).strip() or None

    enrichment = {
        "parcel_id": str(tax_acct) if tax_acct else None,
        "assessed_value": total_val or None,
        "market_value": total_val or None,
        "property_type": map_property_type(use_code),
        # beds, baths, year_built: NOT on GIS Layer 5, left as NULL
        "sqft": attrs.get("LIV_AREA") or None,
        "lot_size": attrs.get("ACRES"),
        "photo_url": photo_url,
        "city": city,
        "zip": zip_code,
        "bcpao_url": (
            f"https://www.bcpao.us/propertysearch/#id={tax_acct}"
            if tax_acct
            else None
        ),
        "acclaimweb_url": (
            f"https://vweb1.brevardclerk.us/AcclaimWeb/search/"
            f"SearchTypeByPartyName?b={tax_acct}"
            if tax_acct
            else None
        ),
        "bcpao_enriched": True,
    }

    # Fill property_address from GIS if we have it and row doesn't
    if full_address:
        enrichment["_gis_address"] = full_address

    return enrichment


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _run_sql(sql: str) -> list[dict]:
    """Execute SQL via Supabase Management API."""
    import urllib.request

    url = "https://api.supabase.com/v1/projects/mocerqjnksmhcjzxrewo/database/query"
    data = json.dumps({"query": sql}).encode()
    req = urllib.request.Request(
        url,
        data,
        method="POST",
        headers={
            "Authorization": f"Bearer {MGMT_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "supabase-cli/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.error(f"SQL execution failed: {e}")
        return []


def patch_row(row_id: str, enrichment: dict) -> bool:
    """UPDATE a single row in multi_county_auctions via Management API SQL.

    Uses Management API instead of REST API because SUPABASE_SERVICE_KEY
    is not set locally. Management API SQL works with just the mgmt token.
    """
    # Remove internal fields
    payload = {k: v for k, v in enrichment.items() if not k.startswith("_")}

    # Build SET clause
    set_parts = []
    for k, v in payload.items():
        if v is None:
            set_parts.append(f"{k} = NULL")
        elif isinstance(v, bool):
            set_parts.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, (int, float)):
            set_parts.append(f"{k} = {v}")
        else:
            # Escape single quotes in string values
            escaped = str(v).replace("'", "''")
            set_parts.append(f"{k} = '{escaped}'")

    set_clause = ", ".join(set_parts)
    sql = f"UPDATE multi_county_auctions SET {set_clause} WHERE id = '{row_id}';"

    result = _run_sql(sql)
    # Management API returns [] on success for UPDATE
    if isinstance(result, list):
        return True
    log.warning(f"UPDATE failed for row {row_id}: {result}")
    return False


# ---------------------------------------------------------------------------
# Main enrichment pass
# ---------------------------------------------------------------------------

async def enrich_brevard_rows(dry_run: bool = False) -> dict:
    """Enrich all Brevard rows that haven't been BCPAO-enriched yet.

    Returns stats dict with enriched/skipped/failed counts.
    """
    # Get unenriched Brevard rows
    rows = _run_sql(
        "SELECT id, parcel_id, property_address, sale_type "
        "FROM multi_county_auctions "
        "WHERE LOWER(county) = 'brevard' "
        "AND (bcpao_enriched IS NULL OR bcpao_enriched = false) "
        "ORDER BY id;"
    )

    if not rows:
        log.info("No unenriched Brevard rows found")
        return {"enriched": 0, "skipped": 0, "failed": 0}

    log.info(f"Found {len(rows)} unenriched Brevard rows")

    stats = {"enriched": 0, "skipped": 0, "failed": 0}

    async with httpx.AsyncClient(
        headers={"User-Agent": "BidDeed.AI/2.0"},
        timeout=15.0,
    ) as client:

        for i, row in enumerate(rows):
            row_id = row["id"]
            parcel_id = row.get("parcel_id")
            address = row.get("property_address")

            log.info(
                f"[{i+1}/{len(rows)}] Enriching row {row_id} "
                f"(parcel={parcel_id}, addr={address})"
            )

            # Query BCPAO — try parcel_id first, then address
            attrs = None
            if parcel_id and parcel_id.isdigit():
                attrs = await query_bcpao_by_taxacct(parcel_id, client)

            if not attrs and address:
                attrs = await query_bcpao_by_address(address, client)

            if not attrs:
                log.warning(f"  No BCPAO match for row {row_id}")
                stats["skipped"] += 1
                await asyncio.sleep(GIS_DELAY)
                continue

            enrichment = build_enrichment(attrs)

            # If row has no address but GIS has one, fill it
            if not address and enrichment.get("_gis_address"):
                enrichment["property_address"] = enrichment["_gis_address"]

            if dry_run:
                print(f"\n  Row {row_id} would be enriched with:")
                for k, v in enrichment.items():
                    if not k.startswith("_") and v is not None:
                        print(f"    {k}: {v}")
                stats["enriched"] += 1
            else:
                success = patch_row(row_id, enrichment)
                if success:
                    stats["enriched"] += 1
                    log.info(f"  Enriched row {row_id}")
                else:
                    stats["failed"] += 1

            await asyncio.sleep(GIS_DELAY)

    log.info(
        f"Enrichment complete: {stats['enriched']} enriched, "
        f"{stats['skipped']} skipped, {stats['failed']} failed"
    )
    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="ZoneWise BCPAO Enrichment Pass"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print enrichment data without patching Supabase",
    )
    args = parser.parse_args()

    log.info("Starting BCPAO enrichment pass for Brevard County...")
    start = time.time()

    stats = await enrich_brevard_rows(dry_run=args.dry_run)

    elapsed = time.time() - start
    log.info(f"Enrichment took {elapsed:.1f}s")
    log.info(f"Results: {json.dumps(stats)}")


if __name__ == "__main__":
    asyncio.run(main())
