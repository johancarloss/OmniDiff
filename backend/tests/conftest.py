import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.main import app
from app.models import Base


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Real Postgres engine, function-scoped.

    Requires `docker compose up -d db` running.

    Function-scoped (not session-scoped) because pytest-asyncio creates a
    fresh event loop per test — a session-scoped async engine would
    bind to the first test's loop and explode on subsequent tests with
    "got Future attached to a different loop". Cost is ~50ms per test,
    acceptable for the integration suite.

    Schema is built via `Base.metadata.create_all` rather than Alembic
    migrations to keep test setup independent of migration history.
    Each test session starts with a clean schema, then rolls back via
    the per-test transaction in `db_session`.
    """
    from sqlalchemy import text

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Drop+recreate ensures a clean schema each test, since we don't
        # have a global teardown.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(
    db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session that commits inline.

    Since `db_engine` already drops+recreates the schema for each test,
    we don't need transaction rollback isolation here — each test starts
    with empty tables.
    """
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.commit()


def _git(repo: Path, *args: str) -> None:
    """Run git in `repo` with isolation flags so tests don't depend on
    the runner's global git config (CI, dev machines, etc).
    """
    env = {
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        # Disable signing — runners might not have a key configured.
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with 5 linear commits.

    Each test gets its own repo; tmp_path is auto-cleaned by pytest.
    """
    repo = tmp_path / "fixture_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "--local", "commit.gpgsign", "false")

    for i in range(5):
        (repo / f"file_{i}.txt").write_text(f"content {i}\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"commit {i}")

    return repo
