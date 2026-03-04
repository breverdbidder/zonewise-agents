"""
ZoneWise.AI — Enricher Factory
Registry + dispatch for county-specific enrichers.
"""

from typing import Optional

from scrapers.enricher_base import CountyEnricher
from scrapers.enricher_fl_parcels import FLParcelsEnricher
from scrapers.enricher_hillsborough import HillsboroughEnricher
from scrapers.enricher_orange import OrangeEnricher
from scrapers.enricher_polk import PolkEnricher
from scrapers.enricher_palm_beach import PalmBeachEnricher
from scrapers.source_map import get_pa_config

# Registry of county-specific enrichers
ENRICHER_REGISTRY: dict[str, type[CountyEnricher]] = {
    "hillsborough": HillsboroughEnricher,
    "orange": OrangeEnricher,
    "polk": PolkEnricher,
    "palm_beach": PalmBeachEnricher,
}


def get_enricher(county_slug: str) -> Optional[CountyEnricher]:
    """Get enricher instance for a county.

    Returns county-specific enricher if registered,
    otherwise returns fl_parcels fallback if co_no is configured.
    Returns None if no enrichment source is available.
    """
    # Check for county-specific enricher
    cls = ENRICHER_REGISTRY.get(county_slug)
    if cls:
        return cls()

    # Fall back to fl_parcels if PA config has co_no
    pa_config = get_pa_config(county_slug)
    if pa_config and pa_config.get("co_no"):
        return FLParcelsEnricher(co_no=pa_config["co_no"])

    return None
