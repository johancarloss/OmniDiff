"""Integration tests for IngestService.index() against a real Postgres.

These tests need `docker compose up -d db` (or equivalent) running.
They're tagged with the `integration` marker so they can be skipped on
machines without Postgres via `pytest -m "not integration"`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import IngestError
from app.models.commit import Commit
from app.models.repository import IndexingStatus, Repository
from app.services.ingest import IngestService

pytestmark = pytest.mark.integration


async def test_index_local_repo_inserts_all_commits(
    db_session: AsyncSession, tmp_git_repo: Path
) -> None:
    service = IngestService(db_session)
    result = await service.index(
        tmp_git_repo,
        url=f"file://{tmp_git_repo}",
        name="fixture",
    )

    assert result.commits_inserted == 5
    assert result.total_commits_seen == 5

    rows = await db_session.execute(select(Commit))
    assert len(list(rows.scalars())) == 5


async def test_index_is_idempotent(db_session: AsyncSession, tmp_git_repo: Path) -> None:
    """Re-running index() on the same repo inserts 0 new rows."""
    service = IngestService(db_session)
    url = f"file://{tmp_git_repo}"

    first = await service.index(tmp_git_repo, url=url, name="fixture")
    assert first.commits_inserted == 5

    second = await service.index(tmp_git_repo, url=url, name="fixture")
    assert second.total_commits_seen == 5
    assert second.commits_inserted == 0

    # DB still has exactly 5 commits.
    rows = await db_session.execute(select(Commit))
    assert len(list(rows.scalars())) == 5


async def test_index_marks_status_completed(db_session: AsyncSession, tmp_git_repo: Path) -> None:
    service = IngestService(db_session)
    url = f"file://{tmp_git_repo}"
    result = await service.index(tmp_git_repo, url=url, name="fixture")

    repo = await db_session.get(Repository, result.repository_id)
    assert repo is not None
    assert repo.status == IndexingStatus.COMPLETED
    assert repo.error_message is None
    assert repo.total_commits == 5
    assert repo.indexed_commits == 5
    assert repo.last_indexed_hash is not None


async def test_index_skips_merge_commits(db_session: AsyncSession, tmp_path: Path) -> None:
    """Repo with a merge commit: commits table should NOT contain it."""
    repo = tmp_path / "merge_repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "t@e.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "t@e.com",
        "GIT_CONFIG_NOSYSTEM": "1",
    }

    def _g(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            env=env,
        )

    _g("init", "-q", "--initial-branch=main")
    _g("config", "--local", "commit.gpgsign", "false")
    (repo / "a.txt").write_text("a")
    _g("add", ".")
    _g("commit", "-q", "-m", "A")

    _g("checkout", "-q", "-b", "feature")
    (repo / "b.txt").write_text("b")
    _g("add", ".")
    _g("commit", "-q", "-m", "B")

    _g("checkout", "-q", "main")
    (repo / "c.txt").write_text("c")
    _g("add", ".")
    _g("commit", "-q", "-m", "C")

    _g("merge", "--no-ff", "-q", "-m", "MERGE", "feature")

    service = IngestService(db_session)
    result = await service.index(repo, url=f"file://{repo}", name="merge_test")

    # Should be 3 (A, B, C) — merge skipped.
    assert result.commits_inserted == 3
    rows = await db_session.execute(select(Commit.message))
    messages = {r[0] for r in rows.all()}
    assert "MERGE" not in messages


async def test_concurrent_index_is_blocked_by_advisory_lock(
    db_session: AsyncSession, tmp_git_repo: Path
) -> None:
    """If the advisory lock is already held, index() raises 409."""
    url = f"file://{tmp_git_repo}"

    # Acquire the lock manually in this same session — second attempt
    # via IngestService will fail to acquire (Postgres advisory locks
    # are session-scoped; same session holds them re-entrantly... so
    # we test by acquiring on a SEPARATE connection).
    #
    # Instead of two connections, simulate by acquiring the same hash
    # under a different lock key would defeat the test. Use a distinct
    # connection via the engine to hold the lock.
    engine = db_session.bind
    assert engine is not None
    async with engine.connect() as other_conn:  # type: ignore[union-attr]
        await other_conn.execute(
            text("SELECT pg_advisory_lock(hashtext(:url))"),
            {"url": url},
        )

        service = IngestService(db_session)
        with pytest.raises(IngestError) as exc_info:
            await service.index(tmp_git_repo, url=url, name="fixture")
        assert exc_info.value.status_code == 409
        assert "already in progress" in exc_info.value.message

        await other_conn.execute(
            text("SELECT pg_advisory_unlock(hashtext(:url))"),
            {"url": url},
        )
