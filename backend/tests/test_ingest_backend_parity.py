"""Indexing through either backend must land the same rows.

`git_backend` picks between the Rust extension and the git subprocess
path. They are separate implementations of the same contract, so the
guarantee worth asserting is not "the functions agree" — the unit tests
cover that — but "the database ends up the same either way".
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.commit import Commit, CommitChunk
from app.services.git_backend import active_backend
from app.services.ingest import IngestService

pytestmark = pytest.mark.integration

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


@pytest.fixture
def select_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Force a backend for one call, clearing both caches around it."""

    def _use(name: str) -> None:
        monkeypatch.setenv("GIT_BACKEND", name)
        get_settings.cache_clear()
        active_backend.cache_clear()

    yield _use
    monkeypatch.delenv("GIT_BACKEND", raising=False)
    get_settings.cache_clear()
    active_backend.cache_clear()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with enough variety that the two backends can disagree."""
    path = tmp_path / "parity"
    path.mkdir()
    _git(path, "init", "-q", "--initial-branch=main")
    _git(path, "config", "--local", "commit.gpgsign", "false")

    def commit(message: str) -> None:
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", message)

    body = "".join(f"line {i}\n" for i in range(60))

    (path / "a.py").write_text(body)
    (path / "notes.md").write_text("# notes\n")
    commit("root")

    (path / "a.py").write_text(body.replace("line 20\n", "line 20 edited\n"))
    commit("modify")

    (path / "b.py").write_text("".join(f"b {i}\n" for i in range(700)))
    commit("add a large file")

    (path / "a.py").rename(path / "c.py")
    commit("rename")

    (path / "blob.bin").write_bytes(bytes(range(256)) * 32)
    (path / "uv.lock").write_text("locked = true\n")
    commit("add binary and a lock file")

    (path / "b.py").unlink()
    commit("delete")

    return path


async def _index(session: AsyncSession, repo: Path, url: str) -> None:
    await IngestService(session).index(repo, url=url, name=url)


async def _rows(session: AsyncSession, url: str) -> dict[str, Any]:
    commits = (
        (
            await session.execute(
                select(Commit).join(Commit.repository).where(Commit.repository.has(url=url))
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, Any] = {}
    for commit in sorted(commits, key=lambda c: c.hash):
        chunks = (
            (
                await session.execute(
                    select(CommitChunk)
                    .where(CommitChunk.commit_id == commit.id)
                    .order_by(CommitChunk.id)
                )
            )
            .scalars()
            .all()
        )
        out[commit.hash] = {
            "stats": (commit.files_changed, commit.insertions, commit.deletions),
            "chunks": [
                (c.chunk_type, c.file_path, c.old_path, c.change_type, c.tokens_used)
                for c in chunks
            ],
            "texts": [c.diff for c in chunks],
        }
    return out


async def test_both_backends_produce_the_same_rows(
    db_session: AsyncSession, repo: Path, select_backend: Any
) -> None:
    select_backend("python")
    assert active_backend() == "python"
    await _index(db_session, repo, "file:///parity-python")
    from_python = await _rows(db_session, "file:///parity-python")

    select_backend("rust")
    assert active_backend() == "rust"
    await _index(db_session, repo, "file:///parity-rust")
    from_rust = await _rows(db_session, "file:///parity-rust")

    assert from_python, "the python run indexed nothing — the fixture is broken"
    assert from_python.keys() == from_rust.keys()
    for commit_hash, expected in from_python.items():
        actual = from_rust[commit_hash]
        assert expected["stats"] == actual["stats"], f"stats diverged on {commit_hash}"
        assert expected["chunks"] == actual["chunks"], f"chunks diverged on {commit_hash}"


async def test_stored_diff_text_matches_between_backends(
    db_session: AsyncSession, repo: Path, select_backend: Any
) -> None:
    """The stored text is what Phase 3 embeds, so it has to be the same
    text — not merely the same number of chunks."""
    select_backend("python")
    await _index(db_session, repo, "file:///text-python")
    select_backend("rust")
    await _index(db_session, repo, "file:///text-rust")

    from_python = await _rows(db_session, "file:///text-python")
    from_rust = await _rows(db_session, "file:///text-rust")

    for commit_hash, expected in from_python.items():
        assert expected["texts"] == from_rust[commit_hash]["texts"], (
            f"stored diff text diverged on {commit_hash}"
        )
