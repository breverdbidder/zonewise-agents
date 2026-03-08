-- ============================================================================
-- BidDeed.AI Behavioral Intelligence Layer
-- Migration: 20260308_behavioral_intelligence.sql
-- Purpose: Nir Eyal Hooked Model - Trigger → Action → Variable Reward → Investment
-- Author: Claude AI Architect
-- Date: March 8, 2026
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- ============================================================================
-- TABLE 1: user_events
-- Every tracked user behavior from PostHog + chatbot interactions
-- Written by: PostHog webhook / Edge Function
-- Read by: Buy Box Engine (compute_buy_boxes)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    -- Event types: search, click, view, analyze, report, watchlist, skip, dwell, chat_query
    entity_type TEXT,
    -- Entity types: property, county, auction, report, agent, teaser
    entity_id TEXT,
    metadata JSONB DEFAULT '{}',
    -- Flexible metadata: search_terms, filters, dwell_ms, page_url, agent_used, etc.
    session_id TEXT,
    source TEXT DEFAULT 'web',
    -- Sources: web, chatbot, push, email, sms
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_events_user_id ON user_events(user_id);
CREATE INDEX idx_user_events_type ON user_events(event_type);
CREATE INDEX idx_user_events_created ON user_events(created_at DESC);
CREATE INDEX idx_user_events_session ON user_events(session_id);
CREATE INDEX idx_user_events_entity ON user_events(entity_type, entity_id);
-- Composite for buy box computation
CREATE INDEX idx_user_events_user_type_created ON user_events(user_id, event_type, created_at DESC);

-- RLS: Users can only read their own events
ALTER TABLE user_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own events" ON user_events FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Service role full access events" ON user_events FOR ALL USING (auth.role() = 'service_role');

-- ============================================================================
-- TABLE 2: user_buy_boxes
-- Computed behavioral buy box per user (rebuilt nightly by Edge Function)
-- Written by: compute_buy_boxes Edge Function (2 AM cron)
-- Read by: match_auctions Edge Function (6 AM cron)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_buy_boxes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Location preferences (weighted by behavior frequency)
    counties JSONB DEFAULT '[]',
    -- Format: [{"name": "brevard", "weight": 0.85}, {"name": "duval", "weight": 0.35}]
    zip_affinities JSONB DEFAULT '[]',
    -- Format: [{"zip": "32937", "weight": 0.92}, {"zip": "32940", "weight": 0.41}]
    
    -- Financial parameters (derived from search/click patterns)
    judgment_range JSONB DEFAULT '{"min": null, "max": null}',
    market_value_range JSONB DEFAULT '{"min": null, "max": null}',
    min_equity_spread NUMERIC(5,4),
    max_repair_estimate NUMERIC(12,2),
    
    -- Property preferences
    property_types TEXT[] DEFAULT '{}',
    -- Values: SFH, Condo, Townhouse, Multi-Family, Land, Commercial
    min_sqft INTEGER,
    min_beds INTEGER,
    
    -- Behavioral profile
    risk_profile TEXT DEFAULT 'moderate',
    -- Values: conservative, moderate, aggressive
    strategy_tags TEXT[] DEFAULT '{}',
    -- Values: flip, rental, HOA_foreclosure, tax_deed, wholesale, buy_hold
    
    -- Engagement patterns
    archetype TEXT DEFAULT 'unknown',
    -- Values: scanner, sniper, researcher, opportunist
    peak_activity_window TEXT,
    -- Format: "07:00-08:30"
    avg_session_frequency TEXT,
    -- Values: daily, weekly, biweekly, monthly, irregular
    preferred_channels TEXT[] DEFAULT ARRAY['email'],
    -- Values: email, push, sms, in_app
    
    -- Confidence & freshness
    confidence_score NUMERIC(3,2) DEFAULT 0.00,
    -- 0.00 to 1.00, increases with more data points
    data_points_count INTEGER DEFAULT 0,
    last_activity TIMESTAMPTZ,
    last_computed TIMESTAMPTZ DEFAULT NOW(),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id)
);

CREATE INDEX idx_user_buy_boxes_user ON user_buy_boxes(user_id);
CREATE INDEX idx_user_buy_boxes_confidence ON user_buy_boxes(confidence_score DESC);
CREATE INDEX idx_user_buy_boxes_archetype ON user_buy_boxes(archetype);

ALTER TABLE user_buy_boxes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own buy box" ON user_buy_boxes FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Service role full access buy boxes" ON user_buy_boxes FOR ALL USING (auth.role() = 'service_role');

-- ============================================================================
-- TABLE 3: user_teasers
-- Teasers sent + outcomes (closes the feedback loop)
-- Written by: match_auctions Edge Function (6 AM cron)
-- Read by: Novu notification delivery + PostHog feedback
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_teasers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Property match
    property_id TEXT,
    -- References multi_county_auctions.id or case_number
    county TEXT,
    auction_date DATE,
    
    -- Match scoring
    match_score INTEGER NOT NULL CHECK (match_score BETWEEN 0 AND 100),
    match_reasons JSONB DEFAULT '[]',
    -- Format: ["county_match", "equity_above_threshold", "price_in_range"]
    
    -- Teaser tier
    tier INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 3),
    -- Tier 1 (60-74): weekly digest email only
    -- Tier 2 (75-89): push + email, during peak window
    -- Tier 3 (90-100): SMS + push + email, immediate
    
    -- Delivery
    channels TEXT[] DEFAULT '{}',
    -- Channels used: email, push, sms, in_app
    teaser_text TEXT,
    -- The curiosity-gap teaser message sent
    
    -- Timing
    sent_at TIMESTAMPTZ,
    scheduled_for TIMESTAMPTZ,
    -- For Tier 1 digests, scheduled for next weekly email
    
    -- Outcome tracking (updated as user interacts)
    opened_at TIMESTAMPTZ,
    -- NULL if never opened
    action_taken TEXT,
    -- Values: NULL, viewed, analyzed, reported, watchlisted, bid, ignored
    action_at TIMESTAMPTZ,
    converted BOOLEAN DEFAULT FALSE,
    -- Did they eventually bid on this property?
    
    -- Novu tracking
    novu_notification_id TEXT,
    delivery_status TEXT DEFAULT 'pending',
    -- Values: pending, sent, delivered, opened, failed
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_teasers_user ON user_teasers(user_id);
CREATE INDEX idx_user_teasers_tier ON user_teasers(tier);
CREATE INDEX idx_user_teasers_sent ON user_teasers(sent_at DESC);
CREATE INDEX idx_user_teasers_score ON user_teasers(match_score DESC);
CREATE INDEX idx_user_teasers_outcome ON user_teasers(action_taken);
CREATE INDEX idx_user_teasers_property ON user_teasers(property_id);
-- Composite for conversion analytics
CREATE INDEX idx_user_teasers_tier_action ON user_teasers(tier, action_taken);

ALTER TABLE user_teasers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own teasers" ON user_teasers FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Service role full access teasers" ON user_teasers FOR ALL USING (auth.role() = 'service_role');

-- ============================================================================
-- TABLE 4: user_preferences
-- Notification channel preferences (user-controlled)
-- Written by: User settings UI
-- Read by: Novu routing logic
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Channel preferences
    email_enabled BOOLEAN DEFAULT TRUE,
    push_enabled BOOLEAN DEFAULT FALSE,
    sms_enabled BOOLEAN DEFAULT FALSE,
    in_app_enabled BOOLEAN DEFAULT TRUE,
    
    -- Digest preferences
    digest_frequency TEXT DEFAULT 'weekly',
    -- Values: daily, weekly, biweekly, never
    digest_day TEXT DEFAULT 'monday',
    -- Day of week for weekly digest
    
    -- Timing preferences
    peak_window_start TIME DEFAULT '07:00',
    peak_window_end TIME DEFAULT '09:00',
    timezone TEXT DEFAULT 'America/New_York',
    
    -- Content preferences
    min_match_score_for_push INTEGER DEFAULT 75,
    min_match_score_for_sms INTEGER DEFAULT 90,
    max_teasers_per_day INTEGER DEFAULT 5,
    max_sms_per_week INTEGER DEFAULT 3,
    
    -- Contact info (for SMS/email delivery)
    phone_number TEXT,
    email_override TEXT,
    -- If NULL, uses auth.users email
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id)
);

ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own preferences" ON user_preferences FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Service role full access preferences" ON user_preferences FOR ALL USING (auth.role() = 'service_role');

-- ============================================================================
-- FUNCTIONS: Updated_at trigger
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_user_buy_boxes_updated
    BEFORE UPDATE ON user_buy_boxes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_user_teasers_updated
    BEFORE UPDATE ON user_teasers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_user_preferences_updated
    BEFORE UPDATE ON user_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- pg_cron SCHEDULED JOBS
-- These call Edge Functions on schedule
-- NOTE: Replace <project-ref> with mocerqjnksmhcjzxrewo
-- NOTE: Store service_role key in vault first:
--   SELECT vault.create_secret('service_role_key', '<key>');
-- ============================================================================

-- Job 1: Compute buy boxes from behavioral data (2 AM EST = 7 AM UTC)
SELECT cron.schedule(
    'compute_buy_boxes',
    '0 7 * * *',
    $$
    SELECT net.http_post(
        url := 'https://mocerqjnksmhcjzxrewo.supabase.co/functions/v1/compute-buy-boxes',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{}'
    );
    $$
);

-- Job 2: Match auctions against buy boxes (6 AM EST = 11 AM UTC)
SELECT cron.schedule(
    'match_auctions',
    '0 11 * * *',
    $$
    SELECT net.http_post(
        url := 'https://mocerqjnksmhcjzxrewo.supabase.co/functions/v1/match-auctions',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{}'
    );
    $$
);

-- Job 3: Send teasers via Novu (6:05 AM EST = 11:05 AM UTC)
SELECT cron.schedule(
    'send_teasers',
    '5 11 * * *',
    $$
    SELECT net.http_post(
        url := 'https://mocerqjnksmhcjzxrewo.supabase.co/functions/v1/send-teasers',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{}'
    );
    $$
);

-- ============================================================================
-- ANALYTICS VIEWS
-- ============================================================================

-- Teaser conversion funnel by tier
CREATE OR REPLACE VIEW v_teaser_funnel AS
SELECT
    tier,
    COUNT(*) AS total_sent,
    COUNT(opened_at) AS total_opened,
    COUNT(action_taken) FILTER (WHERE action_taken IS NOT NULL) AS total_acted,
    COUNT(*) FILTER (WHERE action_taken = 'reported') AS total_reported,
    COUNT(*) FILTER (WHERE action_taken = 'watchlisted') AS total_watchlisted,
    COUNT(*) FILTER (WHERE converted = TRUE) AS total_converted,
    ROUND(COUNT(opened_at)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 1) AS open_rate_pct,
    ROUND(COUNT(*) FILTER (WHERE converted)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 1) AS conversion_rate_pct
FROM user_teasers
WHERE sent_at > NOW() - INTERVAL '30 days'
GROUP BY tier
ORDER BY tier;

-- Buy box confidence distribution
CREATE OR REPLACE VIEW v_buy_box_health AS
SELECT
    archetype,
    COUNT(*) AS user_count,
    ROUND(AVG(confidence_score), 2) AS avg_confidence,
    ROUND(AVG(data_points_count), 0) AS avg_data_points,
    MIN(last_computed) AS oldest_computation
FROM user_buy_boxes
WHERE confidence_score > 0
GROUP BY archetype;

-- Verification
SELECT 'Behavioral Intelligence migration complete!' AS status;
SELECT 'Tables created: user_events, user_buy_boxes, user_teasers, user_preferences' AS tables;
SELECT 'Cron jobs: compute_buy_boxes (2AM), match_auctions (6AM), send_teasers (6:05AM)' AS cron;
SELECT 'Views: v_teaser_funnel, v_buy_box_health' AS views;
