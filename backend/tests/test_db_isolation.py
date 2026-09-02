"""The test suite must never touch the developer database."""

from __future__ import annotations

import pytest

from app.config import get_settings
from tests.db_isolation import (
    TEST_DB_SUFFIX,
    assert_test_database,
    database_name,
    resolve_test_database_url,
)

DEV_URL = "postgresql+asyncpg://omnidiff:omnidiff@localhost:5432/omnidiff"


def test_resolve_points_at_the_test_sibling() -> None:
    assert resolve_test_database_url(DEV_URL) == f"{DEV_URL}{TEST_DB_SUFFIX}"


def test_resolve_is_idempotent() -> None:
    once = resolve_test_database_url(DEV_URL)
    assert resolve_test_database_url(once) == once


def test_resolve_preserves_driver_credentials_and_port() -> None:
    url = resolve_test_database_url("postgresql+asyncpg://u:p@db.internal:6543/omni")
    assert url == "postgresql+asyncpg://u:p@db.internal:6543/omni_test"


def test_resolve_rejects_a_url_without_a_database_name() -> None:
    with pytest.raises(ValueError, match="database name"):
        resolve_test_database_url("postgresql+asyncpg://u:p@localhost:5432/")


def test_resolve_rejects_a_name_that_is_not_a_plain_identifier() -> None:
    with pytest.raises(ValueError, match="identifier"):
        resolve_test_database_url('postgresql+asyncpg://u:p@localhost/omni"; DROP')


def test_guard_rejects_the_developer_database() -> None:
    with pytest.raises(RuntimeError, match="refusing"):
        assert_test_database(DEV_URL)


def test_guard_accepts_the_test_database() -> None:
    assert_test_database(f"{DEV_URL}{TEST_DB_SUFFIX}")


def test_database_name_extracts_the_path_segment() -> None:
    assert database_name(DEV_URL) == "omnidiff"


def test_running_suite_is_pointed_at_the_test_database() -> None:
    """End-to-end: the redirect in conftest reached the app's own settings."""
    assert database_name(get_settings().database_url).endswith(TEST_DB_SUFFIX)


def test_maintenance_url_targets_the_postgres_database() -> None:
    from tests.db_isolation import maintenance_database_url

    assert maintenance_database_url(DEV_URL).endswith("/postgres")
