from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commit import Commit
from app.repositories.base import BaseRepository
from app.schemas.ingest import CommitMeta

# Postgres caps bind parameters at ~32_767. With ~10 columns per commit,
# 500 rows × 10 binds = 5000 binds — comfortable headroom.
DEFAULT_BATCH_SIZE = 500


class CommitRepo(BaseRepository[Commit]):
    """Data access for the `commits` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Commit, session)

    async def bulk_upsert_by_hash(
        self,
        repository_id: int,
        metas: list[CommitMeta],
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """Insert commits in batches with ON CONFLICT (repository_id, hash) DO NOTHING.

        Idempotent: re-running with the same metas returns 0 newly inserted.

        Returns the number of NEWLY inserted rows. Existing rows (matched
        by the unique constraint) are silently skipped.
        """
        if not metas:
            return 0

        total_inserted = 0
        for batch_start in range(0, len(metas), batch_size):
            batch = metas[batch_start : batch_start + batch_size]
            rows = [
                {
                    "repository_id": repository_id,
                    "hash": m.hash,
                    "author_name": m.author_name,
                    "author_email": m.author_email,
                    "message": m.message,
                    "committed_at": m.committed_at,
                    "parents": m.parents,
                    "files_changed": m.files_changed,
                    "insertions": m.insertions,
                    "deletions": m.deletions,
                }
                for m in batch
            ]
            stmt = (
                pg_insert(Commit)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["repository_id", "hash"])
                .returning(Commit.id)
            )
            result = await self._session.execute(stmt)
            total_inserted += len(result.all())

        await self._session.flush()
        return total_inserted

    async def count_by_repo(self, repository_id: int) -> int:
        stmt = select(func.count()).select_from(Commit).where(Commit.repository_id == repository_id)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get_latest_hash(self, repository_id: int) -> str | None:
        """Return the hash of the most recent commit for this repo.

        Used by the incremental indexing path (Slice 3) to compute
        `git log <hash>..HEAD`.
        """
        stmt = (
            select(Commit.hash)
            .where(Commit.repository_id == repository_id)
            .order_by(Commit.committed_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_ids_by_hashes(self, repository_id: int, hashes: list[str]) -> dict[str, int]:
        """Return ``{hash: commit_id}`` for hashes that exist in this repo.

        Single SELECT regardless of how many hashes were given. Used by
        `IngestService` to map walker output → DB IDs after a bulk
        upsert that returned only counts. Will also be used by Slice 3
        for the incremental indexing path.
        """
        if not hashes:
            return {}
        stmt = select(Commit.hash, Commit.id).where(
            Commit.repository_id == repository_id,
            Commit.hash.in_(hashes),
        )
        result = await self._session.execute(stmt)
        return {row.hash: row.id for row in result.all()}
