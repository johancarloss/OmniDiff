import logging
from pathlib import Path
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import IngestError
from app.models.repository import IndexingStatus
from app.repositories.chunk_repo import ChunkRepo
from app.repositories.commit_repo import CommitRepo
from app.repositories.repository_repo import RepositoryRepo
from app.schemas.ingest import Chunk, IndexResult
from app.services._git_subprocess import (
    GitSubprocessError,
    extract_file_diffs,
    get_commit_stats,
    walk_commits,
)
from app.services.ingest_chunker import chunk_file_diff
from app.services.ingest_filters import should_skip_file

logger = logging.getLogger(__name__)


class IngestService:
    """Orchestrates ingestion of a single Git repository.

    Slice 1 scope: walk + persist commit metadata.
    Slice 2 scope (this file): chunking + filters + persist `commit_chunks`.
    Incremental, CLI, and HTTP entrypoint still live in slices 3-4.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo_repo = RepositoryRepo(session)
        self._commit_repo = CommitRepo(session)
        self._chunk_repo = ChunkRepo(session)

    async def index(
        self,
        repo_path: Path,
        *,
        url: str,
        name: str,
        branch: str | None = None,
    ) -> IndexResult:
        """Index a Git repository at the given local path.

        Args:
            repo_path: filesystem path of a cloned repo.
            url: canonical URL recorded in the `repositories` row (used
                also as the advisory lock key).
            name: human-readable name for the row.
            branch: optional ref to walk (e.g. "main"). When None, walks
                whatever HEAD points to in the working tree.

        Steps:
            1. Get-or-create the Repository row (by URL).
            2. Acquire a Postgres advisory lock on the repo (concurrency).
            3. Mark status = INDEXING.
            4. Walk commits via subprocess (OUTSIDE transaction).
            5. Enrich each meta with stats (`git show --shortstat`).
            6. Bulk-upsert commits (idempotent via UNIQUE constraint).
            7. For each commit that has no chunks yet: extract diffs,
               filter, chunk, persist via ChunkRepo.bulk_insert.
            8. Update counts + last_indexed_hash + status = COMPLETED.

        Raises:
            IngestError(status_code=409): another index is already running
                for this repository (advisory lock not obtainable).
            IngestError(status_code=500): git subprocess failure or other
                ingestion error. Repository row is marked FAILED.
        """
        start = perf_counter()
        repo = await self._repo_repo.get_or_create(url=url, name=name)

        if not await self._repo_repo.acquire_advisory_lock(repo):
            raise IngestError(
                f"indexing already in progress for {url}",
                status_code=409,
            )

        await self._repo_repo.mark_status(repo, IndexingStatus.INDEXING)

        try:
            # Walking + stats happen OUTSIDE any DB transaction we care
            # about — subprocess can take minutes on large repos and we
            # don't want to hold the connection pool hostage.
            #
            # Incremental indexing: if this repo was indexed before, its
            # `last_indexed_hash` is the resume point. We pass it to the
            # walker as `since=...` so git only emits commits after it.
            #
            # Force-push handling: if `last_indexed_hash` no longer exists
            # in the repo (rewritten history), the walker raises
            # GitSubprocessError. Fall back to a full walk + log a warning
            # rather than failing the whole indexing job.
            since_hash = repo.last_indexed_hash
            was_incremental = since_hash is not None
            try:
                walk_result = walk_commits(repo_path, since=since_hash, branch=branch)
            except GitSubprocessError as exc:
                if since_hash is not None:
                    logger.warning(
                        "incremental walk failed (force-push or orphaned hash?); "
                        "falling back to full index for repo=%s: %s",
                        url,
                        exc,
                    )
                    was_incremental = False
                    since_hash = None
                    try:
                        walk_result = walk_commits(repo_path, branch=branch)
                    except GitSubprocessError as inner:
                        raise IngestError(
                            f"failed to walk repo: {inner}", status_code=500
                        ) from inner
                else:
                    raise IngestError(f"failed to walk repo: {exc}", status_code=500) from exc

            metas = walk_result.metas

            # Enrich with shortstat. One subprocess per commit — slow,
            # but Slice 1 is the BASELINE for the Rust port. Optimizing
            # this in Python defeats the purpose of the comparison.
            for meta in metas:
                files, ins, dels = get_commit_stats(repo_path, meta.hash)
                meta.files_changed = files
                meta.insertions = ins
                meta.deletions = dels

            # Bulk upsert with ON CONFLICT — second run inserts 0.
            commits_inserted = await self._commit_repo.bulk_upsert_by_hash(repo.id, metas)

            # Map hash → commit_id for the chunking pass below. Single
            # SELECT regardless of how many commits were just upserted.
            hash_to_id = await self._commit_repo.get_ids_by_hashes(repo.id, [m.hash for m in metas])

            # Chunking pass: skip commits that already have chunks (from a
            # previous run) — chunks are a deterministic function of the
            # diff + chunking rules, so re-doing the work would just
            # repeat I/O. To force re-chunking, call
            # `chunk_repo.delete_by_commit(commit_id)` first.
            chunks_inserted = 0
            for meta in metas:
                commit_id = hash_to_id.get(meta.hash)
                if commit_id is None:
                    # Defensive — shouldn't happen because bulk_upsert
                    # already ran, but skip cleanly if it does.
                    continue
                if await self._chunk_repo.count_by_commit(commit_id) > 0:
                    continue

                chunks_inserted += await self._chunk_commit(repo_path, meta.hash, commit_id)

            total = await self._commit_repo.count_by_repo(repo.id)
            await self._repo_repo.update_counts(repo, total=total, indexed=total)
            if metas:
                # `walk_commits` returns chronological order — last is newest.
                await self._repo_repo.set_last_indexed_hash(repo, metas[-1].hash)
            await self._repo_repo.mark_status(repo, IndexingStatus.COMPLETED)

            duration = perf_counter() - start
            logger.info(
                "indexed repo=%s seen=%d inserted=%d chunks=%d merges=%d "
                "incremental=%s duration=%.2fs",
                url,
                len(metas),
                commits_inserted,
                chunks_inserted,
                walk_result.skipped_merges,
                was_incremental,
                duration,
            )
            return IndexResult(
                repository_id=repo.id,
                total_commits_seen=len(metas),
                commits_inserted=commits_inserted,
                chunks_inserted=chunks_inserted,
                skipped_merges=walk_result.skipped_merges,
                duration_seconds=duration,
                was_incremental=was_incremental,
                since_hash=since_hash,
            )
        except Exception as exc:
            await self._repo_repo.mark_status(repo, IndexingStatus.FAILED, error=str(exc))
            raise

    async def _chunk_commit(self, repo_path: Path, commit_hash: str, commit_id: int) -> int:
        """Extract → filter → chunk → persist for one commit. Returns
        the number of chunks inserted."""
        try:
            file_diffs = extract_file_diffs(repo_path, commit_hash)
        except GitSubprocessError as exc:
            # Commit-level failure is non-fatal: log + skip, keep going.
            logger.warning("failed to extract diffs for commit=%s: %s", commit_hash, exc)
            return 0

        chunks: list[Chunk] = []
        for fd in file_diffs:
            if should_skip_file(fd.file_path, is_binary_in_git=fd.is_binary):
                continue
            chunks.extend(chunk_file_diff(fd))

        if not chunks:
            return 0

        return await self._chunk_repo.bulk_insert(commit_id, chunks)
