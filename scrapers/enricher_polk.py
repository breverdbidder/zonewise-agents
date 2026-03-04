"""
ZoneWise.AI — Polk County Enricher
Polk PA is ASP.NET server-rendered with no REST API.
Uses fl_parcels DOR data only (co_no=63).
"""

import logging
from typing import Optional

import httpx

from scrapers.enricher_base import CountyEnricher
from scrapers.enricher_fl_parcels import FLParcelsEnricher

log = logging.getLogger("enricher_polk")


class PolkEnricher(CountyEnricher):
    """Polk County enricher — fl_parcels only (no PA API)."""

    county_slug = "polk"
    county_name = "Polk"

    def __init__(self):
        self._fl_parcels = FLParcelsEnricher(co_no=63)

    async def enrich_row(
        self,
        row: dict,
        client: httpx.AsyncClient,
    ) -> Optional[dict]:
        return await self._fl_parcels.enrich_row(row, client)
