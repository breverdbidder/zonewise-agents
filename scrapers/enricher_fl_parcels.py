"""
ZoneWise.AI — FL Parcels (DOR) Enricher
Fallback enricher that works for ALL counties via FL DOR data in fl_parcels table.

Provides: year_built, sqft, quality, lot_sqft, just_value, land_value, property_type.
Does NOT provide: photo_url, beds, baths, pool.
"""

import logging
import re
from typing import Optional

import httpx

from scrapers.enricher_base import CountyEnricher
from scrapers.shared import _run_sql

log = logging.getLogger("enricher_fl_parcels")

# DOR use code → property type mapping
DOR_USE_CODE_MAP = {
    "00": "Land",        # Vacant residential
    "01": "SFR",         # Single family
    "02": "Multi",       # Mobile home
    "03": "Multi",       # Multi-family (2-9)
    "04": "Condo",       # Condominiums
    "05": "Multi",       # Cooperatives
    "06": "Multi",       # Retirement homes
    "07": "Multi",       # Misc residential
    "08": "Multi",       # Multi-family (10+)
    "09": "Land",        # Vacant residential
    "10": "Land",        # Vacant commercial
}


def _map_dor_property_type(dor_uc: str) -> str:
    """Map FL DOR use code to property type."""
    if not dor_uc:
        return "Unknown"
    prefix = str(dor_uc).zfill(2)[:2]
    if prefix in DOR_USE_CODE_MAP:
        return DOR_USE_CODE_MAP[prefix]
    try:
        if int(prefix) >= 11:
            return "Commercial"
    except ValueError:
        pass
    return "Unknown"


class FLParcelsEnricher(CountyEnricher):
    """Enricher using FL DOR fl_parcels data. Works for all counties."""

    county_slug = "fl_parcels"
    county_name = "FL DOR (All Counties)"

    def __init__(self, co_no: int = 0):
        self.co_no = co_no

    async def enrich_row(
        self,
        row: dict,
        client: httpx.AsyncClient,
    ) -> Optional[dict]:
        """Enrich a row using fl_parcels data.

        Tries parcel_id match first, then address match.
        """
        parcel_id = row.get("parcel_id")
        address = row.get("property_address")

        attrs = None

        # Try by parcel_id (may be DOR format string)
        if parcel_id:
            attrs = self._query_by_parcel_id(parcel_id)

        # Fall back to address match
        if not attrs and address:
            attrs = self._query_by_address(address)

        if not attrs:
            return None

        return self._build_enrichment(attrs)

    def _query_by_parcel_id(self, parcel_id: str) -> Optional[dict]:
        """Query fl_parcels by parcel_id string."""
        pid_safe = parcel_id.replace("'", "''")
        co_filter = f" AND co_no = {self.co_no}" if self.co_no else ""
        rows = _run_sql(
            f"SELECT id, co_no, parcel_id, eff_yr_blt, act_yr_blt, tot_lvg_ar, "
            f"no_buldng, imp_qual, const_clas, lnd_sqfoot, jv, lnd_val, "
            f"dor_uc, phy_addr1, phy_city "
            f"FROM fl_parcels "
            f"WHERE parcel_id = '{pid_safe}'{co_filter} "
            f"LIMIT 1;"
        )
        return rows[0] if rows else None

    def _query_by_address(self, address: str) -> Optional[dict]:
        """Query fl_parcels by address match."""
        if not address or address.strip() in ("0 UNKNOWN", "UNKNOWN", ""):
            return None

        # Normalize address for matching
        clean = address.upper().strip()
        clean = clean.split(",")[0].strip()
        clean = re.sub(r"\s+FL[-\s]*\d*$", "", clean).strip()
        addr_safe = clean.replace("'", "''")

        co_filter = f" AND co_no = {self.co_no}" if self.co_no else ""
        rows = _run_sql(
            f"SELECT id, co_no, parcel_id, eff_yr_blt, act_yr_blt, tot_lvg_ar, "
            f"no_buldng, imp_qual, const_clas, lnd_sqfoot, jv, lnd_val, "
            f"dor_uc, phy_addr1, phy_city "
            f"FROM fl_parcels "
            f"WHERE UPPER(phy_addr1) = '{addr_safe}'{co_filter} "
            f"LIMIT 1;"
        )
        return rows[0] if rows else None

    @staticmethod
    def _build_enrichment(attrs: dict) -> dict:
        """Transform fl_parcels row into enrichment dict."""
        yr = attrs.get("eff_yr_blt") or attrs.get("act_yr_blt")
        sqft = attrs.get("tot_lvg_ar")
        if sqft is not None:
            try:
                sqft = int(sqft)
            except (ValueError, TypeError):
                sqft = None

        lnd_sqft = attrs.get("lnd_sqfoot")
        if lnd_sqft is not None:
            try:
                lnd_sqft = int(lnd_sqft)
            except (ValueError, TypeError):
                lnd_sqft = None

        jv = attrs.get("jv")
        if jv is not None:
            try:
                jv = float(jv)
            except (ValueError, TypeError):
                jv = None

        lnd_val = attrs.get("lnd_val")
        if lnd_val is not None:
            try:
                lnd_val = float(lnd_val)
            except (ValueError, TypeError):
                lnd_val = None

        dor_uc = str(attrs.get("dor_uc", "")) if attrs.get("dor_uc") else None
        city = (attrs.get("phy_city") or "").strip() or None

        enrichment = {
            "assessed_value": jv,
            "market_value": jv,
            "property_type": _map_dor_property_type(dor_uc),
            "sqft": sqft,
            "lot_size": round(lnd_sqft / 43560, 2) if lnd_sqft else None,
            "year_built": yr,
            "bcpao_enriched": True,
        }

        if city:
            enrichment["city"] = city

        return enrichment
