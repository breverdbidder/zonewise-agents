"""
ZoneWise.AI — Foreclosure Sale Scraper
Hook Phase: ACTION (data foundation)

AgentQL scraper for county RealForeclose portals.
Outputs: multi_county_auctions rows with sale_type='foreclosure'

See TODO.md TASK-005 for implementation requirements.
"""

# TODO TASK-005: Implement county scraper
# 
# Target counties (start): Brevard, Orange, Polk, Hillsborough, Palm Beach
# Target portals: brevard.realforeclose.com and equivalents
# 
# Fields to capture:
#   case_number, judgment_amount, plaintiff, sale_date, property_address
#
# All output rows MUST have:
#   sale_type = 'foreclosure'  ← NEVER null
#
# Anti-detection:
#   - Rotating delays: 3-7 seconds between requests
#   - Session rotation every 50 requests
#   - Retry 3x per county before logging failure
#
# On failure: log to daily_metrics.counties_failed, continue to next county
# Do NOT halt scraper for one failed county

SUPPORTED_COUNTIES = [
    "brevard",
    "orange", 
    "polk",
    "hillsborough",
    "palm_beach"
]

def scrape_county(county: str) -> list[dict]:
    """Scrape all foreclosure sales for county.
    
    Returns list of dicts ready for Supabase insert.
    Every dict must include sale_type='foreclosure'.
    """
    raise NotImplementedError("See TODO.md TASK-005")
