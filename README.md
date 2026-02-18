# ZoneWise Agents — NLP Backend 🤖

**FastAPI NLP backend powering ZoneWise.AI zoning intelligence queries.**

[![CI](https://github.com/breverdbidder/zonewise-agents/actions/workflows/ci.yml/badge.svg)](https://github.com/breverdbidder/zonewise-agents/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-brightgreen.svg)](https://python.org)

**Status:** ✅ ACTIVE — serving production traffic at `zonewise-agents.onrender.com`

> **Note:** This repo was previously mislabeled as "DEPRECATED". It is the active NLP backend.

---

## What It Does

ZoneWise Agents is the FastAPI backend that handles:
- Natural language zoning queries via Claude Sonnet 4.5
- Structured zoning data retrieval from Supabase
- LangGraph multi-step reasoning for complex queries
- Response caching and rate limiting

## Architecture

```
zonewise-web (Next.js)
       │
       │ POST /api/query
       ▼
zonewise-agents (FastAPI on Render)
       │
       ├── Claude Sonnet 4.5 (LLM reasoning)
       └── Supabase (zoning data retrieval)
```

## Quick Start

```bash
git clone https://github.com/breverdbidder/zonewise-agents.git
cd zonewise-agents

pip install -r requirements.txt
cp .env.example .env  # add ANTHROPIC_API_KEY, SUPABASE_URL, etc.

# Dev server
uvicorn app.main:app --reload --port 8000

# Health check
curl http://localhost:8000/health
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/query` | POST | Natural language zoning query |
| `/api/parcel/{id}` | GET | Parcel zoning details |
| `/api/districts` | GET | List zoning districts |

## Tech Stack

| Layer | Technology |
|-------|------------|
| Framework | FastAPI (Python 3.11) |
| AI | Claude Sonnet 4.5 (Anthropic) |
| Orchestration | LangGraph |
| Database | Supabase (PostgreSQL) |
| Hosting | Render.com |

## Development

```bash
# Tests
pytest tests/ -v --cov=app --cov-fail-under=85

# Lint
ruff check app/ tests/

# Type check  
mypy app/ --ignore-missing-imports
```

## Deployment

Automatically deploys to Render.com on push to `main` via `render.yaml`.

## License

MIT — see [LICENSE](./LICENSE)
