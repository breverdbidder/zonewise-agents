"""
ZoneWise.AI — Palm Beach County Enricher
Primary: PBCPA GIS ArcGIS REST (parcel data)
Fallback: fl_parcels DOR data (co_no=60)
"""

import logging
from typing import Optional

import httpx

from scrapers.enricher_base import CountyEnricher
from scrapers.enricher_fl_parcels import FLParcelsEnricher

log = logging.getLogger("enricher_palm_beach")

PBCPA_GIS_URL = (
    "https://gis.pbcgov.org/arcgis/rest/services/"
    "Parcels/PARCEL_INFO/FeatureServer/4/query"
)

PBCPA_OUT_FIELDS = (
    "PARCEL_NUMBER,OWNER_NAME,SITE_ADDR,TOTAL_MARKET,ASSESSED_VAL,"
    "PROPERTY_USE,HMSTD_FLG,ACRES,CITY,ZIP"
)


class PalmBeachEnricher(CountyEnricher):
    """Palm Beach County enricher using PBCPA GIS + fl_parcels fallback."""

    county_slug = "palm_beach"
    county_name = "Palm Beach"

    def __init__(self):
        self._fl_parcels = FLParcelsEnricher(co_no=60)
        self._gis_available = None

    async def enrich_row(
        self,
        row: dict,
        client: httpx.AsyncClient,
    ) -> Optional[dict]:
        """Try PBCPA GIS first, fall back to fl_parcels."""
        if self._gis_available is not False:
            attrs = await self._query_gis(row, client)
            if attrs:
                self._gis_available = True
                return self._build_from_gis(attrs)
            elif self._gis_available is None:
                self._gis_available = await self._check_gis(client)

        return await self._fl_parcels.enrich_row(row, client)

    async def _query_gis(
        self,
        row: dict,
        client: httpx.AsyncClient,
    ) -> Optional[dict]:
        """Query PBCPA GIS by parcel number or address."""
        parcel_id = row.get("parcel_id")
        if parcel_id:
            attrs = await self.query_arcgis(
                client, PBCPA_GIS_URL,
                f"PARCEL_NUMBER='{parcel_id}'",
                PBCPA_OUT_FIELDS,
            )
            if attrs:
                return attrs

        address = row.get("property_address")
        if address and address.strip() not in ("0 UNKNOWN", "UNKNOWN", ""):
            clean = address.upper().split(",")[0].strip()
            attrs = await self.query_arcgis(
                client, PBCPA_GIS_URL,
                f"SITE_ADDR LIKE '{clean}%'",
                PBCPA_OUT_FIELDS,
            )
            if attrs:
                return attrs

        return None

    async def _check_gis(self, client: httpx.AsyncClient) -> bool:
        """Check if PBCPA GIS is reachable."""
        try:
            resp = await client.get(
                PBCPA_GIS_URL,
                params={"where": "1=1", "resultRecordCount": "1", "f": "json"},
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _build_from_gis(attrs: dict) -> dict:
        """Build enrichment dict from PBCPA GIS attributes."""
        assessed = attrs.get("ASSESSED_VAL")
        market = attrs.get("TOTAL_MARKET")
        acres = attrs.get("ACRES")
        prop_use = str(attrs.get("PROPERTY_USE", "")) if attrs.get("PROPERTY_USE") else None

        prop_type = "Unknown"
        if prop_use:
            prefix = prop_use[:2] if len(prop_use) >= 2 else prop_use
            if prefix in ("00", "01"):
                prop_type = "SFR"
            elif prefix in ("02", "03", "07", "08"):
                prop_type = "Multi"
            elif prefix in ("04", "05"):
                prop_type = "Condo"
            elif prefix in ("09", "10"):
                prop_type = "Land"
            else:
                try:
                    if int(prefix) >= 11:
                        prop_type = "Commercial"
                except ValueError:
                    pass

        city = (attrs.get("CITY") or "").strip() or None
        zip_code = (str(attrs.get("ZIP", "") or "")).strip() or None

        return {
            "assessed_value": assessed or market,
            "market_value": market or assessed,
            "property_type": prop_type,
            "lot_size": float(acres) if acres else None,
            "city": city,
            "zip": zip_code,
            "bcpao_enriched": True,
        }
