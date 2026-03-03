"""
ZoneWise.AI — Tax Deed Sale Scraper
Hook Phase: ACTION (data foundation)

AgentQL scraper for county tax deed portals + RealTDM cert chain data.
Outputs: multi_county_auctions rows with sale_type='tax_deed'

See TODO.md TASK-006 for implementation requirements.
"""

# TODO TASK-006: Implement tax deed scraper
#
# Target portals: same county RealForeclose portals, tax deed section
# RealTDM: for outstanding certificate chain per property
#
# Fields to capture:
#   cert_number, opening_bid, outstanding_certs_total, portal_url, sale_date
#
# All output rows MUST have:
#   sale_type = 'tax_deed'  ← NEVER null
#
# outstanding_certs_total comes from RealTDM cert chain query
# This field is CRITICAL — investors need total cert exposure before bidding

SUPPORTED_COUNTIES = [
    "brevard",
    "orange",
    "polk", 
    "hillsborough",
    "palm_beach"
]

def scrape_county(county: str) -> list[dict]:
    """Scrape all tax deed sales for county.
    
    Returns list of dicts ready for Supabase insert.
    Every dict must include sale_type='tax_deed'.
    outstanding_certs_total must be populated (from RealTDM) — never null.
    """
    raise NotImplementedError("See TODO.md TASK-006")
