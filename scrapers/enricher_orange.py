"""
ZoneWise.AI — Orange County Enricher
Orange OCPA is a JavaScript SPA with no REST API.
Uses fl_parcels DOR data only (co_no=58).
"""

import logging
from typing import Optional

import httpx

from scrapers.enricher_base import CountyEnricher
from scrapers.enricher_fl_parcels import FLParcelsEnricher

log = logging.getLogger("enricher_orange")


class OrangeEnricher(CountyEnricher):
    """Orange County enricher — fl_parcels only (no PA API)."""

    county_slug = "orange"
    county_name = "Orange"

    def __init__(self):
        self._fl_parcels = FLParcelsEnricher(co_no=58)

    async def enrich_row(
        self,
        row: dict,
        client: httpx.AsyncClient,
    ) -> Optional[dict]:
        return await self._fl_parcels.enrich_row(row, client)
