---
name: supabase
description: Direct Supabase/Postgres operations for BidDeed.AI and ZoneWise. Query, insert, update, and validate data in Supabase tables. Use when validating auction pipeline results, checking insights logs, debugging data issues, or running ad hoc queries against production data.
---

# Supabase Operations — Shapira Stack

## Connection

Always use the `DATABASE_URL` environment variable (direct Postgres, not REST API) for psql:

```bash
# Verify connection
psql "$DATABASE_URL" -c "SELECT NOW(), current_database()"

# If DATABASE_URL not set, construct from Supabase URL
# Host: db.mocerqjnksmhcjzxrewo.supabase.co
# Port: 5432
# DB: postgres
# User: postgres
```

## Core Tables Quick Reference

### multi_county_auctions
```sql
SELECT id, county, case_number, address, auction_date, judgment_amount, status, created_at
FROM multi_county_auctions
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC
LIMIT 20;
```

### historical_auctions
```sql
SELECT id, case_number, address, recommendation, max_bid, arv, repair_estimate, updated_at
FROM historical_auctions
WHERE recommendation IN ('BID', 'REVIEW')
ORDER BY updated_at DESC
LIMIT 10;
```

### insights (run logs)
```sql
-- Latest pipeline runs
SELECT id, task, status, message, created_at
FROM insights
ORDER BY created_at DESC
LIMIT 20;

-- Failed runs only
SELECT id, task, status, message, created_at
FROM insights
WHERE status = 'ERROR'
ORDER BY created_at DESC
LIMIT 10;
```

### master_index
```sql
SELECT id, repo, file_path, file_type, updated_at
FROM master_index
WHERE repo = 'brevard-bidder-scraper'
ORDER BY updated_at DESC
LIMIT 20;
```

## Common Validation Patterns

### After night run — verify auctions scraped
```bash
psql "$DATABASE_URL" -c "
SELECT county, COUNT(*) as count, MAX(created_at) as latest
FROM multi_county_auctions
WHERE created_at > NOW() - INTERVAL '2 hours'
GROUP BY county
ORDER BY count DESC"
```

### After analysis — verify recommendations set
```bash
psql "$DATABASE_URL" -c "
SELECT recommendation, COUNT(*) 
FROM historical_auctions 
WHERE updated_at > NOW() - INTERVAL '24 hours'
GROUP BY recommendation"
```

### Check for duplicate auctions
```bash
psql "$DATABASE_URL" -c "
SELECT county, case_number, COUNT(*) as dupes
FROM multi_county_auctions
GROUP BY county, case_number
HAVING COUNT(*) > 1"
```

### Verify insights logged
```bash
psql "$DATABASE_URL" -c "
SELECT task, status, COUNT(*) 
FROM insights 
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY task, status"
```

## Write Operations (use service role only)

Always use `SUPABASE_SERVICE_ROLE_KEY` for inserts/updates, never anon key.

### Log to insights
```bash
psql "$DATABASE_URL" -c "
INSERT INTO insights (task, status, message, created_at)
VALUES ('e2e-test', 'COMPLETED', 'E2E run passed all journeys', NOW())"
```

### Clean up test data
```bash
psql "$DATABASE_URL" -c "
DELETE FROM multi_county_auctions 
WHERE case_number LIKE 'TEST-%' 
AND created_at > NOW() - INTERVAL '1 hour'"
```

## Supabase REST API (for app code, not CLI)

Use REST when psql not available:
```bash
curl -X GET \
  "$SUPABASE_URL/rest/v1/multi_county_auctions?select=*&limit=5" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"
```

## Schema Management

```bash
# Push Drizzle schema changes
npm run db:push

# Generate migration
npm run db:generate

# Open Drizzle Studio (visual editor)
npm run db:studio
```

## Key Rules

- **Never** read `.env` directly in agent context — use env var names from `.env.example`
- **Never** use anon key for server-side writes — use service role
- **Always** log agent runs to `insights` table (task, status, message)
- **Always** check for duplicate records before insert using `case_number + county` uniqueness
- RLS policies are active on `multi_county_auctions` — service role bypasses them
