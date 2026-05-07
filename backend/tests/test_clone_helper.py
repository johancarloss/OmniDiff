"""Unit tests for the clone helper.

These run without a database. Where a real `git clone` is needed, we
use a local `file://` URL pointing to a fixture repo created in tmp.
That keeps the suite offline and deterministic — no network access at
test time.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.clone import (
    InvalidRepoSourceError,
    derive_repo_name,
    ensure_local_clone,
    looks_like_url,
)

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@e.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@e.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=_GIT_ENV,
    )


def _make_origin_repo(tmp_path: Path, name: str = "origin") -> Path:
    """Create a small bare-ish source repo with a few commits, suitable
    as a `file://` clone source for tests."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "--local", "commit.gpgsign", "false")
    (repo / "first.txt").write_text("first\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    (repo / "second.txt").write_text("second\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "second")
    return repo


def test_looks_like_url_recognizes_common_schemes() -> None:
    assert looks_like_url("https://github.com/x/y")
    assert looks_like_url("http://example.com/a/b.git")
    assert looks_like_url("ssh://git@host/team/repo.git")
    assert looks_like_url("git://kernel.org/repo.git")
    assert looks_like_url("git@github.com:x/y.git")

    assert not looks_like_url("./local/path")
    assert not looks_like_url("/absolute/path")
    assert not looks_like_url("relative/path")
    assert not looks_like_url("")


def test_derive_repo_name_from_https_url() -> None:
    assert derive_repo_name("https://github.com/johancarloss/OmniDiff") == "johancarloss__OmniDiff"
    assert (
        derive_repo_name("https://github.com/johancarloss/OmniDiff.git") == "johancarloss__OmniDiff"
    )
    assert derive_repo_name("https://gitlab.com/group/sub/proj.git") == "sub__proj"


def test_derive_repo_name_from_ssh_url() -> None:
    assert derive_repo_name("git@github.com:johancarloss/OmniDiff.git") == "johancarloss__OmniDiff"
    assert derive_repo_name("ssh://git@example.com/team/repo.git") == "team__repo"


def test_ensure_local_clone_returns_path_for_existing_dir(
    tmp_path: Path,
) -> None:
    """When `arg` is an existing local directory, no clone happens —
    we just use it as-is."""
    repo = _make_origin_repo(tmp_path)
    repos_dir = tmp_path / "repos"

    local_path, url, name = ensure_local_clone(str(repo), repos_dir)

    assert local_path == repo.resolve()
    assert url == f"file://{repo.resolve()}"
    assert name == repo.name
    # `repos/` should NOT have been created — the helper used the local path.
    assert not repos_dir.exists()


def test_ensure_local_clone_clones_then_fetches_on_second_call(
    tmp_path: Path,
) -> None:
    """First call clones into repos_dir; second call fetches + resets,
    bringing in any new commits made on the source repo in between."""
    origin = _make_origin_repo(tmp_path)
    origin_url = f"file://{origin.resolve()}"
    repos_dir = tmp_path / "repos"

    # First call: clone fresh.
    local_path1, url1, name1 = ensure_local_clone(origin_url, repos_dir)
    assert local_path1.exists()
    assert (local_path1 / "first.txt").exists()
    assert (local_path1 / "second.txt").exists()

    # Add a new commit to the origin AFTER the clone.
    (origin / "third.txt").write_text("third\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "third")

    # Second call: must fetch and bring `third.txt` into the clone.
    local_path2, url2, name2 = ensure_local_clone(origin_url, repos_dir)
    assert local_path2 == local_path1
    assert (local_path2 / "third.txt").exists(), (
        "second call should refresh the clone with new commits from origin"
    )


def test_ensure_local_clone_raises_for_invalid_arg(tmp_path: Path) -> None:
    """Argument that's neither a URL with a known scheme nor an existing
    directory must raise InvalidRepoSourceError."""
    repos_dir = tmp_path / "repos"
    with pytest.raises(InvalidRepoSourceError):
        ensure_local_clone("not-a-url-not-a-path", repos_dir)
