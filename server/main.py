"""
ZoneWise Agent API Server v1.1.0
Enterprise-grade FastAPI backend for zoning intelligence
Queries REAL data from Supabase across all 67 FL counties
Hybrid: regex intent classification + Claude Sonnet 4.5 for complex queries
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import json
import httpx
import re
import asyncio
from datetime import datetime
from pathlib import Path
import anthropic


# ═══════════════════════════════════════════════════════════════
# APP CONFIG
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title="ZoneWise Agent API",
    description="Enterprise zoning intelligence for all 67 FL counties",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://zonewise.ai",
        "https://www.zonewise.ai",
        "https://zonewise-desktop-viewer.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mocerqjnksmhcjzxrewo.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Persistent HTTP client for connection pooling
_http_client: httpx.AsyncClient = None


async def get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


@app.on_event("shutdown")
async def shutdown():
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()


# ═══════════════════════════════════════════════════════════════
# ANTHROPIC CLIENT (Claude Sonnet 4.5 for complex queries)
# ═══════════════════════════════════════════════════════════════

_anthropic_client = None

def get_anthropic():
    global _anthropic_client
    if _anthropic_client is None and ANTHROPIC_API_KEY:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client

CLAUDE_SYSTEM_PROMPT = """You are ZoneWise AI, Florida's zoning intelligence assistant.
You help users understand zoning codes, setbacks, permitted uses, building envelopes,
and development feasibility across all 67 Florida counties.

When answering questions:
- Be specific with zoning codes, setbacks, heights, and densities
- Reference the jurisdiction and county when known
- If you don't have specific data in the provided context, say so clearly
- Use markdown formatting for readability (headers, tables, bold, lists)
- Keep responses concise but thorough
- Suggest follow-up queries the user might find helpful

Current platform data: {stats}
"""


# ═══════════════════════════════════════════════════════════════
# SUPABASE DATA LAYER
# ═══════════════════════════════════════════════════════════════

async def sb_query(table: str, params: str = "", limit: int = 100) -> List[Dict]:
    """Query Supabase REST API. params is the raw query string."""
    if not SUPABASE_KEY:
        raise HTTPException(status_code=503, detail="Database not configured")
    client = await get_client()
    sep = "&" if params else ""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}{sep}limit={limit}"
    resp = await client.get(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    if resp.status_code != 200:
        return []
    return resp.json()


async def sb_count(table: str, params: str = "") -> int:
    """Get count from Supabase table."""
    if not SUPABASE_KEY:
        return 0
    client = await get_client()
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}&select=id"
    resp = await client.get(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Prefer": "count=exact",
        "Range": "0-0",
    })
    cr = resp.headers.get("content-range", "*/0")
    try:
        return int(cr.split("/")[1])
    except (IndexError, ValueError):
        return 0


def extract_dims(description: str) -> Dict[str, Any]:
    """Extract DIMS JSON from description HTML comment."""
    if not description:
        return {}
    m = re.search(r'<!--DIMS:({.*?})-->', description)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return {}


# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = "anonymous"
    history: Optional[List[Dict[str, str]]] = None

class ChatResponse(BaseModel):
    answer: str
    intent: str
    entities: Dict[str, Any]
    data: Optional[Dict[str, Any]] = None
    citations: List[Dict[str, str]] = []
    suggestions: List[str] = []


# ═══════════════════════════════════════════════════════════════
# INTENT CLASSIFICATION + ENTITY EXTRACTION
# ═══════════════════════════════════════════════════════════════

INTENT_RULES = [
    # COMPARISON first — strong signal
    ("COMPARISON", ["compare", "difference between", "vs ", "versus"]),
    # ADDRESS_QUERY before FEASIBILITY — "what can I build at [address]" must
    # match here, not fall into generic FEASIBILITY which has no address handling
    ("ADDRESS_QUERY", ["what can i build at", "can i build at", "build at",
                       "what can be built at", "development at",
                       "build on", "build a ", "build an ",
                       "what's allowed at", "whats allowed at",
                       "zoning at", "zone at", "zoned at"]),
    # FEASIBILITY: zone-code questions without a street address
    ("FEASIBILITY", ["is it feasible", "is it possible", "feasible",
                     "allowed in", "permitted in", "permitted use",
                     "is a ", "is an "]),
    ("LIST_DISTRICTS", ["what zones", "zoning districts", "list zones", "all zones",
                        "what zoning", "districts in", "zone types"]),
    ("DISTRICT_DETAIL", ["setback", "height limit", "lot size", "density",
                         "far ", "floor area", "building envelope", "requirements for"]),
    ("PARCEL_LOOKUP", ["parcel", "folio", "property at",
                       "what zone is", "zoned as"]),
    ("REPORT", ["report", "generate", "pdf", "export", "download"]),
    ("COUNTY_STATS", ["how many", "statistics", "coverage", "counties",
                      "total districts"]),
]



def format_confidence(score) -> str:
    """Format confidence_score for display. Returns empty string when NULL."""
    if score is None:
        return ""
    score = float(score)
    if score >= 0.75:
        return "_Confidence: High (verified)_"
    elif score >= 0.50:
        return "_Confidence: Medium (scraped)_"
    else:
        return "_\u26a0\ufe0f Unverified data \u2014 confirm with source_"

def classify_intent(query: str) -> str:
    q = query.lower()
    for intent, keywords in INTENT_RULES:
        if any(kw in q for kw in keywords):
            return intent
    return "GENERAL"


# All 67 FL county names for matching
FL_COUNTIES = [
    "Alachua", "Baker", "Bay", "Bradford", "Brevard", "Broward", "Calhoun",
    "Charlotte", "Citrus", "Clay", "Collier", "Columbia", "DeSoto", "Dixie",
    "Duval", "Escambia", "Flagler", "Franklin", "Gadsden", "Gilchrist",
    "Glades", "Gulf", "Hamilton", "Hardee", "Hendry", "Hernando", "Highlands",
    "Hillsborough", "Holmes", "Indian River", "Jackson", "Jefferson",
    "Lafayette", "Lake", "Lee", "Leon", "Levy", "Liberty", "Madison",
    "Manatee", "Marion", "Martin", "Miami-Dade", "Monroe", "Nassau",
    "Okaloosa", "Okeechobee", "Orange", "Osceola", "Palm Beach", "Pasco",
    "Pinellas", "Polk", "Putnam", "Santa Rosa", "Sarasota", "Seminole",
    "St. Johns", "St. Lucie", "Sumter", "Suwannee", "Taylor", "Union",
    "Volusia", "Wakulla", "Walton", "Washington"
]

# Common FL cities for matching (top 150+)
FL_CITIES = [
    "Apopka", "Atlantic Beach", "Baldwin", "Belle Isle", "Belleair",
    "Belleview", "Boynton Beach", "Brooksville", "Bunnell", "Cape Canaveral",
    "Cape Coral", "Clearwater", "Clewiston", "Cocoa", "Cocoa Beach",
    "Coconut Creek", "Coral Gables", "Cutler Bay", "Daytona Beach",
    "DeFuniak Springs", "Delray Beach", "Deltona", "Destin", "Doral",
    "Edgewood", "Eustis", "Fort Lauderdale", "Fort Myers",
    "Fort Myers Beach", "Frostproof", "Gainesville", "Grant-Valkaria",
    "Greenacres", "Gulf Breeze", "Hialeah", "Hilliard", "Homestead",
    "Indian Harbour Beach", "Indian River Shores", "Indialantic",
    "Jacksonville", "Jacksonville Beach", "Juno Beach", "Jupiter",
    "Jupiter Island", "Key Colony Beach", "Key West", "Keystone Heights",
    "Lake Hamilton", "Lake Park", "Lake Wales", "Lakeland",
    "Madeira Beach", "Malabar", "Mangonia Park", "Margate", "Melbourne",
    "Melbourne Beach", "Melbourne Village", "Miami", "Miami Gardens",
    "Miami Lakes", "Miami Springs", "Milton", "Naples",
    "North Palm Beach", "Oakland Park", "Ocala", "Orange City",
    "Orlando", "Palm Bay", "Palm Beach", "Palm Beach Gardens",
    "Palm Shores", "Pensacola", "Pinecrest", "Pinellas Park",
    "Plant City", "Riviera Beach", "Rockledge", "Safety Harbor",
    "Sanibel", "Satellite Beach", "South Palm Beach", "St. Petersburg",
    "Tampa", "Temple Terrace", "Tequesta", "Titusville",
    "West Melbourne", "West Palm Beach", "Windermere",
    "Winter Garden", "Winter Haven", "Winter Park",
]


def extract_entities(query: str) -> Dict[str, Any]:
    entities = {}
    q = query.lower()

    # Zoning code: RS-1, BU-1-A, RR-65, C-2, PUD, GU, etc.
    code_match = re.search(r'\b([A-Z]{1,5}(?:-\d{1,3})?(?:-[A-Z]{1,2})?)\b', query)
    if code_match:
        candidate = code_match.group(1)
        # Filter out common false positives
        if len(candidate) >= 2 and candidate not in {"FL", "AI", "US", "OR", "IN", "ID"}:
            entities["zoning_code"] = candidate

    # Jurisdiction: try cities first (more specific), then counties
    for city in sorted(FL_CITIES, key=len, reverse=True):
        if city.lower() in q:
            entities["jurisdiction"] = city
            break
    if "jurisdiction" not in entities:
        for county in sorted(FL_COUNTIES, key=len, reverse=True):
            if county.lower() in q:
                entities["jurisdiction"] = county
                entities["is_county"] = True
                break

    # Parcel ID patterns: XX XXXX-XX-XXX or numeric folio
    parcel_match = re.search(r'\b(\d{2}\s*\d{4}-\d{2}-\d{3})\b', query)
    if parcel_match:
        entities["parcel_id"] = parcel_match.group(1)

    # Address pattern
    addr_match = re.search(r'(\d+\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:St|Ave|Blvd|Rd|Dr|Ct|Ln|Way|Pl|Cir))', query)
    if addr_match:
        entities["address"] = addr_match.group(1)

    return entities


# ═══════════════════════════════════════════════════════════════
# AGENT FUNCTIONS — ALL QUERY REAL SUPABASE DATA
# ═══════════════════════════════════════════════════════════════

async def agent_list_districts(entities: Dict) -> Dict:
    """List all zoning districts for a jurisdiction."""
    jurisdiction = entities.get("jurisdiction", "Satellite Beach")

    # Resolve jurisdiction ID
    juris = await sb_query("jurisdictions",
        f"select=id,name,county,data_completeness,municode_url&or=(name.ilike.%25{jurisdiction}%25,county.ilike.%25{jurisdiction}%25)",
        limit=10)

    if not juris:
        return {"answer": f"I couldn't find '{jurisdiction}' in our database. Try a Florida city or county name.",
                "data": None, "citations": [], "suggestions": ["List all counties", f"Show zones in Brevard"]}

    j = juris[0]
    jid = j["id"]

    # Get all districts for this jurisdiction
    districts = await sb_query("zoning_districts",
        f"select=id,code,name,category&jurisdiction_id=eq.{jid}&order=category,code",
        limit=200)

    # Get zone_standards count
    district_ids = [str(d["id"]) for d in districts]
    standards_count = 0
    if district_ids:
        standards = await sb_query("zone_standards",
            f"select=zoning_district_id&zoning_district_id=in.({','.join(district_ids[:50])})",
            limit=200)
        standards_count = len(set(s["zoning_district_id"] for s in standards))

    # Group by category
    by_cat = {}
    for d in districts:
        cat = d.get("category", "Other") or "Other"
        by_cat.setdefault(cat, []).append(d)

    lines = [f"**{j['name']}** ({j['county']} County) — {len(districts)} zoning districts\n"]
    lines.append(f"Data completeness: {j.get('data_completeness', 0):.0f}% | "
                 f"Standards available: {standards_count}/{len(districts)} districts\n")

    for cat, dists in sorted(by_cat.items()):
        lines.append(f"\n**{cat}** ({len(dists)}):")
        for d in dists:
            lines.append(f"  • **{d['code']}** — {d['name']}")

    lines.append(f"\n_Ask about any code for setbacks and requirements, e.g. \"What are the setbacks for {districts[0]['code']}?\"_")

    citations = []
    if j.get("municode_url"):
        citations.append({"source": "Municode", "url": j["municode_url"],
                          "title": f"{j['name']} Code of Ordinances"})

    return {
        "answer": "\n".join(lines),
        "data": {"jurisdiction": j, "district_count": len(districts), "categories": {k: len(v) for k, v in by_cat.items()}},
        "citations": citations,
        "suggestions": [f"Setbacks for {districts[0]['code']}" if districts else "Search another city",
                        f"Compare zones in {j['name']}"]
    }


async def agent_district_detail(entities: Dict) -> Dict:
    """Get detailed dimensional standards for a zoning district."""
    code = entities.get("zoning_code")
    jurisdiction = entities.get("jurisdiction")

    if not code:
        return {"answer": "Please specify a zoning code like RS-1, C-2, or BU-1-A.",
                "data": None, "citations": [],
                "suggestions": ["What are the setbacks for RS-1?", "Show me RR-65 requirements"]}

    # Build query
    params = f"select=*&code=ilike.{code}"
    if jurisdiction:
        juris = await sb_query("jurisdictions", f"select=id&name=ilike.%25{jurisdiction}%25", limit=1)
        if juris:
            params += f"&jurisdiction_id=eq.{juris[0]['id']}"

    districts = await sb_query("zoning_districts", params, limit=5)

    if not districts:
        return {"answer": f"No district found with code **{code}**" + (f" in {jurisdiction}" if jurisdiction else "") + ". Check the code and try again.",
                "data": None, "citations": [],
                "suggestions": [f"List zones in {jurisdiction}" if jurisdiction else "List zones in Satellite Beach"]}

    district = districts[0]
    did = district["id"]
    jid = district["jurisdiction_id"]

    # Get jurisdiction name
    juris_info = await sb_query("jurisdictions", f"select=name,county,municode_url&id=eq.{jid}", limit=1)
    j = juris_info[0] if juris_info else {"name": "Unknown", "county": "Unknown"}

    # Try zone_standards table first (structured data)
    standards = await sb_query("zone_standards", f"select=*&zoning_district_id=eq.{did}", limit=1)

    if standards:
        s = standards[0]
        lines = [f"## {code} — {district.get('name', 'Zoning District')}",
                 f"**{j['name']}**, {j['county']} County\n",
                 f"**Category:** {district.get('category', 'N/A')}\n",
                 "### Dimensional Standards\n",
                 "| Requirement | Value |",
                 "|---|---|"]

        field_labels = [
            ("min_lot_sqft", "Minimum Lot Size", " sq ft"),
            ("min_lot_width_ft", "Minimum Lot Width", " ft"),
            ("min_lot_depth_ft", "Minimum Lot Depth", " ft"),
            ("max_height_ft", "Maximum Height", " ft"),
            ("max_stories", "Maximum Stories", ""),
            ("front_setback_ft", "Front Setback", " ft"),
            ("side_setback_ft", "Side Setback", " ft"),
            ("rear_setback_ft", "Rear Setback", " ft"),
            ("corner_setback_ft", "Corner Setback", " ft"),
            ("max_lot_coverage_pct", "Max Lot Coverage", "%"),
            ("max_impervious_pct", "Max Impervious", "%"),
            ("max_far", "Max FAR", ""),
            ("max_density_du_acre", "Max Density", " du/acre"),
            ("parking_per_unit", "Parking per Unit", " spaces"),
            ("parking_per_1000sf", "Parking per 1,000 SF", " spaces"),
        ]

        for field, label, suffix in field_labels:
            val = s.get(field)
            if val is not None:
                if isinstance(val, float) and val == int(val):
                    val = int(val)
                lines.append(f"| {label} | **{val:,}{suffix}** |" if isinstance(val, (int, float)) else f"| {label} | **{val}{suffix}** |")

        conf_line = format_confidence(s.get("confidence_score"))
        source = s.get('source_url', '')
        footer = conf_line
        if source:
            footer = (conf_line + " | " if conf_line else "") + f"[Source]({source})"
        if footer:
            lines.append(f"\n{footer}")

        citations = []
        if s.get("source_url"):
            citations.append({"source": "Municode", "url": s["source_url"],
                              "title": f"{j['name']} Zoning Ordinance"})

        return {"answer": "\n".join(lines),
                "data": {"district": district, "standards": s, "jurisdiction": j},
                "citations": citations,
                "suggestions": [f"Compare {code} with another zone", f"List all zones in {j['name']}"]}

    # Fallback: try DIMS in description
    dims = extract_dims(district.get("description", ""))
    if dims:
        setbacks = dims.get("setbacks_ft", {})
        lines = [f"## {code} — {district.get('name', 'Zoning District')}",
                 f"**{j['name']}**, {j['county']} County\n",
                 "### Requirements\n",
                 f"• **Min Lot Size:** {dims.get('min_lot_sqft', 'N/A'):,} sq ft" if isinstance(dims.get('min_lot_sqft'), (int, float)) else f"• **Min Lot Size:** {dims.get('min_lot_sqft', 'N/A')}",
                 f"• **Min Lot Width:** {dims.get('min_lot_width_ft', 'N/A')} ft",
                 f"• **Max Height:** {dims.get('max_height_ft', 'N/A')} ft",
                 f"• **Density:** {dims.get('density_du_acre', 'N/A')} du/acre\n",
                 "### Setbacks",
                 f"• Front: **{setbacks.get('front', 'N/A')}** ft",
                 f"• Side: **{setbacks.get('side', 'N/A')}** ft",
                 f"• Rear: **{setbacks.get('rear', 'N/A')}** ft",
                 f"\n_Source: {dims.get('source', 'Municode')} | Verified: {dims.get('verified_date', 'N/A')}_"]

        citations = []
        if dims.get("source_url"):
            citations.append({"source": "Municode", "url": dims["source_url"], "title": f"{j['name']} LDC"})

        return {"answer": "\n".join(lines), "data": {"district": district, "dims": dims, "jurisdiction": j},
                "citations": citations, "suggestions": [f"List all zones in {j['name']}"]}

    # No standards at all
    return {
        "answer": f"**{code} — {district.get('name', 'Zoning District')}** in {j['name']}\n\nCategory: {district.get('category', 'N/A')}\n\nDimensional standards haven't been extracted yet for this district. Our scraper is currently processing all 67 FL counties — check back soon.",
        "data": {"district": district, "jurisdiction": j},
        "citations": [],
        "suggestions": [f"List zones in {j['name']}", "Show counties with full data"]
    }


async def agent_comparison(entities: Dict) -> Dict:
    """Compare two zoning districts."""
    # Extract both codes from query
    code = entities.get("zoning_code")
    if not code:
        return {"answer": "Please specify two zoning codes to compare, e.g. 'Compare RS-1 vs C-2'",
                "data": None, "citations": [],
                "suggestions": ["Compare RS-1 vs RS-2", "Compare BU-1 vs BU-2"]}

    # For now, show the one we found and ask for the second
    result = await agent_district_detail(entities)
    result["answer"] = result["answer"] + "\n\n_Specify a second zone code to complete the comparison._"
    return result


async def agent_parcel_lookup(entities: Dict) -> Dict:
    """Look up parcel zoning assignment."""
    parcel_id = entities.get("parcel_id")

    if not parcel_id:
        return {"answer": "Please provide a parcel ID (e.g., 29 3712-00-529) or address to look up zoning.",
                "data": None, "citations": [],
                "suggestions": ["What zone is parcel 29 3712-00-529?", "Zoning at 123 Main St Satellite Beach"]}

    parcels = await sb_query("parcel_zones", f"select=*&parcel_id=eq.{parcel_id}", limit=1)

    if not parcels:
        return {"answer": f"Parcel **{parcel_id}** not found in our database. It may not have been scraped yet.",
                "data": None, "citations": [],
                "suggestions": ["Try a different parcel ID", "List zones in Satellite Beach"]}

    p = parcels[0]
    lines = [f"## Parcel: {p['parcel_id']}",
             f"• **Zone Code:** {p.get('zone_code', 'N/A')}",
             f"• **Zone Name:** {p.get('zone_name', 'N/A')}",
             f"• **Source:** {p.get('source', 'N/A')}"]

    if p.get("overlay_codes"):
        lines.append(f"• **Overlays:** {p['overlay_codes']}")
    if p.get("future_land_use"):
        lines.append(f"• **Future Land Use:** {p['future_land_use']}")

    lines.append(f"\n_Want details? Ask: \"What are the requirements for {p.get('zone_code', 'RS-1')}?\"_")

    return {"answer": "\n".join(lines), "data": {"parcel": p}, "citations": [],
            "suggestions": [f"Setbacks for {p.get('zone_code', 'RS-1')}", f"Generate report for {parcel_id}"]}


async def agent_county_stats(entities: Dict) -> Dict:
    """Platform statistics and coverage. Filters to a specific county when mentioned."""
    county = None
    # Check if a county was detected (is_county flag) or jurisdiction matches a county name
    if entities.get("is_county"):
        county = entities.get("jurisdiction")
    elif entities.get("jurisdiction"):
        # Check if the jurisdiction name is actually a county
        jname = entities["jurisdiction"]
        for c in FL_COUNTIES:
            if c.lower() == jname.lower():
                county = c
                break

    if county:
        # County-specific stats
        juris = await sb_query("jurisdictions",
            f"select=id,name,county,data_completeness&county=ilike.{county}&order=name",
            limit=200)

        jids = [str(j["id"]) for j in juris]
        district_count = 0
        standards_count = 0
        if jids:
            districts = await sb_query("zoning_districts",
                f"select=id&jurisdiction_id=in.({','.join(jids)})",
                limit=1000)
            district_count = len(districts)
            dids = [str(d["id"]) for d in districts]
            if dids:
                standards = await sb_query("zone_standards",
                    f"select=id&zoning_district_id=in.({','.join(dids[:200])})",
                    limit=1000)
                standards_count = len(standards)

        lines = [f"## {county} County — Zoning Data\n",
                 f"**{len(juris)}** jurisdictions | **{district_count:,}** zoning districts | **{standards_count:,}** dimensional standards\n",
                 "### Jurisdictions\n",
                 "| Jurisdiction | Data Completeness |",
                 "|---|---|"]

        for j in juris:
            comp = j.get("data_completeness", 0) or 0
            lines.append(f"| {j['name']} | {comp:.0f}% |")

        lines.append(f"\n_Ask about any jurisdiction: \"Show zones in {juris[0]['name']}\"_" if juris else "")

        return {"answer": "\n".join(lines),
                "data": {"county": county, "jurisdictions": len(juris),
                         "districts": district_count, "standards": standards_count,
                         "jurisdiction_list": [j["name"] for j in juris]},
                "citations": [],
                "suggestions": [f"Show zones in {juris[0]['name']}" if juris else "List all counties",
                                f"What zones are in {county} County?"]}

    # Statewide stats (no county specified)
    juris_count = await sb_count("jurisdictions")
    district_count = await sb_count("zoning_districts")
    standards_count = await sb_count("zone_standards")
    parcel_count = await sb_count("parcel_zones")

    top = await sb_query("jurisdictions",
        "select=county,data_completeness&data_completeness=gte.90&order=data_completeness.desc",
        limit=200)

    from collections import Counter
    county_counts = Counter(j["county"] for j in top)

    lines = ["## ZoneWise.AI — Florida Coverage\n",
             "| Metric | Count |",
             "|---|---|",
             f"| Counties | **67** |",
             f"| Jurisdictions | **{juris_count:,}** |",
             f"| Zoning Districts | **{district_count:,}** |",
             f"| Dimensional Standards | **{standards_count:,}** |",
             f"| Parcel Assignments | **{parcel_count:,}** |",
             f"| Jurisdictions at 90%+ | **{len(top)}** |",
             f"\n### Top Counties (by 90%+ jurisdictions)\n"]

    for county_name, count in county_counts.most_common(10):
        lines.append(f"• **{county_name}:** {count} jurisdictions at 90%+")

    return {"answer": "\n".join(lines), "data": {"jurisdictions": juris_count, "districts": district_count,
            "standards": standards_count, "parcels": parcel_count, "high_complete": len(top)},
            "citations": [], "suggestions": ["List zones in Tampa", "Show zones in Palm Beach"]}


async def agent_general(query: str, entities: Dict) -> Dict:
    """Handle general/unknown queries. Uses Claude for complex questions."""
    jurisdiction = entities.get("jurisdiction")
    if jurisdiction:
        return await agent_list_districts(entities)

    code = entities.get("zoning_code")
    if code:
        return await agent_district_detail(entities)

    # Try Claude for intelligent response
    client = get_anthropic()
    if client:
        try:
            stats_data = await get_stats()
            system = CLAUDE_SYSTEM_PROMPT.format(stats=json.dumps(stats_data, default=str))
            message = await client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": query}],
                timeout=25.0,
            )
            answer = message.content[0].text
            return {
                "answer": answer,
                "data": None, "citations": [],
                "suggestions": ["Show zones in Satellite Beach", "What are setbacks for RS-1?",
                                "How many counties do you cover?"]
            }
        except Exception as e:
            print(f"Anthropic API error: {e}")

    return {
        "answer": "Welcome to **ZoneWise.AI** — Florida's zoning intelligence platform.\n\nI can help you with:\n• **Look up zones** — \"What zones are in Satellite Beach?\"\n• **Get requirements** — \"What are the setbacks for RS-1?\"\n• **Find parcel zoning** — \"What zone is parcel 29 3712-00-529?\"\n• **Compare zones** — \"Compare RS-1 vs C-2\"\n• **Platform stats** — \"How many districts do you have?\"\n\nTry asking about any Florida city or county!",
        "data": None, "citations": [],
        "suggestions": ["Show zones in Satellite Beach", "What are setbacks for RS-1?",
                        "How many counties do you cover?"]
    }




async def agent_address_query(query: str, entities: Dict) -> Dict:
    """
    Handle address/property queries: "What can I build at 625 Ocean St Satellite Beach?"
    Strategy:
      1. Extract city from entities (already parsed by extract_entities)
      2. Look up jurisdiction in Supabase
      3. Get all zoning districts for that jurisdiction
      4. Get dimensional standards for residential districts (most likely for address queries)
      5. Get permitted uses if available
      6. Return real data — never hallucinate standards
    """
    jurisdiction = entities.get("jurisdiction")

    if not jurisdiction:
        return {
            "answer": (
                "I need a city or area name to look up zoning. Try:\n\n"
                "• _What can I build in **Satellite Beach**?_\n"
                "• _What's the zoning at 625 Ocean St, **Cocoa Beach**?_\n"
                "• _Development rules in **Melbourne**?_"
            ),
            "data": None, "citations": [],
            "suggestions": ["What can I build in Satellite Beach?",
                            "Zoning rules in Cocoa Beach",
                            "What zones are in Brevard County?"]
        }

    # ── Step 1: Resolve jurisdiction ────────────────────────────────────────
    juris_rows = await sb_query(
        "jurisdictions",
        f"select=id,name,county,data_completeness,municode_url"
        f"&or=(name.ilike.%25{jurisdiction}%25,county.ilike.%25{jurisdiction}%25)",
        limit=5
    )

    if not juris_rows:
        return {
            "answer": (
                f"I couldn't find **{jurisdiction}** in our Florida database.\n\n"
                f"Try the county name (e.g. _Brevard County_) or a nearby city."
            ),
            "data": None, "citations": [],
            "suggestions": [f"Show zones in Brevard County",
                            "What counties do you cover?"]
        }

    # Prefer exact name match, fall back to first result
    j = next((r for r in juris_rows if r["name"].lower() == jurisdiction.lower()), juris_rows[0])
    jid = j["id"]

    # ── Step 2: Get all zoning districts ────────────────────────────────────
    districts = await sb_query(
        "zoning_districts",
        f"select=id,code,name,category,description&jurisdiction_id=eq.{jid}&order=category,code",
        limit=200
    )

    if not districts:
        return {
            "answer": (
                f"**{j['name']}** ({j['county']} County) is in our database but "
                f"zoning districts haven't been loaded yet.\n\n"
                f"Data completeness: {j.get('data_completeness', 0):.0f}%\n\n"
                f"Check back soon — our scraper processes all 67 FL counties nightly."
            ),
            "data": {"jurisdiction": j}, "citations": [],
            "suggestions": [f"Show zones in {j['county']} County",
                            "Which counties have full data?"]
        }

    # ── Step 3: Get dimensional standards for districts ──────────────────────
    district_ids = [str(d["id"]) for d in districts]
    standards_map: Dict[str, Dict] = {}

    if district_ids:
        # Fetch standards in batches of 50
        for i in range(0, min(len(district_ids), 100), 50):
            batch = district_ids[i:i+50]
            standards = await sb_query(
                "zone_standards",
                f"select=*&zoning_district_id=in.({','.join(batch)})",
                limit=200
            )
            for s in standards:
                standards_map[str(s["zoning_district_id"])] = s

    # ── Step 4: Get permitted uses ───────────────────────────────────────────
    uses_map: Dict[str, list] = {}
    if district_ids:
        for i in range(0, min(len(district_ids), 50), 50):
            batch = district_ids[i:i+50]
            uses = await sb_query(
                "permitted_uses",
                f"select=zoning_district_id,use_type,use_name,permission_type"
                f"&zoning_district_id=in.({','.join(batch)})&order=permission_type,use_name",
                limit=500
            )
            for u in uses:
                did = str(u["zoning_district_id"])
                uses_map.setdefault(did, []).append(u)

    # ── Step 5: Build response ───────────────────────────────────────────────
    # Group districts by category
    by_cat: Dict[str, list] = {}
    for d in districts:
        cat = d.get("category") or "Other"
        by_cat.setdefault(cat, []).append(d)

    # Address line from query (best-effort)
    addr_match = entities.get("address", "")
    location_line = f"**{addr_match}, {j['name']}**" if addr_match else f"**{j['name']}**"

    lines = [
        f"## {location_line}",
        f"**County:** {j['county']} | "
        f"**Data completeness:** {j.get('data_completeness', 0):.0f}% | "
        f"**{len(districts)} zoning districts**\n",
    ]

    has_standards = bool(standards_map)

    # Residential districts first (most relevant for property queries)
    priority_cats = ["Residential", "Single Family", "Multi-Family"]
    other_cats = [c for c in by_cat if c not in priority_cats]
    ordered_cats = [c for c in priority_cats if c in by_cat] + other_cats

    for cat in ordered_cats[:4]:  # Cap at 4 categories for readability
        dists = by_cat[cat]
        lines.append(f"### {cat} Districts\n")

        for d in dists[:6]:  # Cap at 6 districts per category
            did_str = str(d["id"])
            s = standards_map.get(did_str)
            u_list = uses_map.get(did_str, [])

            lines.append(f"**{d['code']}** — {d.get('name', '')}\n")

            if s:
                # Show key dimensional standards
                std_rows = []
                field_map = [
                    ("min_lot_sqft",        "Min Lot Size",    lambda v: f"{int(v):,} sq ft"),
                    ("front_setback_ft",    "Front Setback",   lambda v: f"{v} ft"),
                    ("side_setback_ft",     "Side Setback",    lambda v: f"{v} ft"),
                    ("rear_setback_ft",     "Rear Setback",    lambda v: f"{v} ft"),
                    ("max_height_ft",       "Max Height",      lambda v: f"{v} ft"),
                    ("max_lot_coverage_pct","Max Lot Coverage",lambda v: f"{v}%"),
                    ("max_density_du_acre", "Max Density",     lambda v: f"{v} du/acre"),
                ]
                for field, label, fmt in field_map:
                    val = s.get(field)
                    if val is not None:
                        std_rows.append(f"| {label} | **{fmt(val)}** |")

                if std_rows:
                    lines.append("| Requirement | Value |")
                    lines.append("|---|---|")
                    lines.extend(std_rows)

                conf_line = format_confidence(s.get("confidence_score"))
                if conf_line:
                    lines.append(conf_line + "\n")
            else:
                lines.append("_Dimensional standards pending for this district_\n")

            # Permitted uses summary
            if u_list:
                permitted = [u["use_name"] for u in u_list if u.get("permission_type") in ("P", "permitted", "by-right")][:4]
                conditional = [u["use_name"] for u in u_list if u.get("permission_type") in ("C", "conditional", "CU")][:3]
                prohibited = [u["use_name"] for u in u_list if u.get("permission_type") in ("N", "prohibited", "not-permitted")][:3]

                if permitted:
                    lines.append(f"✅ **Permitted:** {', '.join(permitted)}")
                if conditional:
                    lines.append(f"⚠️ **Conditional:** {', '.join(conditional)}")
                if prohibited:
                    lines.append(f"❌ **Not Permitted:** {', '.join(prohibited)}")
                lines.append("")

        lines.append("")

    # Footer
    lines.append("---")
    if not has_standards:
        lines.append(
            "> ⚠️ Dimensional standards for this jurisdiction are still being processed. "
            "Districts shown are real — setback/height data coming soon."
        )
    lines.append(
        f"_For exact parcel zoning, provide your parcel ID or visit "
        f"[Brevard Property Appraiser](https://www.bcpao.us) / county GIS._"
        if j["county"] == "Brevard"
        else f"_For exact parcel zoning, provide your parcel ID or visit {j['county']} County GIS._"
    )

    citations = []
    if j.get("municode_url"):
        citations.append({
            "source": "Municode",
            "url": j["municode_url"],
            "title": f"{j['name']} Code of Ordinances"
        })

    # Top suggestion based on most complete residential district
    best_district = next(
        (d for d in districts if standards_map.get(str(d["id"]))),
        districts[0] if districts else None
    )

    return {
        "answer": "\n".join(lines),
        "data": {
            "jurisdiction": j,
            "district_count": len(districts),
            "standards_count": len(standards_map),
            "categories": {k: len(v) for k, v in by_cat.items()}
        },
        "citations": citations,
        "suggestions": [
            f"Setbacks for {best_district['code']} in {j['name']}" if best_district else f"List zones in {j['name']}",
            f"What can I build in {j['county']} County?",
            f"Compare zones in {j['name']}",
        ]
    }

# ═══════════════════════════════════════════════════════════════
# AGENT ROUTER
# ═══════════════════════════════════════════════════════════════

AGENT_MAP = {
    "LIST_DISTRICTS":  lambda q, e: agent_list_districts(e),
    "DISTRICT_DETAIL": lambda q, e: agent_district_detail(e),
    "COMPARISON":      lambda q, e: agent_comparison(e),
    "FEASIBILITY":     lambda q, e: agent_district_detail(e),
    "ADDRESS_QUERY":   lambda q, e: agent_address_query(q, e),
    "PARCEL_LOOKUP":   lambda q, e: agent_parcel_lookup(e),
    "COUNTY_STATS":    lambda q, e: agent_county_stats(e),
    "GENERAL":         agent_general,
}


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    db_ok = bool(SUPABASE_KEY)
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "no_key",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.1.0",
        "counties": 67,
    }


@app.get("/agents")
async def list_agents():
    return [
        {"name": "ZoningResearchAgent", "intents": ["LIST_DISTRICTS", "DISTRICT_DETAIL", "COMPARISON", "FEASIBILITY"],
         "description": "Zoning codes, setbacks, height limits, density, FAR, permitted uses"},
        {"name": "ParcelAnalysisAgent", "intents": ["PARCEL_LOOKUP"],
         "description": "Parcel-to-zone mapping and property analysis"},
        {"name": "StatsAgent", "intents": ["COUNTY_STATS"],
         "description": "Platform coverage and data statistics"},
        {"name": "ReportAgent", "intents": ["REPORT"],
         "description": "Generate zoning reports (PDF/DOCX)"},
    ]


@app.post("/agents/query", response_model=ChatResponse)
async def query_agents(req: ChatRequest):
    intent = classify_intent(req.query)
    entities = extract_entities(req.query)

    handler = AGENT_MAP.get(intent, agent_general)
    result = await handler(req.query, entities)

    return ChatResponse(
        answer=result.get("answer", "I couldn't process that query."),
        intent=intent,
        entities=entities,
        data=result.get("data"),
        citations=result.get("citations", []),
        suggestions=result.get("suggestions", []),
    )


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """Alias for /agents/query — used by frontend chat UI."""
    return await query_agents(req)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE streaming endpoint for real-time chat UI.
    Structured intents use fast regex handlers. GENERAL/FEASIBILITY/REPORT
    stream from Claude Sonnet 4.5 with Supabase context injection.
    """
    intent = classify_intent(req.query)
    entities = extract_entities(req.query)

    async def generate():
        yield f"data: {json.dumps({'type': 'intent', 'value': intent})}\n\n"
        yield f"data: {json.dumps({'type': 'entities', 'value': entities})}\n\n"

        # Structured intents: fast regex → Supabase
        if intent in ("LIST_DISTRICTS", "DISTRICT_DETAIL",
                       "ADDRESS_QUERY", "PARCEL_LOOKUP", "COUNTY_STATS"):
            yield f"data: {json.dumps({'type': 'thinking', 'value': f'Querying {intent}...'})}\n\n"
            handler = AGENT_MAP.get(intent, agent_general)
            result = await handler(req.query, entities)
            yield f"data: {json.dumps({'type': 'answer', 'value': result.get('answer', '')})}\n\n"
            if result.get("data"):
                yield f"data: {json.dumps({'type': 'data', 'value': result['data']}, default=str)}\n\n"
            for c in result.get("citations", []):
                yield f"data: {json.dumps({'type': 'citation', 'value': c})}\n\n"
            for s in result.get("suggestions", []):
                yield f"data: {json.dumps({'type': 'suggestion', 'value': s})}\n\n"
        else:
            # GENERAL/FEASIBILITY/REPORT: try Claude streaming
            yield f"data: {json.dumps({'type': 'thinking', 'value': 'Consulting Claude...'})}\n\n"

            # Gather context from Supabase
            context_parts = []
            if entities.get("jurisdiction"):
                jname = entities["jurisdiction"]
                jurs = await sb_query("jurisdictions",
                    f"select=id,name,county&name=ilike.%25{jname}%25", limit=3)
                if jurs:
                    context_parts.append(f"Jurisdictions: {json.dumps(jurs)}")
                    for j in jurs[:1]:
                        dists = await sb_query("zoning_districts",
                            f"select=code,name,category&jurisdiction_id=eq.{j['id']}", limit=20)
                        if dists:
                            context_parts.append(f"Districts in {j['name']}: {json.dumps(dists)}")

            if entities.get("zoning_code"):
                zcode = entities["zoning_code"]
                dists = await sb_query("zoning_districts",
                    f"select=id,code,name,description,category&code=ilike.{zcode}", limit=3)
                if dists:
                    context_parts.append(f"District data: {json.dumps(dists)}")
                    for d in dists[:1]:
                        stds = await sb_query("zone_standards",
                            f"select=*&zoning_district_id=eq.{d['id']}", limit=1)
                        if stds:
                            context_parts.append(f"Standards: {json.dumps(stds)}")

            context = "\n".join(context_parts)

            client = get_anthropic()
            if client:
                try:
                    stats_data = await get_stats()
                    system = CLAUDE_SYSTEM_PROMPT.format(stats=json.dumps(stats_data, default=str))
                    if context:
                        system += f"\n\nDatabase context:\n{context}"

                    full_answer = ""
                    async with client.messages.stream(
                        model="claude-sonnet-4-5-20250929",
                        max_tokens=1024,
                        system=system,
                        messages=[{"role": "user", "content": req.query}],
                        timeout=30.0,
                    ) as stream:
                        async for text in stream.text_stream:
                            full_answer += text
                            yield f"data: {json.dumps({'type': 'answer', 'value': full_answer})}\n\n"
                            await asyncio.sleep(0.01)
                except Exception as e:
                    print(f"Claude streaming error: {type(e).__name__}: {e}")
                    yield f"data: {json.dumps({'type': 'thinking', 'value': 'Falling back to structured query...'})}\n\n"
                    # Fallback to regex handler
                    result = await agent_general(req.query, entities)
                    yield f"data: {json.dumps({'type': 'answer', 'value': result.get('answer', '')})}\n\n"
            else:
                # No API key — regex fallback
                result = await agent_general(req.query, entities)
                yield f"data: {json.dumps({'type': 'answer', 'value': result.get('answer', '')})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ═══════════════════════════════════════════════════════════════
# REST ENDPOINTS — Direct data access for frontend map/tables
# ═══════════════════════════════════════════════════════════════

@app.get("/api/jurisdictions")
async def get_jurisdictions(
    county: Optional[str] = None,
    min_completeness: float = 0,
    limit: int = 100
):
    """List jurisdictions with optional county filter."""
    params = f"select=id,name,county,data_completeness,data_source,municode_url&data_completeness=gte.{min_completeness}&order=county,name"
    if county:
        params += f"&county=ilike.%25{county}%25"
    return await sb_query("jurisdictions", params, limit=limit)


@app.get("/api/jurisdictions/{jid}/districts")
async def get_jurisdiction_districts(jid: int):
    """Get all zoning districts for a jurisdiction."""
    districts = await sb_query("zoning_districts",
        f"select=id,code,name,category&jurisdiction_id=eq.{jid}&order=category,code", limit=200)

    # Batch fetch standards
    if districts:
        dids = ",".join(str(d["id"]) for d in districts)
        standards = await sb_query("zone_standards",
            f"select=zoning_district_id,min_lot_sqft,max_height_ft,front_setback_ft,side_setback_ft,rear_setback_ft&zoning_district_id=in.({dids})",
            limit=200)
        std_map = {s["zoning_district_id"]: s for s in standards}
        for d in districts:
            d["standards"] = std_map.get(d["id"])

    return districts


@app.get("/api/districts/{did}")
async def get_district(did: int):
    """Get full district detail with standards."""
    districts = await sb_query("zoning_districts", f"select=*&id=eq.{did}", limit=1)
    if not districts:
        raise HTTPException(404, "District not found")
    d = districts[0]

    standards = await sb_query("zone_standards", f"select=*&zoning_district_id=eq.{did}", limit=1)
    d["standards"] = standards[0] if standards else None
    d["dims"] = extract_dims(d.get("description", ""))
    return d


@app.get("/api/parcels/{parcel_id}")
async def get_parcel(parcel_id: str):
    """Look up parcel zone assignment."""
    parcels = await sb_query("parcel_zones", f"select=*&parcel_id=eq.{parcel_id}", limit=1)
    if not parcels:
        raise HTTPException(404, "Parcel not found")
    return parcels[0]


@app.get("/api/stats")
async def get_stats():
    """Platform-wide statistics."""
    results = await asyncio.gather(
        sb_count("jurisdictions"),
        sb_count("zoning_districts"),
        sb_count("zone_standards"),
        sb_count("parcel_zones"),
        sb_count("overlay_districts"),
    )
    return {
        "jurisdictions": results[0],
        "zoning_districts": results[1],
        "zone_standards": results[2],
        "parcel_zones": results[3],
        "overlay_districts": results[4],
        "counties": 67,
        "updated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/search")
async def search_districts(
    q: str = Query(..., min_length=1, description="Search zoning codes or names"),
    limit: int = 20
):
    """Full-text search across districts."""
    results = await sb_query("zoning_districts",
        f"select=id,code,name,category,jurisdiction_id&or=(code.ilike.%25{q}%25,name.ilike.%25{q}%25)&order=code",
        limit=limit)
    return results


# ═══════════════════════════════════════════════════════════════
# CHAT UI - Serves NLP chatbot with multilingual + Hebrew RTL
# ═══════════════════════════════════════════════════════════════

@app.get("/chat-ui")
async def chat_ui():
    """Serve the NLP chatbot interface."""
    chat_file = Path(__file__).parent / "static" / "chat.html"
    if chat_file.exists():
        return FileResponse(chat_file, media_type="text/html")
    return HTMLResponse("<h1>Chat UI not found</h1>", status_code=404)


# ═══════════════════════════════════════════════════════════════
# OPS DASHBOARD — /ops/metrics
# ═══════════════════════════════════════════════════════════════

GH_TOKEN = os.getenv("GH_TOKEN", "")
GH_ORG = "breverdbidder"
GH_MODAL_REPO = "zonewise-modal"

SCHEDULED_WORKFLOWS = [
    {"name": "master_scraper.yml", "label": "Nightly County Scrape", "schedule": "Daily 11PM EST"},
    {"name": "self_optimize.yml",  "label": "Self-Optimize",          "schedule": "Daily 1AM EST"},
    {"name": "weekly-security-report.yml", "label": "Security Report","schedule": "Weekly Sunday"},
    {"name": "scheduled-monitoring.yml",   "label": "Monitoring",     "schedule": "Daily"},
]


async def gh_workflow_runs(workflow: str) -> dict:
    """Fetch last run status for a GitHub Actions workflow."""
    if not GH_TOKEN:
        return {"status": "unknown", "last_run": None, "duration_seconds": None}
    client = await get_client()
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{GH_ORG}/{GH_MODAL_REPO}/actions/workflows/{workflow}/runs?per_page=1",
            headers={"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"},
            timeout=5.0
        )
        if resp.status_code != 200:
            return {"status": "unknown", "last_run": None, "duration_seconds": None}
        data = resp.json()
        runs = data.get("workflow_runs", [])
        if not runs:
            return {"status": "never_run", "last_run": None, "duration_seconds": None}
        run = runs[0]
        conclusion = run.get("conclusion") or run.get("status", "unknown")
        created = run.get("created_at")
        updated = run.get("updated_at")
        duration = None
        if created and updated:
            from datetime import timezone
            t1 = datetime.fromisoformat(created.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            duration = int((t2 - t1).total_seconds())
        return {
            "status": conclusion,
            "last_run": updated,
            "duration_seconds": duration,
            "run_url": run.get("html_url")
        }
    except Exception:
        return {"status": "error", "last_run": None, "duration_seconds": None}


@app.get("/ops/metrics")
async def ops_metrics():
    """
    Aggregate pipeline health, agent status, data quality, and scheduled tasks
    for the ZoneWise Agent Ops Dashboard.
    """
    now = datetime.utcnow().isoformat() + "Z"

    # ── Pipeline Health ──────────────────────────────────────────
    county_total = await sb_count("jurisdictions")
    counties_with_data = await sb_count("jurisdictions", "co_no=not.is.null")

    # Recent scrape jobs (last 7 days)
    scrape_jobs_recent = []
    try:
        scrape_jobs_recent = await sb_query(
            "scrape_jobs",
            "select=id,county,status,started_at,completed_at,records_scraped,error_message&order=started_at.desc",
            limit=100
        )
    except Exception:
        pass

    total_jobs = len(scrape_jobs_recent)
    successful_jobs = sum(1 for j in scrape_jobs_recent if j.get("status") == "success")
    failed_jobs = [j for j in scrape_jobs_recent if j.get("status") == "error"]
    last_run = scrape_jobs_recent[0].get("completed_at") if scrape_jobs_recent else None
    success_rate = round(successful_jobs / total_jobs * 100, 1) if total_jobs > 0 else 0

    # Duration of last full run
    last_duration = None
    if scrape_jobs_recent:
        j = scrape_jobs_recent[0]
        if j.get("started_at") and j.get("completed_at"):
            try:
                t1 = datetime.fromisoformat(j["started_at"].replace("Z", ""))
                t2 = datetime.fromisoformat(j["completed_at"].replace("Z", ""))
                last_duration = int((t2 - t1).total_seconds())
            except Exception:
                pass

    # ── Agent Status ─────────────────────────────────────────────
    running_jobs = [j for j in scrape_jobs_recent if j.get("status") == "running"]
    pending_reports = []
    try:
        pending_reports = await sb_query(
            "scrape_jobs",
            "select=id&status=eq.pending_report",
            limit=50
        )
    except Exception:
        pass

    # ── Data Quality ─────────────────────────────────────────────
    records_today = 0
    try:
        today_jobs = [j for j in scrape_jobs_recent
                      if j.get("completed_at", "").startswith(now[:10])]
        records_today = sum(j.get("records_scraped", 0) or 0 for j in today_jobs)
    except Exception:
        pass

    # Recent errors from insights table
    recent_errors = []
    try:
        recent_errors = await sb_query(
            "insights",
            "select=id,county,error_message,created_at&type=eq.scrape_error&order=created_at.desc",
            limit=20
        )
    except Exception:
        pass

    validation_errors = len(recent_errors)
    schema_compliance = round((1 - validation_errors / max(total_jobs, 1)) * 100, 1)

    # ── Scheduled Tasks ───────────────────────────────────────────
    workflow_tasks = []
    for wf in SCHEDULED_WORKFLOWS:
        run_data = await gh_workflow_runs(wf["name"])
        workflow_tasks.append({
            "workflow": wf["name"],
            "label": wf["label"],
            "schedule": wf["schedule"],
            **run_data
        })

    return {
        "fetched_at": now,
        "pipeline_health": {
            "county_total": county_total,
            "counties_with_data": counties_with_data,
            "last_full_run": last_run,
            "last_duration_seconds": last_duration,
            "success_rate_pct": success_rate,
            "jobs_total": total_jobs,
            "jobs_successful": successful_jobs,
            "failed_counties": [
                {"county": j.get("county"), "error": j.get("error_message", "unknown")}
                for j in failed_jobs[:10]
            ]
        },
        "agent_status": {
            "scraper": "RUNNING" if running_jobs else "IDLE",
            "scraper_active_county": running_jobs[0].get("county") if running_jobs else None,
            "analysis_queue_depth": len([j for j in scrape_jobs_recent if j.get("status") == "pending_analysis"]),
            "report_pending": len(pending_reports),
            "qa_pass_rate_pct": schema_compliance,
        },
        "data_quality": {
            "records_today": records_today,
            "validation_errors_recent": validation_errors,
            "schema_compliance_pct": schema_compliance,
            "recent_errors": recent_errors[:5],
        },
        "scheduled_tasks": workflow_tasks,
    }
