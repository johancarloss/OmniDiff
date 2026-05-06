from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commit import ChunkType, CommitChunk
from app.repositories.base import BaseRepository
from app.schemas.ingest import Chunk

# Same batch size rationale as CommitRepo: ~10 cols × 500 rows = 5K binds,
# safely under Postgres' ~32K bind parameter cap.
DEFAULT_BATCH_SIZE = 500


class ChunkRepo(BaseRepository[CommitChunk]):
    """Data access for the `commit_chunks` table.

    Chunks are *derived* artifacts (a function of the commit's diff and
    the chunking rules). Re-running with different rules SHOULD produce
    different chunks — so this repository deliberately does NOT do
    `ON CONFLICT` upsert. Use `delete_by_commit` followed by
    `bulk_insert` for re-chunking.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CommitChunk, session)

    async def bulk_insert(
        self,
        commit_id: int,
        chunks: list[Chunk],
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """Insert chunks for one commit. Returns the number of inserted rows.

        Uses single-statement multi-row INSERT VALUES, which guarantees
        sequential IDs in declaration order (DB-005 in the KB).
        """
        if not chunks:
            return 0

        total_inserted = 0
        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start : batch_start + batch_size]
            rows = [
                {
                    "commit_id": commit_id,
                    "chunk_type": ChunkType(c.chunk_type),
                    "file_path": c.file_path,
                    "old_path": c.old_path,
                    "change_type": c.change_type,
                    "diff": c.diff_content,
                    "tokens_used": c.tokens_used,
                }
                for c in batch
            ]
            self._session.add_all([CommitChunk(**row) for row in rows])
            total_inserted += len(rows)

        await self._session.flush()
        return total_inserted

    async def delete_by_commit(self, commit_id: int) -> int:
        """Remove all chunks for one commit. Used before re-chunking."""
        stmt = delete(CommitChunk).where(CommitChunk.commit_id == commit_id)
        # AsyncSession.execute returns a generic Result[T] in the type stubs,
        # but for a DELETE statement the runtime object is always a
        # CursorResult that exposes rowcount. Cast to make mypy --strict happy.
        result = cast("CursorResult[tuple[int, ...]]", await self._session.execute(stmt))
        await self._session.flush()
        return result.rowcount or 0

    async def count_by_commit(self, commit_id: int) -> int:
        """Number of chunks already stored for a commit. Used by
        IngestService as an idempotency guard (skip chunking if > 0)."""
        stmt = (
            select(func.count()).select_from(CommitChunk).where(CommitChunk.commit_id == commit_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())
