//! omnidiff_core — performance-critical Git ingestion layer for OmniDiff.
//!
//! This crate is the Rust half of OmniDiff's two-language architecture:
//! Python orchestrates I/O (DB, LLM APIs, HTTP); Rust does the CPU-bound
//! work that measurement showed to be worth porting.
//!
//! ## Scope
//!
//! Phase 2-B profiled the pipeline and cut the original port list from
//! four areas down to one: reading commit diffs. Chunking and
//! tokenisation stay in Python because `tiktoken` already runs a Rust
//! BPE behind PyO3, and commit walking costs ~0. The reasoning and the
//! numbers are in `docs/private/benchmarks/profiling-bottleneck.md`.
//!
//! - `diff` — one libgit2 pass per commit: stats, file metadata, patch.
//! - `filters` — skip rules, mirrored from `app/services/ingest_filters.py`.
//! - `errors` — maps `CoreError` onto Python exceptions.

use pyo3::prelude::*;

pub mod diff;
pub mod errors;
pub mod filters;

/// Module entrypoint — registered with Python as `omnidiff_core`.
#[pymodule]
fn omnidiff_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
