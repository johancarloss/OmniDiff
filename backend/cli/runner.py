"""Async session lifecycle for the CLI.

The CLI is a short-lived process: open the engine on entry, dispose on
exit. This is different from the FastAPI app, where engine and session
factory live for the whole server's lifetime — that's why we don't
reuse `app.database.get_session()`.

Usage:
    async with cli_session() as session:
        service = IngestService(session)
        result = await service.index(...)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


@asynccontextmanager
async def cli_session() -> AsyncIterator[AsyncSession]:
    """Yield an `AsyncSession` backed by a fresh engine.

    On normal exit, commits and disposes the engine. On exception,
    rolls back, then disposes — never leaks connections back to the
    pool, since this engine doesn't go anywhere after the CLI exits.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await engine.dispose()
