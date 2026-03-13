# OmniDiff — Project Instructions

## Overview
Open-source RAG platform for semantic search of Git commits via embeddings of diffs.
Portfolio project — self-referential demo indexes its own commits.

## Architecture
- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), asyncpg, pgvector
- **Frontend:** React 19, Tailwind CSS v4, shadcn/ui, Vite
- **Database:** PostgreSQL 17 + pgvector (HNSW index, 1024d vectors)
- **Package manager:** uv (backend), npm (frontend)

## Conventions
- All code in English (variables, functions, classes)
- Communication in Portuguese (pt-BR)
- Commits: `tipo(escopo): descrição` (e.g., `feat(api): add search endpoint`)
- Clean Architecture: services/ (logic), repositories/ (data), api/ (HTTP)
- Provider abstraction: swap AI providers via .env (Strategy Pattern)

## Key Files
- `backend/app/config.py` — all settings via pydantic-settings
- `backend/app/providers/factory.py` — AI provider factory
- `backend/app/models/` — SQLAlchemy models (Repository, Commit, CommitChunk)
- `docs/private/blueprint/OMNIDIFF-BLUEPRINT.md` — full project blueprint

## Testing
```bash
cd backend && uv run pytest tests/ -v
cd backend && uv run ruff check app/ tests/
cd frontend && npx tsc --noEmit
```

## Current Phase
Phase 1 (Setup & Infrastructure) — COMPLETE
Next: Phase 2 (Git Ingest Pipeline)
