"""Unit tests for the git subprocess parser.

These run without a database — they only need git installed and a
temporary repo built via the `tmp_git_repo` fixture (or built inline
when a non-default shape is needed).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services._git_subprocess import (
    GitSubprocessError,
    get_commit_stats,
    walk_commits,
)


def _git(repo: Path, *args: str) -> None:
    env = {
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


def test_walk_commits_returns_all_linear_commits(tmp_git_repo: Path) -> None:
    """`tmp_git_repo` has 5 linear commits — walk should return all 5
    in chronological order (oldest first)."""
    metas = walk_commits(tmp_git_repo).metas
    assert len(metas) == 5
    assert [m.message for m in metas] == [
        "commit 0",
        "commit 1",
        "commit 2",
        "commit 3",
        "commit 4",
    ]


def test_walk_commits_skips_merge_commits(tmp_path: Path) -> None:
    """Build a repo with a merge commit and confirm it's filtered out."""
    repo = tmp_path / "merge_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "--local", "commit.gpgsign", "false")

    # main: commit A
    (repo / "a.txt").write_text("a")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "A")

    # branch feature: commit B
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "b.txt").write_text("b")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "B")

    # main: commit C
    _git(repo, "checkout", "-q", "main")
    (repo / "c.txt").write_text("c")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "C")

    # Merge feature into main (creates a merge commit M with 2 parents)
    _git(repo, "merge", "--no-ff", "-q", "-m", "M", "feature")

    result = walk_commits(repo)
    # Should have A, B, C — merge M is skipped, skipped_merges == 1.
    messages = [m.message for m in result.metas]
    assert "M" not in messages
    assert {"A", "B", "C"} == set(messages)
    assert result.skipped_merges == 1


def test_walk_commits_raises_on_missing_path(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(GitSubprocessError, match="path does not exist"):
        walk_commits(nonexistent)


def test_walk_commits_raises_on_non_repo(tmp_path: Path) -> None:
    """A regular directory (not a git repo) should fail cleanly."""
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    with pytest.raises(GitSubprocessError):
        walk_commits(plain)


def test_walk_commits_handles_multiline_message(tmp_path: Path) -> None:
    """Commit messages with embedded newlines must not corrupt parsing
    (this is what the `-z` null separator protects against)."""
    repo = tmp_path / "multiline_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "--local", "commit.gpgsign", "false")
    (repo / "x.txt").write_text("x")
    _git(repo, "add", ".")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "subject line",
        "-m",
        "body line 1\nbody line 2\nbody line 3",
    )

    metas = walk_commits(repo).metas
    assert len(metas) == 1
    assert "subject line" in metas[0].message
    assert "body line 2" in metas[0].message


def test_get_commit_stats_returns_counts(tmp_git_repo: Path) -> None:
    """First commit of fixture creates one file (1 insertion, 0 deletions)."""
    metas = walk_commits(tmp_git_repo).metas
    files, ins, dels = get_commit_stats(tmp_git_repo, metas[0].hash)
    assert files == 1
    assert ins >= 1
    assert dels == 0


def test_get_commit_stats_returns_zeros_on_unknown_hash(
    tmp_git_repo: Path,
) -> None:
    """Unknown commit hash should degrade to (0, 0, 0), not raise."""
    files, ins, dels = get_commit_stats(tmp_git_repo, "0" * 40)
    assert (files, ins, dels) == (0, 0, 0)


def test_walk_commits_with_since_returns_only_new(tmp_git_repo: Path) -> None:
    """`tmp_git_repo` has 5 linear commits; passing the hash of the third
    commit as `since` must return only the 2 commits after it."""
    all_metas = walk_commits(tmp_git_repo).metas
    assert len(all_metas) == 5

    # Use commit index 2 (third in chronological order) as the cutoff.
    cutoff_hash = all_metas[2].hash

    incremental = walk_commits(tmp_git_repo, since=cutoff_hash).metas
    assert len(incremental) == 2
    assert incremental[0].hash == all_metas[3].hash
    assert incremental[1].hash == all_metas[4].hash


def test_walk_commits_with_unknown_since_raises(tmp_git_repo: Path) -> None:
    """A `since` hash that doesn't exist in the repo (e.g. after a
    force-push) must raise GitSubprocessError, letting the caller decide
    whether to fall back to a full walk."""
    with pytest.raises(GitSubprocessError):
        walk_commits(tmp_git_repo, since="0" * 40)


def test_walk_commits_with_branch_walks_only_that_branch(tmp_path: Path) -> None:
    """`branch=<name>` walks the named ref instead of HEAD.

    Build a repo where `main` has 2 commits and a divergent `feature`
    branch (sharing the first commit, then 3 unique ones). Confirm:
      - walk(branch="main") sees 2
      - walk(branch="feature") sees 4 (1 shared root + 3 unique)
      - walk() (no branch arg) defaults to whatever HEAD points to
    """
    repo = tmp_path / "branchy_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "--local", "commit.gpgsign", "false")

    # main: shared root + 1 main-only commit.
    (repo / "root.txt").write_text("root")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "shared root")
    (repo / "main_only.txt").write_text("main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "main only")

    # feature: branches off after root, adds 3 commits.
    _git(repo, "checkout", "-q", "-b", "feature", "HEAD~1")
    for i in range(3):
        (repo / f"feature_{i}.txt").write_text(f"feature {i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"feature {i}")

    main_metas = walk_commits(repo, branch="main").metas
    feature_metas = walk_commits(repo, branch="feature").metas

    assert len(main_metas) == 2
    assert {m.message for m in main_metas} == {"shared root", "main only"}

    assert len(feature_metas) == 4
    assert "main only" not in {m.message for m in feature_metas}

    # Default (no branch) follows HEAD, which is `feature` after the
    # last checkout above.
    head_metas = walk_commits(repo).metas
    assert {m.message for m in head_metas} == {m.message for m in feature_metas}


def test_walk_commits_with_unknown_branch_raises(tmp_git_repo: Path) -> None:
    """An unknown branch name must surface as GitSubprocessError so the
    caller can map it to an exit code rather than crashing."""
    with pytest.raises(GitSubprocessError):
        walk_commits(tmp_git_repo, branch="branch-that-does-not-exist")
