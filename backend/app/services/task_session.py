"""Async session lifecycle for short-lived processes.

Used by:
    - the CLI (`python -m cli index ...`), where the entire process
      lifetime is one `task_session()` block;
    - the HTTP endpoint's background task (`POST /api/v1/index`), where the
      task runs after the request handler has returned and the request's
      session is already closed.

Both contexts share the same need: open an engine, yield a session,
dispose the engine on exit. We don't reuse `app.database.get_session()`
because that one expects to live as long as the FastAPI app — the
engine is cached at module level. Here we want a fresh engine that
disposes when the work finishes, so leftover connections don't leak
into the pool.
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
async def task_session() -> AsyncIterator[AsyncSession]:
    """Yield an `AsyncSession` backed by a fresh engine.

    On normal exit, commits and disposes the engine. On exception,
    rolls back, then disposes — never leaks connections, since this
    engine doesn't outlive the `async with` block.
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
