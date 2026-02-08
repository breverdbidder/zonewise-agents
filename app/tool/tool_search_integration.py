"""
BidDeed.AI / ZoneWise - Tool Search Integration for LangGraph
==============================================================
Integrates Anthropic's Tool Search Tool (Beta) with multi-agent
LangGraph orchestration for dynamic tool discovery at 67-county scale.

Beta Header: advanced-tool-use-2025-11-20
Models: Sonnet 4.5+, Opus 4.6 (no Haiku, no DeepSeek)
Max Tools: 10,000 | Returns: 3-5 tools per search

Usage:
    from tool_search_integration import ToolSearchOrchestrator
    
    orchestrator = ToolSearchOrchestrator(variant="bm25")
    response = orchestrator.execute(
        message="Analyze foreclosure auctions in Duval County",
        counties=["duval"]
    )
"""

import anthropic
from typing import List, Dict, Optional, Literal
from dataclasses import dataclass, field
import json
import os

# ─────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────

BETA_HEADER = "advanced-tool-use-2025-11-20"
MCP_BETA_HEADER = "mcp-client-2025-11-20"

# Models that support tool search (Sonnet 4.0+, Opus 4.0+)
SUPPORTED_MODELS = {
    "default": "claude-sonnet-4-5-20250929",
    "complex": "claude-opus-4-6",
}

# Florida counties for multi-county scaling
FL_COUNTIES = [
    "alachua", "baker", "bay", "bradford", "brevard", "broward",
    "calhoun", "charlotte", "citrus", "clay", "collier", "columbia",
    "desoto", "dixie", "duval", "escambia", "flagler", "franklin",
    "gadsden", "gilchrist", "glades", "gulf", "hamilton", "hardee",
    "hendry", "hernando", "highlands", "hillsborough", "holmes",
    "indian_river", "jackson", "jefferson", "lafayette", "lake",
    "lee", "leon", "levy", "liberty", "madison", "manatee",
    "marion", "martin", "miami_dade", "monroe", "nassau", "okaloosa",
    "okeechobee", "orange", "osceola", "palm_beach", "pasco",
    "pinellas", "polk", "putnam", "santa_rosa", "sarasota",
    "seminole", "st_johns", "st_lucie", "sumter", "suwannee",
    "taylor", "union", "volusia", "wakulla", "walton", "washington",
]


# ─────────────────────────────────────────────────
# Tool Definitions
# ─────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    """A tool that can be always-loaded or deferred."""
    name: str
    description: str
    input_schema: dict
    defer_loading: bool = False

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        if self.defer_loading:
            d["defer_loading"] = True
        return d


# ── Always-Loaded Tools (top 5, never deferred) ──

ALWAYS_LOADED_TOOLS = [
    ToolDefinition(
        name="supabase_query",
        description="Execute queries against Supabase database tables including multi_county_auctions, historical_auctions, activities, daily_metrics, and insights",
        input_schema={
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name to query"},
                "operation": {"type": "string", "enum": ["select", "insert", "update", "upsert"]},
                "filters": {"type": "object", "description": "Query filters"},
                "data": {"type": "object", "description": "Data for insert/update"},
            },
            "required": ["table", "operation"],
        },
    ),
    ToolDefinition(
        name="github_operations",
        description="Git operations: commit, push, create issues, trigger workflows on breverdbidder repos",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["commit", "push", "create_issue", "trigger_workflow"]},
                "repo": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["action", "repo"],
        },
    ),
    ToolDefinition(
        name="ml_score_predict",
        description="Run XGBoost ML model to predict third-party purchase probability and sale price for foreclosure properties",
        input_schema={
            "type": "object",
            "properties": {
                "case_number": {"type": "string"},
                "features": {"type": "object", "description": "Property features for prediction"},
            },
            "required": ["case_number"],
        },
    ),
    ToolDefinition(
        name="report_generate",
        description="Generate DOCX or PDF foreclosure analysis reports with BidDeed.AI branding, BCPAO photos, and ML predictions",
        input_schema={
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["docx", "pdf"]},
                "properties": {"type": "array", "items": {"type": "object"}},
                "auction_date": {"type": "string"},
            },
            "required": ["format", "properties"],
        },
    ),
    ToolDefinition(
        name="send_notification",
        description="Send alerts, escalations, and status updates via configured channels",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["email", "log", "supabase"]},
                "message": {"type": "string"},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
            },
            "required": ["channel", "message"],
        },
    ),
]


# ── County-Specific Deferred Tools (generated per county) ──

def generate_county_tools(counties: List[str]) -> List[ToolDefinition]:
    """Generate deferred tool definitions for each county."""
    tools = []
    for county in counties:
        county_title = county.replace("_", " ").title()

        # Foreclosure scraper
        tools.append(ToolDefinition(
            name=f"{county}_scrape_foreclosure",
            description=f"Scrape foreclosure auction listings from {county_title} County RealForeclose portal. Returns case numbers, judgment amounts, property addresses, and auction dates for {county_title} County Florida foreclosures.",
            input_schema={
                "type": "object",
                "properties": {
                    "auction_date": {"type": "string", "description": "Target auction date YYYY-MM-DD"},
                    "max_results": {"type": "integer", "default": 50},
                },
                "required": ["auction_date"],
            },
            defer_loading=True,
        ))

        # Tax deed scraper
        tools.append(ToolDefinition(
            name=f"{county}_scrape_taxdeed",
            description=f"Scrape tax deed auction listings from {county_title} County. Returns tax certificate data, assessed values, and delinquent tax amounts for {county_title} County Florida tax deed sales.",
            input_schema={
                "type": "object",
                "properties": {
                    "auction_date": {"type": "string"},
                },
                "required": ["auction_date"],
            },
            defer_loading=True,
        ))

        # Lien priority analyzer
        tools.append(ToolDefinition(
            name=f"{county}_lien_priority",
            description=f"Analyze lien priority and title search for {county_title} County properties. Searches recorded documents for mortgages, HOA liens, tax certificates, and determines lien seniority for {county_title} County Florida.",
            input_schema={
                "type": "object",
                "properties": {
                    "parcel_id": {"type": "string"},
                    "case_number": {"type": "string"},
                },
                "required": ["parcel_id"],
            },
            defer_loading=True,
        ))

        # Tax certificate lookup
        tools.append(ToolDefinition(
            name=f"{county}_tax_certs",
            description=f"Look up outstanding tax certificates for {county_title} County properties. Returns certificate numbers, face amounts, and redemption amounts from {county_title} County Tax Collector.",
            input_schema={
                "type": "object",
                "properties": {
                    "parcel_id": {"type": "string"},
                },
                "required": ["parcel_id"],
            },
            defer_loading=True,
        ))

        # Demographics / Census
        tools.append(ToolDefinition(
            name=f"{county}_census_data",
            description=f"Retrieve Census demographic data for {county_title} County including median income, population, vacancy rates, and housing statistics for neighborhood analysis in {county_title} County Florida.",
            input_schema={
                "type": "object",
                "properties": {
                    "zip_code": {"type": "string"},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["zip_code"],
            },
            defer_loading=True,
        ))

    return tools


# ─────────────────────────────────────────────────
# Tool Search Orchestrator
# ─────────────────────────────────────────────────

class ToolSearchOrchestrator:
    """
    Orchestrates Anthropic API calls with Tool Search for
    dynamic tool discovery across multi-county operations.
    """

    def __init__(
        self,
        variant: Literal["bm25", "regex"] = "bm25",
        counties: Optional[List[str]] = None,
        model: str = SUPPORTED_MODELS["default"],
    ):
        self.client = anthropic.Anthropic()
        self.variant = variant
        self.model = model
        self.counties = counties or FL_COUNTIES
        self.betas = [BETA_HEADER]

        # Build tool catalog
        self.always_loaded = ALWAYS_LOADED_TOOLS
        self.deferred = generate_county_tools(self.counties)

        print(f"[ToolSearch] Initialized: {len(self.always_loaded)} always-loaded, "
              f"{len(self.deferred)} deferred ({len(self.counties)} counties)")

    @property
    def search_tool(self) -> dict:
        """The tool search tool definition (never deferred)."""
        return {
            "type": f"tool_search_tool_{self.variant}_20251119",
            "name": f"tool_search_tool_{self.variant}",
        }

    @property
    def all_tools(self) -> List[dict]:
        """Complete tool list for API request."""
        return [
            self.search_tool,
            *[t.to_dict() for t in self.always_loaded],
            *[t.to_dict() for t in self.deferred],
        ]

    def execute(
        self,
        message: str,
        system: Optional[str] = None,
        messages: Optional[List[dict]] = None,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Execute a request with tool search enabled.
        
        Args:
            message: User message (ignored if messages provided)
            system: Optional system prompt
            messages: Full conversation history (overrides message)
            max_tokens: Max output tokens
            
        Returns:
            Anthropic API response
        """
        if messages is None:
            messages = [{"role": "user", "content": message}]

        kwargs = {
            "model": self.model,
            "betas": self.betas,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": self.all_tools,
        }
        if system:
            kwargs["system"] = system

        response = self.client.beta.messages.create(**kwargs)

        # Log tool search usage
        usage = response.usage
        if hasattr(usage, "server_tool_use"):
            stu = usage.server_tool_use
            if hasattr(stu, "tool_search_requests"):
                print(f"[ToolSearch] Searches: {stu.tool_search_requests}")

        return response

    def execute_with_mcp(
        self,
        message: str,
        mcp_servers: List[dict],
        mcp_toolsets: List[dict],
        max_tokens: int = 4096,
    ) -> dict:
        """
        Execute with both tool search and MCP servers.
        Used for ZoneWise integration.
        """
        tools = [
            self.search_tool,
            *[t.to_dict() for t in self.always_loaded],
            *[t.to_dict() for t in self.deferred],
            *mcp_toolsets,
        ]

        return self.client.beta.messages.create(
            model=self.model,
            betas=[BETA_HEADER, MCP_BETA_HEADER],
            max_tokens=max_tokens,
            mcp_servers=mcp_servers,
            tools=tools,
            messages=[{"role": "user", "content": message}],
        )

    def add_cache_breakpoint(self, messages: List[dict]) -> List[dict]:
        """Add prompt caching to last user message for multi-turn efficiency."""
        if messages and messages[-1]["role"] == "user":
            messages[-1]["cache_control"] = {"type": "ephemeral"}
        return messages


# ─────────────────────────────────────────────────
# LangGraph Node Functions
# ─────────────────────────────────────────────────

def tool_search_scraper_node(state: dict) -> dict:
    """
    LangGraph node: Scraper agent with tool search.
    Discovers county-specific scrapers dynamically.
    """
    orchestrator = ToolSearchOrchestrator(
        variant="bm25",
        counties=state.get("target_counties", ["brevard"]),
    )

    system = (
        "You are a foreclosure auction data scraper agent. "
        "Search for and use county-specific scraping tools to collect "
        "auction data. Available tool categories: foreclosure scrapers, "
        "tax deed scrapers, lien analyzers, tax certificate lookups, "
        "and census data tools — organized by Florida county."
    )

    response = orchestrator.execute(
        message=state["task_description"],
        system=system,
    )

    return {
        **state,
        "scraper_response": response.content,
        "tools_discovered": _extract_discovered_tools(response),
    }


def tool_search_analysis_node(state: dict) -> dict:
    """
    LangGraph node: Analysis agent with tool search.
    Discovers lien priority and tax cert tools per county.
    """
    orchestrator = ToolSearchOrchestrator(
        variant="bm25",
        counties=state.get("target_counties", ["brevard"]),
    )

    system = (
        "You are a foreclosure property analysis agent. "
        "Search for county-specific lien priority analyzers and "
        "tax certificate lookup tools. Determine bid/review/skip "
        "recommendations based on lien analysis results."
    )

    response = orchestrator.execute(
        message=f"Analyze properties: {json.dumps(state.get('properties', []))}",
        system=system,
    )

    return {
        **state,
        "analysis_response": response.content,
    }


def _extract_discovered_tools(response) -> List[str]:
    """Extract names of tools discovered via tool search from response."""
    discovered = []
    for block in response.content:
        if hasattr(block, "type") and block.type == "tool_search_tool_result":
            for ref in block.content.tool_references:
                discovered.append(ref.tool_name)
    return discovered


# ─────────────────────────────────────────────────
# Smart Router Integration
# ─────────────────────────────────────────────────

def route_with_tool_search(request: dict) -> dict:
    """
    Smart Router decision: should this request use tool search?
    
    Rules:
    - >10 potential tools → enable tool search
    - Multi-county request → Opus 4.6 + tool search
    - Single county, simple query → Sonnet 4.5 + tool search
    - No county tools needed → standard routing (DeepSeek ok)
    """
    county_count = len(request.get("counties", []))
    needs_county_tools = request.get("needs_county_tools", False)

    if not needs_county_tools:
        # No tool search needed, standard Smart Router applies
        return {"use_tool_search": False, "model": None}

    if county_count > 5:
        return {
            "use_tool_search": True,
            "model": SUPPORTED_MODELS["complex"],  # Opus 4.6
            "variant": "bm25",
        }

    return {
        "use_tool_search": True,
        "model": SUPPORTED_MODELS["default"],  # Sonnet 4.5
        "variant": "bm25",
    }


# ─────────────────────────────────────────────────
# Quick Test
# ─────────────────────────────────────────────────

if __name__ == "__main__":
    # Test: Initialize with 3 counties (demo)
    orchestrator = ToolSearchOrchestrator(
        variant="bm25",
        counties=["brevard", "duval", "orange"],
    )
    print(f"Total tools: {len(orchestrator.all_tools)}")
    print(f"  Search tool: 1")
    print(f"  Always loaded: {len(orchestrator.always_loaded)}")
    print(f"  Deferred: {len(orchestrator.deferred)}")
    print(f"\nAt 67-county scale:")
    print(f"  Deferred: {67 * 5} tools")
    print(f"  Token savings: ~{67 * 5 * 200 // 1000}K tokens/request")
