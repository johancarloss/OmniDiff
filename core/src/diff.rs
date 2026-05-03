//! Diff extraction — for a given commit, produce per-file diff entries
//! that the chunker can later split into embeddable chunks.
//!
//! This is intentionally separate from `chunker.rs`:
//!   - `diff` is about "what changed" (raw structured data)
//!   - `chunker` is about "how to size the data for embedding"
//! Keeping them split lets the chunker stay testable with synthetic input.

use crate::errors::CoreError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChangeType {
    Added,
    Modified,
    Deleted,
    Renamed,
}

impl ChangeType {
    pub fn as_char(self) -> char {
        match self {
            ChangeType::Added => 'A',
            ChangeType::Modified => 'M',
            ChangeType::Deleted => 'D',
            ChangeType::Renamed => 'R',
        }
    }
}

#[derive(Debug, Clone)]
pub struct FileDiff {
    pub file_path: String,
    pub old_path: Option<String>, // for renames
    pub change_type: ChangeType,
    pub diff_content: String,     // unified-format text
    pub is_binary: bool,
}

/// Extract per-file diffs for a single commit (against its first parent,
/// or against the empty tree if the commit is a root).
pub fn extract(_repo_path: &str, _commit_hash: &str) -> Result<Vec<FileDiff>, CoreError> {
    // PHASE 2-C IMPL — sketch:
    //
    // let repo = git2::Repository::open(repo_path)?;
    // let oid = git2::Oid::from_str(commit_hash)?;
    // let commit = repo.find_commit(oid)?;
    // let tree = commit.tree()?;
    // let parent_tree = if commit.parent_count() > 0 {
    //     Some(commit.parent(0)?.tree()?)
    // } else {
    //     None
    // };
    //
    // let mut opts = git2::DiffOptions::new();
    // opts.context_lines(3).interhunk_lines(0);
    //
    // let diff = repo.diff_tree_to_tree(parent_tree.as_ref(), Some(&tree), Some(&mut opts))?;
    // let mut find_opts = git2::DiffFindOptions::new();
    // find_opts.renames(true).copies(false);
    // diff.find_similar(Some(&mut find_opts))?;
    //
    // let mut files: Vec<FileDiff> = Vec::new();
    // diff.foreach(
    //     &mut |delta, _| { /* push a new FileDiff with metadata */ true },
    //     None,
    //     None,
    //     Some(&mut |_delta, _hunk, line| {
    //         /* append line to current FileDiff.diff_content */
    //         true
    //     }),
    // )?;
    // Ok(files)
    todo!("implement after Fase 2-A baseline is established")
}

#[cfg(test)]
mod tests {
    // Cover: simple add, modify, delete, rename, binary file (should be marked
    // is_binary=true with empty diff_content), root commit (parent=None path).
}
