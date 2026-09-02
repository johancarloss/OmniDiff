//! Diff extraction — for a given commit, produce per-file diff entries
//! that the Python chunker splits into embeddable chunks.
//!
//! Chunking stays in Python (`app/services/ingest_chunker.py`): Phase
//! 2-B measured that its cost is redundant tokenisation, not language
//! speed, and `tiktoken` already runs a Rust BPE underneath.

use git2::Repository;

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
    pub diff_content: String, // unified-format text
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

/// Diff statistics for one commit: `(files_changed, insertions, deletions)`.
///
/// Mirrors `git show --shortstat`, rename detection included: git turns
/// it on by default, libgit2 does not.
///
/// Note the borrow: `Commit`, `Tree` and `Diff` all borrow from `repo`,
/// so none of them may outlive it. Returning plain numbers keeps the
/// caller free of that constraint.
fn stats_for(repo: &Repository, commit_hash: &str) -> Result<(usize, usize, usize), CoreError> {
    let commit = repo.revparse_single(commit_hash)?.peel_to_commit()?;
    let tree = commit.tree()?;

    // A root commit has no parent. `None` here means "diff against the
    // empty tree", which is what git itself shows for a root commit.
    let parent_tree = match commit.parent(0) {
        Ok(parent) => Some(parent.tree()?),
        Err(_) => None,
    };

    let mut diff = repo.diff_tree_to_tree(parent_tree.as_ref(), Some(&tree), None)?;

    // Spell git's defaults out. libgit2's own defaults pair files git
    // would leave alone, and the stats drift apart on files sitting near
    // the similarity threshold.
    let mut find = git2::DiffFindOptions::new();
    find.renames(true).rename_threshold(50).copies(false);
    diff.find_similar(Some(&mut find))?;

    let stats = diff.stats()?;
    Ok((stats.files_changed(), stats.insertions(), stats.deletions()))
}

/// Diff statistics for a single commit.
pub fn commit_stats(
    repo_path: &str,
    commit_hash: &str,
) -> Result<(usize, usize, usize), CoreError> {
    let repo = Repository::open(repo_path)?;
    stats_for(&repo, commit_hash)
}

/// Diff statistics for many commits, opening the repository once.
///
/// Opening a repository costs roughly half a millisecond — negligible
/// alone, ~0.9s across the 1620 commits of the benchmark corpus. The
/// batch form also crosses the Python boundary once instead of N times.
pub fn commit_stats_batch(
    repo_path: &str,
    commit_hashes: &[String],
) -> Result<Vec<(usize, usize, usize)>, CoreError> {
    let repo = Repository::open(repo_path)?;
    commit_hashes.iter().map(|h| stats_for(&repo, h)).collect()
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;

    use git2::{IndexAddOption, Signature};
    use tempfile::TempDir;

    use super::*;

    /// Stage everything (including deletions) and commit; returns the hash.
    fn commit_all(repo: &Repository, message: &str) -> String {
        let mut index = repo.index().unwrap();
        index
            .add_all(["*"].iter(), IndexAddOption::DEFAULT, None)
            .unwrap();
        // `add_all` records additions and edits; deletions need `update_all`.
        index.update_all(["*"].iter(), None).unwrap();
        index.write().unwrap();

        let tree = repo.find_tree(index.write_tree().unwrap()).unwrap();
        let sig = Signature::now("Test", "t@e.com").unwrap();
        let parents = match repo.head() {
            Ok(head) => vec![head.peel_to_commit().unwrap()],
            Err(_) => vec![],
        };
        let refs: Vec<&git2::Commit> = parents.iter().collect();
        repo.commit(Some("HEAD"), &sig, &sig, message, &tree, &refs)
            .unwrap()
            .to_string()
    }

    fn body(lines: usize) -> String {
        (0..lines).map(|i| format!("line {i}\n")).collect()
    }

    fn init(dir: &Path) -> Repository {
        Repository::init(dir).unwrap()
    }

    #[test]
    fn root_commit_counts_against_the_empty_tree() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        fs::write(tmp.path().join("a.txt"), body(3)).unwrap();
        let hash = commit_all(&repo, "root");
        assert_eq!(stats_for(&repo, &hash).unwrap(), (1, 3, 0));
    }

    #[test]
    fn modifying_one_line_counts_one_each_way() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        fs::write(tmp.path().join("a.txt"), body(10)).unwrap();
        commit_all(&repo, "root");

        fs::write(
            tmp.path().join("a.txt"),
            body(10).replace("line 4", "changed"),
        )
        .unwrap();
        let hash = commit_all(&repo, "modify");
        assert_eq!(stats_for(&repo, &hash).unwrap(), (1, 1, 1));
    }

    #[test]
    fn deleting_a_file_counts_its_lines_as_deletions() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        fs::write(tmp.path().join("a.txt"), body(5)).unwrap();
        commit_all(&repo, "root");

        fs::remove_file(tmp.path().join("a.txt")).unwrap();
        let hash = commit_all(&repo, "delete");
        assert_eq!(stats_for(&repo, &hash).unwrap(), (1, 0, 5));
    }

    #[test]
    fn pure_rename_counts_one_file_and_no_lines() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        fs::write(tmp.path().join("a.txt"), body(40)).unwrap();
        commit_all(&repo, "root");

        fs::rename(tmp.path().join("a.txt"), tmp.path().join("b.txt")).unwrap();
        let hash = commit_all(&repo, "rename");
        assert_eq!(stats_for(&repo, &hash).unwrap(), (1, 0, 0));
    }

    #[test]
    fn batch_matches_one_by_one() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        let mut hashes = Vec::new();
        for i in 0..4 {
            fs::write(tmp.path().join("a.txt"), body(i + 1)).unwrap();
            hashes.push(commit_all(&repo, &format!("commit {i}")));
        }
        let path = tmp.path().to_str().unwrap();
        let one_by_one: Vec<_> = hashes
            .iter()
            .map(|h| commit_stats(path, h).unwrap())
            .collect();
        assert_eq!(commit_stats_batch(path, &hashes).unwrap(), one_by_one);
    }

    #[test]
    fn unknown_commit_is_an_error() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        fs::write(tmp.path().join("a.txt"), body(1)).unwrap();
        commit_all(&repo, "root");
        assert!(stats_for(&repo, &"0".repeat(40)).is_err());
    }
}
