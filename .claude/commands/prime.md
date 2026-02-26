---
description: Boot full project context — reads CLAUDE.md, schema, recent activity, TODO.md, and Supabase state. Run at the start of every session.
---

# Prime: Load Project Context

## Objective

Build comprehensive understanding of the current repo state before doing any work.

## Process

### 1. Read Root Directive

```bash
cat CLAUDE.md
```

### 2. Project Structure

```bash
git ls-files | head -100
tree -L 3 -I 'node_modules|__pycache__|.git|dist|build|.next' 2>/dev/null || find . -type f -not -path '*/node_modules/*' -not -path '*/.git/*' | head -80
```

### 3. Read Core Docs

- `CLAUDE.md` — already read above
- `README.md` — project overview
- `TODO.md` — current task queue (MANDATORY — identifies what to work on next)
- `.env.example` — env var names (never read `.env`)
- `drizzle/` or `src/db/` — schema definition
- `.github/workflows/` — CI/CD pipeline definitions

### 4. Current State

```bash
git log --oneline -10
git status
git branch --show-current
```

### 5. Supabase Health Check

```bash
# Recent pipeline activity
psql "$DATABASE_URL" -c "
SELECT task, status, created_at 
FROM insights 
ORDER BY created_at DESC LIMIT 5" 2>/dev/null || echo "psql not available — use REST API"

# Tonight's auction count
psql "$DATABASE_URL" -c "
SELECT COUNT(*) as total_auctions, MAX(created_at) as latest_scrape
FROM multi_county_auctions
WHERE created_at > NOW() - INTERVAL '24 hours'" 2>/dev/null || true
```

### 6. TODO.md — Load Current Task

Read `TODO.md` from repo. Find the **first unchecked item** `[ ]`. That is the active task for this session.

Report which task is active.

### 7. GitHub Actions Status

```bash
curl -s -H "Authorization: token $GITHUB_PAT" \
  "https://api.github.com/repos/breverdbidder/$(basename $PWD)/actions/runs?per_page=3" \
  2>/dev/null | python3 -c "
import sys, json
try:
  runs = json.load(sys.stdin).get('workflow_runs', [])
  for r in runs[:3]:
    print(f\"{r['name']}: {r['status']} / {r['conclusion']} ({r['created_at'][:10]})\")
except: print('Could not fetch Actions status')
" || true
```

---

## Output Report

Provide a concise, scannable summary:

### Active Task
`[ ] [task from TODO.md]` — this is what we work on this session.

### Project State
- Repo + branch + last commit
- Any uncommitted changes

### Pipeline Health
- Last scraper run: [status + time]
- Recent auction count: [n auctions in last 24h]
- Open GitHub Actions failures: [list or "none"]

### Tech Stack Confirmed
- [detected stack]

### Key Files to Know
- [3-5 most relevant files for today's task]

### Warnings
- Any `.env` vars missing from `.env.example`
- Any TODO items marked BLOCKED
- Any recent ERROR entries in insights table
