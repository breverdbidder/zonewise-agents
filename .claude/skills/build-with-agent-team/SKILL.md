---
name: build-with-agent-team
description: Build ZoneWise/BidDeed.AI components using Claude Code Agent Teams with tmux split panes. Optimized for county scraper builds, multi-county expansion, and agentic pipeline development. Takes a plan document path and optional team size.
argument-hint: [plan-path] [num-agents]
disable-model-invocation: true
---

# ZoneWise Agent Teams — Contract-First Build Orchestrator

You are coordinating a build using Claude Code Agent Teams, optimized for the ZoneWise/BidDeed.AI agentic ecosystem. Read the plan document, determine the right team structure, spawn teammates using contract-first spawning, and orchestrate the build.

## Context: ZoneWise Architecture

ZoneWise is a multi-county foreclosure auction intelligence platform. Key systems:
- **Scrapers**: AgentQL-based scrapers per county (zonewise-modal repo)
- **API**: FastAPI backend on Render (zonewise-agents repo)
- **UI**: React split-screen chat + artifacts interface (zonewise-web/zonewise-desktop repos)
- **Database**: Supabase with `multi_county_auctions` as primary table
- **Orchestration**: LangGraph multi-agent workflows via GitHub Actions

**Tech Stack Reference:**
| Layer | Technology |
|-------|-----------|
| Scraping | AgentQL + Playwright + Python |
| Backend | FastAPI + LangGraph + LiteLLM |
| Frontend | React + TypeScript + Tailwind |
| Database | Supabase (PostgreSQL) |
| Deployment | Render (API), Cloudflare Pages (web), Modal (scrapers) |
| CI/CD | GitHub Actions |

## Arguments

- **Plan path**: `$ARGUMENTS[0]` - Path to a markdown file describing what to build
- **Team size**: `$ARGUMENTS[1]` - Number of agents (optional, auto-determined if omitted)

## Step 1: Read the Plan

Read the plan document at `$ARGUMENTS[0]`. Understand:
- What are we building? (new county scraper, API feature, UI component, pipeline stage)
- What are the major components/layers?
- What are the dependencies between components?
- Which ZoneWise repos are involved?
- What Supabase tables are affected?

**CRITICAL**: Check if a TODO.md exists in the target repo. If so, load it and align work with current unchecked tasks.

## Step 2: Determine Team Structure

If team size is specified (`$ARGUMENTS[1]`), use that number of agents.

If NOT specified, use these ZoneWise-specific guidelines:

**County Scraper Build (most common):**
- 3 agents: Schema Agent + Scraper Agent + Test/Integration Agent
- This is the default for `/build-county-scraper` commands

**Multi-County Expansion:**
- 4 agents: Schema Agent + Scraper Agent + API Agent + Test Agent
- Use when building scrapers that also need new API endpoints

**Full Feature Build:**
- 4-5 agents: Schema + Backend + Frontend + Test + (DevOps)
- Use for new pipeline stages or major features

**Pipeline Stage Build:**
- 3 agents: LangGraph Agent + Data Agent + Validation Agent
- Use for new analysis/processing stages

For each agent, define:
1. **Name**: Domain-specific (e.g., "schema", "scraper", "api", "ui", "test")
2. **Ownership**: Exact files/directories they own
3. **Does NOT touch**: Off-limits areas
4. **Repo**: Which ZoneWise repo they work in
5. **Key responsibilities**: What they're building
6. **Validation checklist**: What they must verify before reporting done

## Step 3: Set Up Agent Team

Enable tmux split panes:

```
teammateMode: "tmux"
```

Before spawning, enter **Delegate Mode** (Shift+Tab). You coordinate — you do NOT implement code yourself.

## Step 4: Contract-First Spawning

**CRITICAL**: Agents that build in parallel WILL diverge on interfaces unless they agree on contracts FIRST. The lead enforces a **contract-first, build-second** protocol.

### ZoneWise Contract Chains

**County Scraper Build:**
```
Schema Agent → publishes Supabase table schema + column types → Lead verifies → Scraper Agent
Scraper Agent → publishes output data format + field mapping → Lead verifies → Test Agent
```

**Full Stack Feature:**
```
Schema Agent → publishes Supabase migrations + RLS policies → Lead verifies
Scraper/Data Agent → publishes data contracts (JSON shapes) → Lead verifies → API Agent
API Agent → publishes FastAPI endpoint specs (URLs, request/response) → Lead verifies → UI Agent
```

**Pipeline Stage:**
```
LangGraph Agent → publishes state schema + node interfaces → Lead verifies
Data Agent → publishes input/output contracts per node → Lead verifies → Validation Agent
```

### Spawn Order

1. **Spawn upstream agents first** (always Schema Agent first)
2. Each upstream agent's FIRST task: define and send their contract via SendMessage
3. **Lead receives and verifies the contract** — check for ambiguities, missing fields
4. **Lead forwards verified contract to downstream agents** — do NOT rely on agent-to-agent messaging
5. **Only then spawn or unblock downstream agents** with the contract in their prompt

### Lead as Active Contract Relay

**Do NOT tell agents "share your contract with the other agent."** This fails because:
- Upstream agent may finish and share too late
- Downstream agent may build with wrong assumptions
- Messages between agents may be missed

Instead, the lead must:
1. Receive the contract from the producing agent
2. **Verify it** — check for: exact column names/types, exact JSON field names, exact API URLs, Supabase RLS implications
3. **Forward it to consuming agents** with: "Build to this contract exactly. Do not deviate."

### ZoneWise-Specific Contract Verification

**For Supabase schemas, verify:**
- Table name matches `multi_county_auctions` conventions or new table naming
- Column types are correct (TEXT, NUMERIC, TIMESTAMPTZ, JSONB, etc.)
- RLS policies are defined (who can read/write)
- Foreign keys reference correct parent tables
- Indexes exist for county_id, auction_date, case_number lookups

**For Scraper outputs, verify:**
- Field names match Supabase column names EXACTLY
- Date formats are ISO 8601
- Numeric fields are actual numbers (not strings)
- County identifier is consistent (FIPS code or standardized name)
- All required fields are present (case_number, property_address, auction_date, judgment_amount, plaintiff)

**For API endpoints, verify:**
- URL patterns follow `/api/v1/{resource}` convention
- Request/response JSON shapes are explicit
- Error responses include status codes and body format
- Pagination follows cursor-based pattern
- Authentication uses Supabase JWT

**For LangGraph nodes, verify:**
- State schema includes all required fields
- Node input/output types are explicit
- Conditional edges have clear routing logic
- Checkpointing strategy is defined

### Cross-Cutting Concerns for ZoneWise

| Concern | Default Owner | Detail |
|---------|--------------|--------|
| County ID format | Schema Agent | FIPS code (12009 for Brevard) vs name string — must be consistent everywhere |
| Date handling | Schema Agent | All dates as ISO 8601 TIMESTAMPTZ in Supabase, parsed correctly by scrapers |
| Anti-detection | Scraper Agent | Rate limiting, user-agent rotation, proxy support — scraper's responsibility |
| Error logging | All Agents | Errors logged to Supabase `scraper_logs` table with county_id, timestamp, error_type |
| GitHub Secrets | Lead Agent | API keys, credentials stored in GitHub Secrets, never hardcoded |
| Supabase RLS | Schema Agent | Row-level security policies for multi-tenant access |

### Spawn Prompt Structure

```
You are the [ROLE] agent for this ZoneWise build.

## Your Ownership
- You own: [directories/files]
- You work in repo: [repo-name]
- Do NOT touch: [other agents' files]

## What You're Building
[Relevant section from plan]

## ZoneWise Standards
- Database: Supabase (mocerqjnksmhcjzxrewo.supabase.co)
- All Python code: type hints, docstrings, async where possible
- All scraper code: AgentQL patterns with anti-detection
- All API code: FastAPI with Pydantic models
- Deployment: GitHub Actions for CI/CD
- Secrets: NEVER hardcode — use environment variables or GitHub Secrets

## Mandatory Communication (REQUIRED)

### Before You Build
- Your FIRST deliverable is your [schema/data contract/API spec/test plan]
- Send it to the lead via SendMessage BEFORE writing implementation code
- Include: exact field names, types, formats, constraints
- Wait for the lead to confirm before proceeding

### The Contract You Must Conform To
[Include the upstream agent's verified contract here]

### Cross-Cutting Concerns You Own
[List from the table above]

## Before Reporting Done
Run these validations and fix any failures:
1. [specific validation command]
2. [specific validation command]
3. [specific check]

Do NOT report done until all validations pass.
```

## Step 5: Facilitate Collaboration

### Phase 1: Contracts (Sequential, Lead-Orchestrated)

Spawn agents in dependency order. Each agent's first task is publishing their contract:

1. **Schema Agent** → publishes Supabase migration SQL + column definitions → lead verifies → forwards to Scraper/API agents
2. **Scraper Agent** → receives schema contract → publishes output data mapping + field transformations → lead verifies → forwards to Test agent
3. **API Agent** (if applicable) → receives schema + scraper contracts → publishes endpoint specs → lead verifies → forwards to UI agent
4. **Test Agent** → receives all contracts → builds validation suite

**Lead verification checklist:**
- Are column names exact and consistent across agents?
- Are data types compatible (scraper output types → Supabase column types)?
- Are all required fields accounted for?
- Is the county_id format consistent?
- Are date formats standardized?

### Phase 2: Implementation (Parallel where safe)

Once contracts are verified, agents build in parallel. They MUST:
- Send a message to the lead when they discover something that affects the contract
- Ask before deviating from the agreed contract
- Flag cross-cutting concerns that weren't anticipated

### Phase 3: Pre-Completion Contract Verification

Before any agent reports "done", the lead runs a **contract diff**:
- "Schema Agent: show me the final CREATE TABLE statement"
- "Scraper Agent: show me a sample output JSON for one auction record"
- "API Agent: show me the exact curl commands for each endpoint"
- Lead compares and flags mismatches BEFORE integration testing

### Phase 4: Integration Testing

- Run scraper against test data → verify output matches schema
- Insert scraper output into Supabase → verify no constraint violations
- Call API endpoints → verify response shapes match contracts
- Run full pipeline end-to-end if applicable

## Collaboration Anti-Patterns

**Anti-pattern 1: Fully parallel spawn**
```
Lead spawns all 3 agents simultaneously
Scraper builds with wrong column names
Test agent builds assertions against wrong schema ❌
```

**Anti-pattern 2: Hardcoded credentials**
```
Scraper agent puts Supabase URL directly in code
Gets committed to GitHub → security violation ❌
```

**Anti-pattern 3: Inconsistent county identifiers**
```
Schema uses FIPS code (12009), scraper uses "Brevard", API uses "brevard-county"
Integration fails on joins and lookups ❌
```

**Good pattern: Contract-first with lead relay**
```
Schema publishes: county_id TEXT (FIPS format, e.g., "12009")
Lead verifies → forwards to all agents
Everyone uses "12009" consistently ✅
```

## Step 6: Validation

### Agent-Level Validation

**Schema Agent validates:**
```bash
# Migration applies cleanly
psql $SUPABASE_URL -f migration.sql
# RLS policies work
psql $SUPABASE_URL -c "SELECT * FROM multi_county_auctions LIMIT 1;"
# Indexes exist
psql $SUPABASE_URL -c "\di"
```

**Scraper Agent validates:**
```bash
# Scraper runs without errors
python -m pytest tests/test_scraper.py -v
# Output matches schema contract
python -c "
from scraper import scrape_county
data = scrape_county('test')
assert all(k in data[0] for k in ['case_number', 'property_address', 'auction_date', 'judgment_amount'])
print('✓ Output matches contract')
"
# Anti-detection measures work
python -c "
from scraper import get_session
s = get_session()
assert s.headers.get('User-Agent') != 'python-requests/2.31.0'
print('✓ Anti-detection active')
"
```

**API Agent validates:**
```bash
# Server starts
uvicorn main:app --port 8000 &
sleep 2
# Health check
curl -s http://localhost:8000/health | grep -q "ok" && echo "✓ Server running"
# Endpoints respond
curl -s http://localhost:8000/api/v1/auctions?county_id=12009 | python3 -c "
import sys, json
data = json.load(sys.stdin)
assert 'data' in data
print('✓ Endpoint responds correctly')
"
```

**Test Agent validates:**
```bash
# All tests pass
python -m pytest tests/ -v --tb=short
# Coverage meets minimum
python -m pytest tests/ --cov=src --cov-report=term --cov-fail-under=80
```

### Lead Validation (End-to-End)

After ALL agents return control:

1. **Can the scraper fetch data?**
   - Run scraper against target county
   - Verify output is valid JSON with all required fields

2. **Can data be inserted into Supabase?**
   - Insert scraper output via Supabase client
   - Verify no constraint violations
   - Verify data appears in table

3. **Does the API serve the data?**
   - Query API for the inserted data
   - Verify response matches contract

4. **Does the GitHub Action work?**
   - Verify workflow YAML is valid
   - Dry-run if possible

If validation fails:
- Identify which agent's domain contains the bug
- Re-spawn that agent with the specific issue
- Re-run validation after fix

## Step 7: Deployment

After validation passes:

1. **Commit to correct repos** with descriptive messages
2. **Push to GitHub** — each agent pushes to their respective repo
3. **Verify GitHub Actions** trigger correctly
4. **Update TODO.md** — mark completed tasks as `[x]`
5. **Log to Supabase** — insert completion record to `scraper_logs` or `activities` table

## Definition of Done

The build is complete when:
1. All agents report their work is done
2. Each agent has passed their validation checklist
3. Integration points have been tested end-to-end
4. Contract diff shows zero mismatches
5. Code is committed and pushed to correct repos
6. GitHub Actions are valid and trigger correctly
7. TODO.md is updated
8. **Lead agent has run end-to-end validation**

---

## Execute

Now read the plan at `$ARGUMENTS[0]` and begin:

1. Read and understand the plan
2. Check for TODO.md in target repo(s) — align with current tasks
3. Determine team size (use `$ARGUMENTS[1]` if provided, otherwise decide)
4. Define agent roles, ownership, cross-cutting concerns, and validation requirements
5. **Map the contract chain** — which agent produces interfaces that others consume?
6. Enter Delegate Mode
7. **Spawn upstream agents first** — their first task is publishing their contract
8. **Receive and verify each contract** — check field names, types, formats
9. **Forward verified contracts to downstream agents** — include in their spawn prompt
10. Spawn downstream agents with verified contracts + validation checklist
11. **Run contract diff before integration** — compare outputs vs expectations
12. When all agents return, run **end-to-end validation yourself**
13. If validation fails, re-spawn the relevant agent with the specific issue
14. Commit, push, update TODO.md, log completion
15. Confirm the build meets the plan's requirements
