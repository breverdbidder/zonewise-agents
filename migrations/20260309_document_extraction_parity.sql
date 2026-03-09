-- ============================================================================
-- BidDeed.AI Document Extraction Parity Layer
-- Migration: 20260309_document_extraction_parity.sql
--
-- PURPOSE: Achieve parity with Dono.ai's 32+ data points per document.
-- Current BidDeed.AI extracts 15-18 fields per AUCTION LISTING.
-- This migration enables 40 fields per RECORDED DOCUMENT.
--
-- A single foreclosure property may have 20-50 recorded documents:
--   Original deed, mortgage, assignments, modifications, lis pendens,
--   judgment, tax certs, HOA liens, satisfactions, etc.
--
-- TABLES CREATED:
--   1. property_documents     — Core: 40 data points per recorded document
--   2. ownership_chains       — Derived: grantor→grantee chain per parcel
--   3. title_defects          — Flagged issues from rules engine
--   4. document_extractions   — Raw extraction logs (audit trail)
--
-- PIPELINE STAGES AFFECTED:
--   Stage 2 (Scraping)       — Extract documents from clerk systems
--   Stage 3 (Title Search)   — Populate property_documents
--   Stage 4 (Lien Priority)  — Build ownership_chains + title_defects
--   Stage 10 (Report)        — Include document-level data in reports
--   Stage 12 (Archive)       — Full-text search on legal descriptions
--
-- Author: Claude AI Architect
-- Date: March 9, 2026
-- ============================================================================

-- ============================================================================
-- TABLE 1: property_documents
-- One row per recorded document. This is the Dono parity table.
-- 40 structured data points extracted from each clerk document.
-- ============================================================================
CREATE TABLE IF NOT EXISTS property_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- ── LINK TO AUCTION ──────────────────────────────────────────────
    -- Links back to multi_county_auctions or foreclosure_auctions
    auction_id UUID,
    case_number TEXT,
    parcel_id TEXT,
    county TEXT NOT NULL,

    -- ── PARTY INFORMATION (6 points) ─────────────────────────────────
    -- Points 1-6: Who is on each side of this document
    grantor_name TEXT,                     -- 1. Seller/mortgagor/lienholder
    grantee_name TEXT,                     -- 2. Buyer/mortgagee/lien beneficiary
    grantor_entity_type TEXT,              -- 3. individual/corporation/trust/estate/llc/government
    grantee_entity_type TEXT,              -- 4. individual/corporation/trust/estate/llc/government
    witness_names TEXT[],                  -- 5. Witness names (if present)
    notary_info TEXT,                      -- 6. Notary acknowledgment details

    -- ── DOCUMENT IDENTIFICATION (6 points) ──────────────────────────
    -- Points 7-12: What is this document and when was it recorded
    instrument_type TEXT NOT NULL,         -- 7. deed/mortgage/lien/satisfaction/assignment/
                                          --    lis_pendens/judgment/tax_cert/hoa_lien/
                                          --    release/modification/subordination/
                                          --    power_of_attorney/affidavit/court_order
    instrument_number TEXT,               -- 8. Official recording number
    recording_date DATE,                  -- 9. When filed with the clerk
    execution_date DATE,                  -- 10. When signed by parties
    book_page TEXT,                        -- 11. Book/page reference (OR instrument #)
    recording_county TEXT,                -- 12. County of recording (may differ from property county)

    -- ── PROPERTY INFORMATION (6 points) ─────────────────────────────
    -- Points 13-18: What property does this document affect
    legal_description TEXT,               -- 13. Full metes & bounds or lot/block/subdivision
    property_address TEXT,                -- 14. Street address (if stated in document)
    subdivision_name TEXT,                -- 15. Subdivision or plat name
    lot_number TEXT,                       -- 16. Lot number
    block_number TEXT,                     -- 17. Block number
    property_type TEXT,                    -- 18. SFH/condo/townhouse/land/commercial

    -- ── FINANCIAL TERMS (6 points) ──────────────────────────────────
    -- Points 19-24: Money involved in this document
    consideration_amount NUMERIC(15,2),   -- 19. Sale price / transfer value
    mortgage_amount NUMERIC(15,2),        -- 20. Loan principal amount
    interest_rate NUMERIC(5,3),           -- 21. Interest rate (e.g., 6.500)
    maturity_date DATE,                   -- 22. When loan is due
    loan_type TEXT,                        -- 23. conventional/fha/va/usda/heloc/commercial
    doc_stamps NUMERIC(12,2),             -- 24. Documentary stamp tax paid

    -- ── LIEN/ENCUMBRANCE STATUS (5 points) ──────────────────────────
    -- Points 25-29: Current status of this lien/encumbrance
    lien_status TEXT DEFAULT 'active',    -- 25. active/satisfied/released/partial/assigned
    satisfaction_date DATE,               -- 26. When lien was released
    satisfaction_instrument TEXT,          -- 27. Instrument # of satisfaction/release
    lien_priority INTEGER,                -- 28. Priority position (1=first, 2=second, etc.)
    related_documents TEXT[],             -- 29. Cross-references (assignments, modifications)

    -- ── TITLE CHAIN DATA (5 points) ────────────────────────────────
    -- Points 30-34: Ownership and conveyance details
    vesting_type TEXT,                    -- 30. fee_simple/life_estate/joint_tenancy/
                                          --     tenants_in_common/tenancy_by_entirety
    deed_type TEXT,                        -- 31. warranty/quitclaim/special_warranty/
                                          --     trustees_deed/tax_deed/sheriffs_deed/
                                          --     personal_rep/deed_in_lieu
    conveyance_conditions TEXT,           -- 32. Conditions or restrictions on conveyance
    easement_references TEXT[],           -- 33. Referenced easements or covenants
    exception_language TEXT,              -- 34. Exceptions or reservations

    -- ── COURT/JUDGMENT DATA (6 points) ──────────────────────────────
    -- Points 35-40: For foreclosure/court-related documents
    court_case_number TEXT,               -- 35. Court case number
    court_jurisdiction TEXT,              -- 36. Court name and county
    court_plaintiff TEXT,                 -- 37. Plaintiff in court action
    court_defendant TEXT,                 -- 38. Defendant in court action
    judgment_amount NUMERIC(15,2),        -- 39. Judgment/lien amount from court
    lis_pendens_status TEXT,              -- 40. active/dismissed/resolved

    -- ── EXTRACTION METADATA ────────────────────────────────────────
    extraction_source TEXT NOT NULL DEFAULT 'manual',
    -- Sources: acclaimweb/bcpao/clerk_pdf/realforeclose/manual
    extraction_method TEXT DEFAULT 'scraper',
    -- Methods: scraper/gemini_vision/claude_extraction/manual/firecrawl
    extraction_confidence NUMERIC(3,2) DEFAULT 1.00,
    -- 0.00-1.00: how confident was the extraction
    raw_document_url TEXT,
    -- URL to original document image/PDF in clerk system
    raw_extracted_text TEXT,
    -- Full OCR text (for search and re-processing)
    needs_human_review BOOLEAN DEFAULT FALSE,
    -- Flag for manual verification

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Performance indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_propdocs_parcel ON property_documents(parcel_id);
CREATE INDEX IF NOT EXISTS idx_propdocs_case ON property_documents(case_number);
CREATE INDEX IF NOT EXISTS idx_propdocs_county ON property_documents(county);
CREATE INDEX IF NOT EXISTS idx_propdocs_auction ON property_documents(auction_id);
CREATE INDEX IF NOT EXISTS idx_propdocs_instrument_type ON property_documents(instrument_type);
CREATE INDEX IF NOT EXISTS idx_propdocs_recording_date ON property_documents(recording_date DESC);
CREATE INDEX IF NOT EXISTS idx_propdocs_grantor ON property_documents(grantor_name);
CREATE INDEX IF NOT EXISTS idx_propdocs_grantee ON property_documents(grantee_name);
CREATE INDEX IF NOT EXISTS idx_propdocs_lien_status ON property_documents(lien_status);
CREATE INDEX IF NOT EXISTS idx_propdocs_needs_review ON property_documents(needs_human_review) WHERE needs_human_review = TRUE;

-- Composite indexes for pipeline queries
CREATE INDEX IF NOT EXISTS idx_propdocs_parcel_type ON property_documents(parcel_id, instrument_type);
CREATE INDEX IF NOT EXISTS idx_propdocs_county_date ON property_documents(county, recording_date DESC);
CREATE INDEX IF NOT EXISTS idx_propdocs_case_type ON property_documents(case_number, instrument_type);

-- Full-text search on legal descriptions and extracted text
CREATE INDEX IF NOT EXISTS idx_propdocs_legal_desc_trgm ON property_documents USING gin (legal_description gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_propdocs_raw_text_trgm ON property_documents USING gin (raw_extracted_text gin_trgm_ops);

-- ============================================================================
-- TABLE 2: ownership_chains
-- Derived table: computed chain of title per parcel.
-- Built by Stage 4 (Lien Priority) from property_documents.
-- One row per transfer in the chain.
-- ============================================================================
CREATE TABLE IF NOT EXISTS ownership_chains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    parcel_id TEXT NOT NULL,
    county TEXT NOT NULL,
    case_number TEXT,

    -- Chain position
    chain_position INTEGER NOT NULL,       -- 1 = earliest, ascending to current
    transfer_date DATE,
    
    -- Parties
    from_party TEXT NOT NULL,              -- Grantor (seller/transferor)
    from_party_type TEXT,                  -- individual/corp/trust/estate
    to_party TEXT NOT NULL,                -- Grantee (buyer/transferee)
    to_party_type TEXT,

    -- Transfer details
    deed_type TEXT,                         -- warranty/quitclaim/etc.
    consideration NUMERIC(15,2),
    instrument_number TEXT,
    document_id UUID REFERENCES property_documents(id),

    -- Chain health
    chain_complete BOOLEAN DEFAULT TRUE,   -- FALSE if gap detected
    gap_description TEXT,                  -- Description of chain break if incomplete
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ownchain_parcel ON ownership_chains(parcel_id);
CREATE INDEX IF NOT EXISTS idx_ownchain_case ON ownership_chains(case_number);
CREATE INDEX IF NOT EXISTS idx_ownchain_position ON ownership_chains(parcel_id, chain_position);
CREATE INDEX IF NOT EXISTS idx_ownchain_to_party ON ownership_chains(to_party);

-- ============================================================================
-- TABLE 3: title_defects
-- Flagged issues detected by the Title Rules Engine.
-- Each row is one potential defect or risk found during Stage 4.
-- Maps to Dono's "underwriting intelligence with hundreds of rules."
-- ============================================================================
CREATE TABLE IF NOT EXISTS title_defects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    parcel_id TEXT NOT NULL,
    case_number TEXT,
    county TEXT NOT NULL,
    auction_id UUID,

    -- Rule that triggered the defect
    rule_id TEXT NOT NULL,
    -- Format: category_number e.g., "CHAIN_001", "LIEN_015", "HOA_003"
    rule_category TEXT NOT NULL,
    -- Categories: CHAIN, LIEN, MORTGAGE, TAX, HOA, JUDGMENT, DEED,
    --   EASEMENT, ENCUMBRANCE, PROBATE, ENTITY, SURVEY, LEGAL_DESC
    rule_name TEXT NOT NULL,
    -- Human-readable rule name

    -- Defect details
    severity TEXT NOT NULL DEFAULT 'medium',
    -- critical/high/medium/low/info
    defect_description TEXT NOT NULL,
    -- Plain English description of the issue
    affected_document_id UUID REFERENCES property_documents(id),
    affected_parties TEXT[],
    -- Names of affected grantor/grantee

    -- Resolution
    resolution_status TEXT DEFAULT 'open',
    -- open/resolved/waived/exception
    resolution_notes TEXT,
    curative_action TEXT,
    -- Recommended action to cure the defect

    -- Impact on bid
    bid_impact TEXT DEFAULT 'none',
    -- none/reduce_bid/skip/requires_review
    bid_discount_pct NUMERIC(5,2),
    -- Suggested discount percentage if bid_impact = reduce_bid

    auto_detected BOOLEAN DEFAULT TRUE,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_titledefects_parcel ON title_defects(parcel_id);
CREATE INDEX IF NOT EXISTS idx_titledefects_case ON title_defects(case_number);
CREATE INDEX IF NOT EXISTS idx_titledefects_severity ON title_defects(severity);
CREATE INDEX IF NOT EXISTS idx_titledefects_rule ON title_defects(rule_category, rule_id);
CREATE INDEX IF NOT EXISTS idx_titledefects_open ON title_defects(resolution_status) WHERE resolution_status = 'open';

-- ============================================================================
-- TABLE 4: document_extractions
-- Audit trail: logs every extraction attempt for debugging and quality.
-- ============================================================================
CREATE TABLE IF NOT EXISTS document_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    document_id UUID REFERENCES property_documents(id),
    parcel_id TEXT,
    county TEXT,

    -- Extraction details
    source_url TEXT,
    extraction_method TEXT NOT NULL,
    -- gemini_vision/claude_extraction/firecrawl/pdfplumber/regex/manual
    model_used TEXT,
    -- e.g., "gemini-2.0-flash", "claude-sonnet-4-5"
    tokens_used INTEGER,
    cost_usd NUMERIC(8,4),
    processing_time_ms INTEGER,

    -- Quality metrics
    fields_extracted INTEGER,
    fields_confident INTEGER,
    -- Number of fields with confidence > 0.8
    confidence_avg NUMERIC(3,2),
    
    -- Raw I/O
    raw_input_hash TEXT,
    -- SHA256 of input document for dedup
    raw_output JSONB,
    -- Full extraction response (for re-processing)
    errors TEXT[],

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_docextract_document ON document_extractions(document_id);
CREATE INDEX IF NOT EXISTS idx_docextract_parcel ON document_extractions(parcel_id);
CREATE INDEX IF NOT EXISTS idx_docextract_method ON document_extractions(extraction_method);
CREATE INDEX IF NOT EXISTS idx_docextract_date ON document_extractions(created_at DESC);

-- ============================================================================
-- ENABLE pg_trgm FOR FULL-TEXT SEARCH
-- Required for the gin_trgm_ops indexes above
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================================
-- RLS POLICIES
-- ============================================================================
ALTER TABLE property_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE ownership_chains ENABLE ROW LEVEL SECURITY;
ALTER TABLE title_defects ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_extractions ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "service_role_propdocs" ON property_documents FOR ALL
    USING (current_setting('request.jwt.claim.role', true) = 'service_role');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
  CREATE POLICY "service_role_ownchain" ON ownership_chains FOR ALL
    USING (current_setting('request.jwt.claim.role', true) = 'service_role');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
  CREATE POLICY "service_role_titledefects" ON title_defects FOR ALL
    USING (current_setting('request.jwt.claim.role', true) = 'service_role');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
  CREATE POLICY "service_role_docextract" ON document_extractions FOR ALL
    USING (current_setting('request.jwt.claim.role', true) = 'service_role');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- TRIGGERS
-- ============================================================================
DROP TRIGGER IF EXISTS trg_propdocs_updated ON property_documents;
CREATE TRIGGER trg_propdocs_updated
    BEFORE UPDATE ON property_documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trg_titledefects_updated ON title_defects;
CREATE TRIGGER trg_titledefects_updated
    BEFORE UPDATE ON title_defects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- ANALYTICS VIEWS
-- ============================================================================

-- Document extraction coverage per county
CREATE OR REPLACE VIEW v_document_coverage AS
SELECT
    county,
    COUNT(DISTINCT parcel_id) AS parcels_with_docs,
    COUNT(*) AS total_documents,
    ROUND(AVG(extraction_confidence), 2) AS avg_confidence,
    COUNT(*) FILTER (WHERE needs_human_review) AS needs_review,
    COUNT(DISTINCT instrument_type) AS instrument_types_found,
    MIN(recording_date) AS earliest_document,
    MAX(recording_date) AS latest_document
FROM property_documents
GROUP BY county
ORDER BY total_documents DESC;

-- Lien stack summary per parcel (for Stage 4)
CREATE OR REPLACE VIEW v_lien_stack AS
SELECT
    parcel_id,
    county,
    case_number,
    COUNT(*) AS total_liens,
    COUNT(*) FILTER (WHERE lien_status = 'active') AS active_liens,
    COUNT(*) FILTER (WHERE lien_status = 'satisfied') AS satisfied_liens,
    COUNT(*) FILTER (WHERE instrument_type = 'mortgage') AS mortgages,
    COUNT(*) FILTER (WHERE instrument_type = 'hoa_lien') AS hoa_liens,
    COUNT(*) FILTER (WHERE instrument_type = 'tax_cert') AS tax_certs,
    COUNT(*) FILTER (WHERE instrument_type = 'judgment') AS judgments,
    SUM(mortgage_amount) FILTER (WHERE lien_status = 'active' AND instrument_type = 'mortgage') AS total_active_mortgage_balance,
    MIN(lien_priority) AS senior_lien_position
FROM property_documents
WHERE instrument_type IN ('mortgage', 'lien', 'hoa_lien', 'tax_cert', 'judgment', 'lis_pendens')
GROUP BY parcel_id, county, case_number;

-- Title defect summary per property
CREATE OR REPLACE VIEW v_title_health AS
SELECT
    parcel_id,
    county,
    case_number,
    COUNT(*) AS total_defects,
    COUNT(*) FILTER (WHERE severity = 'critical') AS critical_defects,
    COUNT(*) FILTER (WHERE severity = 'high') AS high_defects,
    COUNT(*) FILTER (WHERE resolution_status = 'open') AS open_defects,
    COUNT(*) FILTER (WHERE bid_impact = 'skip') AS skip_flags,
    COUNT(*) FILTER (WHERE bid_impact = 'reduce_bid') AS discount_flags,
    COALESCE(MAX(bid_discount_pct), 0) AS max_discount_pct,
    CASE
        WHEN COUNT(*) FILTER (WHERE severity = 'critical' AND resolution_status = 'open') > 0 THEN 'SKIP'
        WHEN COUNT(*) FILTER (WHERE severity = 'high' AND resolution_status = 'open') > 2 THEN 'REVIEW'
        WHEN COUNT(*) FILTER (WHERE severity = 'high' AND resolution_status = 'open') > 0 THEN 'REVIEW'
        ELSE 'CLEAR'
    END AS title_recommendation
FROM title_defects
GROUP BY parcel_id, county, case_number;

-- Extraction performance metrics
CREATE OR REPLACE VIEW v_extraction_metrics AS
SELECT
    extraction_method,
    model_used,
    COUNT(*) AS total_extractions,
    ROUND(AVG(fields_extracted), 1) AS avg_fields,
    ROUND(AVG(confidence_avg), 2) AS avg_confidence,
    ROUND(AVG(processing_time_ms), 0) AS avg_time_ms,
    ROUND(SUM(cost_usd)::NUMERIC, 2) AS total_cost,
    ROUND(AVG(cost_usd)::NUMERIC, 4) AS avg_cost_per_doc
FROM document_extractions
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY extraction_method, model_used
ORDER BY total_extractions DESC;

-- ============================================================================
-- TITLE RULES ENGINE: Initial FL Foreclosure Rules
-- These are the first 25 rules. Target: 100+ for full Dono parity.
-- Category prefixes: CHAIN_, LIEN_, MORTGAGE_, TAX_, HOA_, JUDGMENT_,
--   DEED_, EASEMENT_, PROBATE_, ENTITY_, SURVEY_
-- ============================================================================

-- Store rules as a reference table (not enforced by DB, used by extraction agents)
CREATE TABLE IF NOT EXISTS title_rules (
    rule_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    condition_logic TEXT NOT NULL,
    -- Pseudo-code or SQL condition that triggers the rule
    curative_action TEXT,
    fl_statute TEXT,
    -- Florida statute reference if applicable
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert initial FL foreclosure title rules
INSERT INTO title_rules (rule_id, category, name, description, severity, condition_logic, curative_action, fl_statute) VALUES
-- Chain of Title Rules
('CHAIN_001', 'CHAIN', 'Break in chain of title', 'Gap detected: grantee of prior deed does not match grantor of next deed', 'critical', 'ownership_chain.chain_complete = FALSE', 'Obtain corrective deed or affidavit of title', 'FL §689.01'),
('CHAIN_002', 'CHAIN', 'Wild deed detected', 'Deed from grantor not in chain of title', 'critical', 'grantor_name NOT IN prior_grantees', 'Title curative action required', NULL),
('CHAIN_003', 'CHAIN', 'Quitclaim in chain', 'Quitclaim deed in ownership chain reduces title quality', 'medium', 'deed_type = ''quitclaim'' AND chain_position < max_position - 1', 'Review for title insurance exceptions', NULL),
('CHAIN_004', 'CHAIN', 'Death in chain without probate', 'Owner deceased but no probate/PR deed in chain', 'high', 'owner_deceased AND NOT EXISTS probate_deed', 'Require probate proceeding or affidavit of heirship', 'FL §733.103'),

-- Lien Rules
('LIEN_001', 'LIEN', 'Unsatisfied mortgage', 'Active mortgage with no recorded satisfaction', 'high', 'instrument_type = ''mortgage'' AND lien_status = ''active'' AND age > 30 years', 'Obtain satisfaction or estoppel letter', 'FL §95.281'),
('LIEN_002', 'LIEN', 'Multiple active mortgages', 'More than one unsatisfied mortgage on property', 'high', 'COUNT(active_mortgages) > 1', 'Verify subordination or satisfaction', NULL),
('LIEN_003', 'LIEN', 'Lien exceeds judgment', 'Recorded lien amount exceeds court judgment', 'medium', 'lien_amount > judgment_amount', 'Verify correct amount with clerk', NULL),

-- HOA Rules (critical for FL foreclosures)
('HOA_001', 'HOA', 'HOA foreclosure - senior mortgage survives', 'HOA is foreclosing but first mortgage survives the sale', 'critical', 'plaintiff_is_hoa AND EXISTS first_mortgage_active', 'Senior mortgage balance must be added to bid calculation', 'FL §720.3085'),
('HOA_002', 'HOA', 'HOA super-lien priority', 'HOA lien has super-lien priority for 12 months assessments', 'high', 'instrument_type = ''hoa_lien'' AND amount <= 12_months_assessments', 'Verify super-lien amount per FL statute', 'FL §720.3085(2)(c)'),
('HOA_003', 'HOA', 'Missing HOA estoppel', 'No estoppel letter from HOA in file', 'medium', 'property_in_hoa AND NOT EXISTS hoa_estoppel', 'Request estoppel letter from HOA', 'FL §720.30851'),

-- Tax Rules
('TAX_001', 'TAX', 'Delinquent property taxes', 'Property taxes unpaid for current or prior year', 'high', 'tax_status = ''delinquent''', 'Taxes must be paid at closing', 'FL §197.122'),
('TAX_002', 'TAX', 'Tax certificate outstanding', 'Third-party tax certificate holder has claim', 'critical', 'EXISTS tax_cert AND cert_holder != ''county''', 'Tax cert must be redeemed before or at closing', 'FL §197.442'),
('TAX_003', 'TAX', 'Tax deed application pending', 'Tax cert holder has applied for tax deed', 'critical', 'tax_deed_application = TRUE', 'SKIP - competing foreclosure action', 'FL §197.502'),

-- Mortgage Rules
('MORT_001', 'MORTGAGE', 'Assignment chain incomplete', 'Mortgage assigned but chain of assignments is broken', 'high', 'EXISTS assignment AND NOT all_assignments_recorded', 'Obtain missing assignment recordings', NULL),
('MORT_002', 'MORTGAGE', 'MERS mortgage', 'Mortgage registered with MERS - assignment chain may be unclear', 'medium', 'mortgagee LIKE ''%MERS%'' OR mortgagee LIKE ''%Mortgage Electronic%''', 'Verify current servicer and assignment chain', NULL),
('MORT_003', 'MORTGAGE', 'Modification not recorded', 'Loan modification referenced but not recorded', 'medium', 'EXISTS modification_reference AND NOT EXISTS recorded_modification', 'Obtain and record modification agreement', NULL),

-- Judgment Rules
('JUDG_001', 'JUDGMENT', 'Judgment lien against owner', 'Court judgment recorded against current property owner', 'high', 'EXISTS judgment_against_owner AND lien_status = ''active''', 'Judgment must be satisfied at closing or survive', 'FL §55.10'),
('JUDG_002', 'JUDGMENT', 'Federal tax lien', 'IRS tax lien recorded against property owner', 'critical', 'instrument_type = ''federal_tax_lien'' AND lien_status = ''active''', 'IRS has 120-day redemption right after sale', '26 USC §7425'),
('JUDG_003', 'JUDGMENT', 'Lis pendens - other action', 'Another lawsuit pending affecting the property', 'critical', 'EXISTS other_lis_pendens AND lis_pendens_status = ''active''', 'SKIP - multiple competing actions create uncertainty', 'FL §48.23'),

-- Deed Rules
('DEED_001', 'DEED', 'Deed in lieu recorded', 'Deed in lieu of foreclosure in chain', 'medium', 'deed_type = ''deed_in_lieu''', 'Verify all junior liens were addressed', NULL),
('DEED_002', 'DEED', 'Personal representative deed', 'Property conveyed by personal representative of estate', 'medium', 'deed_type = ''personal_rep''', 'Verify probate court authority and Letters of Administration', 'FL §733.612'),
('DEED_003', 'DEED', 'Trustee deed without trust reference', 'Deed from trustee but trust document not referenced', 'high', 'grantor LIKE ''%trustee%'' AND trust_reference IS NULL', 'Obtain trust agreement or certification of trust', 'FL §689.073'),

-- Entity Rules
('ENTITY_001', 'ENTITY', 'Dissolved corporation in chain', 'Corporation that conveyed property has been dissolved', 'high', 'grantor_entity_type = ''corporation'' AND entity_status = ''dissolved''', 'May need court order to confirm title', 'FL §607.1405'),
('ENTITY_002', 'ENTITY', 'LLC not authorized', 'LLC grantor not authorized to do business in Florida', 'medium', 'grantor_entity_type = ''llc'' AND fl_registration = FALSE', 'Verify LLC authority via sunbiz.org', 'FL §605.0902')

ON CONFLICT (rule_id) DO NOTHING;

-- ============================================================================
-- VERIFICATION
-- ============================================================================
SELECT 'Document extraction parity migration complete' AS status;
SELECT
    (SELECT COUNT(*) FROM information_schema.tables WHERE table_name IN ('property_documents', 'ownership_chains', 'title_defects', 'document_extractions', 'title_rules')) AS tables_created,
    (SELECT COUNT(*) FROM title_rules) AS rules_loaded;
