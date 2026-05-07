"""Integration tests for the indexing HTTP endpoint.

These exercise `POST /api/v1/index` and `GET /api/v1/index/{job_id}` end-to-end
against a real Postgres (docker compose up -d db) and a temporary git
fixture repo (5 linear commits, 1 file each).

Note about background tasks: with `httpx.AsyncClient` + `ASGITransport`,
the response is held until the BackgroundTask completes. This is opposite
to production behavior (where 202 returns instantly and the task runs
after) but it makes the tests deterministic — by the time `client.post`
returns, the indexing has already finished. See Slice 4 plan, G-5.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import database
from app.config import get_settings
from app.middleware.request_id import REQUEST_ID_HEADER
from app.models.commit import Commit
from app.models.repository import IndexingStatus, Repository

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def reset_app_engine() -> Iterator[None]:
    """Dispose `app.database._engine` between tests.

    `database.py` caches the engine module-globally so the FastAPI app
    doesn't pay setup cost on every request. In production that's
    correct. In tests, the `db_engine` fixture drops+recreates the
    schema each function — but the global pool still holds connections
    bound to the old schema, leading to `cannot perform operation:
    another operation is in progress` from asyncpg on the next query.

    This fixture forces a fresh engine per test so the pool starts
    empty and connections only see the freshly-created schema.
    """
    if database._engine is not None:  # noqa: SLF001
        await database._engine.dispose()  # noqa: SLF001
    database._engine = None  # noqa: SLF001
    database._async_session = None  # noqa: SLF001
    yield
    if database._engine is not None:  # noqa: SLF001
        await database._engine.dispose()  # noqa: SLF001
    database._engine = None  # noqa: SLF001
    database._async_session = None  # noqa: SLF001


@pytest.fixture
def isolated_repos_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Override `settings.repos_dir` so the endpoint clones into tmp.

    Without this, real `POST /api/v1/index` calls in tests would dirty the
    project's `./repos/` directory with leftover fixture clones.
    """
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    # Clear the lru_cached settings so the new env var takes effect on
    # the next `get_settings()` call.
    get_settings.cache_clear()
    monkeypatch.setenv("REPOS_DIR", str(repos_dir))
    yield repos_dir
    get_settings.cache_clear()


async def test_post_index_returns_202_and_job_id(
    db_engine: AsyncEngine,
    client: AsyncClient,
    tmp_git_repo: Path,
    isolated_repos_dir: Path,
) -> None:
    """Smoke: POST returns 202 with a stable job_id and the right status."""
    response = await client.post(
        "/api/v1/index",
        json={"repo_url": f"file://{tmp_git_repo}"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["job_id"] > 0
    assert body["repo_url"] == f"file://{tmp_git_repo}"
    assert body["status"] in {"pending", "indexing", "completed"}
    assert body["message"] == "Indexing scheduled"


async def test_post_then_poll_returns_completed_with_full_state(
    db_engine: AsyncEngine,
    client: AsyncClient,
    tmp_git_repo: Path,
    isolated_repos_dir: Path,
) -> None:
    """End-to-end: schedule a job, then GET shows COMPLETED with the
    right counts. With ASGITransport the BackgroundTask completes before
    the POST response returns, so a single GET is enough to observe the
    final state."""
    post_resp = await client.post(
        "/api/v1/index",
        json={"repo_url": f"file://{tmp_git_repo}"},
    )
    assert post_resp.status_code == 202
    job_id = post_resp.json()["job_id"]

    get_resp = await client.get(f"/api/v1/index/{job_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()

    assert body["job_id"] == job_id
    assert body["status"] == "completed"
    assert body["total_commits"] == 5
    assert body["indexed_commits"] == 5
    assert body["last_indexed_hash"] is not None
    assert len(body["last_indexed_hash"]) == 40
    assert body["error_message"] is None


async def test_get_job_status_returns_404_for_unknown_id(
    db_engine: AsyncEngine,
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/index/999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


async def test_post_returns_409_when_job_already_indexing(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    client: AsyncClient,
    tmp_git_repo: Path,
    isolated_repos_dir: Path,
) -> None:
    """Pre-seed a Repository row in INDEXING state and verify POST
    rejects a second concurrent run for the same URL."""
    repo_url = f"file://{tmp_git_repo}"
    repo = Repository(
        url=repo_url,
        name="held",
        status=IndexingStatus.INDEXING,
    )
    db_session.add(repo)
    await db_session.commit()

    response = await client.post("/api/v1/index", json={"repo_url": repo_url})

    assert response.status_code == 409
    assert "already in progress" in response.json()["detail"]


async def test_post_validates_empty_repo_url(
    db_engine: AsyncEngine,
    client: AsyncClient,
) -> None:
    """Pydantic enforces min_length=1 — empty string returns 422."""
    response = await client.post("/api/v1/index", json={"repo_url": ""})
    assert response.status_code == 422


async def test_post_rejects_branch_over_max_length(
    db_engine: AsyncEngine,
    client: AsyncClient,
    tmp_git_repo: Path,
    isolated_repos_dir: Path,
) -> None:
    response = await client.post(
        "/api/v1/index",
        json={
            "repo_url": f"file://{tmp_git_repo}",
            "branch": "x" * 250,
        },
    )
    assert response.status_code == 422


async def test_x_request_id_propagates_in_response(
    db_engine: AsyncEngine,
    client: AsyncClient,
    tmp_git_repo: Path,
    isolated_repos_dir: Path,
) -> None:
    """A client-supplied X-Request-ID must round-trip in the response,
    proving the middleware ran on a real API endpoint (not just the
    standalone Starlette app used in test_request_id_middleware.py)."""
    response = await client.post(
        "/api/v1/index",
        json={"repo_url": f"file://{tmp_git_repo}"},
        headers={REQUEST_ID_HEADER: "test-trace-9876"},
    )
    assert response.status_code == 202
    assert response.headers[REQUEST_ID_HEADER] == "test-trace-9876"


async def test_reindex_after_completed_is_incremental(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    client: AsyncClient,
    tmp_git_repo: Path,
    isolated_repos_dir: Path,
) -> None:
    """POST after a previous COMPLETED run must reuse the same job_id
    (same Repository row) and re-run cleanly — incremental indexing
    finds no new commits, so nothing duplicates in the DB."""
    repo_url = f"file://{tmp_git_repo}"

    first = await client.post("/api/v1/index", json={"repo_url": repo_url})
    assert first.status_code == 202
    first_id = first.json()["job_id"]

    second = await client.post("/api/v1/index", json={"repo_url": repo_url})
    assert second.status_code == 202
    assert second.json()["job_id"] == first_id, "same repo URL must reuse job_id"

    # DB still has exactly 5 commit rows — no duplicates.
    rows = (await db_session.execute(select(Commit))).scalars().all()
    assert len(list(rows)) == 5
