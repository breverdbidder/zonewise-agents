"""
ZoneWise.AI — County Source Map
Ground truth for auction data sources across all active counties.

This file is the SINGLE SOURCE OF TRUTH for which URL to scrape for each
county + sale type combination. If a source changes, update HERE and
nowhere else.

Verified: 2026-03-03
  - Palm Beach: both pbcgov.realforeclose.com and palmbeach.realforeclose.com
    resolve to the same RealForeclose instance. Using pbcgov (county government
    subdomain) as canonical. Confirmed via browser on 2026-03-03.
  - Brevard foreclosure: brevardclerk.us/foreclosure-sales-list redirects to
    vweb2.brevardclerk.us/Foreclosures/foreclosure_sales.html (static HTML table).
"""

# ---------------------------------------------------------------------------
# BREVARD COUNTY SPECIAL CASE:
# Foreclosure sales = IN-PERSON at Titusville courthouse
#   Source: brevardclerk.us/foreclosure-sales-list
#   auction_venue = 'in_person'
#   auction_url = NULL (no online bidding link)
#
# Tax deed sales = ONLINE via RealAuction
#   Source: brevard.realforeclose.com (TAXDEED filter)
#   auction_venue = 'online'
#   auction_url = direct link to listing on brevard.realforeclose.com
# ---------------------------------------------------------------------------

COUNTY_SOURCE_MAP = {
    "brevard": {
        "name": "Brevard",
        "foreclosure": {
            "method": "in_person",
            "source_url": "https://www.brevardclerk.us/foreclosure-sales-list",
            "actual_url": "http://vweb2.brevardclerk.us/Foreclosures/foreclosure_sales.html",
            "auction_venue": "in_person",
            "platform": "brevard_clerk",
            "auction_time": "11:00",
            "location": (
                "Brevard County Government Center North, "
                "Brevard Room, 518 S. Palm Avenue, Titusville, Florida"
            ),
        },
        "tax_deed": {
            "method": "online",
            "source_url": "https://brevard.realforeclose.com",
            "subdomain": "brevard",
            "auction_venue": "online",
            "platform": "realforeclose",
        },
    },
    "hillsborough": {
        "name": "Hillsborough",
        "foreclosure": {
            "method": "online",
            "source_url": "https://hillsborough.realforeclose.com",
            "subdomain": "hillsborough",
            "auction_venue": "online",
            "platform": "realforeclose",
            "clerk_url": "https://pubrec.hillsclerk.com/oncore/search.aspx",
        },
        "tax_deed": {
            "method": "online",
            "source_url": "https://hillsborough.realforeclose.com",
            "subdomain": "hillsborough",
            "auction_venue": "online",
            "platform": "realforeclose",
        },
        "pa": {
            "name": "HCPA",
            "gis_url": (
                "https://gis.hcpafl.org/arcgis/rest/services/"
                "Webmaps/HillsboroughFL_WebParcels/MapServer/0/query"
            ),
            "parcel_field": "FOLIO",
            "co_no": 39,
        },
    },
    "orange": {
        "name": "Orange",
        "foreclosure": {
            "method": "online",
            "source_url": "https://myorangeclerk.realforeclose.com",
            "subdomain": "myorangeclerk",
            "auction_venue": "online",
            "platform": "realforeclose",
            "clerk_url": "https://myeclerk.myorangeclerk.com/cases/search",
        },
        "tax_deed": {
            "method": "online",
            "source_url": "https://myorangeclerk.realforeclose.com",
            "subdomain": "myorangeclerk",
            "auction_venue": "online",
            "platform": "realforeclose",
        },
        "pa": {
            "name": "OCPA",
            "gis_url": None,  # SPA only, no REST API
            "parcel_field": None,
            "co_no": 58,
        },
    },
    "polk": {
        "name": "Polk",
        "foreclosure": {
            "method": "online",
            "source_url": "https://polk.realforeclose.com",
            "subdomain": "polk",
            "auction_venue": "online",
            "platform": "realforeclose",
            "clerk_url": "https://www.polkcountyclerk.net/court-records",
        },
        "tax_deed": {
            "method": "online",
            "source_url": "https://polk.realforeclose.com",
            "subdomain": "polk",
            "auction_venue": "online",
            "platform": "realforeclose",
        },
        "pa": {
            "name": "PCPAO",
            "gis_url": None,  # ASP.NET server-rendered, no REST API
            "parcel_field": None,
            "co_no": 63,
        },
    },
    "palm_beach": {
        "name": "Palm Beach",
        "foreclosure": {
            "method": "online",
            # Palm Beach subdomain verified 2026-03-03:
            #   palmbeach.realforeclose.com — LIVE, returns auction dates
            #   pbcgov.realforeclose.com — redirects to realauction.com (broken)
            "source_url": "https://palmbeach.realforeclose.com",
            "subdomain": "palmbeach",
            "auction_venue": "online",
            "platform": "realforeclose",
            "clerk_url": "https://efiling.mypalmbeachclerk.com/default.aspx",
        },
        "tax_deed": {
            "method": "online",
            "source_url": "https://palmbeach.realforeclose.com",
            "subdomain": "palmbeach",
            "auction_venue": "online",
            "platform": "realforeclose",
        },
        "pa": {
            "name": "PBCPA",
            "gis_url": (
                "https://gis.pbcgov.org/arcgis/rest/services/"
                "Parcels/PARCEL_INFO/FeatureServer/4/query"
            ),
            "parcel_field": "PARCEL_NUMBER",
            "co_no": 60,
        },
    },
}


def get_foreclosure_config(county_slug: str) -> dict | None:
    """Get the foreclosure source config for a county."""
    county = COUNTY_SOURCE_MAP.get(county_slug)
    if not county:
        return None
    return county.get("foreclosure")


def get_tax_deed_config(county_slug: str) -> dict | None:
    """Get the tax deed source config for a county."""
    county = COUNTY_SOURCE_MAP.get(county_slug)
    if not county:
        return None
    return county.get("tax_deed")


def get_county_name(county_slug: str) -> str:
    """Get display name for a county slug."""
    county = COUNTY_SOURCE_MAP.get(county_slug)
    return county["name"] if county else county_slug.replace("_", " ").title()


def get_clerk_url(county_slug: str) -> str | None:
    """Get the clerk of court URL for a county."""
    county = COUNTY_SOURCE_MAP.get(county_slug)
    if not county:
        return None
    fc = county.get("foreclosure", {})
    return fc.get("clerk_url")


def get_pa_config(county_slug: str) -> dict | None:
    """Get the property appraiser config for a county."""
    county = COUNTY_SOURCE_MAP.get(county_slug)
    if not county:
        return None
    return county.get("pa")


def get_realforeclose_subdomain(county_slug: str, sale_type: str) -> str | None:
    """Get the RealForeclose subdomain for a county + sale type."""
    county = COUNTY_SOURCE_MAP.get(county_slug)
    if not county:
        return None
    config = county.get(sale_type)
    if not config or config.get("platform") != "realforeclose":
        return None
    return config.get("subdomain")
