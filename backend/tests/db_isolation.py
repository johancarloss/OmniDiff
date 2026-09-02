"""Resolves the database the test suite is allowed to destroy.

`app.database` builds a single module-level engine from an lru_cached
`Settings`, and the API tests drive the real `app` object instead of
overriding `get_session`. Redirecting per fixture would therefore leave
the app itself writing to the developer database, so `conftest` performs
the redirect once, at process level, using the helpers here.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

TEST_DB_SUFFIX = "_test"
MAINTENANCE_DB = "postgres"

_PLAIN_IDENTIFIER = re.compile(r"\A[A-Za-z0-9_]+\Z")


def database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def _with_database(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


def resolve_test_database_url(url: str) -> str:
    """Point `url` at the `<name>_test` sibling, or leave it if already there."""
    name = database_name(url)
    if not name:
        raise ValueError(f"URL carries no database name: {url!r}")
    if not _PLAIN_IDENTIFIER.match(name):
        raise ValueError(f"database name {name!r} is not a plain identifier")
    if name.endswith(TEST_DB_SUFFIX):
        return url
    return _with_database(url, f"{name}{TEST_DB_SUFFIX}")


def maintenance_database_url(url: str) -> str:
    """Same server, `postgres` database — the only place CREATE DATABASE runs."""
    return _with_database(url, MAINTENANCE_DB)


def assert_test_database(url: str) -> None:
    """Last line of defence before `drop_all` reaches a real database."""
    name = database_name(url)
    if not name.endswith(TEST_DB_SUFFIX):
        raise RuntimeError(
            f"refusing to drop the schema of {name!r}: the suite only operates on "
            f"databases ending in {TEST_DB_SUFFIX!r}. Check DATABASE_URL."
        )
