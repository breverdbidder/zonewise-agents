# Claude Code Task Brief — DiscoverWise Phase 2
# BidDeed API Implementation + ZoneWise Consumer

**Status:** READY FOR CLAUDE CODE
**Created:** 2026-02-26 by Claude AI Architect
**Depends on:** Architecture deployed by AI Architect (this session)
**Duration estimate:** 7-hour Claude Code session

---

## What the AI Architect Deployed (DO NOT REDO)

✅ `sql/migrations/001_capability_registry.sql` — capability registry, data sources, RLS
✅ `src/api/main.py` — BidDeed FastAPI skeleton (contracts defined, logic stubbed)
✅ `src/api/requirements.txt` — FastAPI dependencies
✅ `render.yaml` — second Render service for biddeed-api
✅ `.github/workflows/sync-claude-skills.yml` — auto-sync .claude/ across repos
✅ `.claude/commands/prime.md` — updated cross-repo /prime command
✅ `scripts/install-biddeed-sources.sh` — CraftAgents source installer
✅ `.agents/plans/discoverwise-prd.md` — full PRD

---

## Your Tasks (Claude Code)

### TASK 1: Run Database Migration
```bash
psql "$DATABASE_URL" -f sql/migrations/001_capability_registry.sql
# Verify:
psql "$DATABASE_URL" -c "SELECT slug, name, status FROM capabilities ORDER BY sort_order"
```

Expected output: 5 rows (discoverwise, lienwise, cmawise, titlewise, zoneanalyze)

---

### TASK 2: Implement BidDeed API Endpoints

**File:** `src/api/main.py` (skeleton exists — implement the TODOs)

Start with `src/api/db.py` — create the Supabase client helper:

```python
# src/api/db.py
from supabase import create_client, Client
import os

def get_supabase() -> Client:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    )
```

Then implement each endpoint. Reference these existing files for patterns:
- `src/scrapers/bcpao_scraper.py` — BCPAO photo URL format
- `src/pipeline/` — existing Supabase query patterns
- `.claude/rules/api.md` — pipeline stage rules
- `.claude/rules/python-style.py` — code style

**Endpoint implementation order (dependency order):**

1. `/api/v1/health` — query insights + multi_county_auctions (easiest, do first)
2. `/api/v1/auctions/county/{county}` — map overlay (high value, relatively simple)
3. `/api/v1/auctions` — list with filters (most used by ZoneWise)
4. `/api/v1/auctions/{case_number}` — full detail (HOA warning logic here)
5. `/api/v1/auctions/{case_number}/report` — Supabase storage signed URL
6. `/api/v1/pipeline/trigger` — GitHub Actions dispatch

**Critical business logic for endpoint 4:**
```python
# HOA plaintiff detection — NEVER skip this
if "HOA" in plaintiff.upper() or "ASSOCIATION" in plaintiff.upper():
    hoa_plaintiff = True
    # Add to response AND log to insights as WARNING
```

**Validation after each endpoint:**
```bash
# Start API locally
uvicorn src.api.main:app --host 0.0.0.0 --port 8001 &

# Test health
curl http://localhost:8001/api/v1/health

# Test auctions (replace with real BIDDEED_API_KEY)
curl -H "Authorization: Bearer $BIDDEED_API_KEY" \
  "http://localhost:8001/api/v1/auctions?county=Brevard&page=1&page_size=5"
```

---

### TASK 3: Add BIDDEED_API_KEY to GitHub Secrets

```bash
# Add secret to brevard-bidder-scraper repo
curl -X PUT \
  -H "Authorization: token $GITHUB_PAT" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/breverdbidder/brevard-bidder-scraper/actions/secrets/BIDDEED_API_KEY" \
  -d '{"encrypted_value":"<encrypt with repo public key>","key_id":"<key_id>"}'
```

Use the GitHub Secrets encryption helper or set via GitHub UI (one-time manual action is acceptable here).

---

### TASK 4: Deploy render.yaml

```bash
# render.yaml is already written
# Commit and push — Render auto-detects render.yaml on push
git add render.yaml src/api/
git commit -m "feat(api): BidDeed external API — 6 endpoints for ZoneWise integration"
git push origin main
```

Monitor: https://dashboard.render.com
Expected: `biddeed-api` service appears as second service.
Health check: `https://biddeed-api.onrender.com/api/v1/health`

---

### TASK 5: ZoneWise Consumer (zonewise-agents repo)

After BidDeed API is live, switch to `breverdbidder/zonewise-agents`:

**File:** `src/clients/biddeed_client.py` (create new)

```python
"""
BidDeed.AI API client for ZoneWise agents.
ZoneWise reads auction data through this client — never directly touches BidDeed DB.
"""
import httpx
import os
from functools import lru_cache

BIDDEED_API_URL = os.environ.get("BIDDEED_API_URL", "https://biddeed-api.onrender.com")
BIDDEED_API_KEY = os.environ["BIDDEED_API_KEY"]

# 15-minute cache (reduces Render cold starts)
@lru_cache(maxsize=256)
def get_county_auctions(county: str) -> list:
    ...
```

**File:** `src/agents/discoverwise_agent.py` (create new)

This is the LangGraph agent that powers DiscoverWise queries in the ZoneWise chatbot:
- Receives: parcel_id + zoning_data (from ZoneWise zone agent)
- Calls: BidDeed client for auction data
- Returns: enriched property object with both zoning + auction context
- Registers: as `discoverwise` capability in capabilities table

---

### TASK 6: Update /prime in All Repos

The updated `prime.md` is staged at `.claude/commands/prime.md`.
The sync-claude-skills.yml action will auto-push to all other repos on next push.
Verify the action runs successfully after TASK 2 commit.

---

## Acceptance Criteria

- [ ] `SELECT slug, status FROM capabilities` returns 5 rows
- [ ] `/api/v1/health` returns 200 with real data
- [ ] `/api/v1/auctions?county=Brevard` returns auction records
- [ ] HOA plaintiff properties have `hoa_plaintiff: true` in response
- [ ] BidDeed API deployed to Render (second service live)
- [ ] ZoneWise can call BidDeed API with BIDDEED_API_KEY
- [ ] sync-claude-skills.yml triggered and pushed to all 7 repos
- [ ] All endpoints log to insights table on error
- [ ] No BidDeed business logic in ZoneWise codebase

## Escalation

If blocked after 3 attempts:
```
BLOCKED: [issue]. Tried: [attempts]. Recommend: [solution]. Approve?
```
Log to insights table with status='BLOCKED' before surfacing to Ariel.
