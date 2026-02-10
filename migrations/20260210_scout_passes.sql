-- ============================================================================
-- ZoneWise.AI Scout Pass Referral System
-- Migration: 20260210_scout_passes.sql
-- Deploys: Supabase (mocerqjnksmhcjzxrewo)
-- ============================================================================

-- 1. Scout Passes table - tracks each pass a paid user can distribute
CREATE TABLE IF NOT EXISTS scout_passes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Who owns this pass
  referrer_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  referrer_email TEXT NOT NULL,
  
  -- Pass details
  pass_code TEXT UNIQUE NOT NULL DEFAULT encode(gen_random_bytes(6), 'hex'),
  status TEXT NOT NULL DEFAULT 'available' 
    CHECK (status IN ('available', 'shared', 'claimed', 'expired', 'revoked')),
  
  -- When shared (link generated)
  shared_at TIMESTAMPTZ,
  shared_via TEXT CHECK (shared_via IN ('email', 'link', 'dashboard', 'api')),
  
  -- When claimed by recipient
  recipient_id UUID REFERENCES auth.users(id),
  recipient_email TEXT,
  claimed_at TIMESTAMPTZ,
  
  -- Trial window
  trial_start TIMESTAMPTZ,
  trial_end TIMESTAMPTZ,
  
  -- Which counties the recipient can access (inherits from referrer)
  county_access JSONB DEFAULT '[]'::jsonb,
  
  -- Pass generation context
  quarter TEXT NOT NULL,  -- e.g., '2026-Q1'
  batch_number INTEGER NOT NULL DEFAULT 1,
  
  -- Expiry (passes expire 30 days after generation if not shared)
  expires_at TIMESTAMPTZ NOT NULL,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Referral rewards - tracks benefits earned by referrers
CREATE TABLE IF NOT EXISTS referral_rewards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  pass_id UUID NOT NULL REFERENCES scout_passes(id),
  
  -- Reward type
  reward_type TEXT NOT NULL CHECK (reward_type IN (
    'trial_extension',     -- +7 days for each accepted invite
    'month_free',          -- top referrer quarterly prize
    'county_unlock',       -- bonus county access
    'feature_upgrade'      -- premium feature unlock
  )),
  
  -- Reward details
  reward_value JSONB NOT NULL,  -- e.g., {"days": 7} or {"county": "Orange"}
  
  -- Status
  status TEXT NOT NULL DEFAULT 'pending' 
    CHECK (status IN ('pending', 'applied', 'expired')),
  applied_at TIMESTAMPTZ,
  
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Referral leaderboard - aggregated stats per user per quarter
CREATE TABLE IF NOT EXISTS referral_leaderboard (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  quarter TEXT NOT NULL,  -- e.g., '2026-Q1'
  
  -- Stats
  passes_generated INTEGER DEFAULT 0,
  passes_shared INTEGER DEFAULT 0,
  passes_claimed INTEGER DEFAULT 0,
  passes_converted INTEGER DEFAULT 0,  -- claimed → paid subscriber
  
  -- Rewards earned
  days_earned INTEGER DEFAULT 0,
  
  -- Ranking
  rank INTEGER,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  UNIQUE(user_id, quarter)
);

-- 4. Referral events - full audit trail
CREATE TABLE IF NOT EXISTS referral_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  pass_id UUID REFERENCES scout_passes(id),
  event_type TEXT NOT NULL CHECK (event_type IN (
    'pass_generated',
    'pass_shared',
    'link_clicked',
    'signup_started',
    'card_entered',
    'trial_activated',
    'trial_expired',
    'converted_to_paid',
    'reward_granted',
    'pass_expired'
  )),
  
  -- Context
  actor_id UUID REFERENCES auth.users(id),
  metadata JSONB DEFAULT '{}'::jsonb,
  ip_address INET,
  user_agent TEXT,
  
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ──
CREATE INDEX idx_scout_passes_referrer ON scout_passes(referrer_id);
CREATE INDEX idx_scout_passes_status ON scout_passes(status);
CREATE INDEX idx_scout_passes_code ON scout_passes(pass_code);
CREATE INDEX idx_scout_passes_quarter ON scout_passes(quarter);
CREATE INDEX idx_scout_passes_recipient ON scout_passes(recipient_id);
CREATE INDEX idx_referral_rewards_user ON referral_rewards(user_id);
CREATE INDEX idx_referral_leaderboard_quarter ON referral_leaderboard(quarter, rank);
CREATE INDEX idx_referral_events_pass ON referral_events(pass_id);
CREATE INDEX idx_referral_events_type ON referral_events(event_type);
CREATE INDEX idx_referral_events_created ON referral_events(created_at DESC);

-- ── RLS Policies ──
ALTER TABLE scout_passes ENABLE ROW LEVEL SECURITY;
ALTER TABLE referral_rewards ENABLE ROW LEVEL SECURITY;
ALTER TABLE referral_leaderboard ENABLE ROW LEVEL SECURITY;
ALTER TABLE referral_events ENABLE ROW LEVEL SECURITY;

-- Users can see their own passes
CREATE POLICY "Users view own passes" ON scout_passes
  FOR SELECT USING (auth.uid() = referrer_id OR auth.uid() = recipient_id);

-- Users can update their own available passes (share them)
CREATE POLICY "Users share own passes" ON scout_passes
  FOR UPDATE USING (auth.uid() = referrer_id AND status = 'available');

-- Users can see their own rewards
CREATE POLICY "Users view own rewards" ON referral_rewards
  FOR SELECT USING (auth.uid() = user_id);

-- Leaderboard is public (read-only)
CREATE POLICY "Public leaderboard read" ON referral_leaderboard
  FOR SELECT USING (true);

-- Events: users see events for their passes
CREATE POLICY "Users view own events" ON referral_events
  FOR SELECT USING (
    pass_id IN (SELECT id FROM scout_passes WHERE referrer_id = auth.uid() OR recipient_id = auth.uid())
  );

-- ── Functions ──

-- Generate quarterly passes for a paid user (called on subscription or quarterly reset)
CREATE OR REPLACE FUNCTION generate_scout_passes(
  p_user_id UUID,
  p_user_email TEXT,
  p_county_access JSONB DEFAULT '[]'::jsonb,
  p_quarter TEXT DEFAULT NULL
)
RETURNS SETOF scout_passes
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_quarter TEXT;
  v_existing INTEGER;
BEGIN
  v_quarter := COALESCE(p_quarter, 
    EXTRACT(YEAR FROM NOW())::TEXT || '-Q' || CEIL(EXTRACT(MONTH FROM NOW()) / 3.0)::TEXT
  );
  
  -- Check how many passes already exist for this user this quarter
  SELECT COUNT(*) INTO v_existing
  FROM scout_passes
  WHERE referrer_id = p_user_id AND quarter = v_quarter;
  
  -- Max 3 per quarter
  IF v_existing >= 3 THEN
    RAISE EXCEPTION 'User already has 3 passes for %', v_quarter;
  END IF;
  
  -- Generate remaining passes (up to 3)
  RETURN QUERY
  INSERT INTO scout_passes (
    referrer_id, referrer_email, county_access, quarter, 
    batch_number, expires_at
  )
  SELECT 
    p_user_id, p_user_email, p_county_access, v_quarter,
    v_existing + row_number() OVER (),
    NOW() + INTERVAL '30 days'
  FROM generate_series(1, 3 - v_existing)
  RETURNING *;
END;
$$;

-- Claim a scout pass (called when recipient signs up + enters card)
CREATE OR REPLACE FUNCTION claim_scout_pass(
  p_pass_code TEXT,
  p_recipient_id UUID,
  p_recipient_email TEXT
)
RETURNS scout_passes
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_pass scout_passes;
BEGIN
  -- Find and lock the pass
  SELECT * INTO v_pass
  FROM scout_passes
  WHERE pass_code = p_pass_code AND status IN ('available', 'shared')
  FOR UPDATE;
  
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Pass not found or already claimed';
  END IF;
  
  IF v_pass.expires_at < NOW() THEN
    UPDATE scout_passes SET status = 'expired' WHERE id = v_pass.id;
    RAISE EXCEPTION 'Pass has expired';
  END IF;
  
  -- Claim the pass
  UPDATE scout_passes SET
    status = 'claimed',
    recipient_id = p_recipient_id,
    recipient_email = p_recipient_email,
    claimed_at = NOW(),
    trial_start = NOW(),
    trial_end = NOW() + INTERVAL '14 days',
    updated_at = NOW()
  WHERE id = v_pass.id
  RETURNING * INTO v_pass;
  
  -- Grant reward to referrer (+7 days)
  INSERT INTO referral_rewards (user_id, pass_id, reward_type, reward_value)
  VALUES (v_pass.referrer_id, v_pass.id, 'trial_extension', '{"days": 7}'::jsonb);
  
  -- Update leaderboard
  INSERT INTO referral_leaderboard (user_id, quarter, passes_claimed, days_earned)
  VALUES (v_pass.referrer_id, v_pass.quarter, 1, 7)
  ON CONFLICT (user_id, quarter) DO UPDATE SET
    passes_claimed = referral_leaderboard.passes_claimed + 1,
    days_earned = referral_leaderboard.days_earned + 7,
    updated_at = NOW();
  
  -- Log event
  INSERT INTO referral_events (pass_id, event_type, actor_id, metadata)
  VALUES (v_pass.id, 'trial_activated', p_recipient_id, 
    jsonb_build_object('referrer', v_pass.referrer_email, 'recipient', p_recipient_email));
  
  RETURN v_pass;
END;
$$;
