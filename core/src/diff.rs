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
    /// Set when the patch exceeds `MAX_DIFF_BYTES_PER_FILE`; content is
    /// dropped and the Python chunker emits a stub chunk instead.
    pub truncated: bool,
}

/// Marker git emits in place of content for a changed binary file.
/// Mirror of `BINARY_MARKER` in `app/services/_git_subprocess.py`.
pub const BINARY_MARKER: &str = "Binary files ";

/// Mirrors `MAX_DIFF_BYTES_PER_FILE` in `app/services/_git_subprocess.py`.
pub const MAX_DIFF_BYTES_PER_FILE: usize = 10 * 1024 * 1024;

/// Map libgit2's delta status onto the four codes the schema uses.
///
/// Mirrors `_STATUS_MAP` in `app/services/_git_subprocess.py`: a copy
/// reads as an addition, a type change as a modification.
fn change_type_of(status: git2::Delta) -> ChangeType {
    match status {
        git2::Delta::Added | git2::Delta::Copied | git2::Delta::Untracked => ChangeType::Added,
        git2::Delta::Deleted => ChangeType::Deleted,
        git2::Delta::Renamed => ChangeType::Renamed,
        _ => ChangeType::Modified,
    }
}

fn path_string(path: Option<&std::path::Path>) -> Option<String> {
    path.map(|p| p.to_string_lossy().into_owned())
}

/// Per-file diffs for one commit, from a single libgit2 pass.
///
/// Replaces the two `git show` invocations the Python path needs (one
/// `--raw` for metadata, one `-U3` for content): the same `Diff` object
/// answers both.
fn extract_for(repo: &Repository, commit_hash: &str) -> Result<Vec<FileDiff>, CoreError> {
    let commit = repo.revparse_single(commit_hash)?.peel_to_commit()?;
    let tree = commit.tree()?;
    let parent_tree = match commit.parent(0) {
        Ok(parent) => Some(parent.tree()?),
        Err(_) => None,
    };

    let mut opts = git2::DiffOptions::new();
    // `-U3` plus the heuristic git has applied by default since 2.14.
    // Without it the same changes come out with hunk boundaries shifted
    // by a line or two, and the patch text stops matching git's.
    opts.context_lines(3).indent_heuristic(true);
    let mut diff = repo.diff_tree_to_tree(parent_tree.as_ref(), Some(&tree), Some(&mut opts))?;

    let mut find = git2::DiffFindOptions::new();
    find.renames(true).rename_threshold(50).copies(false);
    diff.find_similar(Some(&mut find))?;

    let mut out = Vec::new();
    for idx in 0..diff.deltas().len() {
        // The patch has to be built before the binary flag is meaningful:
        // libgit2 only inspects file contents when generating it.
        let patch = git2::Patch::from_diff(&diff, idx)?;
        let delta = diff
            .get_delta(idx)
            .ok_or_else(|| CoreError::Invalid(format!("delta {idx} vanished between calls")))?;

        let change_type = change_type_of(delta.status());
        let new_path = path_string(delta.new_file().path());
        let old_path = path_string(delta.old_file().path());

        let mut diff_content = String::new();
        let mut truncated = false;

        if let Some(mut patch) = patch {
            let buf = patch.to_buf()?;
            if buf.len() > MAX_DIFF_BYTES_PER_FILE {
                truncated = true;
            } else {
                diff_content = String::from_utf8_lossy(&buf).into_owned();
            }
        }

        // The Python rule, applied to libgit2's text: "did the patch
        // print a binary marker?".
        //
        // Known divergence: for a *pure rename* of a binary file, git
        // prints the rename header and no marker, so the Python path
        // reports `is_binary=False` and keeps the header. libgit2 prints
        // the marker instead, so this side reports `is_binary=True` with
        // no content. Such files carry binary extensions and are dropped
        // by `filters::should_skip_file` before the chunker sees them, so
        // the difference does not reach the pipeline.
        let is_binary = diff_content.contains(BINARY_MARKER);
        if is_binary {
            diff_content = String::new();
        }

        out.push(FileDiff {
            // git names the file on both sides even for a deletion, so
            // the new path is present except in odd histories.
            file_path: new_path.or_else(|| old_path.clone()).unwrap_or_default(),
            old_path: match change_type {
                ChangeType::Renamed => old_path,
                _ => None,
            },
            change_type,
            diff_content,
            is_binary,
            truncated,
        });
    }

    Ok(out)
}

/// Per-file diffs for a single commit.
pub fn extract(repo_path: &str, commit_hash: &str) -> Result<Vec<FileDiff>, CoreError> {
    let repo = Repository::open(repo_path)?;
    extract_for(&repo, commit_hash)
}

/// Per-file diffs for many commits, opening the repository once.
pub fn extract_batch(
    repo_path: &str,
    commit_hashes: &[String],
) -> Result<Vec<Vec<FileDiff>>, CoreError> {
    let repo = Repository::open(repo_path)?;
    commit_hashes
        .iter()
        .map(|h| extract_for(&repo, h))
        .collect()
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

    #[test]
    fn root_commit_reports_every_file_as_added() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        fs::write(tmp.path().join("a.txt"), body(3)).unwrap();
        fs::write(tmp.path().join("b.txt"), body(2)).unwrap();
        let hash = commit_all(&repo, "root");

        let files = extract_for(&repo, &hash).unwrap();
        assert_eq!(files.len(), 2);
        assert!(files.iter().all(|f| f.change_type == ChangeType::Added));
        assert!(files.iter().all(|f| !f.diff_content.is_empty()));
    }

    #[test]
    fn rename_carries_the_old_path() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        fs::write(tmp.path().join("a.txt"), body(40)).unwrap();
        commit_all(&repo, "root");

        fs::rename(tmp.path().join("a.txt"), tmp.path().join("b.txt")).unwrap();
        let hash = commit_all(&repo, "rename");

        let files = extract_for(&repo, &hash).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].change_type, ChangeType::Renamed);
        assert_eq!(files[0].file_path, "b.txt");
        assert_eq!(files[0].old_path.as_deref(), Some("a.txt"));
    }

    #[test]
    fn deletion_keeps_the_path_and_reports_removed_lines() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        fs::write(tmp.path().join("a.txt"), body(4)).unwrap();
        commit_all(&repo, "root");

        fs::remove_file(tmp.path().join("a.txt")).unwrap();
        let hash = commit_all(&repo, "delete");

        let files = extract_for(&repo, &hash).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].change_type, ChangeType::Deleted);
        assert_eq!(files[0].file_path, "a.txt");
        assert!(files[0].diff_content.contains("-line 0"));
    }

    #[test]
    fn changed_binary_reports_no_content() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        let blob: Vec<u8> = (0..=255u8).cycle().take(4096).collect();
        fs::write(tmp.path().join("blob.bin"), &blob).unwrap();
        commit_all(&repo, "root");

        let flipped: Vec<u8> = blob.iter().rev().copied().collect();
        fs::write(tmp.path().join("blob.bin"), &flipped).unwrap();
        let hash = commit_all(&repo, "modify binary");

        let files = extract_for(&repo, &hash).unwrap();
        assert_eq!(files.len(), 1);
        assert!(files[0].is_binary);
        assert!(files[0].diff_content.is_empty());
    }

    #[test]
    fn extract_batch_matches_one_by_one() {
        let tmp = TempDir::new().unwrap();
        let repo = init(tmp.path());
        let mut hashes = Vec::new();
        for i in 0..3 {
            fs::write(tmp.path().join("a.txt"), body(i + 2)).unwrap();
            hashes.push(commit_all(&repo, &format!("commit {i}")));
        }
        let path = tmp.path().to_str().unwrap();
        let one_by_one: Vec<Vec<_>> = hashes
            .iter()
            .map(|h| {
                extract(path, h)
                    .unwrap()
                    .into_iter()
                    .map(|f| (f.file_path, f.change_type, f.diff_content))
                    .collect()
            })
            .collect();
        let batched: Vec<Vec<_>> = extract_batch(path, &hashes)
            .unwrap()
            .into_iter()
            .map(|c| {
                c.into_iter()
                    .map(|f| (f.file_path, f.change_type, f.diff_content))
                    .collect()
            })
            .collect();
        assert_eq!(batched, one_by_one);
    }
}
