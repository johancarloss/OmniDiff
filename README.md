# OmniDiff

> Semantic search for Git commits via embeddings of diffs.
>
> Created by **[Johan Carlos](https://github.com/johancarloss)** · 2026 · Licensed under [AGPL-3.0](./LICENSE)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](./LICENSE)
[![Status](https://img.shields.io/badge/status-in%20development-orange.svg)](#current-status)
[![Stack](https://img.shields.io/badge/stack-Python%20%2B%20Rust%20%2B%20PostgreSQL-success.svg)](#architecture)

---

## What it is

OmniDiff turns the commit history of any Git repository into a knowledge
base searchable by **natural language**.

Instead of grepping commit messages — which are notoriously sparse,
cryptic, or simply wrong — OmniDiff indexes the **actual content of the
changes** (diffs) as vector embeddings. You ask a question in plain
language, and it returns the commits whose code changes semantically
match your intent.

```
You ask:
   "Which commit fixed the race condition in the payment queue?"

OmniDiff answers in ~2 seconds:
   commit a1b2c3d — "fix queue processing"
   98.7% match · This commit added a Redis-based distributed lock to
   the payment worker, preventing two workers from processing the
   same item concurrently.
```

## The problem this solves

Finding old commits is painful. The information you need is usually in
the diff, not in the message someone hastily typed three years ago.

| What devs do today | Why it fails |
|--------------------|--------------|
| `git log --grep="deadlock"` | Returns 0 results because the message said "fix queue" |
| `git log --grep="queue"` | Returns 47 results — read each one |
| `git log -S "Lock"` | Returns 200+ results — too much noise |
| Ask on Slack | "I think it was João, last week?" |
| Read 23 commits manually | 30 minutes to 2 hours, and often you give up |

OmniDiff replaces all of that with a single query against the **meaning**
of the changes.

## Why it's interesting

The market has tools for semantic search over **current code** —
Sourcegraph Cody, Greptile, Bloop. **None** focus on semantic search over
**diffs** (what changed over time). That's the gap OmniDiff fills.

| Tool | Searches current code | Searches diffs | Semantic | LLM explanation | Open-source |
|------|:--:|:--:|:--:|:--:|:--:|
| Sourcegraph Cody | ✅ | ❌ | Partial | ✅ | Partial |
| Greptile | ✅ | ❌ | ✅ | ✅ | ❌ |
| `git log --grep` | ❌ | ❌ | ❌ | ❌ | ✅ |
| **OmniDiff** | ❌ | **✅** | **✅** | **✅** | **✅** |

There's also a recursive twist that makes the live demo special — see
[The self-referential demo](#the-self-referential-demo) below.

## Architecture

OmniDiff is a two-language system:
**Python orchestrates I/O, Rust executes the CPU-bound hot path.**
This is the same pattern used by `uv`, `ruff`, and `pydantic-core`.

```
┌──────────────────────────────────────────────────────────────────┐
│   FRONTEND                                                        │
│   React 19 · Tailwind CSS v4 · shadcn/ui · Motion                │
└────────────────────────┬─────────────────────────────────────────┘
                         │ POST /api/search
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│   BACKEND  (Python — orchestration)                               │
│   FastAPI · SQLAlchemy 2.0 (async) · asyncpg · Pydantic v2       │
│                                                                   │
│   Search pipeline:                                                │
│     query → embedding → semantic + keyword search →               │
│     RRF fusion → LLM explanation                                  │
└──────┬─────────────────────────────────┬─────────────────────────┘
       │                                 │
       ▼                                 ▼
┌──────────────────┐         ┌──────────────────────────────────────┐
│  CORE  (Rust)    │         │   PostgreSQL 17 + pgvector           │
│  PyO3 + maturin  │         │   HNSW index · 1024-dim vectors      │
│                  │         │                                       │
│  · Git walking   │         │   repositories · commits ·           │
│  · Diff parsing  │         │   commit_chunks (with embeddings)    │
│  · Chunking      │         └──────────────────────────────────────┘
│  · Filtering     │
│                  │         ┌──────────────────────────────────────┐
│  CPU-bound work  │         │   AI providers (free tiers)          │
│  via libgit2     │         │                                       │
└──────────────────┘         │   Voyage AI    (embeddings)          │
                             │   Groq         (batch LLM)           │
                             │   Gemini Pro   (interactive LLM)     │
                             └──────────────────────────────────────┘
```

### Stack at a glance

| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend | React 19, Tailwind CSS v4, shadcn/ui, Motion | Modern, fast, copy-paste components, dark-mode native |
| Backend (orchestration) | Python 3.12, FastAPI, SQLAlchemy 2.0 async | Best-in-class async I/O, pluggable provider layer |
| Performance layer | Rust + PyO3 + git2 + rayon | Native speed for diff parsing, parallel chunking without GIL |
| Database | PostgreSQL 17 + pgvector (HNSW) | Single-store for relational + vector data; HNSW for recall |
| Embeddings | Voyage AI `voyage-code-3` | Best embedding model for code (97.3% MRR on CodeSearchNet) |
| LLM (interactive) | Gemini 2.5 Pro / Groq Llama 70B | Free tiers, low latency |
| LLM (batch) | Groq Llama 3.1 8B Instant | Fast + free for indexing-time NL descriptions of diffs |

### The semantic insight

The non-obvious architectural choice — and the one that makes the
quality jump from "search by tokens" to "search by meaning" — is to
embed a **natural-language description** of each diff, not the raw diff
itself. Raw diffs are syntactically noisy (whitespace, hunk markers,
renames). A sentence like *"this commit adds exponential backoff retry
to the external API calls"* embeds far better, and the model retrieves
matching ideas regardless of how the original commit message was
phrased.

## The self-referential demo

OmniDiff's reference deployment indexes **its own commit history**.

That means the live demo lets you ask questions like *"how was hybrid
search implemented?"* and the answer is the actual commit where hybrid
search was implemented in this repository — explained in natural
language by the same pipeline you're querying. It's recursive,
self-validating, and grows automatically: every push adds a new
searchable data point.

## Current status

This project is in **active development** as a personal portfolio
project. It is **not** offered as a hosted SaaS — anyone wanting to use
it on their own data is expected to clone the repo and run it on their
own infrastructure.

A condensed public roadmap is in the table below. The full strategic
blueprint, phase docs, and tactical slice plans are kept private — they
contain working notes, open decisions, and internal trade-off discussions
that aren't meant for general audience. A polished public design
document will be published alongside the first working prototype.

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Setup & infrastructure (Docker Compose, FastAPI bootstrap, schema, providers) | ✅ Complete |
| 2-A | Git ingestion pipeline (Python baseline) | 🚧 In progress |
| 2-B | Profiling — identify the hot path | ⏳ Planned |
| 2-C | Performance layer in Rust (port hot path via PyO3) | ⏳ Planned |
| 3 | Embedding pipeline (Voyage + Groq descriptions, HNSW index) | ⏳ Planned |
| 4 | Search engine (semantic + keyword + RRF + LLM explanation) | ⏳ Planned |
| 5 | Frontend core (Linear-style UI with animations) | ⏳ Planned |
| 6 | Self-referential demo, public release, polish | ⏳ Planned |

## License

OmniDiff is released under the **GNU Affero General Public License
v3.0** ([`LICENSE`](./LICENSE)).

This means you are free to use, modify, and redistribute it — including
commercially — but if you run a modified version on a server, you must
make the source code of your modifications available to its users
(AGPL §13). This protects the project from being captured into closed
SaaS forks.

For commercial use without AGPL obligations, contact the author for
dual-licensing inquiries. See [`NOTICE.md`](./NOTICE.md) for full
attribution requirements.

## Author

Created by **Johan Carlos** · [github.com/johancarloss](https://github.com/johancarloss)

If you're a recruiter or fellow engineer who finds this project
interesting and wants to chat about the architecture, performance
engineering, or RAG systems — open an issue or reach out on GitHub.
