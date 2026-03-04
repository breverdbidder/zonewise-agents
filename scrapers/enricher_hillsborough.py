"""
ZoneWise.AI — Hillsborough County Enricher
Primary: HCPA GIS ArcGIS REST (parcel data)
Fallback: fl_parcels DOR data (co_no=39)
"""

import logging
from typing import Optional

import httpx

from scrapers.enricher_base import CountyEnricher
from scrapers.enricher_fl_parcels import FLParcelsEnricher
from scrapers.source_map import get_pa_config

log = logging.getLogger("enricher_hillsborough")

HCPA_GIS_URL = (
    "https://gis.hcpafl.org/arcgis/rest/services/"
    "Webmaps/HillsboroughFL_WebParcels/MapServer/0/query"
)

HCPA_OUT_FIELDS = (
    "FOLIO,STRAP,OWNER_NAME,SITE_ADDR,SALE_DATE,SALE_PRICE,"
    "JV,CITY_NAME,ZIP_CODE,USE_CODE,LND_SQFT,BLD_SQFT,ACRES"
)


class HillsboroughEnricher(CountyEnricher):
    """Hillsborough County enricher using HCPA GIS + fl_parcels fallback."""

    county_slug = "hillsborough"
    county_name = "Hillsborough"

    def __init__(self):
        self._fl_parcels = FLParcelsEnricher(co_no=39)
        self._gis_available = None

    async def enrich_row(
        self,
        row: dict,
        client: httpx.AsyncClient,
    ) -> Optional[dict]:
        """Try HCPA GIS first, fall back to fl_parcels."""
        # Try GIS if we haven't confirmed it's unavailable
        if self._gis_available is not False:
            attrs = await self._query_gis(row, client)
            if attrs:
                self._gis_available = True
                return self._build_from_gis(attrs)
            elif self._gis_available is None:
                # First failure — check if GIS is reachable
                self._gis_available = await self._check_gis(client)

        # Fall back to fl_parcels
        return await self._fl_parcels.enrich_row(row, client)

    async def _query_gis(
        self,
        row: dict,
        client: httpx.AsyncClient,
    ) -> Optional[dict]:
        """Query HCPA GIS by parcel_id (FOLIO) or address."""
        parcel_id = row.get("parcel_id")
        if parcel_id:
            attrs = await self.query_arcgis(
                client, HCPA_GIS_URL,
                f"FOLIO='{parcel_id}'",
                HCPA_OUT_FIELDS,
            )
            if attrs:
                return attrs

        address = row.get("property_address")
        if address and address.strip() not in ("0 UNKNOWN", "UNKNOWN", ""):
            clean = address.upper().split(",")[0].strip()
            attrs = await self.query_arcgis(
                client, HCPA_GIS_URL,
                f"SITE_ADDR LIKE '{clean}%'",
                HCPA_OUT_FIELDS,
            )
            if attrs:
                return attrs

        return None

    async def _check_gis(self, client: httpx.AsyncClient) -> bool:
        """Check if HCPA GIS is reachable."""
        try:
            resp = await client.get(
                HCPA_GIS_URL,
                params={"where": "1=1", "resultRecordCount": "1", "f": "json"},
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _build_from_gis(attrs: dict) -> dict:
        """Build enrichment dict from HCPA GIS attributes."""
        jv = attrs.get("JV")
        sqft = attrs.get("BLD_SQFT")
        acres = attrs.get("ACRES")
        use_code = str(attrs.get("USE_CODE", "")) if attrs.get("USE_CODE") else None

        # Simple use code mapping for Hillsborough
        prop_type = "Unknown"
        if use_code:
            prefix = use_code[:2] if len(use_code) >= 2 else use_code
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

        city = (attrs.get("CITY_NAME") or "").strip() or None
        zip_code = (str(attrs.get("ZIP_CODE", "") or "")).strip() or None

        return {
            "assessed_value": jv,
            "market_value": jv,
            "property_type": prop_type,
            "sqft": int(sqft) if sqft else None,
            "lot_size": float(acres) if acres else None,
            "city": city,
            "zip": zip_code,
            "bcpao_enriched": True,
        }
