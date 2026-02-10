# ZoneWise.AI Scout Pass Referral System — PRD

## Overview

**Codename:** Scout Pass  
**Inspired by:** Claude Code `/passes` (weaponized scarcity + trust-based distribution)  
**Goal:** Turn paid ZoneWise users into the primary acquisition channel  
**Launch:** Coincides with 67-county FL rollout (Q1 2026)

---

## Core Mechanics

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Passes per user per quarter | **3** | Real scarcity, not unlimited spam |
| Trial duration | **14 days** | 2x Claude's 7-day (real estate decisions take longer) |
| Credit card required | **Yes, before trial** | Filters to high-intent users only |
| Pass expiry | **30 days after generation** | Creates urgency to share |
| Referrer reward | **+7 days per accepted invite** | Concrete, measurable, stacking |
| County access | **Inherits referrer's counties** | Recipient sees real data, gets hooked |
| Quarterly leaderboard | **Top 3 get free month** | Competition among power users |

---

## User Flows

### Flow 1: Referrer Generates Pass

```
Paid User → Dashboard → "Scout Passes" tab
  → Sees: "You have 3 Scout Passes this quarter"
  → Clicks "Generate Link"
  → Gets: zonewise.ai/scout/[12-char-code]
  → Options: Copy Link | Share via Email | Share via SMS
  → Pass status: available → shared
  → Event logged: pass_shared
```

### Flow 2: Recipient Claims Pass

```
Recipient → clicks zonewise.ai/scout/[code]
  → Landing page: "You've been invited by [Referrer Name]"
  → Shows: [Referrer's county] market preview (blurred data teaser)
  → CTA: "Start 14-Day Free Trial"
  → Sign up form (email, password)
  → Payment form (card required, $0 charge)
  → Trial activated → full access to referrer's counties
  → Referrer notified: "[Name] accepted your Scout Pass! +7 days added"
  → Event logged: trial_activated
```

### Flow 3: Trial → Conversion

```
Day 1-10: Full access, onboarding emails
Day 10: "4 days left" nudge email
Day 13: "Last day tomorrow" urgency email  
Day 14: Trial ends → 
  IF card on file → Auto-charge first month
  IF no card → Access revoked, "Reactivate" CTA
  Event logged: converted_to_paid OR trial_expired
```

### Flow 4: Leaderboard + Rewards

```
Quarterly cycle:
  → All paid users get 3 fresh passes
  → Leaderboard tracks: shared, claimed, converted
  → Top 3 referrers per quarter → free month
  → All referrers with 1+ conversion → +7 days per conversion
```

---

## API Endpoints (FastAPI — zonewise-agents)

### POST /api/v1/referral/passes/generate
**Auth:** Bearer token (paid users only)  
**Response:**
```json
{
  "passes": [
    {
      "id": "uuid",
      "pass_code": "a1b2c3d4e5f6",
      "share_url": "https://zonewise.ai/scout/a1b2c3d4e5f6",
      "status": "available",
      "county_access": ["brevard", "orange", "seminole"],
      "expires_at": "2026-03-12T00:00:00Z"
    }
  ],
  "total_available": 3,
  "quarter": "2026-Q1"
}
```

### POST /api/v1/referral/passes/{pass_code}/share
**Auth:** Bearer token (pass owner only)  
**Body:** `{ "method": "email", "recipient_email": "friend@example.com" }`  
**Actions:** Updates status to "shared", sends invite email, logs event

### GET /api/v1/referral/scout/{pass_code}
**Auth:** Public (no auth — this is the invite landing page API)  
**Response:**
```json
{
  "valid": true,
  "referrer_name": "Ariel S.",
  "counties": ["Brevard", "Orange", "Seminole"],
  "trial_days": 14,
  "preview_stats": {
    "total_auctions_tracked": 847,
    "avg_savings_per_deal": "$43,200",
    "counties_covered": 67
  }
}
```

### POST /api/v1/referral/passes/{pass_code}/claim
**Auth:** Bearer token (new user, post-signup)  
**Body:** `{ "payment_method_id": "pm_stripe_xxx" }`  
**Actions:** Claims pass, starts trial, grants +7 days to referrer, updates leaderboard

### GET /api/v1/referral/leaderboard
**Auth:** Bearer token (paid users)  
**Query:** `?quarter=2026-Q1`  
**Response:**
```json
{
  "quarter": "2026-Q1",
  "leaderboard": [
    { "rank": 1, "name": "Mike T.", "claimed": 3, "converted": 2, "days_earned": 21 },
    { "rank": 2, "name": "Sarah K.", "claimed": 2, "converted": 2, "days_earned": 14 }
  ],
  "user_stats": {
    "rank": 5,
    "passes_available": 1,
    "passes_claimed": 2,
    "days_earned": 14,
    "next_reward_at": 3
  }
}
```

### GET /api/v1/referral/rewards
**Auth:** Bearer token  
**Response:** List of rewards earned with status

---

## LangGraph Agent: Referral Orchestrator

### Agent Graph

```
                    ┌──────────────┐
                    │  START/Event │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Route Event  │
                    └──────┬───────┘
           ┌───────┬───────┼───────┬──────────┐
           ▼       ▼       ▼       ▼          ▼
      ┌────────┐┌──────┐┌──────┐┌───────┐┌────────┐
      │Generate││Share ││Claim ││Expire ││Convert │
      │Passes  ││Pass  ││Pass  ││Check  ││Check   │
      └───┬────┘└──┬───┘└──┬───┘└───┬───┘└───┬────┘
          │        │       │        │         │
          ▼        ▼       ▼        ▼         ▼
      ┌────────────────────────────────────────────┐
      │            Notify + Log Events             │
      └────────────────────────────────────────────┘
                           │
                    ┌──────▼───────┐
                    │   Update     │
                    │  Leaderboard │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │     END      │
                    └──────────────┘
```

### Agent Nodes

```python
# agents/referral_agent.py

from langgraph.graph import StateGraph, END
from typing import TypedDict, Literal

class ReferralState(TypedDict):
    event_type: str
    user_id: str
    pass_code: str | None
    recipient_email: str | None
    result: dict
    notifications: list[dict]
    errors: list[str]

def route_event(state: ReferralState) -> Literal[
    "generate_passes", "share_pass", "claim_pass", 
    "expire_check", "convert_check"
]:
    return state["event_type"]

def generate_passes(state: ReferralState) -> ReferralState:
    """Generate 3 Scout Passes for a paid user at quarter start."""
    # Call Supabase: generate_scout_passes(user_id, email, counties)
    # Log event: pass_generated (x3)
    # Send notification: "Your 3 Scout Passes are ready!"
    ...

def share_pass(state: ReferralState) -> ReferralState:
    """Mark pass as shared, send invite email to recipient."""
    # Update pass status: available → shared
    # Send invite email via SendGrid/Resend
    # Log event: pass_shared
    ...

def claim_pass(state: ReferralState) -> ReferralState:
    """Recipient claims pass, starts trial, rewards referrer."""
    # Call Supabase: claim_scout_pass(code, recipient_id, email)
    # Create Stripe trial subscription (14 days, card on file)
    # Grant +7 days to referrer
    # Send notifications to both parties
    # Log events: trial_activated, reward_granted
    ...

def expire_check(state: ReferralState) -> ReferralState:
    """Scheduled: expire unclaimed passes older than 30 days."""
    # Query: WHERE status IN ('available','shared') AND expires_at < NOW()
    # Batch update to 'expired'
    # Notify referrers: "Your Scout Pass expired. Share sooner next time!"
    ...

def convert_check(state: ReferralState) -> ReferralState:
    """Scheduled: check trial users at day 14, process conversion."""
    # Query: WHERE status = 'claimed' AND trial_end < NOW()
    # Check Stripe: subscription active? → converted_to_paid
    # No payment? → trial_expired, revoke access
    # Update leaderboard: passes_converted++
    ...

def notify_and_log(state: ReferralState) -> ReferralState:
    """Send all queued notifications and log events."""
    # Process state["notifications"] queue
    # Insert into referral_events
    ...

def update_leaderboard(state: ReferralState) -> ReferralState:
    """Recalculate rankings after any event."""
    # Upsert referral_leaderboard
    # Recalculate ranks per quarter
    # Check if user hit top 3 → grant month_free reward
    ...

# Build graph
graph = StateGraph(ReferralState)
graph.add_node("generate_passes", generate_passes)
graph.add_node("share_pass", share_pass)
graph.add_node("claim_pass", claim_pass)
graph.add_node("expire_check", expire_check)
graph.add_node("convert_check", convert_check)
graph.add_node("notify_and_log", notify_and_log)
graph.add_node("update_leaderboard", update_leaderboard)

graph.add_conditional_edges("__start__", route_event)

for node in ["generate_passes", "share_pass", "claim_pass", "expire_check", "convert_check"]:
    graph.add_edge(node, "notify_and_log")

graph.add_edge("notify_and_log", "update_leaderboard")
graph.add_edge("update_leaderboard", END)

referral_graph = graph.compile()
```

### Scheduled Jobs (GitHub Actions / Render Cron)

```yaml
# .github/workflows/referral_cron.yml
name: Referral System Cron Jobs

on:
  schedule:
    # Expire stale passes daily at midnight EST
    - cron: '0 5 * * *'
    # Check trial conversions daily at 9am EST
    - cron: '0 14 * * *'
    # Generate quarterly passes on 1st of quarter
    - cron: '0 12 1 1,4,7,10 *'

jobs:
  expire-passes:
    runs-on: ubuntu-latest
    steps:
      - name: Expire stale passes
        run: |
          curl -X POST "${{ secrets.AGENTS_URL }}/api/v1/referral/cron/expire" \
            -H "Authorization: Bearer ${{ secrets.CRON_SECRET }}"

  check-conversions:
    runs-on: ubuntu-latest
    steps:
      - name: Check trial conversions
        run: |
          curl -X POST "${{ secrets.AGENTS_URL }}/api/v1/referral/cron/convert" \
            -H "Authorization: Bearer ${{ secrets.CRON_SECRET }}"

  generate-quarterly:
    runs-on: ubuntu-latest
    if: github.event.schedule == '0 12 1 1,4,7,10 *'
    steps:
      - name: Generate quarterly passes for all paid users
        run: |
          curl -X POST "${{ secrets.AGENTS_URL }}/api/v1/referral/cron/generate-quarterly" \
            -H "Authorization: Bearer ${{ secrets.CRON_SECRET }}"
```

---

## Stripe Integration

### Trial Subscription Flow

```python
# When recipient claims pass with card on file:
stripe.Subscription.create(
    customer=recipient_stripe_id,
    items=[{"price": "price_zonewise_pro_monthly"}],
    trial_period_days=14,
    payment_behavior="default_incomplete",
    metadata={
        "scout_pass_id": pass_id,
        "referrer_id": referrer_id,
        "source": "scout_pass_referral"
    }
)
```

### Webhook Handler

```python
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    event = stripe.Webhook.construct_event(...)
    
    if event.type == "customer.subscription.updated":
        sub = event.data.object
        if sub.metadata.get("source") == "scout_pass_referral":
            if sub.status == "active" and sub.trial_end < time.time():
                # Trial ended, card charged → CONVERTED
                await referral_graph.ainvoke({
                    "event_type": "convert_check",
                    "pass_code": sub.metadata["scout_pass_id"]
                })
    
    elif event.type == "customer.subscription.deleted":
        # Trial expired, no payment → NOT CONVERTED
        ...
```

---

## Metrics & KPIs

| Metric | Target | Measurement |
|--------|--------|-------------|
| Pass generation rate | 80% of paid users generate ≥1 pass | `passes_generated / paid_users` |
| Share rate | 60% of generated passes get shared | `passes_shared / passes_generated` |
| Claim rate | 40% of shared passes get claimed | `passes_claimed / passes_shared` |
| Conversion rate | 30% of trials convert to paid | `converted / trials_started` |
| Referrer reward uptake | 90% of rewards applied | `rewards_applied / rewards_granted` |
| CAC via Scout Pass | < $15 | `total_trial_cost / conversions` |
| Viral coefficient | > 0.3 | `new_paid_from_referrals / existing_paid` |

---

## Implementation Priority

| Phase | What | Where | Timeline |
|-------|------|-------|----------|
| 1 | Supabase migration (4 tables + functions) | Supabase | Day 1 |
| 2 | FastAPI endpoints (6 routes) | zonewise-agents | Day 1-2 |
| 3 | LangGraph referral agent | zonewise-agents | Day 2-3 |
| 4 | Scout Pass dashboard UI | zonewise-web | Day 3-5 |
| 5 | Invite landing page | zonewise-web | Day 3-5 |
| 6 | Email templates (invite, claim, expiry, convert) | zonewise-agents | Day 4-5 |
| 7 | Stripe integration + webhooks | zonewise-agents | Day 5-6 |
| 8 | Cron jobs (expire, convert, quarterly gen) | GitHub Actions | Day 6 |
| 9 | Leaderboard UI | zonewise-web | Day 7 |
| 10 | Launch email to existing paid users | SendGrid | Day 7 |
