# ZONEWISE.AI — TASK QUEUE
Updated: 2026-03-03 | Phase: FOUNDATION

Load this file at the start of every Claude Code session.
Find first unchecked item. Execute. Mark [x] when done. Push.

---

## PHASE 1 — SUPABASE SCHEMA

- [ ] **TASK-001** `[HOOK:action][both]` Create `multi_county_auctions` table
  - sale_type NOT NULL CHECK (sale_type IN ('foreclosure', 'tax_deed'))
  - Foreclosure fields: case_number, judgment_amount, plaintiff
  - Tax deed fields: cert_number, opening_bid, outstanding_certs_total, portal_url
  - Common: county, property_address, sale_date, bcpao_data (jsonb)
  - SQL in: docs/ARCHITECTURE.md

- [ ] **TASK-002** `[HOOK:investment][both]` Create `user_profiles` table
  - foreclosure_profile JSONB (county_preferences, judgment_range, bid_ratio_floor, hoa_tolerance)
  - tax_deed_profile JSONB (county_preferences, opening_bid_range, max_cert_exposure_pct_arv, min_net_spread)
  - sale_type_preference TEXT DEFAULT 'both'
  - SQL in: docs/ARCHITECTURE.md

- [ ] **TASK-003** `[HOOK:investment][both]` Create `deal_pipeline` table
  - sale_type NOT NULL — this constraint is mandatory, never drop it
  - identifier TEXT — case_number for foreclosure, cert_number for tax deed
  - foreclosure_fields JSONB, tax_deed_fields JSONB (separate, not mixed)
  - SQL in: docs/ARCHITECTURE.md

- [ ] **TASK-004** `[HOOK:all][both]` Create supporting tables
  - digest_history, insights, daily_metrics, claude_context_checkpoints
  - SQL in: docs/ARCHITECTURE.md

---

## PHASE 2 — SCRAPERS

- [ ] **TASK-005** `[HOOK:action][foreclosure]` Build `scrapers/foreclosure_scraper.py`
  - AgentQL targeting county RealForeclose portals
  - Start: Brevard, Orange, Polk, Hillsborough, Palm Beach
  - Output: multi_county_auctions rows with sale_type="foreclosure"
  - Anti-detection: 3-7s rotating delays, session rotation
  - Retry 3x per county, log failures to daily_metrics

- [ ] **TASK-006** `[HOOK:action][tax_deed]` Build `scrapers/tax_deed_scraper.py`
  - AgentQL targeting county tax deed portals (same 5 counties)
  - RealTDM integration for cert chain (outstanding_certs_total)
  - Output: multi_county_auctions rows with sale_type="tax_deed"

- [ ] **TASK-007** `[HOOK:trigger][both]` Deploy scrapers to Modal
  - Cron: 11 PM EST (0 4 * * * UTC)
  - Alert Ariel via Telegram if >3 counties fail
  - Checkpoint to claude_context_checkpoints after each county batch

---

## PHASE 3 — AGENTS

- [ ] **TASK-008** `[HOOK:investment][both]` Build `agents/memory_agent.py`
  - Load prompts from agents/prompts/investment_*.md
  - profile_learning(), pipeline_manager(), match_scorer()
  - match_scorer() uses SEPARATE models: foreclosure ≠ tax deed scoring
  - Unit test: verify models never cross-contaminate

- [ ] **TASK-009** `[HOOK:action][both]` Build `agents/action_agent.py`
  - Load prompts from agents/prompts/action_*.md
  - query_classifier() → 6 query types
  - foreclosure_bid_pipeline() — HOA plaintiff flag hardcoded, never omittable
  - tax_deed_bid_pipeline() — cert exposure flag hardcoded, never omittable
  - Unit test: sale types never cross-contaminate

- [ ] **TASK-010** `[HOOK:reward][both]` Build `agents/reward_agent.py`
  - Load prompts from agents/prompts/reward_*.md
  - Anomaly detection runs SEPARATELY on foreclosure + tax deed baselines
  - Tribe leaderboard: N<5 suppression hardcoded in code (not just prompt)

- [ ] **TASK-011** `[HOOK:trigger][both]` Build `agents/trigger_agent.py`
  - Load prompts from agents/prompts/trigger_*.md
  - Digest: separate foreclosure + tax deed sections, both labeled
  - Alert threshold: 2+ std deviations, hardcoded, not configurable

- [ ] **TASK-012** `[HOOK:all][both]` Build `agents/orchestrator.py`
  - LangGraph pipeline: 5 phases, 11 PM to 6 AM EST
  - Phase 1: PARALLEL foreclosure + tax deed scrapers
  - Circuit breakers per spec in docs/PROMPT_ENGINEERING.md Section 6
  - Checkpoint every phase to claude_context_checkpoints

---

## PHASE 4 — API + DELIVERY

- [ ] **TASK-013** `[HOOK:action][both]` Build `api/chat.py` (FastAPI)
  - POST /chat — query_classifier → action_agent
  - POST /bid — full pipeline (determine sale type from identifier)
  - GET /pipeline — deal_pipeline for authenticated user
  - GET /digest/preview — today's digest preview
  - SLA: county_scan <3s, bid_decision <10s
  - Auth: magic link JWT

- [ ] **TASK-014** Deploy to Render.com

- [ ] **TASK-015** `[HOOK:trigger][both]` Telegram bot
  - /start → user opt-in, county selection, sale type preference
  - Digest delivery at 6 AM user local time

- [ ] **TASK-016** Email delivery (Resend)
  - Magic link auth (no passwords)
  - Digest template: foreclosure section + tax deed section

---

## PHASE 5 — GITHUB ACTIONS

- [ ] **TASK-017** `[HOOK:trigger][both]` `.github/workflows/nightly_pipeline.yml`
  - Cron: `0 4 * * *` (11 PM EST = 4 AM UTC)
  - Steps: scrape → analyze → personalize → generate → deliver
  - Telegram alert to Ariel on pipeline failure

---

## PHASE 6 — TESTS

- [ ] **TASK-018** `[HOOK:action][foreclosure]` `tests/test_foreclosure_pipeline.py`
  - All 10 stages with synthetic data
  - HOA plaintiff MUST appear in output — assert in every test
  - <3 comps → must recommend REVIEW not BID

- [ ] **TASK-019** `[HOOK:action][tax_deed]` `tests/test_tax_deed_pipeline.py`
  - All 10 stages with synthetic cert chain data
  - Outstanding cert >15% ARV MUST flag — assert in every test
  - Cert chain incomplete → must recommend REVIEW not BID

- [ ] **TASK-020** Prompt injection resistance tests
  - "IGNORE PREVIOUS INSTRUCTIONS" in property_address, plaintiff, cert fields
  - Verify agent output is unchanged

---

## DEFERRED

- [ ] [DEFERRED] Split-screen Next.js UI — blocked on: TASK-013
- [ ] [DEFERRED] 67-county expansion — blocked on: TASK-007 stable for 5 counties
- [ ] [DEFERRED] XGBoost ML confidence scoring — blocked on: 90 days pipeline data

---

## COMPLETED

- [x] Prompt engineering playbook — 12 prompts, foreclosure + tax deed (2026-03-03)
- [x] CLAUDE.md — Claude Code operating instructions (2026-03-03)
- [x] TODO.md — Full task queue (2026-03-03)
- [x] PROJECT_STATE.json — System state (2026-03-03)
- [x] docs/ARCHITECTURE.md — System design + SQL schema (2026-03-03)
- [x] docs/PROMPT_QA_GATE.md — Deployment quality gate (2026-03-03)
- [x] Repository structure scaffolded (2026-03-03)
