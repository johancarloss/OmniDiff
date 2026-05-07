"""HTTP endpoints for repository indexing.

    POST /api/index               schedule a new indexing job
    GET  /api/index/{job_id}      poll job status

The POST handler is intentionally short: it validates input, ensures
a `Repository` row exists (so it can return a stable `job_id`), and
schedules the heavy work as a `BackgroundTask`. The response is 202
Accepted — actual indexing happens asynchronously in the same Uvicorn
process.

Trade-off note: `BackgroundTasks` blocks one Uvicorn worker for the
duration of the index. Adequate for demo and low-volume self-hosted
use; for production fan-out, swap to a worker queue (Arq/Celery) —
the swap is localized to this file (`run_index_job` is queue-agnostic).
See deferred-work entry [DW-002].
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.models.repository import IndexingStatus, Repository
from app.repositories.repository_repo import RepositoryRepo
from app.schemas.indexing import (
    IndexAcceptedResponse,
    IndexRequest,
    JobStatusResponse,
)
from app.services.clone import derive_repo_name
from app.services.indexing_runner import run_index_job

router = APIRouter(prefix="/api", tags=["indexing"])


@router.post(
    "/index",
    response_model=IndexAcceptedResponse,
    status_code=202,
)
async def schedule_index(
    body: IndexRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> IndexAcceptedResponse:
    """Schedule indexing of a Git repository. Returns 202 + job_id.

    Returns 409 only when an indexing run is already in flight for the
    same URL. Re-indexing a COMPLETED or FAILED repo is allowed (and
    incremental — Slice 3 logic kicks in via `last_indexed_hash`).
    """
    repo_repo = RepositoryRepo(session)
    existing = await repo_repo.get_by_url(body.repo_url)
    if existing is not None and existing.status == IndexingStatus.INDEXING:
        raise HTTPException(
            status_code=409,
            detail=f"indexing already in progress for {body.repo_url}",
        )

    # Pre-create the row so we can return a stable job_id immediately.
    # `get_or_create` handles both "first POST" and "POST after a prior
    # COMPLETED/FAILED run" — the row is reused, only its status will
    # transition once the background task picks up.
    derived_name = derive_repo_name(body.repo_url) or "unknown"
    repo = await repo_repo.get_or_create(url=body.repo_url, name=derived_name)
    # Ensure the get_or_create commit lands before the background task
    # tries to look up the row. Without this flush+commit, the new row
    # is only visible inside the request transaction.
    await session.commit()

    background_tasks.add_task(
        run_index_job,
        body.repo_url,
        Path(settings.repos_dir),
        branch=body.branch,
    )

    return IndexAcceptedResponse(
        job_id=repo.id,
        repo_url=body.repo_url,
        status=repo.status.value,
    )


@router.get(
    "/index/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> JobStatusResponse:
    """Return current state of a previously-scheduled indexing job.

    The `Repository` row IS the job record (Slice 4 DT-1: no separate
    `index_runs` table). Look up by `job_id` (= `repository.id`).
    """
    repo = await session.get(Repository, job_id)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")

    return JobStatusResponse(
        job_id=repo.id,
        repo_url=repo.url,
        status=repo.status.value,
        total_commits=repo.total_commits,
        indexed_commits=repo.indexed_commits,
        last_indexed_hash=repo.last_indexed_hash,
        error_message=repo.error_message,
    )
