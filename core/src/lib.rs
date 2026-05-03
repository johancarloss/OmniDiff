//! omnidiff_core — performance-critical Git ingestion layer for OmniDiff.
//!
//! This crate is the Rust half of OmniDiff's two-language architecture:
//! Python orchestrates I/O (DB, LLM APIs, HTTP); Rust does the CPU-bound
//! work (Git walking, diff parsing, chunking, filtering).
//!
//! ## Status: scaffold
//!
//! The modules below (`walker`, `diff`, `chunker`, `filters`, `tokens`,
//! `errors`) define the data model and module boundaries. Implementation
//! lands in Phase 2-C of the project — see
//! `docs/private/blueprint/RUST-MIGRATION-PLAN.md`.
//!
//! Until Phase 2-C, the only thing exposed to Python is the module name
//! and `__version__`. The `#![allow(dead_code)]` at the top of this file
//! exists for that reason and will be removed once the modules are wired
//! into the public PyO3 functions.

#![allow(dead_code)]

use pyo3::prelude::*;

mod chunker;
mod diff;
mod errors;
mod filters;
mod tokens;
mod walker;

/// Module entrypoint — registered with Python as `omnidiff_core`.
///
/// Phase 2-C will add `walk_commits`, `extract_chunks`, and
/// `extract_chunks_batch` here as `#[pyfunction]`s wrapping the
/// corresponding modules above.
#[pymodule]
fn omnidiff_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
