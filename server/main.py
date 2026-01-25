"""
ZoneWise Agent API Server
FastAPI application for multi-agent zoning intelligence
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
from datetime import datetime

# Initialize FastAPI
app = FastAPI(
    title="ZoneWise Agent API",
    description="Multi-agent backend for zoning intelligence",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://zonewise.ai",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

class AgentInfo(BaseModel):
    name: str
    description: str
    intents: List[str]

# Intent Classification
INTENT_KEYWORDS = {
    "FEASIBILITY": ["can i build", "allowed", "permitted", "feasible", "possible"],
    "CALCULATION": ["setback", "height", "far", "density", "coverage", "how much", "how many"],
    "LOOKUP": ["zoning", "what is", "what's the", "zone for", "tell me about"],
    "HBU": ["highest and best", "best use", "hbu", "optimal use"],
    "COMPARISON": ["compare", "vs", "versus", "difference between"],
    "REPORT": ["report", "generate", "create document", "pdf", "summary"],
}

def classify_intent(query: str) -> str:
    """Classify the intent of a query based on keywords."""
    query_lower = query.lower()
    
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return intent
    
    return "LOOKUP"  # Default

def extract_entities(query: str) -> Dict[str, Any]:
    """Extract entities from a query (addresses, parcel IDs, zoning codes)."""
    entities = {}
    
    # Simple pattern matching (in production, use NER or LLM)
    import re
    
    # Parcel ID pattern (e.g., 25-37-21-00-00003.0-0000.00)
    parcel_pattern = r'\d{2}-\d{2}-\d{2}-\d{2}-\d{5}\.\d+-\d{4}\.\d{2}'
    parcel_match = re.search(parcel_pattern, query)
    if parcel_match:
        entities['parcel_id'] = parcel_match.group()
    
    # Address pattern (simplified)
    address_pattern = r'\d+\s+[\w\s]+(?:st|street|ave|avenue|rd|road|dr|drive|blvd|boulevard|ln|lane|ct|court|way|pl|place)\b'
    address_match = re.search(address_pattern, query, re.IGNORECASE)
    if address_match:
        entities['address'] = address_match.group().strip()
    
    # Zoning code pattern (e.g., RS-1, C-2, BU-1-A)
    zoning_pattern = r'\b[A-Z]{1,3}-\d{1,2}(?:-[A-Z])?\b'
    zoning_match = re.search(zoning_pattern, query.upper())
    if zoning_match:
        entities['zoning_code'] = zoning_match.group()
    
    # Jurisdiction names
    jurisdictions = [
        "melbourne", "palm bay", "titusville", "cocoa", "cocoa beach",
        "rockledge", "satellite beach", "indian harbour beach", "west melbourne",
        "cape canaveral", "indialantic", "melbourne beach", "melbourne village",
        "malabar", "grant-valkaria", "brevard county"
    ]
    query_lower = query.lower()
    for jurisdiction in jurisdictions:
        if jurisdiction in query_lower:
            entities['jurisdiction'] = jurisdiction.title()
            break
    
    return entities

# Agent Functions
async def run_zoning_research(query: str, entities: Dict, context: Dict = None) -> AsyncGenerator:
    """ZoningResearchAgent - Looks up zoning codes, setbacks, FAR, etc."""
    thinking = []
    citations = []
    
    # Step 1: Identify what we're looking for
    yield {"type": "thinking", "value": "Analyzing zoning query..."}
    thinking.append("Analyzing zoning query...")
    
    # Step 2: Determine jurisdiction
    jurisdiction = entities.get("jurisdiction", "Brevard County")
    yield {"type": "thinking", "value": f"Identified jurisdiction: {jurisdiction}"}
    thinking.append(f"Identified jurisdiction: {jurisdiction}")
    
    # Step 3: Look up zoning data
    zoning_code = entities.get("zoning_code")
    if zoning_code:
        yield {"type": "thinking", "value": f"Looking up zoning code: {zoning_code}"}
        thinking.append(f"Looking up zoning code: {zoning_code}")
        
        # Simulated zoning data (in production, query Supabase)
        zoning_data = {
            "RS-1": {
                "name": "Single Family Residential",
                "min_lot_size": "7,500 sq ft",
                "setback_front": "25 ft",
                "setback_side": "7.5 ft",
                "setback_rear": "20 ft",
                "max_height": "35 ft",
                "uses": ["Single-family dwelling", "Home occupation", "Accessory structures"],
            },
            "C-1": {
                "name": "Neighborhood Commercial",
                "min_lot_size": "None",
                "setback_front": "0-25 ft",
                "setback_side": "0 ft",
                "setback_rear": "10 ft",
                "max_height": "45 ft",
                "uses": ["Retail", "Office", "Restaurant", "Personal services"],
            },
        }
        
        data = zoning_data.get(zoning_code, {})
        if data:
            citations.append({
                "source": "Municode",
                "url": f"https://library.municode.com/fl/{jurisdiction.lower().replace(' ', '_')}/codes/code_of_ordinances",
                "title": f"{jurisdiction} Code of Ordinances"
            })
    
    # Step 4: Generate answer
    yield {"type": "thinking", "value": "Generating response..."}
    
    if zoning_code and zoning_code in zoning_data:
        data = zoning_data[zoning_code]
        answer = f"""**{zoning_code} - {data['name']}**

**Setbacks:**
- Front: {data['setback_front']}
- Side: {data['setback_side']}
- Rear: {data['setback_rear']}

**Other Requirements:**
- Minimum Lot Size: {data['min_lot_size']}
- Maximum Height: {data['max_height']}

**Permitted Uses:**
{chr(10).join(f'- {use}' for use in data['uses'])}
"""
    else:
        answer = f"I found information about zoning in {jurisdiction}. To get specific setbacks and requirements, please provide a zoning code (e.g., RS-1, C-1) or a property address."
    
    yield {"type": "intent", "value": "LOOKUP" if not zoning_code else "CALCULATION"}
    yield {"type": "content", "value": answer}
    
    for citation in citations:
        yield {"type": "citation", "value": citation}

async def run_parcel_analysis(query: str, entities: Dict, context: Dict = None) -> AsyncGenerator:
    """ParcelAnalysisAgent - Looks up parcel data from BCPAO."""
    yield {"type": "thinking", "value": "Searching for parcel information..."}
    
    parcel_id = entities.get("parcel_id")
    address = entities.get("address")
    
    if parcel_id:
        yield {"type": "thinking", "value": f"Found parcel ID: {parcel_id}"}
        yield {"type": "parcel", "value": parcel_id}
    elif address:
        yield {"type": "thinking", "value": f"Searching for address: {address}"}
        # In production: geocode address and find parcel
        yield {"type": "thinking", "value": "Matching address to parcel..."}
    
    yield {"type": "thinking", "value": "Retrieving BCPAO data..."}
    
    # Simulated parcel data
    answer = f"""**Parcel Information**

I found the parcel you're looking for. Here's the summary:

- **Address:** {address or '123 Main St, Melbourne, FL'}
- **Parcel ID:** {parcel_id or '25-37-21-00-00003.0-0000.00'}
- **Zoning:** RS-1 (Single Family Residential)
- **Acreage:** 0.25 acres
- **Just Value:** $285,000
- **Owner:** Sample Owner LLC

Would you like me to analyze the zoning requirements or generate a full report?
"""
    
    yield {"type": "intent", "value": "LOOKUP"}
    yield {"type": "content", "value": answer}
    yield {"type": "citation", "value": {
        "source": "BCPAO",
        "url": "https://www.bcpao.us",
        "title": "Brevard County Property Appraiser"
    }}

async def run_hbu_analysis(query: str, entities: Dict, context: Dict = None) -> AsyncGenerator:
    """HBUCalculatorAgent - Analyzes highest and best use."""
    yield {"type": "thinking", "value": "Initiating Highest & Best Use analysis..."}
    yield {"type": "thinking", "value": "Evaluating legally permissible uses..."}
    yield {"type": "thinking", "value": "Assessing physical possibilities..."}
    yield {"type": "thinking", "value": "Analyzing financial feasibility..."}
    yield {"type": "thinking", "value": "Determining maximum productivity..."}
    
    answer = """**Highest & Best Use Analysis**

Based on the zoning, location, and market conditions:

**Legally Permissible:**
- Single-family residential (by-right)
- Duplex (with special exception)
- Home occupation

**Physically Possible:**
- Site is relatively flat with good access
- Standard rectangular lot (75' x 150')
- No environmental constraints identified

**Financially Feasible:**
- Single-family: Est. value $350-400K (feasible)
- Duplex: Est. value $450-500K (feasible with variance)

**Maximally Productive:**
→ **Single-family residence** is the highest and best use

*This analysis is preliminary. A formal HBU study should be conducted by a licensed appraiser.*
"""
    
    yield {"type": "intent", "value": "HBU"}
    yield {"type": "content", "value": answer}

# Route to appropriate agent
AGENT_ROUTES = {
    "FEASIBILITY": run_zoning_research,
    "CALCULATION": run_zoning_research,
    "LOOKUP": run_parcel_analysis,
    "HBU": run_hbu_analysis,
    "COMPARISON": run_zoning_research,
    "REPORT": run_parcel_analysis,  # Placeholder
}

# Endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/agents", response_model=List[AgentInfo])
async def list_agents():
    """List available agents."""
    return [
        AgentInfo(
            name="ZoningResearchAgent",
            description="Looks up zoning codes, setbacks, FAR, and permitted uses",
            intents=["FEASIBILITY", "CALCULATION", "COMPARISON"],
        ),
        AgentInfo(
            name="ParcelAnalysisAgent",
            description="Analyzes parcels using BCPAO data",
            intents=["LOOKUP"],
        ),
        AgentInfo(
            name="HBUCalculatorAgent",
            description="Performs Highest & Best Use analysis",
            intents=["HBU"],
        ),
        AgentInfo(
            name="ReportGeneratorAgent",
            description="Generates PDF/DOCX zoning reports",
            intents=["REPORT"],
        ),
    ]

@app.post("/agents/query/stream")
async def query_agents_stream(request: QueryRequest):
    """Streaming query endpoint."""
    
    async def generate():
        # Classify intent
        intent = classify_intent(request.query)
        
        # Extract entities
        entities = extract_entities(request.query)
        
        # Route to appropriate agent
        agent_fn = AGENT_ROUTES.get(intent, run_parcel_analysis)
        
        # Stream agent response
        async for chunk in agent_fn(request.query, entities, request.context):
            yield f"data: {json.dumps(chunk)}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

@app.post("/agents/query", response_model=QueryResponse)
async def query_agents(request: QueryRequest):
    """Non-streaming query endpoint."""
    
    intent = classify_intent(request.query)
    entities = extract_entities(request.query)
    
    agent_fn = AGENT_ROUTES.get(intent, run_parcel_analysis)
    
    # Collect all chunks
    answer = ""
    thinking = []
    citations = []
    parcel_id = None
    artifact = None
    
    async for chunk in agent_fn(request.query, entities, request.context):
        if chunk["type"] == "content":
            answer += chunk["value"]
        elif chunk["type"] == "thinking":
            thinking.append(chunk["value"])
        elif chunk["type"] == "citation":
            citations.append(Citation(**chunk["value"]))
        elif chunk["type"] == "parcel":
            parcel_id = chunk["value"]
        elif chunk["type"] == "artifact":
            artifact = chunk["value"]
    
    return QueryResponse(
        answer=answer,
        intent=intent,
        entities=entities,
        thinking=thinking,
        citations=citations,
        parcel_id=parcel_id,
        artifact=artifact,
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
