"""
ZoneWise.AI — Shared Scraper Utilities
Common parsing functions used by both foreclosure and tax deed scrapers.

Extracted from foreclosure_scraper.py to avoid duplication.
"""

import json
import logging
import os
import re
import urllib.request
from typing import Optional

import httpx

log = logging.getLogger("shared_scraper")

# ---------------------------------------------------------------------------
# HTTP Headers (required — RealForeclose returns 403 without User-Agent)
# ---------------------------------------------------------------------------

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
    pattern = (
        r'AD_LBL"[^>]*>[^<]*'
        + label_pattern
        + r'[^<]*<'
        + r'.*?'
        + r'AD_DTA"[^>]*>(.*?)</(?:td|div)>'
    )
    m = re.search(pattern, html_block, re.IGNORECASE | re.DOTALL)
    if m:
        raw_value = m.group(1)
        return strip_html_tags(raw_value).strip()
    return None


def extract_auction_type(html_block: str) -> Optional[str]:
    """Extract the Auction Type field value (FORECLOSURE or TAXDEED)."""
    return extract_field(html_block, r"Auction\s+Type")


def extract_auction_id(html_block: str) -> Optional[str]:
    """Extract AID from detail links inside an auction item."""
    m = re.search(r'AID=(\d+)', html_block, re.IGNORECASE)
    return m.group(1) if m else None


def parse_auction_items(
    expanded_html: str,
    sale_type_filter: str = "FORECLOSURE",
) -> list[dict]:
    """Parse expanded HTML into list of auction dicts.

    Only includes items matching sale_type_filter (FORECLOSURE or TAXDEED).
    """
    items = []

    aitem_pattern = re.compile(
        r'<div\s+id="AITEM_(\d+)"[^>]*AUCTION_ITEM[^>]*>(.*?)(?=<div\s+id="AITEM_|\Z)',
        re.DOTALL,
    )
    matches = aitem_pattern.findall(expanded_html)

    if not matches:
        parts = re.split(r'<div\s+[^>]*AUCTION_ITEM[^>]*', expanded_html)
        matches = [(None, part) for part in parts[1:]]

    for aid, part in matches:
        auction_type = extract_auction_type(part)
        if auction_type and auction_type.upper().strip() != sale_type_filter:
            continue

        if not aid:
            aid = extract_auction_id(part)

        case_number = extract_field(part, r"Case\s*#")
        judgment_raw = extract_field(part, r"(?:Final\s+)?Judgment\s*(?:Amount)?")
        plaintiff_raw = extract_field(part, r"Plaintiff")
        address = extract_field(part, r"(?:Property\s+)?Address")
        parcel_id = extract_field(part, r"Parcel\s*(?:ID)?")
        appraised_raw = extract_field(part, r"Assessed\s*(?:Value)?")
        plaintiff_max_raw = extract_field(part, r"Plaintiff\s+Max\s+Bid")
        opening_bid_raw = extract_field(part, r"(?:Opening|Minimum)\s+Bid")
        cert_holder_raw = extract_field(part, r"(?:Certificate|Cert)\s+Holder")

        # Look for city/state in the row immediately after address
        city_match = re.search(
            r'AD_LBL"\s*scope="row">\s*<'
            r'.*?AD_DTA"[^>]*>(.*?)</td>',
            part[part.find("Address"):] if "Address" in part else "",
            re.IGNORECASE | re.DOTALL,
        )
        city = strip_html_tags(city_match.group(1)) if city_match else None

        full_address = address or ""
        if city and city not in (full_address or ""):
            full_address = f"{full_address}, {city}" if full_address else city

        item = {
            "case_number": case_number,
            "judgment_amount": parse_currency(judgment_raw),
            "plaintiff": plaintiff_raw,
            "property_address": full_address.strip(", ") or None,
            "parcel_id": parcel_id,
            "assessed_value": parse_currency(appraised_raw),
            "opening_bid": parse_currency(opening_bid_raw),
            "plaintiff_max_bid": (
                parse_currency(plaintiff_max_raw)
                if plaintiff_max_raw and "Hidden" not in plaintiff_max_raw
                else None
            ),
            "cert_holder": cert_holder_raw,
            "auction_id": aid,
        }

        # Include items with either case number or cert number
        if case_number:
            items.append(item)

    return items


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

SUPABASE_URL = os.getenv(
    "SUPABASE_URL", "https://mocerqjnksmhcjzxrewo.supabase.co"
)
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

MGMT_TOKEN = os.environ.get("SUPABASE_MGMT_TOKEN", "")


def _run_sql(sql: str, timeout: int = 30) -> list[dict]:
    """Execute SQL via Supabase Management API."""
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.error(f"SQL execution failed: {e}")
        return []


def _escape_sql(value) -> str:
    """Escape a value for SQL insertion."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def get_supabase_headers() -> dict:
    """Get authenticated headers for Supabase REST API."""
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


async def fetch_existing_identifiers(
    county: str,
    sale_type: str,
    id_field: str = "case_number",
) -> set[str]:
    """Fetch existing identifiers from Supabase to avoid duplicates.

    Uses REST API if SUPABASE_SERVICE_KEY is set, otherwise Management API SQL.
    """
    if SUPABASE_SERVICE_KEY:
        headers = get_supabase_headers()
        url = (
            f"{SUPABASE_URL}/rest/v1/multi_county_auctions"
            f"?sale_type=eq.{sale_type}&county=eq.{county}"
            f"&select={id_field}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return {
                    row[id_field]
                    for row in resp.json()
                    if row.get(id_field)
                }
        return set()

    # Fallback: Management API SQL
    county_safe = county.replace("'", "''")
    sale_type_safe = sale_type.replace("'", "''")
    id_field_safe = id_field.replace("'", "''")
    rows = _run_sql(
        f"SELECT {id_field_safe} FROM multi_county_auctions "
        f"WHERE sale_type = '{sale_type_safe}' AND county = '{county_safe}' "
        f"AND {id_field_safe} IS NOT NULL;"
    )
    return {row[id_field] for row in rows if row.get(id_field)}


async def insert_rows(rows: list[dict]) -> int:
    """Insert rows into multi_county_auctions.

    Uses REST API if SUPABASE_SERVICE_KEY is set, otherwise Management API SQL.
    """
    if not rows:
        return 0

    if SUPABASE_SERVICE_KEY:
        return await _insert_rows_rest(rows)

    return _insert_rows_sql(rows)


async def _insert_rows_rest(rows: list[dict]) -> int:
    """Insert via Supabase REST API."""
    headers = get_supabase_headers()
    headers["Prefer"] = "return=minimal"
    url = f"{SUPABASE_URL}/rest/v1/multi_county_auctions"

    inserted = 0
    for i in range(0, len(rows), 100):
        batch = rows[i : i + 100]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=batch, headers=headers)
            if resp.status_code in (200, 201):
                inserted += len(batch)
            else:
                log.error(
                    f"Supabase insert failed (batch {i}): "
                    f"{resp.status_code} — {resp.text}"
                )

    log.info(f"Inserted {inserted}/{len(rows)} rows (REST)")
    return inserted


def _insert_rows_sql(rows: list[dict]) -> int:
    """Insert via Management API SQL (fallback when SERVICE_KEY not set)."""
    # Determine columns from first row
    columns = sorted(rows[0].keys())

    inserted = 0
    for i in range(0, len(rows), 50):
        batch = rows[i : i + 50]
        values_list = []
        for row in batch:
            vals = ", ".join(_escape_sql(row.get(col)) for col in columns)
            values_list.append(f"({vals})")

        cols_str = ", ".join(columns)
        values_str = ",\n".join(values_list)
        sql = (
            f"INSERT INTO multi_county_auctions ({cols_str})\n"
            f"VALUES {values_str};"
        )
        result = _run_sql(sql)
        if isinstance(result, list):
            inserted += len(batch)
        else:
            log.error(f"SQL insert failed (batch {i}): {result}")

    log.info(f"Inserted {inserted}/{len(rows)} rows (SQL)")
    return inserted
