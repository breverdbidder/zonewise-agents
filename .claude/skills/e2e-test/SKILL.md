---
name: e2e-test
description: Full end-to-end testing for BidDeed.AI and ZoneWise applications. Launches parallel sub-agents to research the codebase, then uses agent-browser to test every user journey — taking screenshots, validating UI/UX, and querying Supabase to verify records. Run after implementation to validate everything before commit and Render deploy.
disable-model-invocation: true
---

# End-to-End Application Testing — Shapira Stack

## Pre-flight Check

### 1. Platform Check

agent-browser requires **Linux, WSL, or macOS**:
```bash
uname -s
```
- `Linux` or `Darwin` → proceed
- Anything else → stop:
> "agent-browser only supports Linux, WSL, and macOS. Run from WSL or macOS."

### 2. Frontend Check

Verify a browser-accessible frontend exists:
- `package.json` with `dev`/`start` script
- `src/app/`, `src/pages/`, or `index.html`

If no frontend found → stop. For API-only repos, use `/test-api` instead.

### 3. agent-browser Installation

```bash
agent-browser --version
```

If not found:
```bash
npm install -g agent-browser
agent-browser install --with-deps
agent-browser --version
```

If install fails → stop with manual install instructions.

### 4. Supabase CLI Check

Verify `psql` is available for DB validation:
```bash
which psql || apt-get install -y postgresql-client
```

---

## Phase 1: Parallel Research

Launch **three sub-agents simultaneously** using the Task tool.

### Sub-agent 1: Application Structure & User Journeys

> Research this codebase thoroughly. Return a structured summary:
>
> 1. **How to start** — exact commands, URL, port
> 2. **Auth flow** — how to create a test account or log in (check `.env.example` for test credentials, never read `.env` directly)
> 3. **Every route/page** — URL paths and what they render
> 4. **Every user journey** — complete flows with steps, interactions, expected outcomes
> 5. **Key interactive components** — forms, modals, drag-drop, toggles, buttons
> 6. **BidDeed-specific flows** — auction list, property detail, bid recommendation, report generation
> 7. **ZoneWise-specific flows** — county selector, scrape status, modal, map view
>
> Be exhaustive. Testing only covers what you identify here.

### Sub-agent 2: Database Schema & Supabase Data Flows

> Research this codebase's database layer. Read `.env.example` for env var names. DO NOT read `.env` directly. Return:
>
> 1. **Supabase connection** — env var name for `DATABASE_URL` (direct Postgres URL)
> 2. **Full schema** — every table, columns, types, relationships (check `drizzle/` folder or `src/db/`)
> 3. **Key tables** — `multi_county_auctions`, `historical_auctions`, `insights`, `master_index`
> 4. **Data flows per action** — what records are created/updated/deleted per user action
> 5. **Validation queries** — exact psql queries to verify records after each action
> 6. **GitHub Actions triggers** — which workflows exist and what they do
>
> Example validation query format:
> ```bash
> psql "$DATABASE_URL" -c "SELECT id, county, status FROM multi_county_auctions WHERE created_at > NOW() - INTERVAL '1 hour' LIMIT 5"
> ```

### Sub-agent 3: Bug Hunting

> Analyze this codebase for bugs and issues. Focus on:
>
> 1. **Logic errors** — bad conditionals, off-by-one, null checks, race conditions in async scrapers
> 2. **UI/UX issues** — missing loading states, error handling in forms, broken responsive layouts
> 3. **Data integrity** — missing validation, orphaned auction records, incorrect lien priority logic
> 4. **Security** — missing auth checks on API routes, exposed Supabase service keys, SQL injection
> 5. **Auction pipeline** — scraper failures not logged to `insights`, missing retry logic, wrong county data
> 6. **Supabase** — RLS policies that block valid inserts, anon vs service role misuse
>
> Return prioritized list with file paths and line numbers.

**Wait for all three sub-agents before proceeding.**

---

## Phase 2: Start the Application

Using Sub-agent 1's startup instructions:

1. Install dependencies if needed (`npm install --legacy-peer-deps` or `pip install -r requirements.txt`)
2. Start dev server in background: `npm run dev &` or `uvicorn app.main:app --reload &`
3. Wait for server ready:
   ```bash
   agent-browser wait --url "http://localhost:3000" 2>/dev/null || sleep 5
   ```
4. Open and confirm:
   ```bash
   agent-browser open http://localhost:3000
   agent-browser screenshot e2e-screenshots/00-initial-load.png
   ```

---

## Phase 3: Create Task List

Using Sub-agent 1's journeys + Sub-agent 3's findings, create a task per journey with `TaskCreate`:

- **subject:** Journey name (e.g., "Test auction detail view")
- **description:** Steps, expected outcomes, DB queries to verify, related bugs
- **activeForm:** Present continuous (e.g., "Testing auction detail view")

Always include these standard tasks:
- Auth flow (signup → login → logout)
- Core feature flows (per app)
- Supabase data verification
- GitHub Actions pipeline trigger (if applicable)
- Responsive testing (375/768/1440 viewports)

---

## Phase 4: User Journey Testing

For each task, mark `in_progress` with TaskUpdate then execute:

### 4a. Browser Testing

```bash
agent-browser open <url>              # Navigate
agent-browser snapshot -i             # Get interactive refs (@e1, @e2...)
agent-browser click @eN               # Click by ref
agent-browser fill @eN "text"         # Fill input
agent-browser select @eN "option"     # Select dropdown
agent-browser press Enter
agent-browser screenshot <path>       # Save screenshot
agent-browser wait --load networkidle
agent-browser console                 # Check JS errors
agent-browser errors                  # Check uncaught exceptions
agent-browser get text @eN
agent-browser get url
agent-browser drag @e1 @e2            # Drag-and-drop (for reorder flows)
```

**Critical:** Refs become invalid after navigation or DOM changes. Always re-snapshot.

For each step:
1. Snapshot → get refs
2. Interact
3. Wait for settle
4. Screenshot to `e2e-screenshots/[journey-name]/[step].png`
5. Analyze screenshot with Read tool — check visual correctness, layout, error states
6. Check console/errors periodically

**BidDeed-specific testing:**
- Verify bid recommendations (BID/REVIEW/SKIP) display correctly
- Confirm max bid calculations appear in property detail
- Test report generation — verify DOCX download link appears
- Test auction filter by county, date, status

**ZoneWise-specific testing:**
- Test county selector modal (GitHub Issue #14)
- Verify scrape status indicators update
- Test map view renders correctly (Mapbox token)
- Confirm 67-county list loads without timeout

### 4b. Supabase Database Validation

After any write action:

```bash
# Verify auction record created
psql "$DATABASE_URL" -c "SELECT id, county, address, status FROM multi_county_auctions WHERE created_at > NOW() - INTERVAL '10 minutes' LIMIT 5"

# Verify insight log created
psql "$DATABASE_URL" -c "SELECT id, task, status, created_at FROM insights ORDER BY created_at DESC LIMIT 5"

# Verify historical auction updated
psql "$DATABASE_URL" -c "SELECT id, recommendation, max_bid FROM historical_auctions WHERE updated_at > NOW() - INTERVAL '10 minutes' LIMIT 5"
```

Verify:
- Records created/updated as expected
- Values match UI inputs
- `insights` table logged the operation with correct status
- No duplicate auction records (check `county + case_number` unique)
- `recommendation` field is BID, REVIEW, or SKIP (never null after analysis)

### 4c. GitHub Actions Trigger Test (if applicable)

For repos with nightly pipelines:
```bash
# Trigger workflow via API
curl -X POST \
  -H "Authorization: token $GITHUB_PAT" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/breverdbidder/brevard-bidder-scraper/actions/workflows/nightly-auction-scrape.yml/dispatches" \
  -d '{"ref":"main"}'

# Wait 60s then check Supabase for new records
sleep 60
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM multi_county_auctions WHERE created_at > NOW() - INTERVAL '2 minutes'"
```

### 4d. Issue Handling

When issue found:
1. Document: expected vs actual, screenshot path, DB query results
2. Fix the code directly
3. Re-run failing step
4. Screenshot confirming fix
5. Note fix in task description

### 4e. Responsive Testing

```bash
agent-browser set viewport 375 812    # Mobile (iPhone)
agent-browser set viewport 768 1024   # Tablet (iPad)
agent-browser set viewport 1440 900   # Desktop
```

For BidDeed: verify auction table is scrollable on mobile, not broken.
For ZoneWise: verify county modal is usable on mobile.

Mark each task `completed` with TaskUpdate.

---

## Phase 5: Cleanup

```bash
# Kill dev server
pkill -f "npm run dev" || pkill -f "uvicorn" || true

# Close browser
agent-browser close

# Remove test accounts from Supabase if created
psql "$DATABASE_URL" -c "DELETE FROM auth.users WHERE email LIKE '%e2e-test%'"
```

---

## Phase 6: Report

### Text Summary (always output)

```
## E2E Testing Complete — [REPO NAME]

**Date:** [timestamp]
**Journeys Tested:** [count]
**Screenshots Captured:** [count]
**Issues Found:** [count] ([count] fixed, [count] remaining)

### Issues Fixed During Testing
- [Description] — [file:line]

### Remaining Issues
- [Description] — [severity: critical/high/medium/low] — [file:line]

### Supabase Validation
- multi_county_auctions: [count new records verified]
- insights: [count log entries verified]
- historical_auctions: [count updated records verified]

### Bug Hunt Findings
- [Description] — [severity] — [file:line]

### Screenshots
All saved to: e2e-screenshots/
```

### Markdown Export

Ask:
> "Export full report to `e2e-test-report.md`? Includes per-journey breakdowns, Supabase validation results, screenshot paths, and GitHub Actions status."

If yes, write `e2e-test-report.md` with:
- Full summary with stats
- Per-journey breakdown: steps, screenshots, DB checks, issues
- All issues with fix status and file references
- Bug hunt findings
- Recommendations for unresolved issues
- **Next step:** run `/deploy` if all critical issues resolved
