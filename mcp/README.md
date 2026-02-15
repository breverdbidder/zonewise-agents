# ZoneWise County Router MCP

**Claude Delegator pattern adapted for ZoneWise.AI multi-county foreclosure scraping**

Based on [jarrodwatts/claude-delegator](https://github.com/jarrodwatts/claude-delegator) architecture with cost optimization for 67 Florida counties.

---

## Architecture Overview

```
LangGraph Coordinator
        ↓
County Router MCP Server (this repo)
        ↓
DeepSeek V3.2 (ULTRA_CHEAP tier: $0.28/1M tokens)
        ↓
        ├─→ Scraper Agent (advisory mode - read-only)
        ├─→ Analysis Agent (implementation mode - writes to DB)
        ├─→ Report Agent (implementation mode - generates PDFs)
        └─→ QA Agent (advisory mode - validation)
```

**Key Features:**
- **7-section prompt templates** for all agents (TASK, OUTCOME, CONTEXT, CONSTRAINTS, MUST DO, MUST NOT DO, OUTPUT)
- **Dual-mode execution**: Advisory (read-only) vs Implementation (write)
- **Stateless MCP calls**: Each request includes full context (no session memory)
- **Cost optimization**: DeepSeek V3.2 vs GPT-5.2 Codex (95% cost savings)
- **67 FL counties**: Single router handles all counties dynamically

---

## Installation

### 1. Install Dependencies

```bash
cd zonewise-agents/mcp
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create `.env` file:

```bash
# DeepSeek API
DEEPSEEK_API_KEY=your_deepseek_api_key_here

# Supabase
SUPABASE_URL=https://mocerqjnksmhcjzxrewo.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here

# AgentQL (for scraper)
AGENTQL_API_KEY=FCRgiir6uixy8nIHfCt7wNVaqcbb2kDAOp3rLxyHJnh5dkHhj8G2SQ
```

### 3. Register MCP Server

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "zonewise-county-router": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/zonewise-agents/mcp/county_router_mcp.py"]
    }
  }
}
```

### 4. Test Connection

```bash
# Test MCP server
python3 county_router_mcp.py

# Expected output: MCP server running on stdio
```

---

## Usage

### From LangGraph

```python
from app.mcp.county_router import CountyRouterMCP

router = CountyRouterMCP()

# Scrape county
result = await router.scrape_county(
    county="Brevard",
    context={
        "clerk_system": "Benchmark (Odyssey)",
        "rate_limit": 10,
        "timeout": 30
    },
    mode="advisory"  # Read-only
)

# Analyze properties
analysis = await router.analyze_properties(
    county="Brevard",
    properties=result["data"]["data"],
    context={
        "ml_accuracy": 64.4,
        "model_path": "s3://zonewise-models/xgboost-v1.7.4.pkl"
    },
    mode="implementation"  # Writes to DB
)

# Generate reports
reports = await router.generate_reports(
    county="Brevard",
    buy_properties=[p for p in analysis["data"]["results"] if p["final_recommendation"]["decision"] == "BUY"],
    context={
        "report_type": "investor_summary"
    },
    mode="implementation"  # Creates PDFs
)

# QA validation
qa_results = await router.validate_pipeline(
    county="Brevard",
    pipeline_data={
        "scraper": result,
        "analysis": analysis,
        "reports": reports
    },
    context={
        "total_properties": len(result["data"]["data"])
    },
    mode="advisory"  # Read-only validation
)
```

### From Claude Code (MCP Tools)

```
/mcp zonewise_scrape_county --county Brevard --context '{"rate_limit": 10}'

/mcp zonewise_analyze_properties --county Brevard --properties '[...]'

/mcp zonewise_generate_reports --county Brevard --buy_properties '[...]'

/mcp zonewise_validate_pipeline --county Brevard --pipeline_data '{...}'
```

---

## Prompt Templates

All agent prompts use the **7-section template**:

1. **TASK** - What to accomplish (1-2 sentences)
2. **EXPECTED OUTCOME** - Success criteria
3. **CONTEXT** - Background info (county, system, historical data)
4. **CONSTRAINTS** - Hard limits (timeouts, rate limits, memory)
5. **MUST DO** - Required actions
6. **MUST NOT DO** - Forbidden actions
7. **OUTPUT FORMAT** - Exact JSON structure

Example prompts:
- `app/prompts/template.md` - Base template
- `app/prompts/scraper_agent.md` - AgentQL scraping
- `app/prompts/analysis_agent.md` - HBU/CMA/ML scoring
- `app/prompts/report_agent.md` - PDF generation
- `app/prompts/qa_agent.md` - Data validation

---

## Cost Analysis

### DeepSeek V3.2 Pricing (ULTRA_CHEAP tier)
- Input: $0.28 / 1M tokens
- Output: $0.42 / 1M tokens

### Example: Brevard County (42 properties)

| Agent | Input Tokens | Output Tokens | Cost |
|-------|-------------|---------------|------|
| Scraper | 8,500 | 12,000 | $0.008 |
| Analysis | 15,000 | 35,000 | $0.020 |
| Report | 10,000 | 8,000 | $0.007 |
| QA | 6,000 | 4,000 | $0.004 |
| **Total** | **39,500** | **59,000** | **$0.039** |

**67 counties × daily = $2.61/day = $78.30/month**

vs GPT-5.2 Codex (hypothetical): ~$15/day = $450/month

**Savings: 82%**

---

## LangGraph Integration

Create node in `zonewise-agents/app/langgraph/nodes/`:

```python
# county_router_node.py

from app.mcp.county_router import CountyRouterMCP
from app.langgraph.state import WorkflowState

router = CountyRouterMCP()

async def scraper_node_with_mcp(state: WorkflowState) -> WorkflowState:
    """LangGraph node using County Router MCP."""
    
    county = state["county_name"]
    
    # Call MCP scraper
    result = await router.scrape_county(
        county=county,
        context=state.get("scraping_context", {}),
        mode="advisory"
    )
    
    # Update state
    state["scraping_results"] = result
    state["mcp_cost_usd"] = result.get("cost_usd", 0)
    state["next_node"] = "analysis" if result["success"] else "error_handler"
    
    return state


async def analysis_node_with_mcp(state: WorkflowState) -> WorkflowState:
    """Analysis node using County Router MCP."""
    
    result = await router.analyze_properties(
        county=state["county_name"],
        properties=state["scraping_results"]["data"]["data"],
        context=state.get("analysis_context", {}),
        mode="implementation"  # Writes scores to DB
    )
    
    state["analysis_results"] = result
    state["mcp_cost_usd"] += result.get("cost_usd", 0)
    state["next_node"] = "report_generation"
    
    return state
```

Update `everest_ascent.py` graph:

```python
from langgraph.graph import StateGraph

from app.langgraph.nodes.county_router_node import (
    scraper_node_with_mcp,
    analysis_node_with_mcp
)

# Create graph
workflow = StateGraph(WorkflowState)

# Add MCP-powered nodes
workflow.add_node("scraper", scraper_node_with_mcp)
workflow.add_node("analysis", analysis_node_with_mcp)

# Define edges
workflow.add_edge("scraper", "analysis")
workflow.add_edge("analysis", "report_generation")

# Compile
app = workflow.compile()
```

---

## Deployment to Render

### 1. Update `render.yaml`

```yaml
services:
  - type: worker
    name: zonewise-county-router-mcp
    env: python
    plan: starter  # $7/month
    buildCommand: "pip install -r mcp/requirements.txt"
    startCommand: "python mcp/county_router_mcp.py"
    envVars:
      - key: DEEPSEEK_API_KEY
        sync: false
      - key: SUPABASE_URL
        value: https://mocerqjnksmhcjzxrewo.supabase.co
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: AGENTQL_API_KEY
        sync: false
```

### 2. Deploy

```bash
# From zonewise-agents repo root
git add mcp/
git commit -m "feat: Add County Router MCP server"
git push origin main

# Render auto-deploys from main branch
```

---

## Testing

### Unit Tests

```bash
cd mcp
pytest tests/
```

### Integration Test (Brevard County)

```python
import asyncio
from county_router_mcp import CountyRouterMCP

async def test_brevard():
    router = CountyRouterMCP()
    
    # Test scrape
    result = await router.scrape_county(
        county="Brevard",
        context={"rate_limit": 10, "timeout": 30},
        mode="advisory"
    )
    
    assert result["success"]
    assert result["county"] == "Brevard"
    assert "data" in result
    
    print(f"Scraped {len(result['data']['data'])} properties")
    print(f"Cost: ${result['cost_usd']:.4f}")

asyncio.run(test_brevard())
```

---

## Monitoring

### CloudWatch Metrics (Render)

```python
# In county_router_mcp.py, add logging

import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def call_deepseek(self, prompt, mode, max_tokens):
    start_time = datetime.now()
    result = await ...
    duration = (datetime.now() - start_time).total_seconds()
    
    logger.info(f"DeepSeek call: {mode} | {result['tokens_used']} tokens | ${result['cost_usd']:.4f} | {duration:.2f}s")
    
    return result
```

### Supabase Daily Metrics

```sql
-- Create table for MCP metrics
CREATE TABLE mcp_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    county TEXT NOT NULL,
    agent TEXT NOT NULL,
    mode TEXT NOT NULL,
    tokens_used INTEGER,
    cost_usd NUMERIC(10, 6),
    duration_seconds NUMERIC(8, 2),
    success BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Query daily costs
SELECT 
    county,
    agent,
    SUM(cost_usd) as total_cost,
    COUNT(*) as call_count,
    AVG(duration_seconds) as avg_duration
FROM mcp_metrics
WHERE created_at >= CURRENT_DATE
GROUP BY county, agent
ORDER BY total_cost DESC;
```

---

## Troubleshooting

### MCP Server Won't Start

```bash
# Check Python version (requires 3.11+)
python3 --version

# Verify dependencies installed
pip list | grep mcp

# Test import
python3 -c "from mcp.server import Server; print('OK')"
```

### DeepSeek API Errors

```bash
# Test API key
curl -X POST https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"test"}]}'
```

### Prompt Template Errors

```python
# Validate template variables
from county_router_mcp import CountyRouterMCP

router = CountyRouterMCP()

try:
    prompt = router.load_agent_prompt(
        "scraper",
        county_name="Brevard",
        # Missing variables will raise KeyError
    )
except ValueError as e:
    print(f"Missing variable: {e}")
```

---

## Version History

- **v1.0.0** (2026-02-15) - Initial release
  - 7-section prompt templates
  - 4 agents (Scraper, Analysis, Report, QA)
  - DeepSeek V3.2 integration
  - 67 FL counties support

---

## Related Resources

- [Claude Delegator (Original)](https://github.com/jarrodwatts/claude-delegator)
- [ZoneWise.AI Documentation](https://docs.zonewise.ai)
- [LangGraph Multi-Agent Guide](https://python.langchain.com/docs/langgraph)
- [DeepSeek API Docs](https://platform.deepseek.com/docs)

---

## License

MIT - Same as jarrodwatts/claude-delegator

**Adapted by:** ZoneWise.AI Agentic Team  
**Last Updated:** 2026-02-15
