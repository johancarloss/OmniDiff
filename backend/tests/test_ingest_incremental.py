"""Integration tests for the incremental indexing path of IngestService.

These verify the Slice 3 contract:
  - First run is a full index (no resume point).
  - Second run with new commits picks up only those.
  - Force-push (orphaned `last_indexed_hash`) falls back to a full walk.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commit import Commit
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


def _commit_file(repo: Path, name: str, content: str, msg: str) -> None:
    (repo / name).write_text(content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", msg)


async def test_first_run_is_full_index(db_session: AsyncSession, tmp_git_repo: Path) -> None:
    """A repo that has never been indexed has no resume point."""
    service = IngestService(db_session)
    result = await service.index(tmp_git_repo, url=f"file://{tmp_git_repo}", name="fixture")

    assert result.was_incremental is False
    assert result.since_hash is None
    assert result.commits_inserted == 5


async def test_second_run_is_incremental_after_new_commits(
    db_session: AsyncSession, tmp_git_repo: Path
) -> None:
    """After a successful first run, adding commits and re-indexing
    must pick up ONLY the new ones via incremental walking."""
    service = IngestService(db_session)
    url = f"file://{tmp_git_repo}"

    first = await service.index(tmp_git_repo, url=url, name="fixture")
    assert first.commits_inserted == 5
    first_resume_point = (
        await db_session.execute(
            select(Commit.hash)
            .where(Commit.repository_id == first.repository_id)
            .order_by(Commit.committed_at.desc())
            .limit(1)
        )
    ).scalar_one()

    # Add 2 more commits to the repo.
    _commit_file(tmp_git_repo, "extra_a.txt", "extra a\n", "extra A")
    _commit_file(tmp_git_repo, "extra_b.txt", "extra b\n", "extra B")

    second = await service.index(tmp_git_repo, url=url, name="fixture")

    assert second.was_incremental is True
    assert second.since_hash == first_resume_point
    # Only the 2 new commits walked, both inserted.
    assert second.total_commits_seen == 2
    assert second.commits_inserted == 2

    # DB now has 7 commits total.
    rows = await db_session.execute(select(Commit))
    assert len(list(rows.scalars())) == 7


async def test_force_push_falls_back_to_full_index(
    db_session: AsyncSession, tmp_git_repo: Path
) -> None:
    """If the recorded `last_indexed_hash` no longer exists in the
    repository (e.g. force-push reshaping history), the next run must
    NOT crash. It should log a warning and fall back to a full walk."""
    service = IngestService(db_session)
    url = f"file://{tmp_git_repo}"

    # First run: anchors `last_indexed_hash` to some commit in the repo.
    first = await service.index(tmp_git_repo, url=url, name="fixture")
    assert first.commits_inserted == 5

    # Simulate force-push: move HEAD back, create a divergent commit,
    # then advance past it. The original `last_indexed_hash` no longer
    # appears in the new history, but git keeps the object reachable
    # via the reflog. To truly orphan it, we rewrite history and run
    # `git gc --prune=now` so the resume hash is gone from `git log`.
    _git(tmp_git_repo, "reset", "--hard", "HEAD~3")
    _commit_file(tmp_git_repo, "rewritten.txt", "rewritten\n", "rewritten history")

    # The recorded last_indexed_hash still exists as an object in the
    # repo, but it's no longer reachable from HEAD. `git log <hash>..HEAD`
    # will fail because <hash> is no longer in the ancestry chain — git
    # exits with code 128 ("fatal: bad revision").
    #
    # Note: running `gc --prune=now` is not strictly necessary for the
    # test to be valid; what we need is for `<hash>..HEAD` to fail, and
    # rewriting history above already accomplishes that for objects that
    # are not reachable from any current ref.
    _git(tmp_git_repo, "reflog", "expire", "--expire=now", "--all")
    _git(tmp_git_repo, "gc", "--prune=now", "--quiet")

    # Second run: walker raises GitSubprocessError on the orphaned
    # `since`; service catches and falls back to a full walk.
    second = await service.index(tmp_git_repo, url=url, name="fixture")

    # After the fallback, was_incremental must be False (the run resolved
    # by walking the full history).
    assert second.was_incremental is False
    assert second.since_hash is None
    # The new history has 3 commits (5 - 3 from reset + 1 new).
    assert second.total_commits_seen == 3
