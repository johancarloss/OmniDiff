"""Rust and Python filters must agree — the twin-implementation guard.

`ingest_filters.py` and `core/src/filters.rs` are maintained as mirrors.
A behavioural test alone would not catch a constant added to one side
only, so the constants are compared directly as well.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import ingest_filters as py

core = pytest.importorskip(
    "omnidiff_core",
    reason="Rust extension not built — run `maturin develop` from core/",
)

RUST_SOURCE = Path(__file__).resolve().parents[2] / "core" / "src" / "filters.rs"


def _rust_const(name: str) -> list[str]:
    """Pull a `pub const NAME: &[&str] = &[...]` list out of the Rust source."""
    body = re.search(rf"pub const {name}: &\[&str\] = &\[(.*?)\];", RUST_SOURCE.read_text(), re.S)
    assert body, f"{name} not found in {RUST_SOURCE}"
    return re.findall(r'"([^"]*)"', body.group(1))


@pytest.mark.parametrize(
    ("const_name", "python_value"),
    [
        ("LOCK_FILES", py.LOCK_FILES),
        ("GENERATED_PATH_FRAGMENTS", py.GENERATED_PATH_FRAGMENTS),
        ("BINARY_EXTENSIONS", py.BINARY_EXTENSIONS),
    ],
)
def test_constants_stay_in_sync(const_name: str, python_value: object) -> None:
    assert set(_rust_const(const_name)) == set(python_value)  # type: ignore[call-overload]


def _corpus() -> list[str]:
    """Paths exercising every rule, plus the cases most likely to diverge."""
    paths = [
        "app/main.py",
        "README.md",
        "src/lib.rs",
        "Makefile",
        ".gitignore",
        "",
        "a/b/c/deep/file.ts",
    ]
    for name in py.LOCK_FILES:
        paths += [name, f"nested/dir/{name}", f"not-a-{name}", f"{name}.bak"]
    for ext in py.BINARY_EXTENSIONS:
        paths += [f"asset.{ext}", f"asset.{ext.upper()}", f"dir/x.{ext}", f"noext{ext}"]
    for frag in py.GENERATED_PATH_FRAGMENTS:
        bare = frag.strip("/")
        paths += [f"{bare}/pkg/index.js", f"a{frag}b.py", f"{bare}.py", f"x/{bare}"]
    return paths


@pytest.mark.parametrize("path", _corpus())
@pytest.mark.parametrize("is_binary", [False, True])
def test_should_skip_file_matches(path: str, is_binary: bool) -> None:
    assert core.should_skip_file(path, is_binary_in_git=is_binary) == py.should_skip_file(
        path, is_binary_in_git=is_binary
    )


@pytest.mark.parametrize("parent_count", [0, 1, 2, 3, 17])
def test_should_skip_commit_matches(parent_count: int) -> None:
    assert core.should_skip_commit(parent_count) == py.should_skip_commit(parent_count)
