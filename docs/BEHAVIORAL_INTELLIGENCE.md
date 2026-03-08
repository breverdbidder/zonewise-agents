# BidDeed.AI — Behavioral Intelligence Module

## Nir Eyal Hooked Model Integration

This module implements passive behavioral intelligence across the BidDeed.AI platform, enabling the four-phase Hooked Model: **Trigger → Action → Variable Reward → Investment**.

### Architecture Overview

```
User browses BidDeed.AI
       │
       ▼
PostHog JS (tracks every click, search, dwell)
       │
       ▼ (webhook sync)
Supabase: user_events table
       │
       ▼ (pg_cron 2 AM EST)
Edge Function: compute-buy-boxes
       │ Analyzes behavior → builds implicit buy box
       ▼
Supabase: user_buy_boxes table
       │
       ▼ (pg_cron 6 AM EST)
Edge Function: match-auctions
       │ Scores buy_boxes × new auctions → teasers
       ▼
Supabase: user_teasers table
       │
       ▼ (pg_cron 6:05 AM EST)
Edge Function: send-teasers
       │ Routes to Novu → channels by tier
       ▼
┌──────────────┬────────────┬──────────┐
│ Resend       │ FCM        │ Twilio   │
│ (Email)      │ (Push)     │ (SMS)    │
│ Tier 1+2     │ Tier 2+3   │ Tier 3   │
└──────────────┴────────────┴──────────┘
       │
       ▼
User opens teaser → visits BidDeed → PostHog tracks → refines buy box → LOOP
```

### File Structure

```
behavioral-intelligence/
├── README.md                              # This file
├── migrations/
│   └── 20260308_behavioral_intelligence.sql  # Tables + cron + views
├── supabase/functions/
│   ├── compute-buy-boxes/index.ts         # Buy box computation (2 AM)
│   ├── match-auctions/index.ts            # Auction matching (6 AM)
│   └── send-teasers/index.ts              # Novu delivery (6:05 AM)
├── lib/
│   └── posthog/config.ts                  # PostHog tracking functions
└── docs/
    └── BEHAVIORAL_INTELLIGENCE_ARCHITECTURE.docx  # Full architecture doc
```

### New Supabase Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `user_events` | Every tracked behavior | user_id, event_type, entity_type, metadata, session_id |
| `user_buy_boxes` | Computed buy box per user | counties[], zip_affinities[], judgment_range, archetype |
| `user_teasers` | Teasers sent + outcomes | match_score, tier, sent_at, opened_at, action_taken |
| `user_preferences` | Channel preferences | email/push/sms enabled, peak_window, max_teasers |

### pg_cron Schedule

| Time (EST) | Job | Edge Function | Purpose |
|-----------|-----|---------------|---------|
| 2:00 AM | compute_buy_boxes | compute-buy-boxes | Analyze events → build buy boxes |
| 6:00 AM | match_auctions | match-auctions | Match buy boxes × new auctions |
| 6:05 AM | send_teasers | send-teasers | Deliver teasers via Novu |
| 11:00 PM | master_scraper | (existing) | Refresh auction data |

### Teaser Tiers

| Tier | Score | Channels | Timing | Format |
|------|-------|----------|--------|--------|
| 1 | 60-74 | Email digest | Weekly (Monday) | Batch summary |
| 2 | 75-89 | Push + Email | User's peak window | Individual alert |
| 3 | 90-100 | SMS + Push + Email | Immediate | Urgency + curiosity gap |

### User Archetypes (Auto-Classified)

| Archetype | Pattern | Teaser Strategy |
|-----------|---------|----------------|
| Scanner | Daily visits, broad searches, high volume | Volume teasers, many Tier 1 |
| Sniper | Weekly visits, narrow criteria, deep analysis | Few, high-confidence Tier 2-3 only |
| Researcher | Long sessions, uses all agents, generates reports | Data-rich teasers with previews |
| Opportunist | Irregular visits, reacts to alerts | SMS triggers only (Tier 3) |

### Environment Variables Required

```bash
# PostHog
NEXT_PUBLIC_POSTHOG_KEY=phc_xxxxx
NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com

# Novu
NOVU_API_KEY=xxxxx

# Twilio (for Tier 3 SMS via Novu)
TWILIO_ACCOUNT_SID=xxxxx
TWILIO_AUTH_TOKEN=xxxxx
TWILIO_PHONE_NUMBER=+1xxxxxxxxxx

# Firebase Cloud Messaging (for push via Novu)
FCM_SERVER_KEY=xxxxx

# Supabase (already configured)
SUPABASE_URL=https://mocerqjnksmhcjzxrewo.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxx
```

### Implementation Phases

| Phase | Weeks | Focus |
|-------|-------|-------|
| 1 | 1-2 | PostHog tracking + user_events table |
| 2 | 3-4 | Buy box computation + matching engine |
| 3 | 5-6 | Novu + Resend + FCM integration |
| 4 | 7-8 | Twilio SMS + user preferences UI |
| 5 | 9-12 | Feedback loop + A/B testing + archetype tuning |

### Monthly Cost Impact

| Tool | Cost |
|------|------|
| PostHog | $0 (1M events/mo free) |
| Supabase Edge Functions | $0 (included in Pro) |
| Novu | $0 (open source free tier) |
| Resend | $0-20/mo |
| Twilio SMS | $10-15/mo |
| Firebase Cloud Messaging | $0 |
| **Total** | **$10-35/mo** |

---

*Module designed by Claude AI Architect — March 8, 2026*
*Nir Eyal Hooked Model applied to distressed asset intelligence*
