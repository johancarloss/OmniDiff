"""Selects which implementation reads commit data out of git.

Two paths exist on purpose:

* `_git_subprocess` shells out to `git`. It is the reference the Rust
  layer is checked against, and the fallback wherever the compiled
  extension is unavailable.
* `omnidiff_core` does the same work in-process through libgit2. Phase
  2-C measured it about 4x faster across the git layer, most of which
  comes from batching: one repository open and one boundary crossing per
  window instead of per commit.

Both paths raise `GitSubprocessError` and degrade the same way, so
callers do not need to know which one answered.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.config import get_settings
from app.schemas.ingest import FileDiff
from app.services._git_subprocess import (
    GitSubprocessError,
    extract_file_diffs,
    get_commit_stats,
)

logger = logging.getLogger(__name__)

BackendName = Literal["rust", "python"]


@lru_cache(maxsize=1)
def active_backend() -> BackendName:
    """Resolve the backend once per process.

    `auto` prefers Rust and falls back silently; `rust` fails loudly, so
    a misconfigured deployment does not quietly run at a third of the
    speed it was provisioned for.
    """
    configured = get_settings().git_backend
    if configured == "python":
        return "python"

    try:
        import omnidiff_core  # noqa: F401
    except ImportError:
        if configured == "rust":
            raise
        logger.info("omnidiff_core unavailable; using the git subprocess backend")
        return "python"

    return "rust"


def commit_stats_batch(repo_path: Path, commit_hashes: list[str]) -> list[tuple[int, int, int]]:
    """`(files_changed, insertions, deletions)` for each hash, in order."""
    if not commit_hashes:
        return []

    if active_backend() == "rust":
        import omnidiff_core

        try:
            stats = omnidiff_core.commit_stats_batch(str(repo_path), commit_hashes)
        except Exception as exc:
            # The Python path treats stats as best-effort enrichment and
            # returns zeros for a commit git cannot describe. Retrying the
            # window one commit at a time restores that behaviour instead
            # of failing the whole index over a single bad commit.
            logger.warning("rust commit_stats_batch failed, retrying per commit: %s", exc)
        else:
            return stats

    return [get_commit_stats(repo_path, h) for h in commit_hashes]


def extract_file_diffs_batch(repo_path: Path, commit_hashes: list[str]) -> list[list[FileDiff]]:
    """Per-file diffs for each hash, in order.

    A commit whose diffs cannot be read yields an empty list, matching
    the subprocess path's "log and skip" behaviour.
    """
    if not commit_hashes:
        return []

    if active_backend() == "rust":
        import omnidiff_core

        try:
            batches = omnidiff_core.extract_file_diffs_batch(str(repo_path), commit_hashes)
        except Exception as exc:
            logger.warning("rust extract_file_diffs_batch failed, retrying per commit: %s", exc)
        else:
            return [[FileDiff(**entry) for entry in commit] for commit in batches]

    return [_extract_one(repo_path, h) for h in commit_hashes]


def _extract_one(repo_path: Path, commit_hash: str) -> list[FileDiff]:
    try:
        return extract_file_diffs(repo_path, commit_hash)
    except GitSubprocessError as exc:
        logger.warning("failed to extract diffs for commit=%s: %s", commit_hash, exc)
        return []
