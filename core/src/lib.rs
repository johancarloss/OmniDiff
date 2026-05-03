//! omnidiff_core — performance-critical Git ingestion layer for OmniDiff.
//!
//! This crate is the Rust half of OmniDiff's two-language architecture:
//! Python orchestrates I/O (DB, LLM APIs, HTTP); Rust does the CPU-bound work
//! (Git walking, diff parsing, chunking, filtering).
//!
//! Public API is exposed to Python via PyO3 — see `lib::omnidiff_core` below.
//! Each Python-facing function is a thin wrapper that:
//!   1. Releases the GIL (`Python::allow_threads`) for any non-trivial work
//!   2. Calls into a pure-Rust module (`walker`, `diff`, `chunker`, ...)
//!   3. Converts results to Python dicts/lists at the boundary

use pyo3::prelude::*;
use pyo3::types::PyDict;

mod chunker;
mod diff;
mod errors;
mod filters;
mod tokens;
mod walker;

/// Walk commits in a local Git repository.
///
/// Args:
///     repo_path: filesystem path to a cloned repo (must contain `.git/`)
///     since: optional ISO-8601 timestamp; only commits AFTER this are returned
///
/// Returns:
///     list[dict]: each dict has keys `hash`, `author_name`, `author_email`,
///                 `message`, `committed_at` (RFC3339), `parents` (list[str]),
///                 `files_changed`, `insertions`, `deletions`.
#[pyfunction]
#[pyo3(signature = (repo_path, since=None))]
fn walk_commits<'py>(
    py: Python<'py>,
    repo_path: &str,
    since: Option<&str>,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    // PHASE 2-C IMPL — placeholder
    let _ = (repo_path, since);
    let _ = py.allow_threads(|| { /* call walker::walk(...) here */ });
    todo!("implement after Fase 2-A baseline is established")
}

/// Extract diff chunks for a single commit.
///
/// Args:
///     repo_path: filesystem path to a cloned repo
///     commit_hash: full SHA-1 hash of the commit
///     max_tokens_per_chunk: token budget per chunk (chunks larger than this
///                           are split by hunk; chunks larger than 2x this
///                           are subdivided with overlap)
///
/// Returns:
///     list[dict]: each dict has keys `file_path`, `change_type` ('A'|'M'|'D'|'R'),
///                 `chunk_type` ('file'|'hunk'), `diff_content`, `tokens_used`.
#[pyfunction]
#[pyo3(signature = (repo_path, commit_hash, max_tokens_per_chunk=2000))]
fn extract_chunks<'py>(
    py: Python<'py>,
    repo_path: &str,
    commit_hash: &str,
    max_tokens_per_chunk: usize,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    // PHASE 2-C IMPL — placeholder
    let _ = (repo_path, commit_hash, max_tokens_per_chunk);
    let _ = py.allow_threads(|| { /* call diff::extract + chunker::chunk here */ });
    todo!("implement after Fase 2-A baseline is established")
}

/// Batch version: extract chunks for N commits in parallel via rayon.
///
/// This is where most of the speedup over the Python baseline comes from —
/// once the GIL is released, rayon runs `extract_chunks` across all CPU cores
/// with no Python-side coordination overhead.
///
/// Args: same as `extract_chunks`, but `commit_hashes` is a list.
///
/// Returns:
///     list[list[dict]]: same shape as `extract_chunks` but one list per commit,
///                        in the same order as `commit_hashes`.
#[pyfunction]
#[pyo3(signature = (repo_path, commit_hashes, max_tokens_per_chunk=2000))]
fn extract_chunks_batch<'py>(
    py: Python<'py>,
    repo_path: &str,
    commit_hashes: Vec<String>,
    max_tokens_per_chunk: usize,
) -> PyResult<Vec<Vec<Bound<'py, PyDict>>>> {
    // PHASE 2-C IMPL — placeholder
    //
    // Sketch:
    //   let results: Vec<Vec<RustChunk>> = py.allow_threads(|| {
    //       use rayon::prelude::*;
    //       commit_hashes.par_iter()
    //           .map(|h| diff::extract(repo_path, h, max_tokens_per_chunk))
    //           .collect::<Result<_, _>>()
    //   })?;
    //   convert_to_pydicts(py, results)
    let _ = (repo_path, commit_hashes, max_tokens_per_chunk);
    let _ = py.allow_threads(|| { /* parallel diff extraction */ });
    todo!("implement after Fase 2-A baseline is established")
}

/// Module entrypoint — registered with Python as `omnidiff_core`.
#[pymodule]
fn omnidiff_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(walk_commits, m)?)?;
    m.add_function(wrap_pyfunction!(extract_chunks, m)?)?;
    m.add_function(wrap_pyfunction!(extract_chunks_batch, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
