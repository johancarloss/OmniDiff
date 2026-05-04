# omnidiff-core

Performance-critical Git ingestion layer for [OmniDiff](https://github.com/johancarloss/OmniDiff), written in Rust and exposed to Python via [PyO3](https://pyo3.rs/).

This crate handles the **CPU-bound** part of the indexing pipeline:

- Walking commit history (via [`git2-rs`](https://github.com/rust-lang/git2-rs), bindings to libgit2)
- Extracting diffs per commit
- Chunking diffs by file / hunk with token-budget awareness
- Filtering noise (binaries, lock files, generated code, merge commits)

I/O-bound work — calling Voyage / Groq / Gemini, persisting in PostgreSQL — stays in the Python backend (`backend/app/services/ingest.py`), which orchestrates calls to this module.

## Why a separate Rust crate?

The Python backend is great for orchestration and async I/O, but parsing thousands of diffs is pure CPU work where Python's interpreter overhead and the GIL hurt. By dropping the hot path into Rust we get:

1. **Native speed** — libgit2 is C; `git2-rs` is a thin safe wrapper. No GitPython overhead.
2. **Real parallelism** — `Python::allow_threads` + `rayon` lets us process N commits across N cores with no GIL contention.
3. **Type safety** — diff parsing is the kind of code that benefits the most from a strong type system; the borrow checker prevents whole categories of bugs we'd hit in Python.
4. **Reusability** — this crate is publishable to PyPI on its own (`pip install omnidiff-core`); other tools could embed it.

The architectural pattern is the same one Astral uses in `uv` and `ruff`: **Python orchestrates, Rust executes the hot path**.

## Layout

```
core/
├── Cargo.toml              # Rust manifest
├── pyproject.toml          # maturin build config (PyO3 → Python wheel)
├── src/
│   ├── lib.rs              # PyO3 entrypoint — exposed Python module
│   ├── walker.rs           # commit iteration via git2
│   ├── diff.rs             # diff extraction & structuring
│   ├── chunker.rs          # split by file / hunk with token budget
│   ├── filters.rs          # ignore binaries / lockfiles / generated / merges
│   ├── tokens.rs           # token counting (tiktoken-rs)
│   └── errors.rs           # typed errors → Python exceptions
├── tests/                  # cargo test
├── benches/                # criterion benchmarks
└── fixtures/               # small test repos
```

## Development

### Prerequisites

```bash
# Install rustup (Rust toolchain)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install maturin (Rust ↔ Python build tool)
uv pip install maturin
```

### Build & install in the active virtualenv

From the `core/` directory, with the backend's `.venv` activated:

```bash
maturin develop --release
```

This compiles the crate and installs `omnidiff_core` into the venv as a regular Python package. After that:

```python
import omnidiff_core
omnidiff_core.walk_commits("/path/to/repo")
```

For iterative development without the release optimizations:

```bash
maturin develop          # debug build, faster compile, slower runtime
```

### Run tests

```bash
cargo test                         # Rust unit & integration tests
cargo clippy -- -D warnings        # Linter (treat warnings as errors)
cargo fmt --check                  # Formatter check
```

### Run benchmarks

```bash
cargo bench --bench ingest_bench
# Open core/target/criterion/report/index.html for HTML reports
```

## Public API (Python)

> Stable API surface — anything not listed here is internal and may change.

```python
import omnidiff_core

# Walk commits in a local repository.
# Returns a list of dicts: {hash, author_name, author_email, message,
#                           committed_at (RFC3339), parents, files_changed,
#                           insertions, deletions}
commits = omnidiff_core.walk_commits(repo_path: str, since: Optional[str] = None)

# Extract chunks for ONE commit.
# Returns a list of dicts: {file_path, change_type, chunk_type ('file'|'hunk'),
#                           diff_content, tokens_used}
chunks = omnidiff_core.extract_chunks(
    repo_path: str,
    commit_hash: str,
    max_tokens_per_chunk: int = 2000,
)

# Batch version: processes N commits in parallel via rayon.
# Returns a list-of-lists, same order as `commit_hashes`.
chunks_per_commit = omnidiff_core.extract_chunks_batch(
    repo_path: str,
    commit_hashes: list[str],
    max_tokens_per_chunk: int = 2000,
)
```

## License

AGPL-3.0-or-later — see [`../LICENSE`](../LICENSE) and
[`../NOTICE.md`](../NOTICE.md) at the repository root.
