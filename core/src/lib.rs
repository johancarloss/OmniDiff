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

use crate::errors::CoreError;

pub mod diff;
pub mod errors;
pub mod filters;

/// Skip rule for one file inside a commit diff.
///
/// `is_binary_in_git` is keyword-only to mirror the Python signature in
/// `app/services/ingest_filters.py`, so the equivalence tests can call
/// both sides identically.
#[pyfunction]
#[pyo3(signature = (path, *, is_binary_in_git))]
fn should_skip_file(path: &str, is_binary_in_git: bool) -> bool {
    filters::should_skip_file(path, is_binary_in_git)
}

/// Diff statistics for one commit, as `(files_changed, insertions, deletions)`.
///
/// Replaces the `git show --shortstat` subprocess in
/// `app/services/_git_subprocess.py`.
#[pyfunction]
fn commit_stats(repo_path: &str, commit_hash: &str) -> Result<(usize, usize, usize), CoreError> {
    diff::commit_stats(repo_path, commit_hash)
}

/// Diff statistics for many commits, opening the repository once.
///
/// Preferred over calling `commit_stats` in a loop: it amortises the
/// repository open and crosses the language boundary a single time.
#[pyfunction]
fn commit_stats_batch(
    repo_path: &str,
    commit_hashes: Vec<String>,
) -> Result<Vec<(usize, usize, usize)>, CoreError> {
    diff::commit_stats_batch(repo_path, &commit_hashes)
}

/// Skip rule for a commit. Merge commits are skipped.
#[pyfunction]
fn should_skip_commit(parent_count: usize) -> bool {
    filters::should_skip_commit(parent_count)
}

/// Module entrypoint — registered with Python as `omnidiff_core`.
#[pymodule]
fn omnidiff_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(should_skip_file, m)?)?;
    m.add_function(wrap_pyfunction!(should_skip_commit, m)?)?;
    m.add_function(wrap_pyfunction!(commit_stats, m)?)?;
    m.add_function(wrap_pyfunction!(commit_stats_batch, m)?)?;
    Ok(())
}
