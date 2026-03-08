# Behavioral Intelligence Agents

## Overview

The Behavioral Intelligence module adds passive user tracking and automated teaser delivery
to the BidDeed.AI/ZoneWise ecosystem. Full implementation lives in `breverdbidder/biddeed-ai`.

## Agent Integration Points

The following LangGraph agents can feed behavioral signals:

| Agent | Event Type | Metadata |
|-------|-----------|----------|
| Auction Scout | `auction_search` | counties, price_range, filters |
| Equity Analyzer | `equity_analysis` | property_id, equity_spread |
| Lien Researcher | `lien_search` | property_id, lien_count |
| Comp Analyzer | `comp_analysis` | property_id, arv_estimate |
| Historical Outcomes | `historical_query` | county, zip, date_range |
| Report Generator | `report_generated` | property_id, report_type |
| Watchlist Manager | `watchlist_added` | property_id, criteria |

## Supabase Tables (Shared)

These tables are created by `migrations/20260308_behavioral_intelligence.sql`:

- `user_events` — Written by PostHog webhook + agent completions
- `user_buy_boxes` — Read by match-auctions Edge Function
- `user_teasers` — Read by send-teasers Edge Function
- `user_preferences` — Read by Novu routing

## Edge Functions (in biddeed-ai repo)

- `compute-buy-boxes` — 2 AM EST nightly
- `match-auctions` — 6 AM EST nightly
- `send-teasers` — 6:05 AM EST nightly

See: https://github.com/breverdbidder/biddeed-ai/tree/main/behavioral-intelligence
