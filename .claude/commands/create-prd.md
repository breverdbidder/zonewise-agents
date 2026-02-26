---
description: Generate a Product Requirements Document from the current conversation or a feature description. Outputs to specified file (default: PRD.md).
argument-hint: [output-filename]
---

# Create PRD: $ARGUMENTS

## Output File: $ARGUMENTS (default: PRD.md)

---

## Instructions

Extract all requirements from the conversation history and generate a comprehensive PRD using the structure below. Be specific — no generic placeholders.

---

## PRD Structure

```markdown
# [Product Name] — Product Requirements Document

**Version:** 1.0
**Date:** [date]
**Author:** Ariel Shapira — Solo Founder, BidDeed.AI / Everest Capital USA
**Status:** Draft

---

## 1. Executive Summary

[2-3 paragraphs: what, why, MVP goal]

**Core Value Proposition:** [one sentence]
**MVP Goal:** [specific, measurable]

---

## 2. Mission

[Mission statement]

**Core Principles:**
1. [principle]
2. [principle]
3. [principle]

---

## 3. Target Users

**Primary:** Ariel Shapira — foreclosure investor, Brevard County FL
- 10+ years foreclosure auction experience
- ADHD — needs direct, bullet-first interfaces
- 20 min/day max active oversight

**Secondary:** [if applicable]

---

## 4. MVP Scope

### ✅ In Scope (MVP)
- [feature 1]
- [feature 2]

### ❌ Out of Scope (Phase 2+)
- [deferred feature]

---

## 5. User Stories

1. As Ariel, I want to [action], so that [benefit]
   - Example: [concrete scenario]

---

## 6. Core Architecture

**Stack:** Next.js 15 + Supabase + Render.com + GitHub Actions
**Pattern:** [specific pattern for this product]

```
[directory structure]
```

**Key Design Decisions:**
- [decision + rationale]

---

## 7. Features / Tools

### Feature: [name]
**Purpose:** [what it does]
**Inputs:** [data in]
**Outputs:** [data out]
**Supabase tables:** [tables read/written]
**Pipeline stage:** [1-12 or N/A]

---

## 8. Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend | Next.js | 15 |
| Database | Supabase (Postgres) | latest |
| ORM | Drizzle | latest |
| Auth | Supabase Auth | latest |
| Hosting | Render.com | — |
| [more rows] | | |

---

## 9. Supabase Schema

### New Tables

```sql
CREATE TABLE [table_name] (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  -- columns
);
```

### Existing Tables Affected
- `multi_county_auctions` — [what changes]
- `insights` — [logging requirements]

---

## 10. API Specification (if applicable)

### POST /api/[endpoint]

**Auth:** Bearer token (Supabase JWT)
**Body:**
```json
{
  "field": "type"
}
```
**Response:**
```json
{
  "success": true,
  "data": {}
}
```

---

## 11. Success Criteria

**MVP is complete when:**
- ✅ [criterion 1]
- ✅ [criterion 2]
- ✅ All unit tests pass
- ✅ E2E test passes all journeys
- ✅ insights table logs successful runs
- ✅ Deployed to Render and health check passes

---

## 12. Implementation Phases

### Phase 1: Foundation (Days 1-2)
**Goal:** [goal]
**Deliverables:**
- ✅ [deliverable]
**Validation:** [test command]

### Phase 2: Core (Days 3-5)
**Goal:** [goal]
**Deliverables:**
- ✅ [deliverable]

### Phase 3: Integration + Deploy (Days 6-7)
**Goal:** [goal]
**Deliverables:**
- ✅ [deliverable]
- ✅ E2E passing
- ✅ Render deploy live

---

## 13. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| [risk] | High/Med/Low | High/Med/Low | [mitigation] |

---

## 14. Future Considerations

- [Phase 2 feature]
- [Scale consideration for 67 counties]
- [Integration opportunity]

---

## Appendix

**Repos:** breverdbidder/[repo-name]
**Supabase:** mocerqjnksmhcjzxrewo.supabase.co
**Render:** [render-url]
**Related docs:** CLAUDE.md, TODO.md
```

---

## Quality Checklist

- [ ] All sections populated (no placeholders)
- [ ] User stories have concrete examples
- [ ] MVP scope is realistic for Claude Code solo build
- [ ] Supabase schema defined
- [ ] Success criteria are measurable
- [ ] Implementation phases are ≤7 days total for MVP
- [ ] Risks include pipeline scale (67 counties)

---

## After Creating PRD

1. Confirm file path
2. Summarize key decisions made
3. Note assumptions
4. Suggest next step: run `/plan-feature [first feature]`
