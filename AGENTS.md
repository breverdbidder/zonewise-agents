# AGENTS.md — ZoneWise Agents

This file defines the working protocol for AI coding agents in `zonewise-agents`.  
**Scope:** entire repository.

## Project Identity

ZoneWise Agents is the FastAPI NLP backend for ZoneWise.AI.  
**Stack:** Python 3.11, FastAPI, LangGraph, Claude API, Supabase  
**Live:** https://zonewise-agents.onrender.com  
**Status:** ✅ ACTIVE (description in README was incorrect — this service is production)

## Rules for Agents

### ✅ DO
- All endpoints return typed Pydantic response models
- Use async FastAPI routes for all LLM calls
- Implement retry logic on all Claude API calls (429 / 529)
- Health check endpoint at `/health` must always return 200
- Log structured JSON via `structlog`

### ❌ NEVER
- Block the event loop with synchronous I/O
- Return raw Claude completions without validation
- Expose internal Supabase queries via error messages
- Skip input validation on public endpoints

## High-Risk Surfaces

| Path | Risk |
|------|------|
| `app/api/chat.py` | Prompt injection surface |
| `app/api/zoning.py` | Supabase query construction |
| `server/auth.py` | JWT validation |

## Testing

```bash
pytest tests/ -v --cov=app --cov-fail-under=85
ruff check app/ tests/
mypy app/
```
