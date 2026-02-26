---
description: Deploy to production. Runs validation suite, pushes to main, triggers Render.com deploy, and verifies deployment health. Only run after e2e-test passes.
---

# Deploy to Production

## Pre-deploy Gates (ALL must pass)

```bash
# 1. Clean working tree
git status --porcelain
# Must be empty. If not: commit or stash first.

# 2. Unit tests
npm run test:run
# Must: 0 failures

# 3. TypeScript
npx tsc --noEmit
# Must: 0 errors

# 4. Lint
npm run lint
# Must: 0 errors

# 5. Build check
npm run build
# Must: succeed
```

If any gate fails → fix before deploying. Do not bypass.

---

## Deploy

### Push to main (triggers Render auto-deploy)

```bash
git push origin main
```

Render auto-deploys on push to `main`. No manual step needed.

### Monitor Render Deploy

```bash
# Check Render deploy status via API (if RENDER_API_KEY set)
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services?limit=5" \
  | python3 -c "
import sys, json
services = json.load(sys.stdin).get('services', [])
for s in services:
  svc = s.get('service', {})
  print(f\"{svc.get('name')}: {svc.get('suspended', 'unknown')}\")
" 2>/dev/null || echo "Check Render dashboard manually: https://dashboard.render.com"
```

Wait 3-5 minutes for Render build to complete.

---

## Post-deploy Verification

### Health Check

```bash
# Replace with actual Render URL
RENDER_URL="https://[your-app].onrender.com"

# API health
curl -sf "$RENDER_URL/api/health" && echo "✅ Health check passed" || echo "❌ Health check failed"

# Auth endpoint
curl -sf "$RENDER_URL/api/auth/session" -o /dev/null && echo "✅ Auth endpoint responding" || echo "⚠️ Auth endpoint check"
```

### Supabase Connection Verify

```bash
psql "$DATABASE_URL" -c "SELECT NOW()" && echo "✅ Supabase reachable"
```

### Log Deploy to insights

```bash
psql "$DATABASE_URL" -c "
INSERT INTO insights (task, status, message, created_at)
VALUES ('deploy', 'COMPLETED', 'Deployed to Render: $(git rev-parse --short HEAD)', NOW())"
```

---

## Cloudflare Pages Deploy (zonewise-web only)

For the marketing site:
```bash
# Cloudflare auto-deploys on main push via GitHub integration
# Verify at: https://dash.cloudflare.com/pages
git push origin main
echo "Cloudflare Pages will auto-deploy in ~2 minutes"
```

---

## Rollback (if production broken)

```bash
# Find last working commit
git log --oneline -10

# Revert to it
git revert HEAD  # creates new commit undoing last change
git push origin main
# OR force rollback (use carefully):
# git push origin HEAD~1:main --force
```

---

## Output

```
## Deploy Complete

**Commit:** [hash] — [message]
**Branch:** main
**Time:** [timestamp]

### Gates Passed
✅ Unit tests
✅ TypeScript
✅ Lint
✅ Build

### Production Status
✅ Render deploy triggered
✅ Health check: [URL] responding
✅ Supabase: connected
✅ Deploy logged to insights table

### Next Nightly Run
Scheduled: 11:00 PM EST
Monitor: insights table at 11:05 PM
```
