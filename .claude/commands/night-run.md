---
description: Trigger and monitor the BidDeed.AI nightly auction pipeline. Dispatches the GitHub Actions workflow, waits for completion, validates Supabase records, and reports results. Run manually when testing pipeline changes or when the scheduled run fails.
argument-hint: [county] (optional — defaults to all active counties)
---

# Night Run: BidDeed.AI Auction Pipeline

## Target County: $ARGUMENTS (or all if empty)

---

## Step 1: Trigger GitHub Actions Workflow

```bash
# Trigger nightly scrape
curl -X POST \
  -H "Authorization: token $GITHUB_PAT" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/breverdbidder/brevard-bidder-scraper/actions/workflows/nightly-auction-scrape.yml/dispatches" \
  -d '{"ref":"main","inputs":{"county":"$ARGUMENTS"}}'

echo "Pipeline triggered at $(date)"
```

## Step 2: Monitor Run

```bash
# Poll every 30 seconds for up to 10 minutes
for i in $(seq 1 20); do
  STATUS=$(curl -s -H "Authorization: token $GITHUB_PAT" \
    "https://api.github.com/repos/breverdbidder/brevard-bidder-scraper/actions/runs?per_page=1" \
    | python3 -c "
import sys,json
r=json.load(sys.stdin)['workflow_runs'][0]
print(r['status'], r.get('conclusion','—'))")
  echo "[$i/20] $STATUS"
  [[ "$STATUS" == *"completed"* ]] && break
  sleep 30
done
```

## Step 3: Validate Supabase Results

```bash
# New auctions added in last 2 hours
psql "$DATABASE_URL" -c "
SELECT county, COUNT(*) as scraped, MAX(created_at) as latest
FROM multi_county_auctions
WHERE created_at > NOW() - INTERVAL '2 hours'
GROUP BY county
ORDER BY scraped DESC"

# Pipeline log
psql "$DATABASE_URL" -c "
SELECT task, status, message, created_at
FROM insights
WHERE created_at > NOW() - INTERVAL '2 hours'
ORDER BY created_at DESC
LIMIT 20"

# Check recommendations set
psql "$DATABASE_URL" -c "
SELECT recommendation, COUNT(*)
FROM multi_county_auctions
WHERE auction_date >= CURRENT_DATE
AND recommendation IS NOT NULL
GROUP BY recommendation"

# Verify no duplicates
psql "$DATABASE_URL" -c "
SELECT county, case_number, COUNT(*) as dupes
FROM multi_county_auctions
WHERE created_at > NOW() - INTERVAL '2 hours'
GROUP BY county, case_number
HAVING COUNT(*) > 1"
```

## Step 4: Flag High-Value Auctions

```bash
psql "$DATABASE_URL" -c "
SELECT county, case_number, address, judgment_amount, recommendation, max_bid
FROM multi_county_auctions
WHERE created_at > NOW() - INTERVAL '2 hours'
AND judgment_amount > 200000
AND recommendation IN ('BID', 'REVIEW')
ORDER BY judgment_amount DESC"
```

## Step 5: Report

```
## Night Run Complete

**Triggered:** [timestamp]
**Duration:** [minutes]
**GitHub Actions:** [success/failure]

### Auctions Scraped
| County | Count | BID | REVIEW | SKIP |
|--------|-------|-----|--------|------|
| [county] | [n] | [n] | [n] | [n] |

### High-Value Flags (judgment > $200K)
- [address] — [county] — [recommendation] — max bid: $[amount]

### Pipeline Errors
- [any ERROR entries from insights table, or "none"]

### Next Run
Scheduled: 11:00 PM EST tomorrow
```

## On Failure

If GitHub Actions fails or no records inserted:

1. Check workflow logs:
   ```bash
   curl -s -H "Authorization: token $GITHUB_PAT" \
     "https://api.github.com/repos/breverdbidder/brevard-bidder-scraper/actions/runs?per_page=1" \
     | python3 -c "import sys,json; r=json.load(sys.stdin)['workflow_runs'][0]; print(r['html_url'])"
   ```

2. Check insights for ERROR:
   ```bash
   psql "$DATABASE_URL" -c "SELECT task, message FROM insights WHERE status='ERROR' ORDER BY created_at DESC LIMIT 5"
   ```

3. Attempt fix (3 retries max), then escalate:
   ```
   BLOCKED: Night run failed — [reason]
   Tried: [3 attempts]
   Recommend: [fix]
   Approve?
   ```
