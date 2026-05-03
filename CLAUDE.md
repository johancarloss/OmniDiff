# OmniDiff — Project Instructions

## Overview
Open-source RAG platform for semantic search of Git commits via embeddings of diffs.
Portfolio project — self-referential demo indexes its own commits.

## Architecture
- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), asyncpg, pgvector
- **Frontend:** React 19, Tailwind CSS v4, shadcn/ui, Vite
- **Database:** PostgreSQL 17 + pgvector (HNSW index, 1024d vectors)
- **Performance layer (Phase 2-C):** Rust crate `core/` exposed to Python via PyO3
  - Handles Git walking, diff parsing, chunking, filtering — CPU-bound work only
  - Pattern: Python orchestrates I/O, Rust executes the hot path (same as `uv`/`ruff`)
- **Package managers:** uv (backend), npm (frontend), cargo + maturin (core)

## Conventions
- All code in English (variables, functions, classes)
- Communication in Portuguese (pt-BR)
- Commits: `tipo(escopo): descrição` (e.g., `feat(api): add search endpoint`, `feat(core): walker via git2-rs`)
- Clean Architecture: services/ (logic), repositories/ (data), api/ (HTTP)
- Provider abstraction: swap AI providers via .env (Strategy Pattern)
- Rust ↔ Python boundary: only primitive types and dicts cross PyO3; no opaque objects

## Key Files
- `backend/app/config.py` — all settings via pydantic-settings
- `backend/app/providers/factory.py` — AI provider factory
- `backend/app/models/` — SQLAlchemy models (Repository, Commit, CommitChunk)
- `core/src/lib.rs` — PyO3 entrypoint for the Rust performance layer
- `docs/private/blueprint/OMNIDIFF-BLUEPRINT.md` — full project blueprint
- `docs/private/blueprint/RUST-MIGRATION-PLAN.md` — operational plan for the Rust layer

## Testing
```bash
# Python
cd backend && uv run pytest tests/ -v
cd backend && uv run ruff check app/ tests/
cd frontend && npx tsc --noEmit

# Rust (after Phase 2-C starts)
cd core && cargo test --all-targets
cd core && cargo clippy --all-targets -- -D warnings
cd core && cargo fmt --check
```

## Current Phase
Phase 1 (Setup & Infrastructure) — COMPLETE
Next: Phase 2-A (Git Ingest Pipeline in Python — baseline for benchmarking the Rust port)
Then: Phase 2-B (profiling) → Phase 2-C (Rust performance layer)
