import logging
from pathlib import Path
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import IngestError
from app.models.repository import IndexingStatus
from app.repositories.commit_repo import CommitRepo
from app.repositories.repository_repo import RepositoryRepo
from app.schemas.ingest import IndexResult
from app.services._git_subprocess import (
    GitSubprocessError,
    get_commit_stats,
    walk_commits,
)

logger = logging.getLogger(__name__)


class IngestService:
    """Orchestrates ingestion of a single Git repository.

    Slice 1 scope: walk + persist commit metadata. Chunking, filters,
    incremental, CLI, and HTTP entrypoint live in slices 2-4.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo_repo = RepositoryRepo(session)
        self._commit_repo = CommitRepo(session)

    async def index(
        self,
        repo_path: Path,
        *,
        url: str,
        name: str,
    ) -> IndexResult:
        """Index a Git repository at the given local path.

        Steps:
            1. Get-or-create the Repository row (by URL).
            2. Acquire a Postgres advisory lock on the repo (concurrency).
            3. Mark status = INDEXING.
            4. Walk commits via subprocess (OUTSIDE transaction).
            5. Enrich each meta with stats (`git show --shortstat`).
            6. Bulk-upsert commits (idempotent via UNIQUE constraint).
            7. Update counts + last_indexed_hash + status = COMPLETED.

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
            try:
                metas = walk_commits(repo_path)
            except GitSubprocessError as exc:
                raise IngestError(f"failed to walk repo: {exc}", status_code=500) from exc

            # Enrich with shortstat. One subprocess per commit — slow,
            # but Slice 1 is the BASELINE for the Rust port. Optimizing
            # this in Python defeats the purpose of the comparison.
            for meta in metas:
                files, ins, dels = get_commit_stats(repo_path, meta.hash)
                meta.files_changed = files
                meta.insertions = ins
                meta.deletions = dels

            # Bulk upsert with ON CONFLICT — second run inserts 0.
            inserted = await self._commit_repo.bulk_upsert_by_hash(repo.id, metas)
            total = await self._commit_repo.count_by_repo(repo.id)

            await self._repo_repo.update_counts(repo, total=total, indexed=total)
            if metas:
                # `walk_commits` returns chronological order — last is newest.
                await self._repo_repo.set_last_indexed_hash(repo, metas[-1].hash)
            await self._repo_repo.mark_status(repo, IndexingStatus.COMPLETED)

            duration = perf_counter() - start
            logger.info(
                "indexed repo=%s seen=%d inserted=%d duration=%.2fs",
                url,
                len(metas),
                inserted,
                duration,
            )
            return IndexResult(
                repository_id=repo.id,
                total_commits_seen=len(metas),
                commits_inserted=inserted,
                skipped_merges=0,  # tracked properly in Slice 2
                duration_seconds=duration,
            )
        except Exception as exc:
            await self._repo_repo.mark_status(repo, IndexingStatus.FAILED, error=str(exc))
            raise
