"""
ZoneWise.AI — County Enricher Base Class
Abstract base for property enrichment per county.
Each county enricher follows the BCPAO pattern: query PA → build dict → patch row.
"""

from abc import ABC, abstractmethod
from typing import Optional

import httpx


class CountyEnricher(ABC):
    """Abstract base for county property enrichment."""

    county_slug: str = ""
    county_name: str = ""

    @abstractmethod
    async def enrich_row(
        self,
        row: dict,
        client: httpx.AsyncClient,
    ) -> Optional[dict]:
        """Given a row from multi_county_auctions, return enrichment dict.

        Return dict should include keys matching multi_county_auctions columns:
          parcel_id, assessed_value, market_value, property_type,
          sqft, lot_size, city, zip, photo_url, bcpao_enriched (bool),
          bcpao_url (PA link, reused column name)

        Return None if enrichment fails.
        """
        ...

    @staticmethod
    async def query_arcgis(
        client: httpx.AsyncClient,
        layer_url: str,
        where: str,
        out_fields: str = "*",
        return_geometry: bool = False,
    ) -> Optional[dict]:
        """Shared ArcGIS REST query helper. Returns first feature's attributes."""
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": str(return_geometry).lower(),
            "outSR": "4326",
            "f": "json",
        }
        try:
            resp = await client.get(layer_url, params=params, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features", [])
            if features:
                return features[0].get("attributes")
        except Exception:
            pass
        return None
