# OmniDiff

Semantic search for Git commits via embeddings of diffs.

Stop searching by commit messages. Search by **meaning** — find the commit that fixed concurrency, not `"fix: wip"`.

## How it works

1. **Index** a Git repository — OmniDiff clones it, extracts diffs, generates natural language descriptions, and creates vector embeddings
2. **Search** in plain language — "Which commit fixed the race condition in the queue?"
3. **Get answers** — semantic similarity finds the relevant commits and an LLM explains why they match

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/johancarloss/OmniDiff.git
cd OmniDiff
cp .env.example .env  # Add your API keys

# 2. Start everything
docker compose up --build

# 3. Open
# Frontend: http://localhost:5173
# API:      http://localhost:8000/health
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Frontend   │────▶│   FastAPI     │────▶│   PostgreSQL     │
│  React + TW  │     │   Backend     │     │   + pgvector     │
└─────────────┘     └──────┬───────┘     └──────────────────┘
                           │
                    ┌──────┴───────┐
                    │  AI Providers │
                    │  (pluggable)  │
                    └──────────────┘
```

| Component | Technology |
|-----------|-----------|
| Frontend | React 19, Tailwind CSS v4, shadcn/ui |
| Backend | Python, FastAPI, SQLAlchemy 2.0 (async) |
| Performance layer | Rust + PyO3 (`core/`, work in progress) — Git walking, diff parsing, chunking |
| Database | PostgreSQL 17 + pgvector (HNSW) |
| Embeddings | Voyage AI (free tier) or Gemini |
| LLM | Gemini / Groq (free tiers) |

## Development

```bash
# Full stack (Docker)
docker compose up --build

# Individual services
docker compose up db                                          # PostgreSQL only
cd backend && uv run uvicorn app.main:app --reload            # Backend (needs DB)
cd frontend && npm run dev                                    # Frontend

# Testing & linting
cd backend && uv run pytest tests/ -v                         # Tests
cd backend && uv run ruff check app/ tests/                   # Lint
cd backend && uv run ruff format app/ tests/                  # Format
cd backend && uv run alembic upgrade head                     # Migrations
```

## License

MIT
