# ZONEWISE PROMPT QUALITY GATE
# Run before deploying any new or modified prompt to production
# All boxes must be checked. Any unchecked = revision required.
# Updated: 2026-03-03

## SALE TYPE CORRECTNESS — RUN FIRST
- [ ] Prompt correctly distinguishes foreclosure sales from tax deed sales?
- [ ] Foreclosure metrics (bid/judgment ratio) never applied to tax deed?
- [ ] Tax deed metrics (opening bid/ARV spread, cert chain) never applied to foreclosure?
- [ ] Sale type labeled on every specific data reference?
- [ ] Failure handling specifies sale type when reporting data gaps?

## HOOK MODEL ALIGNMENT
- [ ] Prompt serves one of 4 hooks (Trigger/Action/Reward/Investment)?
- [ ] Hook phase stated in prompt metadata header?
- [ ] Output format reinforces correct user behavior for that hook?

## TRIGGER PROMPTS MUST:
- [ ] Create urgency using specific data — never manufactured hype
- [ ] Drive toward a single clear next action (not a menu)
- [ ] Work in under 200 words (read on phone at 6 AM)
- [ ] Label sale type on every specific data point
- [ ] Alert threshold: 2+ std deviations — accuracy over frequency

## ACTION PROMPTS MUST:
- [ ] Deliver first value within first 3 lines of output
- [ ] Use appropriate pipeline for sale type — never mix
- [ ] One decision per response maximum
- [ ] Include fallback for ambiguous input
- [ ] Meet SLA: county_scan <3s / deep_dive <5s / bid_decision <10s

## REWARD PROMPTS MUST:
- [ ] Include at least one output user did NOT explicitly request
- [ ] Quantify value in real numbers (time, dollars)
- [ ] Report foreclosure and tax deed anomalies separately
- [ ] Acknowledge quiet weeks honestly — no manufactured significance

## INVESTMENT PROMPTS MUST:
- [ ] Track foreclosure and tax deed profiles in SEPARATE JSONB objects
- [ ] Extract behavioral signal (not just stated preferences)
- [ ] Output JSON matches exact Supabase schema
- [ ] Switching cost made concrete and visible

## SAFETY CHECKS (hardcoded — not just prompts)
- [ ] No shell command execution pathways
- [ ] No data access outside FL real estate scope
- [ ] Financial actions require explicit user confirmation tap before logging
- [ ] Foreclosure: HOA plaintiff flag ALWAYS surfaces — assert in unit tests
- [ ] Tax deed: outstanding cert exposure ALWAYS surfaces — assert in unit tests
- [ ] Tribe leaderboard: N<5 suppression hardcoded in code (not just prompt)
- [ ] Prompt injection resistance: add test to TASK-020

## TECHNICAL STANDARDS
- [ ] Every {variable} defined in INPUT or CONTEXT section
- [ ] Output format precisely specified
- [ ] Rules section with >= 3 explicit constraints
- [ ] Anti-patterns section with concrete examples
- [ ] Tone explicitly defined
- [ ] Failure handling specified for missing/incomplete data

---
GATE RESULT:
All checked → APPROVED
Any unchecked → REVISION REQUIRED

Reviewer: _________________ Date: _____________ Prompt file: _____________ Version: _____
