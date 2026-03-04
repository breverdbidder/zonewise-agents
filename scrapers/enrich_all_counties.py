"""
ZoneWise.AI — Multi-County Enrichment Driver
Runs enrichment for all counties with unenriched rows.

Usage:
  python -m scrapers.enrich_all_counties --dry-run
  python -m scrapers.enrich_all_counties
  python -m scrapers.enrich_all_counties --county hillsborough
"""

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

from scrapers.enricher_factory import get_enricher
from scrapers.shared import _run_sql, _escape_sql

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("enrich_all")

COUNTIES = ["hillsborough", "orange", "polk", "palm_beach"]
ENRICHMENT_DELAY = 1.0  # seconds between rows


def patch_row(row_id: str, enrichment: dict) -> bool:
    """UPDATE a single row in multi_county_auctions via Management API SQL."""
    payload = {k: v for k, v in enrichment.items() if not k.startswith("_")}

    set_parts = []
    for k, v in payload.items():
        set_parts.append(f"{k} = {_escape_sql(v)}")

    set_clause = ", ".join(set_parts)
    sql = f"UPDATE multi_county_auctions SET {set_clause} WHERE id = '{row_id}';"

    result = _run_sql(sql)
    if isinstance(result, list):
        return True
    log.warning(f"UPDATE failed for row {row_id}: {result}")
    return False


async def enrich_county(
    county_slug: str,
    dry_run: bool = False,
) -> dict:
    """Run enrichment for a single county.

    Returns stats dict with enriched/skipped/failed counts.
    """
    enricher = get_enricher(county_slug)
    if not enricher:
        log.error(f"No enricher available for {county_slug}")
        return {"enriched": 0, "skipped": 0, "failed": 0, "total": 0}

    # Get unenriched rows
    rows = _run_sql(
        f"SELECT id, parcel_id, property_address, sale_type "
        f"FROM multi_county_auctions "
        f"WHERE LOWER(county) = '{county_slug}' "
        f"AND (bcpao_enriched IS NULL OR bcpao_enriched = false) "
        f"ORDER BY id;"
    )

    if not rows:
        log.info(f"[{county_slug}] No unenriched rows found")
        return {"enriched": 0, "skipped": 0, "failed": 0, "total": 0}

    log.info(f"[{county_slug}] Found {len(rows)} unenriched rows")

    stats = {"enriched": 0, "skipped": 0, "failed": 0, "total": len(rows)}

    async with httpx.AsyncClient(
        headers={"User-Agent": "ZoneWise.AI/2.0"},
        timeout=15.0,
    ) as client:
        for i, row in enumerate(rows):
            row_id = row["id"]
            parcel_id = row.get("parcel_id")
            address = row.get("property_address")

            log.info(
                f"[{county_slug}] [{i+1}/{len(rows)}] "
                f"parcel={parcel_id}, addr={address}"
            )

            enrichment = await enricher.enrich_row(row, client)

            if not enrichment:
                log.warning(f"  No enrichment data for row {row_id}")
                stats["skipped"] += 1
                await asyncio.sleep(ENRICHMENT_DELAY)
                continue

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

            await asyncio.sleep(ENRICHMENT_DELAY)

    log.info(
        f"[{county_slug}] Complete: {stats['enriched']} enriched, "
        f"{stats['skipped']} skipped, {stats['failed']} failed"
    )
    return stats


def log_blocker(county_slug: str, error: str):
    """Log enrichment blocker to claude_context_checkpoints."""
    error_safe = error.replace("'", "''")
    _run_sql(
        f"INSERT INTO claude_context_checkpoints "
        f"(pipeline_date, checkpoint_phase, errors) "
        f"VALUES (CURRENT_DATE, '2', "
        f"'[{{\"county\": \"{county_slug}\", \"error\": \"{error_safe}\", \"attempts\": 3}}]'::jsonb);"
    )


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="ZoneWise Multi-County Enrichment"
    )
    parser.add_argument(
        "--county",
        default=None,
        help="Single county to enrich (default: all 4 expansion counties)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print enrichment data without patching Supabase",
    )
    args = parser.parse_args()

    counties = [args.county] if args.county else COUNTIES

    log.info(f"Starting enrichment for {len(counties)} counties...")
    start = time.time()

    all_stats = {}
    for county in counties:
        log.info(f"\n{'='*60}")
        log.info(f"Enriching: {county}")
        log.info(f"{'='*60}")

        stats = await enrich_county(county, dry_run=args.dry_run)
        all_stats[county] = stats

    elapsed = time.time() - start
    log.info(f"\n{'='*60}")
    log.info(f"All enrichment complete in {elapsed:.1f}s")
    log.info(f"{'='*60}")
    for county, stats in all_stats.items():
        log.info(
            f"  {county:15s}: {stats['enriched']}/{stats['total']} enriched, "
            f"{stats['skipped']} skipped, {stats['failed']} failed"
        )


if __name__ == "__main__":
    asyncio.run(main())
