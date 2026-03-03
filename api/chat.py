"""
ZoneWise.AI — FastAPI Chat Endpoint
Hook Phase: ACTION — the conversational interface

SLAs:
  POST /chat    → county_scan <3s, market_question <5s
  POST /bid     → <10s (full 10-stage pipeline)
  GET /pipeline → <2s
  GET /digest/preview → <2s

See TODO.md TASK-013 for implementation requirements.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

app = FastAPI(title="ZoneWise.AI Chat API", version="1.0.0")

class ChatRequest(BaseModel):
    user_id: str
    query: str
    county: Optional[str] = None
    sale_type: Optional[Literal["foreclosure", "tax_deed", "both"]] = None

class BidRequest(BaseModel):
    user_id: str
    sale_type: Literal["foreclosure", "tax_deed"]
    identifier: str  # case_number for foreclosure, cert_number for tax deed
    county: str

@app.post("/chat")
async def chat(req: ChatRequest):
    """NLP chatbot — classify query and route to appropriate agent.
    
    Response time SLA: <3s for COUNTY_SCAN, <5s for others.
    Determine sale_type from query context if not provided.
    """
    # TODO TASK-013: implement with action_agent.classify_query()
    raise HTTPException(status_code=501, detail="Not implemented — see TODO.md TASK-013")

@app.post("/bid")
async def bid_decision(req: BidRequest):
    """Full BID decision pipeline.
    
    Runs the appropriate 10-stage pipeline based on sale_type.
    NEVER mix foreclosure and tax deed pipelines.
    Response time SLA: <10s
    """
    # TODO TASK-013: route to action_agent.foreclosure_bid_pipeline() or tax_deed_bid_pipeline()
    raise HTTPException(status_code=501, detail="Not implemented — see TODO.md TASK-013")

@app.get("/pipeline")
async def get_pipeline(user_id: str, sale_type: Optional[str] = None):
    """Get user's deal pipeline, optionally filtered by sale type."""
    # TODO TASK-013: query deal_pipeline table
    raise HTTPException(status_code=501, detail="Not implemented — see TODO.md TASK-013")

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
