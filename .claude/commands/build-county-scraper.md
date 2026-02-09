---
name: build-county-scraper
description: Build a complete county foreclosure auction scraper using Agent Teams. Spawns a 3-agent team (Schema + Scraper + Test) with contract-first orchestration. Takes county name and RealForeclose URL.
argument-hint: [county-name] [realforeclose-url]
disable-model-invocation: true
---

# Build County Scraper — Agent Teams Shortcut

Fast-track command for building a new county scraper for the ZoneWise multi-county expansion. This spawns a 3-agent team optimized for the most common ZoneWise build pattern.

## Arguments

- **County name**: `$ARGUMENTS[0]` - Florida county name (e.g., "orange", "duval", "hillsborough")
- **RealForeclose URL**: `$ARGUMENTS[1]` - The county's RealForeclose auction page URL (optional — will be constructed if omitted)

## Auto-Generated Plan

Based on the county name, generate this plan internally:

---

### County Scraper Plan: `$ARGUMENTS[0]` County

**Objective:** Build a production-ready AgentQL scraper for `$ARGUMENTS[0]` County foreclosure auctions that integrates with the ZoneWise multi-county pipeline.

**Target URL:** `$ARGUMENTS[1]` or `https://$ARGUMENTS[0].realforeclose.com`

**Target Repo:** `zonewise-modal`

**Target Table:** `multi_county_auctions` (existing Supabase table)

#### Required Output Fields

Every scraper MUST produce records with these fields matching `multi_county_auctions` schema:

```json
{
  "county_id": "FIPS code (e.g., 12095 for Orange)",
  "county_name": "standardized lowercase (e.g., orange)",
  "case_number": "court case number from auction listing",
  "property_address": "full street address",
  "city": "city name",
  "zip_code": "5-digit zip",
  "parcel_id": "county assessor parcel ID if available",
  "auction_date": "ISO 8601 date of auction",
  "auction_type": "foreclosure or tax_deed",
  "plaintiff": "foreclosing party name",
  "defendant": "property owner / defendant name",
  "judgment_amount": "numeric, dollars",
  "opening_bid": "numeric, starting bid amount",
  "sale_price": "numeric, null if not yet sold",
  "sale_status": "scheduled | sold | cancelled | continued",
  "assessed_value": "numeric from county assessor if available",
  "legal_description": "legal property description",
  "scraped_at": "ISO 8601 timestamp of scrape",
  "raw_html": "optional — store raw listing HTML for debugging",
  "metadata": "JSONB — any county-specific extra fields"
}
```

#### Architecture

```
src/scrapers/
├── base_scraper.py          # Abstract base class (existing)
├── brevard_scraper.py       # Reference implementation (existing)
└── {county}_scraper.py      # NEW — this build

tests/
├── test_base.py             # Shared test utilities (existing)
└── test_{county}_scraper.py # NEW — this build

migrations/
└── {county}_setup.sql       # NEW if county needs custom columns (rare)

.github/workflows/
└── master_scraper.yml       # UPDATE — add county to cron schedule
```

#### Agent Team: 3 Agents

**Agent 1: Schema Agent (upstream)**
- Verify `multi_county_auctions` table handles this county
- Check if any county-specific columns are needed
- Produce the data contract: exact field mapping from scraper output → Supabase columns
- Verify FIPS code for the county
- Check for existing data to avoid duplicates
- **Output**: Data contract JSON + any migration SQL if needed

**Agent 2: Scraper Agent (receives schema contract)**
- Analyze the county's RealForeclose page DOM structure
- Build AgentQL scraper following `brevard_scraper.py` patterns
- Implement anti-detection: random delays, user-agent rotation, proxy support
- Handle pagination (auction calendar pages)
- Parse all required fields from listings
- Handle edge cases: cancelled auctions, continued cases, missing data
- **Output**: Working scraper module + sample output JSON

**Agent 3: Test/Integration Agent (receives both contracts)**
- Build pytest suite validating scraper output matches schema contract
- Test against live data (at least 1 real page fetch)
- Validate Supabase insert works
- Update `master_scraper.yml` to include new county in cron
- Verify GitHub Secrets has required credentials
- **Output**: Test suite + workflow update + integration validation

#### Contract Chain
```
Schema Agent → data contract (field mapping) → Lead → Scraper Agent
Scraper Agent → sample output JSON → Lead → Test Agent
```

#### Cross-Cutting Concerns

| Concern | Owner |
|---------|-------|
| FIPS code accuracy | Schema Agent |
| Anti-detection | Scraper Agent |
| Rate limiting (respect target site) | Scraper Agent |
| Error logging to scraper_logs | All agents |
| GitHub Secrets (no hardcoded creds) | Test Agent (verifies) |
| master_scraper.yml update | Test Agent |

#### Validation

**Schema Agent:**
```bash
# Verify FIPS code
python -c "
FIPS = {'orange': '12095', 'duval': '12031', 'hillsborough': '12057', 'brevard': '12009'}
county = '$ARGUMENTS[0]'.lower()
assert county in FIPS, f'Unknown county: {county}. Add FIPS code.'
print(f'✓ FIPS code for {county}: {FIPS[county]}')
"

# Verify table accepts data
python -c "
from supabase import create_client
import os
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
# Check table exists and has required columns
result = sb.table('multi_county_auctions').select('*').limit(0).execute()
print('✓ Table accessible')
"
```

**Scraper Agent:**
```bash
# Scraper imports without errors
python -c "from src.scrapers.{county}_scraper import {County}Scraper; print('✓ Import works')"

# Scraper can fetch at least one page
python -c "
from src.scrapers.{county}_scraper import {County}Scraper
scraper = {County}Scraper()
data = scraper.scrape(limit=1)
assert len(data) >= 1, 'No data returned'
assert 'case_number' in data[0], 'Missing case_number'
assert 'property_address' in data[0], 'Missing property_address'
print(f'✓ Scraped {len(data)} records')
"

# Anti-detection is active
python -c "
from src.scrapers.{county}_scraper import {County}Scraper
s = {County}Scraper()
assert hasattr(s, 'get_headers') or hasattr(s, 'session')
print('✓ Anti-detection configured')
"
```

**Test Agent:**
```bash
# All tests pass
python -m pytest tests/test_{county}_scraper.py -v

# Workflow YAML is valid
python -c "
import yaml
with open('.github/workflows/master_scraper.yml') as f:
    data = yaml.safe_load(f)
assert '$ARGUMENTS[0]' in str(data), 'County not added to workflow'
print('✓ Workflow includes county')
"
```

**Lead End-to-End:**
```bash
# Full pipeline: scrape → insert → verify
python -c "
from src.scrapers.{county}_scraper import {County}Scraper
from supabase import create_client
import os

# Scrape
scraper = {County}Scraper()
records = scraper.scrape(limit=3)
print(f'Scraped {len(records)} records')

# Insert
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
for r in records:
    sb.table('multi_county_auctions').upsert(r, on_conflict='county_id,case_number').execute()
print('✓ Inserted to Supabase')

# Verify
result = sb.table('multi_county_auctions').select('*').eq('county_name', '$ARGUMENTS[0]'.lower()).limit(3).execute()
assert len(result.data) >= 1
print(f'✓ Verified {len(result.data)} records in database')
"
```

#### Acceptance Criteria

1. Scraper fetches auction data from target county's RealForeclose page
2. Output matches `multi_county_auctions` schema exactly
3. Data inserts into Supabase without constraint violations
4. Anti-detection measures are in place (delays, headers, proxies)
5. Pytest suite passes with >80% coverage of scraper module
6. `master_scraper.yml` updated to include new county
7. No hardcoded credentials anywhere in code
8. FIPS code is correct for the target county

---

## Execute

Now use the `/build-with-agent-team` skill with this auto-generated plan:

1. Save the plan above to a temp file
2. Follow the SKILL.md contract-first spawning protocol
3. Use 3 agents (Schema + Scraper + Test)
4. Execute the full build → validate → commit → push cycle
5. Update TODO.md if it exists in zonewise-modal repo
