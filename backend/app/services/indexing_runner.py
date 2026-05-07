"""Background-task entry point for the HTTP indexing endpoint.

Encapsulates "clone + index + status update" so the route handler
stays small and the background work is independently testable. Unlike
the CLI's `run_index` (which translates errors into exit codes), this
runner lives after the response has been sent — there's no caller to
hand exceptions back to. Errors are logged and the `Repository` row's
`status` column carries the failure mode forward to whoever polls
`GET /api/v1/index/{job_id}`.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.services.clone import InvalidRepoSourceError, ensure_local_clone
from app.services.ingest import IngestService
from app.services.task_session import task_session

logger = logging.getLogger(__name__)


async def run_index_job(
    repo_url: str,
    repos_dir: Path,
    *,
    branch: str | None = None,
) -> None:
    """Clone (or refresh) `repo_url` and run a full indexing pass.

    Owns its own session lifecycle via `task_session()` because the
    request that scheduled this task has already returned — the
    request-scoped session is gone. Errors are not re-raised; there is
    no caller to catch them. The `IngestService.index()` except branch
    already marks `Repository.status = FAILED` and stores
    `error_message`, which is the source of truth callers will read.
    """
    try:
        local_path, url, name = ensure_local_clone(repo_url, repos_dir)
    except InvalidRepoSourceError:
        logger.exception("invalid repo source for repo_url=%s", repo_url)
        return
    except subprocess.CalledProcessError:
        logger.exception("git clone/fetch failed for repo_url=%s", repo_url)
        return
    except subprocess.TimeoutExpired:
        logger.exception("git clone/fetch timed out for repo_url=%s", repo_url)
        return

    try:
        async with task_session() as session:
            service = IngestService(session)
            result = await service.index(local_path, url=url, name=name, branch=branch)
        logger.info(
            "background index complete: repo=%s commits_inserted=%d chunks_inserted=%d "
            "duration=%.2fs incremental=%s",
            url,
            result.commits_inserted,
            result.chunks_inserted,
            result.duration_seconds,
            result.was_incremental,
        )
    except Exception:
        logger.exception("background index failed for repo_url=%s", repo_url)
