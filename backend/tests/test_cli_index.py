"""Integration tests for `python -m cli index`.

These exercise the CLI in two modes:
  - In-process: calling `cli.__main__.main(argv)` directly. Fast,
    captures argparse failures cleanly. Used for cases that don't
    overlap with another async DB session.
  - Subprocess: spawning `uv run python -m cli ...`. Slower (~3s/test)
    but gives full event-loop isolation — needed for tests that hold
    a Postgres lock from another connection while invoking the CLI.

Postgres is required for both modes (the underlying IngestService
hits the DB).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from cli.__main__ import main
from cli.index_command import EXIT_LOCKED, EXIT_OK, EXIT_USAGE

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@e.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@e.com",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )


async def _count_commits() -> int:
    """Count rows in `commits` using a fresh engine bound to the current
    event loop. Avoids the cross-loop binding problem when fixtures and
    `main()` create separate loops."""
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM commits"))
            return int(result.scalar_one())
    finally:
        await engine.dispose()


def test_cli_index_local_path_returns_zero(db_engine: object, tmp_git_repo: Path) -> None:
    """Indexing a local repo via the CLI exits 0 and inserts commits.

    `db_engine` fixture is requested (not used directly) so the schema
    exists before main() runs. Counting is done via a fresh engine
    inside main()'s own loop's lifetime to avoid cross-loop binding.
    """
    import asyncio

    exit_code = main(["index", str(tmp_git_repo)])
    assert exit_code == EXIT_OK
    assert asyncio.run(_count_commits()) == 5


def test_cli_index_invalid_arg_returns_usage_error(db_engine: object, tmp_path: Path) -> None:
    """An argument that is neither a URL nor an existing path exits with
    EXIT_USAGE (1), not EXIT_OK and not EXIT_UNEXPECTED."""
    exit_code = main(
        [
            "index",
            "definitely-not-a-url-or-path",
            "--repos-dir",
            str(tmp_path / "repos"),
        ]
    )
    assert exit_code == EXIT_USAGE


def test_cli_help_does_not_crash(capsys: pytest.CaptureFixture[str]) -> None:
    """`--help` exits cleanly with code 0 and prints usage to stdout.

    argparse calls sys.exit(0) on --help; we capture that as SystemExit.
    """
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "Index a Git repository" in captured.out


def test_cli_no_subcommand_returns_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running with no subcommand fails fast (argparse exits with code
    2 for missing required args — distinct from our own EXIT_USAGE=1
    which signals a runtime usage problem)."""
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2


def test_cli_index_via_file_url_clones_into_repos_dir(db_engine: object, tmp_path: Path) -> None:
    """Passing a `file://` URL triggers the clone path: the helper
    clones into `repos/<derived_name>` and indexes from there."""
    origin = tmp_path / "origin_repo"
    origin.mkdir()
    _git(origin, "init", "-q", "--initial-branch=main")
    _git(origin, "config", "--local", "commit.gpgsign", "false")
    (origin / "file.txt").write_text("hello\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "first")

    repos_dir = tmp_path / "repos"
    url = f"file://{origin.resolve()}"

    exit_code = main(["index", url, "--repos-dir", str(repos_dir)])
    assert exit_code == EXIT_OK

    cloned = list(repos_dir.iterdir())
    assert len(cloned) == 1
    assert (cloned[0] / "file.txt").exists()


def test_cli_index_locked_returns_lock_error(db_engine: object, tmp_git_repo: Path) -> None:
    """When another session holds the advisory lock for the same repo,
    the CLI exits with EXIT_LOCKED (3).

    Implementation note: this test runs the CLI as a subprocess so its
    asyncio loop is fully isolated from the lock-holding connection.
    Trying to interleave both in the same process triggers asyncpg's
    'Future attached to a different loop' error.
    """
    import asyncio

    url = f"file://{tmp_git_repo.resolve()}"

    async def _hold_lock_then_run() -> int:
        engine = create_async_engine(get_settings().database_url)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                await session.execute(
                    text("SELECT pg_advisory_lock(hashtext(:url))"),
                    {"url": url},
                )
                # The lock is now held on this session.
                # Spawn a separate process to run the CLI; subprocess
                # runs in its own asyncpg loop, so no cross-loop conflict.
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "cli",
                        "index",
                        str(tmp_git_repo),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env={**os.environ},
                )
                # Release the lock before returning.
                await session.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:url))"),
                    {"url": url},
                )
                # Commit so the lock is fully released for cleanup.
                await session.commit()
                return proc.returncode
        finally:
            await engine.dispose()

    # Allow some warmup so the engine is ready.
    time.sleep(0.1)
    assert asyncio.run(_hold_lock_then_run()) == EXIT_LOCKED
