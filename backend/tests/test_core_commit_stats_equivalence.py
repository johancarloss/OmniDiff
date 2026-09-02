"""Rust `commit_stats` must agree with `git show --shortstat`.

The corpus is built here rather than taken from a real repository so
each change kind is present exactly once and similarity ratios stay far
from the 50% rename threshold — the one place where libgit2 and git
disagree (see `docs/private/benchmarks/`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services._git_subprocess import get_commit_stats

core = pytest.importorskip(
    "omnidiff_core",
    reason="Rust extension not built — run `maturin develop` from core/",
)

_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@e.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@e.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=_ENV
    ).stdout


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo_with_every_change_kind(tmp_path: Path) -> Path:
    """One commit per kind of change git can report."""
    repo = tmp_path / "corpus"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "--local", "commit.gpgsign", "false")

    body = "\n".join(f"line {i}" for i in range(40)) + "\n"

    (repo / "a.py").write_text(body)
    _commit(repo, "root commit")

    (repo / "a.py").write_text(body.replace("line 3\n", "line 3 changed\n"))
    _commit(repo, "modify")

    (repo / "b.py").write_text("print('b')\n")
    _commit(repo, "add")

    (repo / "b.py").unlink()
    _commit(repo, "delete")

    (repo / "a.py").rename(repo / "c.py")
    _commit(repo, "pure rename")

    (repo / "bin.dat").write_bytes(bytes(range(256)) * 8)
    _commit(repo, "binary")

    (repo / "c.py").rename(repo / "d.py")
    (repo / "d.py").write_text(body.replace("line 7\n", "line 7 changed\n"))
    _commit(repo, "rename with edit")

    (repo / "e.py").write_text("x = 1\n")
    (repo / "d.py").unlink()
    _commit(repo, "add and delete together")

    return repo


def _hashes(repo: Path) -> list[str]:
    return _git(repo, "rev-list", "--reverse", "HEAD").split()


def test_commit_stats_matches_git(repo_with_every_change_kind: Path) -> None:
    repo = repo_with_every_change_kind
    for commit_hash in _hashes(repo):
        subject = _git(repo, "show", "-s", "--format=%s", commit_hash).strip()
        assert core.commit_stats(str(repo), commit_hash) == get_commit_stats(repo, commit_hash), (
            f"stats diverged on {subject!r}"
        )


def test_batch_matches_one_by_one(repo_with_every_change_kind: Path) -> None:
    repo = repo_with_every_change_kind
    hashes = _hashes(repo)
    assert core.commit_stats_batch(str(repo), hashes) == [
        core.commit_stats(str(repo), h) for h in hashes
    ]


def test_batch_matches_git(repo_with_every_change_kind: Path) -> None:
    repo = repo_with_every_change_kind
    hashes = _hashes(repo)
    assert core.commit_stats_batch(str(repo), hashes) == [get_commit_stats(repo, h) for h in hashes]


def test_batch_of_nothing_returns_nothing(repo_with_every_change_kind: Path) -> None:
    assert core.commit_stats_batch(str(repo_with_every_change_kind), []) == []


def test_unknown_commit_raises(repo_with_every_change_kind: Path) -> None:
    with pytest.raises(RuntimeError, match="git:"):
        core.commit_stats(str(repo_with_every_change_kind), "0" * 40)


def test_missing_repository_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="git:"):
        core.commit_stats(str(tmp_path / "nope"), "HEAD")
