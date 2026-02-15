# 7-Section Agent Prompt Template

Based on Claude Delegator architecture for stateless, context-rich agent delegation.

## Structure

Every agent prompt MUST include all 7 sections in order:

### 1. TASK
**What** the agent needs to accomplish in 1-2 sentences.

Example:
```
TASK: Extract foreclosure auction data from {county_name} clerk website using AgentQL semantic scraping.
```

### 2. EXPECTED OUTCOME
**Success criteria** - what qualifies as a successful completion.

Example:
```
EXPECTED OUTCOME: Structured JSON containing case_number, plaintiff, defendant, judgment_amount, sale_date for all active foreclosure auctions. Data must pass validation (no missing required fields, dates in ISO format, amounts as floats).
```

### 3. CONTEXT
**Background information** needed to perform the task. Include:
- County/jurisdiction details
- System type (clerk platform, API version)
- Historical data (last successful scrape, known issues)
- Rate limits and timing constraints

Example:
```
CONTEXT:
- County: Brevard County, Florida
- Clerk System: Benchmark (Odyssey File & Serve)
- Population: 606,612 (6th largest FL county)
- Last successful scrape: 2026-02-14 11:23:45 EST
- Known issues: Cloudflare protection, requires JS rendering
- Rate limit: 10 requests/minute
- Business hours: 9AM-5PM EST (avoid outside this window)
```

### 4. CONSTRAINTS
**Hard limits** that cannot be violated.

Example:
```
CONSTRAINTS:
- Timeout: 30 seconds per page request
- Maximum retries: 3 attempts with exponential backoff
- Memory limit: 512MB (Modal container limit)
- Must handle pagination (max 100 records per page)
- No PII storage in logs (mask SSN, addresses)
- Compliance: Fair Housing Act (no demographic discrimination)
```

### 5. MUST DO
**Required actions** - non-negotiable steps.

Example:
```
MUST DO:
- Detect and report anti-bot measures (captcha, Cloudflare)
- Extract ALL required fields (case_number, plaintiff, defendant, judgment, sale_date)
- Validate data types before returning (dates as ISO strings, amounts as floats)
- Log scraping metrics (duration, record_count, errors)
- Store raw HTML in Supabase for audit trail
- Update last_scraped_at timestamp in multi_county_auctions table
```

### 6. MUST NOT DO
**Forbidden actions** - will cause failure.

Example:
```
MUST NOT DO:
- Retry failed requests more than 3 times
- Scrape outside business hours (9AM-5PM EST)
- Store personally identifiable information in logs
- Make synchronous requests (must use async/await)
- Ignore Cloudflare challenges (must handle properly)
- Return partial data without error flag
- Proceed if required fields are missing
```

### 7. OUTPUT FORMAT
**Exact structure** of the response.

Example:
```
OUTPUT FORMAT:
{
  "success": boolean,
  "county": string,
  "scraped_at": ISO_datetime_string,
  "data": [
    {
      "case_number": string,
      "plaintiff": string,
      "defendant": string,
      "judgment_amount": float,
      "sale_date": ISO_date_string,
      "property_address": string,
      "parcel_id": string
    }
  ],
  "metadata": {
    "total_records": int,
    "scrape_duration_seconds": float,
    "errors": [string],
    "cloudflare_detected": boolean,
    "pagination_pages": int
  }
}
```

## Usage Guidelines

### For Agent Developers
1. Copy this template when creating new agent prompts
2. Fill in all 7 sections - NEVER skip a section
3. Be specific - avoid generic language
4. Include real examples from production
5. Update as system evolves

### For LangGraph Integration
```python
from pathlib import Path

def load_agent_prompt(agent_name: str, **kwargs) -> str:
    """Load and format agent prompt with runtime values."""
    prompt_path = Path(__file__).parent / "prompts" / f"{agent_name}.md"
    template = prompt_path.read_text()
    
    # Replace placeholders with runtime values
    return template.format(**kwargs)

# Usage in node
prompt = load_agent_prompt(
    "scraper_agent",
    county_name="Brevard",
    last_scraped="2026-02-14 11:23:45",
    rate_limit=10
)
```

### For MCP Server Integration
```python
# County Router MCP server receives 7-section prompt
def handle_scrape_request(county: str, context: dict) -> dict:
    prompt = build_prompt_from_template(
        agent="scraper",
        county=county,
        context=context
    )
    
    # Call DeepSeek (ULTRA_CHEAP tier) with full prompt
    response = deepseek_client.complete(prompt)
    
    # Parse and validate output against OUTPUT FORMAT
    return validate_and_return(response)
```

## Template Versioning

**Version:** 1.0.0  
**Based on:** Claude Delegator (jarrodwatts/claude-delegator)  
**Adapted for:** ZoneWise.AI multi-county foreclosure scraping  
**Last updated:** 2026-02-15

## Related Files
- `scraper_agent.md` - AgentQL scraping specialist
- `analysis_agent.md` - Property scoring specialist
- `report_agent.md` - PDF generation specialist
- `qa_agent.md` - Data validation specialist
