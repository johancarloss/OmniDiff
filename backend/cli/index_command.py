"""Implementation of `python -m omnidiff index <arg>`.

This module is the thin glue between argparse output, the clone helper,
and `IngestService.index`. It encodes the slice's exit-code contract:

    0  success
    1  usage error (invalid arg, path doesn't exist, etc.)
    2  git error (clone or fetch failed)
    3  lock contention (another indexer is already running)
    4  unexpected error (DB down, etc.)

These are stable across releases — the Phase 6 CI auto-indexer relies
on the difference between "retry later" (3) and "abort" (1, 2, 4).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.exceptions import IngestError
from app.services.clone import InvalidRepoSourceError, ensure_local_clone
from app.services.ingest import IngestService
from app.services.task_session import task_session

logger = logging.getLogger(__name__)


# Exit codes — stable contract for callers.
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_GIT = 2
EXIT_LOCKED = 3
EXIT_UNEXPECTED = 4


async def run_index(arg: str, repos_dir: Path, *, branch: str | None = None) -> int:
    """Run the `index` subcommand. Returns the process exit code.

    Args:
        arg: URL of the repo OR path to an existing local clone.
        repos_dir: where to clone remote repos when `arg` is a URL.
        branch: optional ref to index. None = whatever HEAD points to
            in the working tree (current `git log` default).
    """
    # Step 1: resolve arg → local clone (or raise InvalidRepoSourceError on bad input).
    try:
        local_path, url, name = ensure_local_clone(arg, repos_dir)
    except InvalidRepoSourceError as exc:
        logger.error("invalid argument: %s", exc)
        return EXIT_USAGE
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        logger.error(
            "git clone/fetch failed (exit %d): %s",
            exc.returncode,
            stderr.strip(),
        )
        return EXIT_GIT
    except subprocess.TimeoutExpired:
        logger.error("git clone/fetch timed out")
        return EXIT_GIT

    # Step 2: ingest. Service handles its own concurrency lock; we just
    # translate exceptions to exit codes.
    try:
        async with task_session() as session:
            service = IngestService(session)
            result = await service.index(local_path, url=url, name=name, branch=branch)
    except IngestError as exc:
        if exc.status_code == 409:
            logger.error("indexing already in progress for %s", url)
            return EXIT_LOCKED
        logger.error("ingestion failed: %s", exc.message)
        return EXIT_UNEXPECTED
    except Exception:
        logger.exception("unexpected error during indexing")
        return EXIT_UNEXPECTED

    logger.info(
        "done: repo=%s branch=%s seen=%d inserted=%d chunks=%d merges=%d "
        "incremental=%s duration=%.1fs",
        url,
        branch or "HEAD",
        result.total_commits_seen,
        result.commits_inserted,
        result.chunks_inserted,
        result.skipped_merges,
        result.was_incremental,
        result.duration_seconds,
    )
    return EXIT_OK
