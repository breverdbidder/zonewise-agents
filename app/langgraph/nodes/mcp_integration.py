"""
LangGraph Integration for County Router MCP

Demonstrates how to integrate Claude Delegator-style MCP calls
into existing ZoneWise LangGraph workflow.
"""

import sys
sys.path.append('..')

from app.mcp.county_router_mcp import CountyRouterMCP
from app.langgraph.state import WorkflowState
from typing import Dict


# Initialize router (singleton pattern)
router = CountyRouterMCP()


async def scraper_node_mcp(state: WorkflowState) -> WorkflowState:
    """
    Scraper node using County Router MCP.
    
    Replaces: app/langgraph/nodes/scraper_node.py
    Mode: Advisory (read-only)
    """
    county = state["county_name"]
    
    # Build context from state
    context = {
        "clerk_system": state.get("clerk_system_type", "Unknown"),
        "population": state.get("county_population"),
        "rate_limit": state.get("rate_limit_rpm", 10),
        "timeout": state.get("timeout_seconds", 30),
        "last_scraped": state.get("last_scraped_at"),
        "last_count": state.get("last_record_count", 0),
        "known_issues": state.get("known_issues", "None")
    }
    
    # Call MCP scraper (DeepSeek V3.2)
    result = await router.scrape_county(
        county=county,
        context=context,
        mode="advisory"  # Read-only
    )
    
    # Update state
    state["scraping_results"] = result
    state["mcp_metrics"] = {
        "scraper_tokens": result.get("tokens_used", 0),
        "scraper_cost": result.get("cost_usd", 0),
        "scraper_duration": result.get("duration_seconds", 0)
    }
    
    # Route to next node
    if result["success"]:
        state["next_node"] = "qa_validation"
    else:
        state["next_node"] = "error_handler"
        state["error"] = result.get("error", "Unknown scraping error")
    
    return state


async def analysis_node_mcp(state: WorkflowState) -> WorkflowState:
    """
    Analysis node using County Router MCP.
    
    Replaces: app/langgraph/nodes/analysis_node.py
    Mode: Implementation (writes to Supabase)
    """
    county = state["county_name"]
    properties = state["scraping_results"]["data"]["data"]
    
    # Build analysis context
    context = {
        "ml_accuracy": 64.4,
        "model_path": "s3://zonewise-models/xgboost-v1.7.4.pkl",
        "earliest_sale": min(p["sale_date"] for p in properties),
        "latest_sale": max(p["sale_date"] for p in properties),
        "min_judgment": min(p["judgment_amount"] for p in properties),
        "max_judgment": max(p["judgment_amount"] for p in properties),
        "cma_source": "Zillow API",
        "market_source": "Census API"
    }
    
    # Call MCP analyzer (DeepSeek V3.2)
    result = await router.analyze_properties(
        county=county,
        properties=properties,
        context=context,
        mode="implementation"  # Writes scores to DB
    )
    
    # Update state
    state["analysis_results"] = result
    state["mcp_metrics"]["analyzer_tokens"] = result.get("tokens_used", 0)
    state["mcp_metrics"]["analyzer_cost"] = result.get("cost_usd", 0)
    
    # Extract BUY recommendations
    if result["success"]:
        state["buy_recommendations"] = [
            p for p in result["data"]["results"]
            if p["final_recommendation"]["decision"] == "BUY"
        ]
        state["next_node"] = "report_generation"
    else:
        state["next_node"] = "error_handler"
        state["error"] = result.get("error", "Unknown analysis error")
    
    return state


async def report_node_mcp(state: WorkflowState) -> WorkflowState:
    """
    Report generation node using County Router MCP.
    
    Replaces: app/langgraph/nodes/report_node.py
    Mode: Implementation (creates PDFs, uploads to R2)
    """
    county = state["county_name"]
    buy_properties = state["buy_recommendations"]
    
    # Build report context
    context = {
        "report_type": "investor_summary",
        "bcpao_photo_pattern": "https://bcpao.us/photos/{prefix}/{account}011.jpg",
        "comparables": 4,
        "market_indicators": state.get("market_indicators")
    }
    
    # Call MCP reporter (DeepSeek V3.2)
    result = await router.generate_reports(
        county=county,
        buy_properties=buy_properties,
        context=context,
        mode="implementation"  # Creates PDFs
    )
    
    # Update state
    state["report_results"] = result
    state["mcp_metrics"]["reporter_tokens"] = result.get("tokens_used", 0)
    state["mcp_metrics"]["reporter_cost"] = result.get("cost_usd", 0)
    
    # Extract report URLs
    if result["success"]:
        state["report_urls"] = [
            r["cdn_url"] for r in result["data"]["reports"]
            if r["status"] == "success"
        ]
        state["next_node"] = "notification"
    else:
        state["next_node"] = "error_handler"
        state["error"] = result.get("error", "Unknown report error")
    
    return state


async def qa_node_mcp(state: WorkflowState) -> WorkflowState:
    """
    QA validation node using County Router MCP.
    
    Replaces: app/langgraph/nodes/qa_node.py
    Mode: Advisory (read-only validation)
    """
    county = state["county_name"]
    
    # Build QA context
    pipeline_data = {
        "scraper": state["scraping_results"],
        "analysis": state["analysis_results"],
        "reports": state.get("report_results")
    }
    
    context = {
        "total_properties": len(state["scraping_results"]["data"]["data"]),
        "stage": "post_scraping",
        "prev_pass_rate": 95,
        "rate_limit": 10
    }
    
    # Call MCP QA (DeepSeek V3.2)
    result = await router.validate_pipeline(
        county=county,
        pipeline_data=pipeline_data,
        context=context,
        mode="advisory"  # Read-only
    )
    
    # Update state
    state["qa_results"] = result
    state["mcp_metrics"]["qa_tokens"] = result.get("tokens_used", 0)
    state["mcp_metrics"]["qa_cost"] = result.get("cost_usd", 0)
    
    # Calculate total MCP cost
    state["mcp_metrics"]["total_cost"] = sum([
        state["mcp_metrics"].get("scraper_cost", 0),
        state["mcp_metrics"].get("analyzer_cost", 0),
        state["mcp_metrics"].get("reporter_cost", 0),
        state["mcp_metrics"].get("qa_cost", 0)
    ])
    
    # Route based on QA status
    if result["data"]["overall_status"] == "PASS":
        state["next_node"] = "analysis"  # Continue pipeline
    else:
        # Critical failures block pipeline
        if result["data"]["validation_summary"]["critical_failures"] > 0:
            state["next_node"] = "error_handler"
            state["error"] = f"QA critical failures: {result['data']['validation_summary']['critical_failures']}"
        else:
            # Warnings/errors logged but don't block
            state["next_node"] = "analysis"
    
    return state


# Example: Update LangGraph workflow definition
"""
from langgraph.graph import StateGraph, END
from app.langgraph.nodes.mcp_integration import (
    scraper_node_mcp,
    analysis_node_mcp,
    report_node_mcp,
    qa_node_mcp
)

# Create workflow
workflow = StateGraph(WorkflowState)

# Add MCP-powered nodes
workflow.add_node("scraper", scraper_node_mcp)
workflow.add_node("qa_validation", qa_node_mcp)
workflow.add_node("analysis", analysis_node_mcp)
workflow.add_node("report_generation", report_node_mcp)
workflow.add_node("notification", notification_node)  # Existing node
workflow.add_node("error_handler", error_handler_node)  # Existing node

# Define edges
workflow.set_entry_point("scraper")
workflow.add_edge("scraper", "qa_validation")
workflow.add_edge("qa_validation", "analysis")
workflow.add_edge("analysis", "report_generation")
workflow.add_edge("report_generation", "notification")
workflow.add_edge("notification", END)

# Error handling
workflow.add_edge("error_handler", END)

# Compile
app = workflow.compile()
"""


if __name__ == "__main__":
    # Test integration
    import asyncio
    
    async def test():
        router = CountyRouterMCP()
        
        # Test scraper
        result = await router.scrape_county(
            county="Brevard",
            context={"rate_limit": 10, "timeout": 30},
            mode="advisory"
        )
        
        print(f"Scraper success: {result['success']}")
        print(f"Cost: ${result['cost_usd']:.4f}")
        print(f"Tokens: {result['tokens_used']}")
    
    asyncio.run(test())
