"""
ZoneWise Agent API Server - UPDATED
FastAPI application for multi-agent zoning intelligence
Now queries REAL data from Supabase
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, AsyncGenerator
import os
import json
import asyncio
import httpx
import re
from datetime import datetime

# Initialize FastAPI
app = FastAPI(
    title="ZoneWise Agent API",
    description="Multi-agent backend for zoning intelligence",
    version="0.2.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://zonewise.ai",
        "https://agents.craft.do",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase config
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mocerqjnksmhcjzxrewo.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Models
class QueryRequest(BaseModel):
    query: str = Field(..., description="User's natural language query")
    session_id: str = Field(..., description="Session identifier")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")
    history: Optional[List[Dict[str, str]]] = Field(default=None, description="Chat history")

class Citation(BaseModel):
    source: str
    url: str
    title: str

class QueryResponse(BaseModel):
    answer: str
    intent: str
    entities: Dict[str, Any]
    thinking: List[str]
    citations: List[Citation]
    parcel_id: Optional[str] = None
    artifact: Optional[Dict[str, Any]] = None

# Supabase query helper
async def query_supabase(table: str, params: Dict[str, str] = None) -> List[Dict]:
    """Query Supabase REST API."""
    if not SUPABASE_KEY:
        return []
    
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url,
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}"
                },
                timeout=10.0
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Supabase query error: {e}")
    return []

def extract_dims(description: str) -> Dict[str, Any]:
    """Extract DIMS data from description field."""
    match = re.search(r'<!--DIMS:({.*?})-->', description)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}

async def get_zoning_district(code: str, jurisdiction: str = None) -> Dict[str, Any]:
    """Get zoning district data from Supabase."""
    # First get jurisdiction ID if provided
    jurisdiction_id = None
    if jurisdiction:
        jurisdictions = await query_supabase("jurisdictions", {"name": f"eq.{jurisdiction}"})
        if jurisdictions:
            jurisdiction_id = jurisdictions[0].get("id")
    
    # Query zoning districts
    params = {"code": f"eq.{code}", "select": "*"}
    if jurisdiction_id:
        params["jurisdiction_id"] = f"eq.{jurisdiction_id}"
    
    districts = await query_supabase("zoning_districts", params)
    
    if districts:
        district = districts[0]
        dims = extract_dims(district.get("description", ""))
        return {
            "code": district.get("code"),
            "name": district.get("name"),
            "category": district.get("category"),
            "jurisdiction_id": district.get("jurisdiction_id"),
            "dims": dims
        }
    return {}

# Intent classification
INTENT_KEYWORDS = {
    "LOOKUP": ["what is", "find", "show", "lookup", "search"],
    "CALCULATION": ["setback", "height", "far", "density", "calculate", "how much"],
    "COMPARISON": ["compare", "difference", "vs", "versus"],
    "FEASIBILITY": ["can i build", "allowed", "permitted", "feasible"],
    "HBU": ["highest and best", "best use", "hbu"],
    "REPORT": ["report", "generate", "pdf", "document"],
}

def classify_intent(query: str) -> str:
    query_lower = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return intent
    return "LOOKUP"

def extract_entities(query: str) -> Dict[str, Any]:
    """Extract entities from query."""
    entities = {}
    query_lower = query.lower()
    
    # Zoning code pattern (e.g., RS-1, C-2, RR-65, BU-1-A)
    zoning_pattern = r'\b([A-Z]{1,4}-\d{1,2}(?:-[A-Z])?)\b'
    zoning_match = re.search(zoning_pattern, query, re.IGNORECASE)
    if zoning_match:
        entities['zoning_code'] = zoning_match.group(1).upper()
    
    # Jurisdiction detection
    jurisdictions = ["malabar", "melbourne", "palm bay", "titusville", "cocoa", 
                     "rockledge", "satellite beach", "indian harbour beach",
                     "brevard county", "grant-valkaria", "indialantic", "west melbourne"]
    for j in jurisdictions:
        if j in query_lower:
            entities['jurisdiction'] = j.title()
            break
    
    return entities

async def run_zoning_research(query: str, entities: Dict, context: Dict = None) -> AsyncGenerator:
    """ZoningResearchAgent - Looks up REAL zoning data from Supabase."""
    thinking = []
    citations = []
    
    yield {"type": "thinking", "value": "Analyzing zoning query..."}
    thinking.append("Analyzing zoning query...")
    
    jurisdiction = entities.get("jurisdiction", "Brevard County")
    yield {"type": "thinking", "value": f"Identified jurisdiction: {jurisdiction}"}
    thinking.append(f"Identified jurisdiction: {jurisdiction}")
    
    zoning_code = entities.get("zoning_code")
    
    if zoning_code:
        yield {"type": "thinking", "value": f"Looking up zoning code: {zoning_code}"}
        thinking.append(f"Looking up zoning code: {zoning_code}")
        
        # Query REAL data from Supabase
        yield {"type": "thinking", "value": "Querying ZoneWise database..."}
        district_data = await get_zoning_district(zoning_code, jurisdiction)
        
        if district_data and district_data.get("dims"):
            dims = district_data["dims"]
            setbacks = dims.get("setbacks_ft", {})
            
            # Build citation
            source_url = dims.get("source_url", "https://library.municode.com/fl/malabar")
            citations.append({
                "source": dims.get("source", "Municode"),
                "url": source_url,
                "title": f"{jurisdiction} Land Development Code"
            })
            
            yield {"type": "thinking", "value": "Found verified dimensional standards!"}
            
            # Build answer
            answer = f"""**{zoning_code} - {district_data.get('name', 'Zoning District')}**

**Setbacks:**
- Front: {setbacks.get('front', 'N/A')} ft
- Side: {setbacks.get('side', 'N/A')} ft  
- Rear: {setbacks.get('rear', 'N/A')} ft

**Other Requirements:**
- Minimum Lot Size: {dims.get('min_lot_sqft', 'N/A'):,} sq ft
- Minimum Lot Width: {dims.get('min_lot_width_ft', 'N/A')} ft
- Maximum Height: {dims.get('max_height_ft', 'N/A')} ft
- Density: {dims.get('density_du_acre', 'N/A')} du/acre

**Source:** {dims.get('source', 'Malabar LDC')}
**Verified:** {dims.get('verified_date', 'Unknown')}
"""
        else:
            yield {"type": "thinking", "value": "No verified data found for this code"}
            answer = f"I couldn't find verified dimensional standards for {zoning_code} in {jurisdiction}. The code may not exist in our database, or the data hasn't been verified yet."
    else:
        answer = f"I found information about zoning in {jurisdiction}. Please provide a specific zoning code (e.g., RR-65, RS-10, C-1) to get setbacks and requirements."
    
    yield {"type": "thinking", "value": "Generating response..."}
    yield {"type": "intent", "value": "CALCULATION" if zoning_code else "LOOKUP"}
    yield {"type": "content", "value": answer}
    
    for c in citations:
        yield {"type": "citation", "value": c}

# ... rest of the agent functions remain similar but can be updated to use Supabase

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat(), "version": "0.2.0"}

@app.get("/agents")
async def list_agents():
    return [
        {"name": "ZoningResearchAgent", "description": "Looks up zoning codes, setbacks, FAR, and permitted uses", "intents": ["FEASIBILITY", "CALCULATION", "COMPARISON"]},
        {"name": "ParcelAnalysisAgent", "description": "Analyzes parcels using BCPAO data", "intents": ["LOOKUP"]},
        {"name": "HBUCalculatorAgent", "description": "Performs Highest & Best Use analysis", "intents": ["HBU"]},
        {"name": "ReportGeneratorAgent", "description": "Generates PDF/DOCX zoning reports", "intents": ["REPORT"]},
    ]

AGENT_ROUTES = {
    "LOOKUP": run_zoning_research,
    "CALCULATION": run_zoning_research,
    "COMPARISON": run_zoning_research,
    "FEASIBILITY": run_zoning_research,
}

@app.post("/agents/query", response_model=QueryResponse)
async def query_agents(request: QueryRequest):
    intent = classify_intent(request.query)
    entities = extract_entities(request.query)
    
    agent_fn = AGENT_ROUTES.get(intent, run_zoning_research)
    
    answer = ""
    thinking = []
    citations = []
    
    async for chunk in agent_fn(request.query, entities, request.context):
        if chunk["type"] == "content":
            answer += chunk["value"]
        elif chunk["type"] == "thinking":
            thinking.append(chunk["value"])
        elif chunk["type"] == "citation":
            citations.append(chunk["value"])
    
    return QueryResponse(
        answer=answer,
        intent=intent,
        entities=entities,
        thinking=thinking,
        citations=citations
    )
