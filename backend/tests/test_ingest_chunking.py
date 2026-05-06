"""Integration tests for the chunking step inside IngestService.index.

These run against a real Postgres (docker compose up -d db). They verify
that the pipeline (extract → filter → chunk → persist) produces the
right rows in commit_chunks under realistic conditions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commit import Commit, CommitChunk
from app.services.ingest import IngestService

pytestmark = pytest.mark.integration

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


def _init_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "--local", "commit.gpgsign", "false")
    return repo


async def test_index_populates_commit_chunks(db_session: AsyncSession, tmp_git_repo: Path) -> None:
    """The 5-commit fixture (1 small text file each) → 5 chunks total,
    all chunk_type='file' because each diff is well under 500 tokens."""
    service = IngestService(db_session)
    result = await service.index(tmp_git_repo, url=f"file://{tmp_git_repo}", name="fixture")

    assert result.commits_inserted == 5
    assert result.chunks_inserted == 5
    assert result.skipped_merges == 0

    chunks = (await db_session.execute(select(CommitChunk))).scalars().all()
    assert len(chunks) == 5
    assert all(c.chunk_type.value == "file" for c in chunks)
    assert all(c.change_type == "A" for c in chunks)


async def test_index_skips_lock_files(db_session: AsyncSession, tmp_path: Path) -> None:
    """A commit that adds package-lock.json must produce 0 chunks."""
    repo = _init_repo(tmp_path, "lock_repo")
    (repo / "package-lock.json").write_text('{"name": "x"}\n' * 50)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add lock")

    service = IngestService(db_session)
    result = await service.index(repo, url=f"file://{repo}", name="lock_test")

    assert result.commits_inserted == 1
    assert result.chunks_inserted == 0


async def test_index_skips_binary_files(db_session: AsyncSession, tmp_path: Path) -> None:
    """A commit that adds a PNG must produce 0 chunks."""
    repo = _init_repo(tmp_path, "binary_repo")
    (repo / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add image")

    service = IngestService(db_session)
    result = await service.index(repo, url=f"file://{repo}", name="binary_test")

    assert result.commits_inserted == 1
    assert result.chunks_inserted == 0


async def test_index_skips_node_modules(db_session: AsyncSession, tmp_path: Path) -> None:
    """Files inside frontend/node_modules/ must not produce chunks."""
    repo = _init_repo(tmp_path, "nm_repo")
    nm_dir = repo / "frontend" / "node_modules" / "lodash"
    nm_dir.mkdir(parents=True)
    (nm_dir / "index.js").write_text("module.exports = {};\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add vendored dep")

    service = IngestService(db_session)
    result = await service.index(repo, url=f"file://{repo}", name="nm_test")

    assert result.commits_inserted == 1
    assert result.chunks_inserted == 0


async def test_index_chunks_large_diff(db_session: AsyncSession, tmp_path: Path) -> None:
    """A commit with a large file (well above SMALL_CHUNK_LIMIT in tokens)
    must produce >= 2 chunks. Token budget cap is enforced by the chunker."""
    repo = _init_repo(tmp_path, "large_repo")
    # ~3000 tokens of distinct content guarantees splitting.
    big_content = "\n".join(f"line of meaningful text number {i}" for i in range(1000))
    (repo / "big.txt").write_text(big_content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add big file")

    service = IngestService(db_session)
    result = await service.index(repo, url=f"file://{repo}", name="large_test")

    assert result.commits_inserted == 1
    assert result.chunks_inserted >= 2

    chunks = (await db_session.execute(select(CommitChunk))).scalars().all()
    # Every chunk must respect the budget plus overlap slack.
    assert all(c.tokens_used <= 2400 for c in chunks)


async def test_index_is_idempotent_for_chunks(db_session: AsyncSession, tmp_git_repo: Path) -> None:
    """Re-running index() must NOT duplicate chunks."""
    service = IngestService(db_session)
    url = f"file://{tmp_git_repo}"

    first = await service.index(tmp_git_repo, url=url, name="fixture")
    assert first.chunks_inserted == 5

    second = await service.index(tmp_git_repo, url=url, name="fixture")
    # Second run sees the same 5 commits but skips chunking (already done).
    assert second.commits_inserted == 0
    assert second.chunks_inserted == 0

    # Total still 5 chunks in the DB.
    chunks = (await db_session.execute(select(CommitChunk))).scalars().all()
    assert len(chunks) == 5


async def test_skipped_merges_reported(db_session: AsyncSession, tmp_path: Path) -> None:
    """A repo with one merge commit reports skipped_merges == 1 and the
    merge contributes zero chunks."""
    repo = _init_repo(tmp_path, "merge_chunk_repo")

    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "A")

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "B")

    _git(repo, "checkout", "-q", "main")
    (repo / "c.txt").write_text("c\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "C")

    _git(repo, "merge", "--no-ff", "-q", "-m", "MERGE", "feature")

    service = IngestService(db_session)
    result = await service.index(repo, url=f"file://{repo}", name="merge_chunk")

    # 3 commits inserted (A, B, C) + 1 merge skipped.
    assert result.commits_inserted == 3
    assert result.skipped_merges == 1
    # Each non-merge commit added one file → 3 chunks total.
    assert result.chunks_inserted == 3

    # No commit row exists for the merge.
    msgs = {row[0] for row in (await db_session.execute(select(Commit.message))).all()}
    assert "MERGE" not in msgs
