# ZONEWISE.AI — CLAUDE CODE OPERATING INSTRUCTIONS
# Hook Model Implementation Guide — March 2026
# READ THIS FILE at the start of every Claude Code session

## WHAT YOU ARE BUILDING

ZoneWise.AI tracks Florida **foreclosure sales** (court-ordered, clerk-run) and
**tax deed sales** (county-run) across 67 FL counties.
Implements Nir Eyal's Hook Model across a LangGraph multi-agent architecture.

**CRITICAL DISTINCTION — maintain in all code, comments, and prompts:**
- Foreclosure sales: AcclaimWeb (liens), RealForeclose (schedule), bid vs. judgment ratio
- Tax deed sales: RealTDM (cert chain), county portal (bidding), bid vs. ARV net spread

## 4 HOOKS → 4 AGENTS

| Hook | Agent | File | Status |
|------|-------|------|--------|
| TRIGGER | Nightly digest, alerts, referral | `agents/trigger_agent.py` | prompts done, agent NOT BUILT |
| ACTION | NLP chatbot, bid pipelines | `agents/action_agent.py` | prompts done, agent NOT BUILT |
| REWARD | Insights, leaderboard, scorecard | `agents/reward_agent.py` | prompts done, agent NOT BUILT |
| INVESTMENT | Profile learning, pipeline, scorer | `agents/memory_agent.py` | prompts done, agent NOT BUILT |

**Full prompt engineering playbook:** `docs/PROMPT_ENGINEERING.md`

## REPO STRUCTURE

```
zonewise-agents/
├── CLAUDE.md                    ← YOU ARE HERE (read every session)
├── PROJECT_STATE.json           ← Update after every task
├── TODO.md                      ← Load first, mark complete after each task
├── docs/
│   ├── PROMPT_ENGINEERING.md   ← All 12 production prompts (Hook Model)
│   ├── PROMPT_QA_GATE.md       ← Checklist before deploying any prompt
│   └── ARCHITECTURE.md         ← System architecture + schema
├── agents/
│   ├── orchestrator.py
│   ├── trigger_agent.py
│   ├── action_agent.py
│   ├── reward_agent.py
│   ├── memory_agent.py
│   └── prompts/               ← All 13 prompt files live here
├── scrapers/
│   ├── foreclosure_scraper.py
│   └── tax_deed_scraper.py
├── api/
│   └── chat.py
├── tests/
│   ├── test_foreclosure_pipeline.py
│   └── test_tax_deed_pipeline.py
└── .github/workflows/
    └── nightly_pipeline.yml
```

## SUPABASE TABLES

| Table | Owner | Critical Rule |
|-------|-------|---------------|
| `multi_county_auctions` | Scraper | `sale_type` NOT NULL — "foreclosure" or "tax_deed" |
| `user_profiles` | Memory | Separate `foreclosure_profile` + `tax_deed_profile` JSONB |
| `deal_pipeline` | Memory | `sale_type` NOT NULL on every row |
| `digest_history` | Trigger | — |
| `insights` | Reward | — |
| `daily_metrics` | Orchestrator | Separate counts per sale type |
| `claude_context_checkpoints` | Orchestrator | State persistence |

Supabase URL: mocerqjnksmhcjzxrewo.supabase.co

## COMMIT FORMAT
```
[HOOK:{trigger|action|reward|investment}][{foreclosure|tax_deed|both}] description
```

## AUTONOMOUS SESSION WORKFLOW
1. Load `TODO.md` — find first unchecked task
2. Check `PROJECT_STATE.json` — understand current state
3. Identify Hook phase + sale type this task serves
4. Execute → test → verify against `docs/PROMPT_QA_GATE.md`
5. Commit → push → update `PROJECT_STATE.json` → mark `TODO.md` done

## OPENCLAW FAILURE MODES — NEVER REPRODUCE
- No shell command execution in any agent
- No access to user email, calendar, or file system outside /zonewise-data/
- No agent-to-agent communication without explicit scope boundaries
- No financial actions (BID logging) without explicit user confirmation tap
- No API keys in user-accessible locations

## ZERO HUMAN-IN-LOOP FOR:
Prompt refinements · Supabase schema additions · New county to scraper · UI improvements · Tests

## ALWAYS SURFACE TO ARIEL:
New external APIs (first time) · BID formula changes · Schema modifications to user_profiles/deal_pipeline · Spend > $10
