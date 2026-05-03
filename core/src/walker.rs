//! Commit walking — iterates a Git repository's history via libgit2.
//!
//! The walker is a thin layer over `git2::Revwalk` that yields a
//! language-agnostic `CommitMeta` struct. The PyO3 layer (lib.rs) is
//! responsible for converting these structs into Python dicts.
//!
//! Design notes:
//!   - Pure Rust, no PyO3 imports here. Keeps the module testable with
//!     `cargo test` without spinning up a Python interpreter.
//!   - Returns owned data (Strings, not &str). The `&Repository` is
//!     short-lived so we can't borrow from it across the FFI boundary.
//!   - `since` filtering is done in Rust to avoid materializing the entire
//!     history just to throw most of it away.

use crate::errors::CoreError;

#[derive(Debug, Clone)]
pub struct CommitMeta {
    pub hash: String,
    pub author_name: String,
    pub author_email: String,
    pub message: String,
    pub committed_at: String, // RFC3339
    pub parents: Vec<String>,
    pub files_changed: usize,
    pub insertions: usize,
    pub deletions: usize,
}

/// Walk all commits reachable from HEAD, optionally filtering by date.
///
/// `since` is an RFC3339 timestamp; if provided, commits committed
/// on or before this time are skipped.
pub fn walk(_repo_path: &str, _since: Option<&str>) -> Result<Vec<CommitMeta>, CoreError> {
    // PHASE 2-C IMPL — sketch:
    //
    // let repo = git2::Repository::open(repo_path)?;
    // let mut revwalk = repo.revwalk()?;
    // revwalk.push_head()?;
    // revwalk.set_sorting(git2::Sort::TIME | git2::Sort::REVERSE)?;
    //
    // let mut out = Vec::new();
    // for oid in revwalk {
    //     let oid = oid?;
    //     let commit = repo.find_commit(oid)?;
    //     if commit.parent_count() > 1 {
    //         continue; // skip merge commits per blueprint § 4.8
    //     }
    //     let stats = compute_stats(&repo, &commit)?;
    //     out.push(CommitMeta {
    //         hash: oid.to_string(),
    //         author_name: commit.author().name().unwrap_or("").to_string(),
    //         author_email: commit.author().email().unwrap_or("").to_string(),
    //         message: commit.message().unwrap_or("").to_string(),
    //         committed_at: format_time(commit.time()),
    //         parents: commit.parent_ids().map(|o| o.to_string()).collect(),
    //         files_changed: stats.files_changed,
    //         insertions: stats.insertions,
    //         deletions: stats.deletions,
    //     });
    // }
    // Ok(out)
    todo!("implement after Fase 2-A baseline is established")
}

#[cfg(test)]
mod tests {
    // Tests will use the `tempfile` + `git2` crates to spin up a tiny
    // in-memory repo, commit a few files, and assert walk() returns
    // them in the expected order with correct stats.
}
