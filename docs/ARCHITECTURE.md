# ZONEWISE.AI — SYSTEM ARCHITECTURE
Updated: 2026-03-03

## Two Sale Types

| | Foreclosure Sale | Tax Deed Sale |
|--|--|--|
| **Triggered by** | Lender or HOA judgment | Unpaid property taxes |
| **Run by** | Clerk of Court | County Tax Collector |
| **Venue** | Courthouse or RealForeclose online | County portal (RealForeclose) |
| **Key metric** | Bid / Judgment ratio | ARV − Opening Bid − Cert Exposure |
| **Critical risk** | HOA plaintiff = senior mortgage survives | Outstanding cert chain exposure |
| **Lien source** | AcclaimWeb | RealTDM |
| **Sale source** | RealForeclose | County portal |
| **Property source** | BCPAO | BCPAO |

## Hook Model Data Flow

```
11 PM EST — TRIGGER fires
    ↓
[PARALLEL]
Foreclosure Scraper (AgentQL → RealForeclose)
Tax Deed Scraper    (AgentQL → county portals + RealTDM)
    ↓
multi_county_auctions (Supabase) — sale_type NOT NULL
    ↓
[PARALLEL ANALYSIS]
Memory Agent  → pull user profiles
Reward Agent  → anomaly detection (separate foreclosure + tax deed baselines)
Action Agent  → pre-process top matches per user per sale type
    ↓
[PERSONALIZE]
Memory Agent  → match score every property (separate scoring models)
    ↓
[GENERATE + DELIVER]
Trigger Agent → personalized digest (labeled sections per sale type)
→ Telegram + Email → 6 AM delivery

REAL-TIME — ACTION fires on user query
    ↓
POST /chat → query_classifier (6 types)
    ├─ COUNTY_SCAN     → Scraper data
    ├─ DEEP_DIVE       → Lien/cert agent
    ├─ MARKET_QUESTION → Reward agent
    ├─ PORTFOLIO       → Memory agent
    └─ BID_DECISION
           ├─ Foreclosure pipeline (10 stages)
           └─ Tax deed pipeline    (10 stages)

SUNDAY 6 PM — REWARD fires
    ↓
Reward Agent → anomaly detection
→ one unexpected insight per user (labeled by sale type)

AFTER EVERY SESSION — INVESTMENT fires
    ↓
Memory Agent → extract behavioral signal
→ update user_profiles (separate foreclosure + tax deed sub-profiles)
```

## LangGraph State

```python
from typing import TypedDict, Literal, Optional

class ZoneWiseState(TypedDict):
    user_id: str
    session_id: str
    sale_type: Literal["foreclosure", "tax_deed", "both"]
    query: str
    query_type: Literal["COUNTY_SCAN","DEEP_DIVE","MARKET_QUESTION","PORTFOLIO","BID_DECISION","CLARIFICATION_NEEDED"]
    county: str
    identifier: str          # case_number or cert_number
    property_data: dict
    pipeline_stage: int
    recommendation: Optional[Literal["BID", "REVIEW", "SKIP"]]
    confidence: float
    audit_trail: list
    user_profile: dict
    messages: list
```

## Supabase Schema (full SQL)

```sql
-- ── multi_county_auctions ──────────────────────────────────────────────
CREATE TABLE multi_county_auctions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sale_type TEXT NOT NULL CHECK (sale_type IN ('foreclosure', 'tax_deed')),
    county TEXT NOT NULL,
    property_address TEXT,
    sale_date DATE,
    bcpao_data JSONB,
    -- Foreclosure only (null for tax deed)
    case_number TEXT,
    judgment_amount NUMERIC,
    plaintiff TEXT,
    courthouse_or_online TEXT,
    -- Tax deed only (null for foreclosure)
    cert_number TEXT,
    opening_bid NUMERIC,
    outstanding_certs_total NUMERIC,
    portal_url TEXT,
    redemption_deadline DATE,
    -- Meta
    scrape_timestamp TIMESTAMPTZ DEFAULT now(),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_auctions_sale_type ON multi_county_auctions(sale_type);
CREATE INDEX idx_auctions_county_date ON multi_county_auctions(county, sale_date);

-- ── user_profiles ──────────────────────────────────────────────────────
CREATE TABLE user_profiles (
    user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE,
    sale_type_preference TEXT DEFAULT 'both' CHECK (sale_type_preference IN ('foreclosure', 'tax_deed', 'both')),
    -- Separate JSONB for each sale type — never merge these
    foreclosure_profile JSONB DEFAULT '{}',
    -- foreclosure_profile schema:
    -- { county_preferences: [{county, rank, confidence}],
    --   judgment_range: {min, max, confidence},
    --   bid_ratio_floor: number,
    --   hoa_tolerance: "avoids"|"accepts_with_senior_check"|"accepts" }
    tax_deed_profile JSONB DEFAULT '{}',
    -- tax_deed_profile schema:
    -- { county_preferences: [{county, rank, confidence}],
    --   opening_bid_range: {min, max},
    --   max_cert_exposure_pct_arv: number,
    --   min_net_spread: number }
    risk_tolerance TEXT CHECK (risk_tolerance IN ('conservative', 'calculated', 'aggressive')),
    exit_preferences TEXT[],
    strategy_summary TEXT,
    data_confidence NUMERIC DEFAULT 0 CHECK (data_confidence BETWEEN 0 AND 1),
    interactions_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── deal_pipeline ──────────────────────────────────────────────────────
CREATE TABLE deal_pipeline (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES user_profiles(user_id),
    sale_type TEXT NOT NULL CHECK (sale_type IN ('foreclosure', 'tax_deed')),
    identifier TEXT NOT NULL,  -- case_number or cert_number
    address TEXT,
    county TEXT,
    sale_date DATE,
    recommendation TEXT CHECK (recommendation IN ('BID', 'REVIEW', 'SKIP')),
    confidence_pct NUMERIC,
    arv_estimate NUMERIC,
    repair_estimate NUMERIC,
    key_risk TEXT,
    key_signal TEXT,
    user_notes TEXT,
    -- Foreclosure-specific fields (null for tax deed rows)
    foreclosure_fields JSONB DEFAULT '{}',
    -- { judgment, max_bid_calculated, bid_judgment_ratio, plaintiff, lien_flags[] }
    -- Tax deed-specific fields (null for foreclosure rows)
    tax_deed_fields JSONB DEFAULT '{}',
    -- { opening_bid, outstanding_certs_total, cert_chain_summary, net_spread_calculated }
    outcome TEXT CHECK (outcome IN ('won', 'lost', 'passed', 'postponed')),
    outcome_price NUMERIC,
    outcome_date DATE,
    saved_date TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_pipeline_user_sale_type ON deal_pipeline(user_id, sale_type);

-- ── digest_history ─────────────────────────────────────────────────────
CREATE TABLE digest_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES user_profiles(user_id),
    digest_date DATE,
    status TEXT DEFAULT 'generated' CHECK (status IN ('generated', 'delivered', 'failed')),
    delivered_at TIMESTAMPTZ,
    foreclosure_matches INTEGER DEFAULT 0,
    tax_deed_matches INTEGER DEFAULT 0,
    insight_sale_type TEXT,
    insight_summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ── insights ───────────────────────────────────────────────────────────
CREATE TABLE insights (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    county TEXT,
    sale_type TEXT NOT NULL CHECK (sale_type IN ('foreclosure', 'tax_deed', 'both')),
    anomaly_type TEXT,
    std_deviation NUMERIC,
    description TEXT,
    properties_affected JSONB,
    detected_at TIMESTAMPTZ DEFAULT now()
);

-- ── daily_metrics ──────────────────────────────────────────────────────
CREATE TABLE daily_metrics (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_date DATE UNIQUE,
    digest_delivery_rate NUMERIC,
    foreclosure_counties_scraped INTEGER DEFAULT 0,
    tax_deed_counties_scraped INTEGER DEFAULT 0,
    foreclosure_properties_analyzed INTEGER DEFAULT 0,
    tax_deed_certs_analyzed INTEGER DEFAULT 0,
    anomalies_foreclosure INTEGER DEFAULT 0,
    anomalies_tax_deed INTEGER DEFAULT 0,
    avg_match_score NUMERIC,
    pipeline_runtime_minutes NUMERIC,
    errors_count INTEGER DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0
);

-- ── claude_context_checkpoints ─────────────────────────────────────────
CREATE TABLE claude_context_checkpoints (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_date DATE,
    checkpoint_phase TEXT CHECK (checkpoint_phase IN ('1','2','3','4','5')),
    foreclosure_counties_scraped INTEGER DEFAULT 0,
    tax_deed_counties_scraped INTEGER DEFAULT 0,
    counties_failed JSONB DEFAULT '{"foreclosure": [], "tax_deed": []}',
    users_processed INTEGER DEFAULT 0,
    digests_generated INTEGER DEFAULT 0,
    digests_delivered INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]',
    resume_from TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

## Foreclosure BID Pipeline (10 stages)

```
Stage 1:  BCPAO API         → ARV estimate, property details, photos
Stage 2:  AcclaimWeb        → all mortgages, HOA liens, judgment liens
Stage 3:  RealTDM           → outstanding tax certificates
Stage 4:  Comparable sales  → last 6mo, 0.5mi radius, same bed/bath/type
Stage 5:  Repair estimate   → condition-based from property data
Stage 6:  Max bid calc      → (ARV × 70%) - Repairs - $10K - MIN($25K, 15%×ARV)
Stage 7:  Bid/judgment ratio → BID ≥75% | REVIEW 60-74% | SKIP <60%
Stage 8:  Lien priority     → HOA plaintiff? → senior mortgage survives flag
Stage 9:  ML confidence     → historical Brevard pattern match
Stage 10: Timeline          → days to sale, procedural issues
```

## Tax Deed BID Pipeline (10 stages)

```
Stage 1:  BCPAO API         → property details, assessed value
Stage 2:  RealTDM           → full cert chain, face amounts, interest, redemption status
Stage 3:  Tax Collector     → opening bid, additional fees, redemption deadline
Stage 4:  AcclaimWeb        → surviving liens check (mortgages generally extinguished)
Stage 5:  Comparable sales  → last 6mo, 0.5mi radius
Stage 6:  Repair estimate   → condition-based
Stage 7:  Net spread calc   → ARV - Opening Bid - Cert Total - Repairs - Closing
Stage 8:  Compare to user   → net spread vs user's minimum threshold
Stage 9:  ML confidence     → historical tax deed outcomes in county
Stage 10: Timeline          → bidding window, deposit requirements
```
