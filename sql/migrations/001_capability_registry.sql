-- ============================================================
-- MIGRATION 001: Capability Registry + CoStar Schema Separation
-- Project: ZoneWise.AI / BidDeed.AI (Everest Capital USA)
-- Supabase: mocerqjnksmhcjzxrewo.supabase.co
-- Date: 2026-02-26
-- Author: Claude AI Architect (autonomous)
-- ============================================================
-- 
-- ARCHITECTURE: CoStar Group model
--   biddeed schema  → BidDeed.AI owns, ZoneWise reads via API only
--   zonewise schema → ZoneWise owns entirely
--   public schema   → shared tables (insights, master_index, capabilities)
-- ============================================================

-- ── 1. CAPABILITY REGISTRY ───────────────────────────────────
-- Web-native replacement for CraftAgents filesystem skills.
-- Add a row → feature appears in ZoneWise chatbot + map interface.
-- No frontend redeploy needed.

CREATE TABLE IF NOT EXISTS public.capabilities (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  slug            TEXT NOT NULL UNIQUE,          -- 'discoverwise', 'lienwise', 'cmawise', 'titlewise'
  name            TEXT NOT NULL,                 -- 'DiscoverWise'
  tagline         TEXT NOT NULL,                 -- 'Distressed asset discovery'
  description     TEXT,
  product         TEXT NOT NULL CHECK (product IN ('zonewise', 'biddeed', 'both')),
  status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'beta', 'coming_soon', 'disabled')),
  tier_required   TEXT NOT NULL DEFAULT 'free' CHECK (tier_required IN ('free', 'pro', 'enterprise')),
  icon_emoji      TEXT DEFAULT '🔍',
  color_hex       TEXT DEFAULT '1E3A5F',
  -- Data source dependencies
  requires_sources JSONB DEFAULT '[]',           -- ["realforeclose", "bcpao", "acclaimweb"]
  -- LangGraph agent routing
  agent_route     TEXT,                          -- 'discoverwise_agent', 'lien_agent', etc.
  api_endpoint    TEXT,                          -- '/api/v1/discoverwise'
  -- Metadata
  sort_order      INTEGER DEFAULT 99,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 2. SEED: Core Capabilities ───────────────────────────────

INSERT INTO public.capabilities (slug, name, tagline, description, product, status, tier_required, icon_emoji, color_hex, requires_sources, agent_route, api_endpoint, sort_order)
VALUES
  (
    'discoverwise',
    'DiscoverWise',
    'Distressed asset discovery at the zoning intersection',
    'Foreclosure and tax deed auction intelligence layered over ZoneWise zoning maps. Shows BID/REVIEW/SKIP ML recommendations, max bid calculations, lien summaries, and BCPAO photos — all within the ZoneWise parcel interface.',
    'both', 'beta', 'pro', '🔍', '1565C0',
    '["realforeclose", "realauction", "bcpao", "acclaimweb", "realtdm"]',
    'discoverwise_agent',
    '/api/v1/discoverwise',
    1
  ),
  (
    'lienwise',
    'LienWise',
    'Lien priority analysis before you bid',
    'Automated AcclaimWeb search by party name. Detects HOA foreclosures (senior mortgage survives), IRS liens, code enforcement, lis pendens. Returns priority-ordered lien stack with red flag alerts.',
    'both', 'beta', 'pro', '⚖️', '006064',
    '["acclaimweb", "bcpao"]',
    'lien_agent',
    '/api/v1/lienwise',
    2
  ),
  (
    'cmawise',
    'CMAwise',
    'Comparable sales for distressed assets',
    'Automated CMA using BCPAO sales history and county property records. Filters comparables by zone type, year built, square footage. Outputs ARV estimate with confidence interval for max bid calculation.',
    'zonewise', 'coming_soon', 'pro', '📊', '2E7D32',
    '["bcpao"]',
    'cma_agent',
    '/api/v1/cmawise',
    3
  ),
  (
    'titlewise',
    'TitleWise',
    'Title red flags before the auction',
    'Pre-bid title search automation. Detects: HOA plaintiff (senior mortgage survives), IRS/federal tax liens, open code enforcement, lis pendens, delinquent tax certificates. Returns clear/caution/stop signal.',
    'zonewise', 'coming_soon', 'pro', '📋', '4A148C',
    '["acclaimweb", "realtdm", "bcpao"]',
    'title_agent',
    '/api/v1/titlewise',
    4
  ),
  (
    'zoneanalyze',
    'ZoneAnalyze',
    'Zoning intelligence and HBU analysis',
    'Core ZoneWise feature. 67-county zoning classification, permitted uses, dimensional standards, highest and best use analysis, 3D building envelope visualization.',
    'zonewise', 'active', 'free', '🗺️', '1E3A5F',
    '[]',
    'zone_agent',
    '/api/v1/zone',
    10
  )
ON CONFLICT (slug) DO UPDATE SET
  updated_at = NOW(),
  status = EXCLUDED.status,
  description = EXCLUDED.description;

-- ── 3. DATA SOURCES REGISTRY ─────────────────────────────────

CREATE TABLE IF NOT EXISTS public.data_sources (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  slug            TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL,
  tagline         TEXT,
  source_type     TEXT NOT NULL CHECK (source_type IN ('scraper', 'api', 'database', 'mcp')),
  base_url        TEXT,
  auth_type       TEXT DEFAULT 'none' CHECK (auth_type IN ('none', 'bearer', 'api_key', 'oauth', 'scrape')),
  -- CraftAgents desktop source config
  craft_config    JSONB,                         -- Full config.json for CraftAgents source
  -- Health
  status          TEXT DEFAULT 'active' CHECK (status IN ('active', 'degraded', 'offline')),
  last_tested_at  TIMESTAMPTZ,
  -- Scraper metadata
  scraper_file    TEXT,                          -- 'src/scrapers/realforeclose_scraper.py'
  counties_covered JSONB DEFAULT '[]',
  -- Metadata
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO public.data_sources (slug, name, tagline, source_type, base_url, auth_type, scraper_file, counties_covered, craft_config)
VALUES
  (
    'realforeclose',
    'RealForeclose',
    'Brevard County foreclosure auction calendar',
    'scraper', 'https://brevard.realforeclose.com', 'scrape',
    'src/scrapers/realforeclose_scraper.py',
    '["Brevard"]',
    '{"type":"api","name":"RealForeclose","slug":"realforeclose","provider":"realforeclose","tagline":"Brevard County foreclosure auction calendar","icon":"🏛️","api":{"baseUrl":"https://brevard.realforeclose.com/","authType":"none"}}'
  ),
  (
    'realauction',
    'RealAuction',
    'Florida statewide online tax deed auctions (67 counties)',
    'scraper', 'https://www.realauction.com', 'scrape',
    'src/scrapers/realauction_scraper.py',
    '["all_67"]',
    '{"type":"api","name":"RealAuction","slug":"realauction","provider":"realauction","tagline":"Florida statewide tax deed auctions — 67 counties","icon":"📜","api":{"baseUrl":"https://www.realauction.com/","authType":"none"}}'
  ),
  (
    'bcpao',
    'BCPAO',
    'Brevard County Property Appraiser — parcel data + photos',
    'api', 'https://www.bcpao.us', 'none',
    'src/scrapers/bcpao_scraper.py',
    '["Brevard"]',
    '{"type":"api","name":"BCPAO","slug":"bcpao","provider":"bcpao","tagline":"Brevard County parcel data, assessments, and property photos","icon":"🏠","api":{"baseUrl":"https://www.bcpao.us/api/v1/","authType":"none"}}'
  ),
  (
    'acclaimweb',
    'AcclaimWeb',
    'Brevard Clerk — mortgages, liens, lis pendens by party name',
    'scraper', 'https://vaclmweb1.brevardclerk.us', 'scrape',
    'src/scrapers/acclaimweb_scraper.py',
    '["Brevard"]',
    '{"type":"api","name":"AcclaimWeb","slug":"acclaimweb","provider":"acclaimweb","tagline":"Brevard Clerk official records — mortgages, liens, lis pendens","icon":"⚖️","api":{"baseUrl":"https://vaclmweb1.brevardclerk.us/","authType":"none"}}'
  ),
  (
    'realtdm',
    'RealTDM',
    'Tax certificate and tax deed management',
    'scraper', 'https://realtdm.com', 'scrape',
    'src/scrapers/realtdm_scraper.py',
    '["Brevard"]',
    '{"type":"api","name":"RealTDM","slug":"realtdm","provider":"realtdm","tagline":"Tax certificates and tax deed management for Brevard County","icon":"📋","api":{"baseUrl":"https://realtdm.com/","authType":"none"}}'
  )
ON CONFLICT (slug) DO UPDATE SET updated_at = NOW();

-- ── 4. USER CAPABILITIES (tier gating) ───────────────────────

CREATE TABLE IF NOT EXISTS public.user_capabilities (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id         UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  capability_slug TEXT REFERENCES public.capabilities(slug),
  granted_at      TIMESTAMPTZ DEFAULT NOW(),
  granted_by      TEXT DEFAULT 'system',         -- 'system', 'admin', 'upgrade'
  expires_at      TIMESTAMPTZ,                   -- NULL = never expires
  UNIQUE(user_id, capability_slug)
);

-- ── 5. CAPABILITY USAGE LOG ───────────────────────────────────

CREATE TABLE IF NOT EXISTS public.capability_usage (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id         UUID,
  capability_slug TEXT,
  session_id      TEXT,
  query_summary   TEXT,
  tokens_used     INTEGER,
  latency_ms      INTEGER,
  status          TEXT CHECK (status IN ('success', 'error', 'timeout')),
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 6. RLS POLICIES ──────────────────────────────────────────

ALTER TABLE public.capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.capability_usage ENABLE ROW LEVEL SECURITY;

-- Capabilities: public read, service-role write
CREATE POLICY "capabilities_public_read" ON public.capabilities
  FOR SELECT USING (true);
CREATE POLICY "capabilities_service_write" ON public.capabilities
  FOR ALL USING (auth.role() = 'service_role');

-- Data sources: public read, service-role write
CREATE POLICY "sources_public_read" ON public.data_sources
  FOR SELECT USING (true);
CREATE POLICY "sources_service_write" ON public.data_sources
  FOR ALL USING (auth.role() = 'service_role');

-- User capabilities: users see their own only
CREATE POLICY "user_caps_own" ON public.user_capabilities
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "user_caps_service" ON public.user_capabilities
  FOR ALL USING (auth.role() = 'service_role');

-- Usage log: service role only
CREATE POLICY "usage_service_only" ON public.capability_usage
  FOR ALL USING (auth.role() = 'service_role');

-- ── 7. HELPER VIEWS ──────────────────────────────────────────

-- Active capabilities with source count
CREATE OR REPLACE VIEW public.capabilities_summary AS
SELECT
  c.*,
  jsonb_array_length(c.requires_sources) as source_count,
  (SELECT COUNT(*) FROM public.capability_usage u
   WHERE u.capability_slug = c.slug
   AND u.created_at > NOW() - INTERVAL '24 hours') as usage_24h
FROM public.capabilities c
WHERE c.status != 'disabled'
ORDER BY c.sort_order;

-- Source health dashboard
CREATE OR REPLACE VIEW public.sources_health AS
SELECT
  s.slug, s.name, s.status, s.last_tested_at,
  (SELECT COUNT(*) FROM public.capabilities c
   WHERE c.requires_sources @> to_jsonb(s.slug::text)) as used_by_capabilities
FROM public.data_sources s
ORDER BY s.slug;

-- ── 8. UPDATED_AT TRIGGER ─────────────────────────────────────

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER capabilities_updated_at
  BEFORE UPDATE ON public.capabilities
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER sources_updated_at
  BEFORE UPDATE ON public.data_sources
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ── DONE ──────────────────────────────────────────────────────
-- Run: psql "$DATABASE_URL" -f sql/migrations/001_capability_registry.sql
-- Verify: SELECT slug, name, status FROM capabilities ORDER BY sort_order;
