"""
ZoneWise Agent API Server v1.0.0
Enterprise-grade FastAPI backend for zoning intelligence
Queries REAL data from Supabase across all 67 FL counties
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


# ═══════════════════════════════════════════════════════════════
# APP CONFIG
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title="ZoneWise Agent API",
    description="Enterprise zoning intelligence for all 67 FL counties",
    version="1.0.0",
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
    ("LIST_DISTRICTS", ["what zones", "zoning districts", "list zones", "all zones",
                        "what zoning", "districts in", "zone types"]),
    ("DISTRICT_DETAIL", ["setback", "height limit", "lot size", "density",
                         "far ", "floor area", "building envelope", "requirements for"]),
    ("COMPARISON", ["compare", "difference between", "vs ", "versus"]),
    ("FEASIBILITY", ["can i build", "allowed", "permitted", "feasible",
                     "what can i", "is it possible"]),
    ("PARCEL_LOOKUP", ["parcel", "folio", "property at", "address",
                       "what zone is", "zoned as"]),
    ("REPORT", ["report", "generate", "pdf", "export", "download"]),
    ("COUNTY_STATS", ["how many", "statistics", "coverage", "counties",
                      "total districts"]),
]


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

        conf = s.get("confidence_score", 0)
        lines.append(f"\n_Confidence: {conf*100:.0f}% | Source: {s.get('source_url', 'Municode')}_")

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
    """Platform statistics and coverage."""
    juris_count = await sb_count("jurisdictions")
    district_count = await sb_count("zoning_districts")
    standards_count = await sb_count("zone_standards")
    parcel_count = await sb_count("parcel_zones")

    # Get top counties by completeness
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

    for county, count in county_counts.most_common(10):
        lines.append(f"• **{county}:** {count} jurisdictions at 90%+")

    return {"answer": "\n".join(lines), "data": {"jurisdictions": juris_count, "districts": district_count,
            "standards": standards_count, "parcels": parcel_count, "high_complete": len(top)},
            "citations": [], "suggestions": ["List zones in Tampa", "Show zones in Palm Beach"]}


async def agent_general(query: str, entities: Dict) -> Dict:
    """Handle general/unknown queries by trying jurisdiction lookup."""
    jurisdiction = entities.get("jurisdiction")
    if jurisdiction:
        return await agent_list_districts(entities)

    code = entities.get("zoning_code")
    if code:
        return await agent_district_detail(entities)

    return {
        "answer": "Welcome to **ZoneWise.AI** — Florida's zoning intelligence platform.\n\nI can help you with:\n• **Look up zones** — \"What zones are in Satellite Beach?\"\n• **Get requirements** — \"What are the setbacks for RS-1?\"\n• **Find parcel zoning** — \"What zone is parcel 29 3712-00-529?\"\n• **Compare zones** — \"Compare RS-1 vs C-2\"\n• **Platform stats** — \"How many districts do you have?\"\n\nTry asking about any Florida city or county!",
        "data": None, "citations": [],
        "suggestions": ["Show zones in Satellite Beach", "What are setbacks for RS-1?",
                        "How many counties do you cover?"]
    }


# ═══════════════════════════════════════════════════════════════
# AGENT ROUTER
# ═══════════════════════════════════════════════════════════════

AGENT_MAP = {
    "LIST_DISTRICTS": lambda q, e: agent_list_districts(e),
    "DISTRICT_DETAIL": lambda q, e: agent_district_detail(e),
    "COMPARISON": lambda q, e: agent_comparison(e),
    "FEASIBILITY": lambda q, e: agent_district_detail(e),
    "PARCEL_LOOKUP": lambda q, e: agent_parcel_lookup(e),
    "COUNTY_STATS": lambda q, e: agent_county_stats(e),
    "GENERAL": agent_general,
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
        "version": "1.0.0",
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
    """SSE streaming endpoint for real-time chat UI."""
    intent = classify_intent(req.query)
    entities = extract_entities(req.query)

    async def generate():
        yield f"data: {json.dumps({'type': 'intent', 'value': intent})}\n\n"
        yield f"data: {json.dumps({'type': 'entities', 'value': entities})}\n\n"
        yield f"data: {json.dumps({'type': 'thinking', 'value': f'Routing to {intent} agent...'})}\n\n"

        handler = AGENT_MAP.get(intent, agent_general)
        result = await handler(req.query, entities)

        yield f"data: {json.dumps({'type': 'thinking', 'value': 'Query complete.'})}\n\n"
        yield f"data: {json.dumps({'type': 'answer', 'value': result.get('answer', '')})}\n\n"

        if result.get("data"):
            yield f"data: {json.dumps({'type': 'data', 'value': result['data']}, default=str)}\n\n"
        for c in result.get("citations", []):
            yield f"data: {json.dumps({'type': 'citation', 'value': c})}\n\n"
        for s in result.get("suggestions", []):
            yield f"data: {json.dumps({'type': 'suggestion', 'value': s})}\n\n"
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
