# CLAUDE.md - ZoneWise Agents Backend

## Project Overview
FastAPI backend for ZoneWise agents, based on OpenManus multi-agent architecture.

## Architecture
```
zonewise-agents/
├── app/
│   ├── agent/           # Agent implementations
│   │   ├── base.py      # From OpenManus
│   │   ├── zoning.py    # ZoningResearchAgent
│   │   ├── parcel.py    # ParcelAnalysisAgent
│   │   ├── hbu.py       # HBUCalculatorAgent
│   │   └── report.py    # ReportGeneratorAgent
│   ├── tool/            # Tool implementations
│   │   ├── base.py      # From OpenManus
│   │   ├── municode.py  # Municode scraper
│   │   ├── bcpao.py     # BCPAO API
│   │   └── supabase.py  # Database queries
│   └── llm.py           # From OpenManus
├── server/
│   └── main.py          # FastAPI application
└── config/
    └── agents.yaml      # Agent configuration
```

## Tech Stack
- FastAPI
- Pydantic
- httpx (async HTTP)
- Supabase Python client
- OpenAI/Anthropic SDKs
- litellm (LLM routing)

## API Endpoints
- POST /agents/query - Main query endpoint
- POST /agents/query/stream - Streaming query endpoint
- GET /health - Health check
- GET /agents - List available agents

## Environment Variables
```
SUPABASE_URL=
SUPABASE_KEY=
GOOGLE_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

## Intent Classification
| Intent | Description | Agent |
|--------|-------------|-------|
| FEASIBILITY | "Can I build X here?" | ZoningResearchAgent |
| CALCULATION | "What are the setbacks?" | ZoningResearchAgent |
| LOOKUP | "What's the zoning at X?" | ParcelAnalysisAgent |
| HBU | "What's the highest and best use?" | HBUCalculatorAgent |
| COMPARISON | "Compare zoning in A vs B" | ZoningResearchAgent |
| REPORT | "Generate a report" | ReportGeneratorAgent |

## Coding Conventions
- Use async/await everywhere
- Type hints required
- Pydantic models for request/response
- Structured logging
- Error handling with custom exceptions
