-- ============================================================================
-- BidDeed.AI Behavioral Intelligence Layer
-- Migration: 20260308_behavioral_intelligence.sql
-- 
-- PURPOSE: Nir Eyal Hooked Model — tables for passive behavioral tracking,
--          buy box computation, teaser delivery, and user preferences.
--
-- STATUS: Tables LIVE in production (deployed March 8, 2026)
--         pg_cron jobs NOT active (re-enable after Edge Functions deployed)
--         Edge Functions NOT deployed (code in behavioral-intelligence/supabase/functions/)
--
-- DEPLOY ORDER:
--   1. Run this SQL (tables + indexes + triggers + views) ← DONE
--   2. Deploy Edge Functions via `supabase functions deploy`
--   3. Sign up for PostHog, add JS snippet to frontend
--   4. THEN re-enable pg_cron jobs (Section 5 below)
--   5. Sign up for Novu + connect Resend/FCM/Twilio channels
--
-- Author: Claude AI Architect
-- Date: March 8, 2026 (fixed March 9, 2026)
-- ============================================================================

-- ============================================================================
-- SECTION 1: EXTENSIONS
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- ============================================================================
-- SECTION 2: TABLES
-- NOTE: user_id is UUID NOT NULL but intentionally has NO foreign key to
-- auth.users. This allows:
--   (a) PostHog to write events using distinct_id before Supabase auth signup
--   (b) Flexibility to track anonymous users pre-registration
--   (c) No CASCADE deletion issues during development
-- Add FK constraints when user auth is stable and you want enforcement:
--   ALTER TABLE user_events ADD CONSTRAINT fk_user_events_user
--     FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
-- ============================================================================

-- TABLE 1: user_events
-- Every tracked user behavior from PostHog + chatbot interactions
CREATE TABLE IF NOT EXISTS user_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    -- Event types: search, click, view, analyze, report, watchlist,
    --   skip, dwell, chat_query, agent_invoked, teaser_opened, bid_decision
    entity_type TEXT,
    -- Entity types: property, county, auction, report, agent, teaser
    entity_id TEXT,
    metadata JSONB DEFAULT '{}',
    -- Flexible: county, zip, judgment_amount, market_value, property_type,
    --   equity_spread, strategy, agent, dwell_ms, search_query, tier
    session_id TEXT,
    source TEXT DEFAULT 'web',
    -- Sources: web, chatbot, push, email, sms
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_events_user_id ON user_events(user_id);
CREATE INDEX IF NOT EXISTS idx_user_events_type ON user_events(event_type);
CREATE INDEX IF NOT EXISTS idx_user_events_created ON user_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_events_session ON user_events(session_id);
CREATE INDEX IF NOT EXISTS idx_user_events_entity ON user_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_user_events_user_type_created ON user_events(user_id, event_type, created_at DESC);

-- TABLE 2: user_buy_boxes
-- Computed behavioral buy box per user (rebuilt by Edge Function)
CREATE TABLE IF NOT EXISTS user_buy_boxes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    
    -- Location preferences (weighted by behavior frequency)
    counties JSONB DEFAULT '[]',
    zip_affinities JSONB DEFAULT '[]',
    
    -- Financial parameters (derived from search/click patterns)
    judgment_range JSONB DEFAULT '{"min": null, "max": null}',
    market_value_range JSONB DEFAULT '{"min": null, "max": null}',
    min_equity_spread NUMERIC(5,4),
    max_repair_estimate NUMERIC(12,2),
    
    -- Property preferences
    property_types TEXT[] DEFAULT '{}',
    min_sqft INTEGER,
    min_beds INTEGER,
    
    -- Behavioral profile
    risk_profile TEXT DEFAULT 'moderate',
    strategy_tags TEXT[] DEFAULT '{}',
    
    -- Engagement patterns
    archetype TEXT DEFAULT 'unknown',
    -- Values: scanner, sniper, researcher, opportunist
    peak_activity_window TEXT,
    avg_session_frequency TEXT,
    preferred_channels TEXT[] DEFAULT ARRAY['email'],
    
    -- Confidence & freshness
    confidence_score NUMERIC(3,2) DEFAULT 0.00,
    data_points_count INTEGER DEFAULT 0,
    last_activity TIMESTAMPTZ,
    last_computed TIMESTAMPTZ DEFAULT NOW(),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_buy_boxes_user ON user_buy_boxes(user_id);
CREATE INDEX IF NOT EXISTS idx_user_buy_boxes_confidence ON user_buy_boxes(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_user_buy_boxes_archetype ON user_buy_boxes(archetype);

-- TABLE 3: user_teasers
-- Teasers sent + outcomes (closes the feedback loop)
CREATE TABLE IF NOT EXISTS user_teasers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    
    property_id TEXT,
    county TEXT,
    auction_date DATE,
    
    match_score INTEGER NOT NULL CHECK (match_score BETWEEN 0 AND 100),
    match_reasons JSONB DEFAULT '[]',
    
    tier INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 3),
    -- Tier 1 (60-74): weekly digest email only
    -- Tier 2 (75-89): push + email, during peak window
    -- Tier 3 (90-100): SMS + push + email, immediate
    
    channels TEXT[] DEFAULT '{}',
    teaser_text TEXT,
    
    sent_at TIMESTAMPTZ,
    scheduled_for TIMESTAMPTZ,
    opened_at TIMESTAMPTZ,
    action_taken TEXT,
    -- Values: NULL, viewed, analyzed, reported, watchlisted, bid, ignored
    action_at TIMESTAMPTZ,
    converted BOOLEAN DEFAULT FALSE,
    
    novu_notification_id TEXT,
    delivery_status TEXT DEFAULT 'pending',
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_teasers_user ON user_teasers(user_id);
CREATE INDEX IF NOT EXISTS idx_user_teasers_tier ON user_teasers(tier);
CREATE INDEX IF NOT EXISTS idx_user_teasers_sent ON user_teasers(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_teasers_score ON user_teasers(match_score DESC);
CREATE INDEX IF NOT EXISTS idx_user_teasers_outcome ON user_teasers(action_taken);
CREATE INDEX IF NOT EXISTS idx_user_teasers_property ON user_teasers(property_id);
CREATE INDEX IF NOT EXISTS idx_user_teasers_tier_action ON user_teasers(tier, action_taken);

-- TABLE 4: user_preferences
-- Notification channel preferences (user-controlled)
CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    
    email_enabled BOOLEAN DEFAULT TRUE,
    push_enabled BOOLEAN DEFAULT FALSE,
    sms_enabled BOOLEAN DEFAULT FALSE,
    in_app_enabled BOOLEAN DEFAULT TRUE,
    
    digest_frequency TEXT DEFAULT 'weekly',
    digest_day TEXT DEFAULT 'monday',
    
    peak_window_start TIME DEFAULT '07:00',
    peak_window_end TIME DEFAULT '09:00',
    timezone TEXT DEFAULT 'America/New_York',
    
    min_match_score_for_push INTEGER DEFAULT 75,
    min_match_score_for_sms INTEGER DEFAULT 90,
    max_teasers_per_day INTEGER DEFAULT 5,
    max_sms_per_week INTEGER DEFAULT 3,
    
    phone_number TEXT,
    email_override TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id)
);

-- ============================================================================
-- SECTION 3: ROW LEVEL SECURITY
-- Current: service_role only (no user-facing auth yet)
-- Future: Add auth.uid() policies when user auth flows are built
-- ============================================================================
ALTER TABLE user_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_buy_boxes ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_teasers ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;

-- Service role has full access (Edge Functions, cron jobs, admin)
DO $$ BEGIN
  CREATE POLICY "service_role_events" ON user_events FOR ALL
    USING (current_setting('request.jwt.claim.role', true) = 'service_role');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "service_role_buy_boxes" ON user_buy_boxes FOR ALL
    USING (current_setting('request.jwt.claim.role', true) = 'service_role');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "service_role_teasers" ON user_teasers FOR ALL
    USING (current_setting('request.jwt.claim.role', true) = 'service_role');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "service_role_preferences" ON user_preferences FOR ALL
    USING (current_setting('request.jwt.claim.role', true) = 'service_role');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- TODO: Add these when user auth is active:
-- CREATE POLICY "users_read_own_events" ON user_events FOR SELECT
--   USING (auth.uid() = user_id);
-- CREATE POLICY "users_read_own_buy_box" ON user_buy_boxes FOR SELECT
--   USING (auth.uid() = user_id);
-- CREATE POLICY "users_read_own_teasers" ON user_teasers FOR SELECT
--   USING (auth.uid() = user_id);
-- CREATE POLICY "users_manage_own_preferences" ON user_preferences FOR ALL
--   USING (auth.uid() = user_id);

-- ============================================================================
-- SECTION 4: TRIGGERS + VIEWS
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_buy_boxes_updated ON user_buy_boxes;
CREATE TRIGGER trg_user_buy_boxes_updated
    BEFORE UPDATE ON user_buy_boxes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trg_user_teasers_updated ON user_teasers;
CREATE TRIGGER trg_user_teasers_updated
    BEFORE UPDATE ON user_teasers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trg_user_preferences_updated ON user_preferences;
CREATE TRIGGER trg_user_preferences_updated
    BEFORE UPDATE ON user_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Teaser conversion funnel by tier (last 30 days)
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

-- ============================================================================
-- SECTION 5: pg_cron JOBS (COMMENTED OUT — DO NOT ENABLE UNTIL READY)
-- Prerequisites before uncommenting:
--   1. Edge Functions deployed: compute-buy-boxes, match-auctions, send-teasers
--   2. Vault secret stored: SELECT vault.create_secret('<key>', 'service_role_key');
--   3. Novu API key set as Edge Function secret
--   4. 50+ active users generating behavioral data
-- ============================================================================

-- SELECT cron.schedule(
--     'compute_buy_boxes',
--     '0 7 * * *',  -- 2 AM EST = 7 AM UTC
--     $$ SELECT net.http_post(
--         url := 'https://mocerqjnksmhcjzxrewo.supabase.co/functions/v1/compute-buy-boxes',
--         headers := jsonb_build_object(
--             'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'service_role_key'),
--             'Content-Type', 'application/json'
--         ),
--         body := '{}'::jsonb
--     ); $$
-- );

-- SELECT cron.schedule(
--     'match_auctions',
--     '0 11 * * *',  -- 6 AM EST = 11 AM UTC
--     $$ SELECT net.http_post(
--         url := 'https://mocerqjnksmhcjzxrewo.supabase.co/functions/v1/match-auctions',
--         headers := jsonb_build_object(
--             'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'service_role_key'),
--             'Content-Type', 'application/json'
--         ),
--         body := '{}'::jsonb
--     ); $$
-- );

-- SELECT cron.schedule(
--     'send_teasers',
--     '5 11 * * *',  -- 6:05 AM EST = 11:05 AM UTC
--     $$ SELECT net.http_post(
--         url := 'https://mocerqjnksmhcjzxrewo.supabase.co/functions/v1/send-teasers',
--         headers := jsonb_build_object(
--             'Authorization', 'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'service_role_key'),
--             'Content-Type', 'application/json'
--         ),
--         body := '{}'::jsonb
--     ); $$
-- );

-- ============================================================================
-- VERIFICATION
-- ============================================================================
SELECT 'Behavioral Intelligence migration complete' AS status;
