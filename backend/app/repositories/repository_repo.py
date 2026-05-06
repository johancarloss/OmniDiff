from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import IndexingStatus, Repository
from app.repositories.base import BaseRepository


class RepositoryRepo(BaseRepository[Repository]):
    """Data access for the `repositories` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Repository, session)

    async def get_by_url(self, url: str) -> Repository | None:
        stmt = select(Repository).where(Repository.url == url)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, url: str, name: str) -> Repository:
        existing = await self.get_by_url(url)
        if existing is not None:
            return existing
        repo = Repository(url=url, name=name)
        self._session.add(repo)
        await self._session.flush()
        return repo

    async def mark_status(
        self,
        repo: Repository,
        status: IndexingStatus,
        *,
        error: str | None = None,
    ) -> None:
        repo.status = status
        if error is not None:
            # Truncate to fit error_message column (VARCHAR(1000)).
            repo.error_message = error[:1000]
        elif status != IndexingStatus.FAILED:
            repo.error_message = None
        await self._session.flush()

    async def update_counts(
        self,
        repo: Repository,
        *,
        total: int,
        indexed: int,
    ) -> None:
        repo.total_commits = total
        repo.indexed_commits = indexed
        await self._session.flush()

    async def set_last_indexed_hash(self, repo: Repository, commit_hash: str) -> None:
        repo.last_indexed_hash = commit_hash
        await self._session.flush()

    async def acquire_advisory_lock(self, repo: Repository) -> bool:
        """Try to acquire a session-scoped Postgres advisory lock for this repo.

        Returns True if the lock was obtained, False if another session
        already holds it. The lock is released automatically when the
        session ends — no manual release needed.

        Lock key derives from `hashtext(url)` for stable hashing across
        sessions and processes.
        """
        stmt = text("SELECT pg_try_advisory_lock(hashtext(:url))")
        result = await self._session.execute(stmt, {"url": repo.url})
        acquired = bool(result.scalar_one())
        return acquired
