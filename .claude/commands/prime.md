---
description: Boot full project context. Reads CLAUDE.md, queries master_index for cross-repo state, loads active task from ssot-task-manager, checks Supabase health and GitHub Actions status. Run at the start of every session.
---

# /prime — Boot Project Context

## Objective
Build complete situational awareness before touching any code.
This command runs in under 90 seconds and tells you exactly what to work on.

---

## Step 1: Read This Repo

```bash
cat CLAUDE.md
git log --oneline -5
git status
git branch --show-current
```

Read in parallel:
- `README.md`
- `.env.example`
- `PROJECT_STATE.json` (if exists)
- `CHANGELOG.md` (last 20 lines)

---

## Step 2: Load Active Task from SSOT

The single task queue for all ZoneWise and BidDeed work lives in:
`breverdbidder/ssot-task-manager`

```bash
# Fetch the active task list
curl -s -H "Authorization: token $GITHUB_PAT" \
  "https://api.github.com/repos/breverdbidder/ssot-task-manager/contents/TODO.md" \
  | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
content = base64.b64decode(d['content']).decode()
print(content[:3000])
" 2>/dev/null || echo "SSOT unavailable — check local TODO.md"
```

Find the first unchecked `[ ]` item. That is the active task for this session.
If the list is empty, report: "SSOT: No active tasks. Awaiting Ariel direction."

---

## Step 3: Cross-Repo State from master_index

```bash
# What's active across ALL repos right now
psql "$DATABASE_URL" -c "
SELECT repo, file_path, file_type, updated_at
FROM master_index
WHERE updated_at > NOW() - INTERVAL '48 hours'
ORDER BY updated_at DESC
LIMIT 20" 2>/dev/null || \
curl -s "$SUPABASE_URL/rest/v1/master_index?select=repo,file_path,updated_at&order=updated_at.desc&limit=20" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" 2>/dev/null | \
  python3 -c "import sys,json; [print(r['repo'],'→',r['file_path']) for r in json.load(sys.stdin)]" \
  || echo "master_index unavailable"
```

---

## Step 4: Capability Registry Health

```bash
# Which capabilities are active/beta/coming_soon
psql "$DATABASE_URL" -c "
SELECT slug, name, status, tier_required, sort_order
FROM capabilities
ORDER BY sort_order" 2>/dev/null || \
curl -s "$SUPABASE_URL/rest/v1/capabilities?select=slug,name,status&order=sort_order" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" 2>/dev/null | \
  python3 -c "import sys,json; [print(r['slug'],r['status']) for r in json.load(sys.stdin)]" \
  || echo "Capability registry not yet deployed — run migration 001"
```

---

## Step 5: Supabase Pipeline Health

```bash
# BidDeed pipeline recent activity
psql "$DATABASE_URL" -c "
SELECT task, status, message, created_at
FROM insights
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC
LIMIT 10" 2>/dev/null || true

# Tonight's auctions
psql "$DATABASE_URL" -c "
SELECT county, COUNT(*) as count,
  SUM(CASE WHEN recommendation='BID' THEN 1 ELSE 0 END) as bids
FROM multi_county_auctions
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY county" 2>/dev/null || true
```

---

## Step 6: BidDeed External API Status

```bash
# Check if BidDeed API is live
curl -sf "https://biddeed-api.onrender.com/api/v1/health" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('BidDeed API:', d.get('status'), '|', d.get('auctions_last_24h'), 'auctions')" \
  2>/dev/null || echo "BidDeed API: not yet deployed"
```

---

## Step 7: GitHub Actions Status

```bash
REPO=$(basename $(git rev-parse --show-toplevel))
curl -s -H "Authorization: token $GITHUB_PAT" \
  "https://api.github.com/repos/breverdbidder/${REPO}/actions/runs?per_page=3" \
  | python3 -c "
import sys, json
try:
  runs = json.load(sys.stdin).get('workflow_runs', [])
  for r in runs[:3]:
    print(f\"{r['name']}: {r['status']}/{r.get('conclusion','pending')} ({r['created_at'][:10]})\")
except: print('Actions status unavailable')
" 2>/dev/null || true
```

---

## Output Report

Print this exact structure:

```
═══════════════════════════════════════════════
/PRIME COMPLETE — [REPO NAME] — [timestamp]
═══════════════════════════════════════════════

ACTIVE TASK (from SSOT):
→ [ ] [task description]
   Complexity: [1-10] | Domain: [BIDDEED/ZONEWISE/LIFE_OS]

CROSS-REPO ACTIVITY (last 48h):
→ [repo]: [file changed] ([time ago])

CAPABILITY REGISTRY:
→ discoverwise: [status]
→ lienwise: [status]
→ cmawise: [status]
→ titlewise: [status]

PIPELINE HEALTH:
→ Last run: [time] — [status]
→ Auctions tonight: [n]
→ Errors (24h): [n]
→ BidDeed API: [healthy/not deployed]

GITHUB ACTIONS:
→ [workflow]: [status]

REPO STATE:
→ Branch: [branch] | Last commit: [hash] [message]
→ Uncommitted: [n files] or CLEAN

WARNINGS: [any blocked tasks, missing env vars, ERROR insights]

NEXT ACTION: [one specific thing to do — execute /execute or /plan-feature]
═══════════════════════════════════════════════
```

---

## Critical Rules
- EXACT values only. Never invent numbers.
- If a system is unavailable, say so — do not fabricate status.
- Active task from SSOT overrides local TODO.md.
- If SSOT says no tasks: do NOT invent work. Report and wait.
