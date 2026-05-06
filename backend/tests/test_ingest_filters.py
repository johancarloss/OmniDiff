"""Unit tests for ingest_filters.

These mirror the tests in `core/src/filters.rs` exactly. When adding or
changing a test here, mirror the same change in the Rust suite — the
two implementations must remain behaviorally identical so the Phase 2-C
Rust port is a true drop-in replacement.
"""

from app.services.ingest_filters import should_skip_commit, should_skip_file


def test_lock_files_are_skipped() -> None:
    assert should_skip_file("package-lock.json", is_binary_in_git=False)
    assert should_skip_file("backend/uv.lock", is_binary_in_git=False)


def test_generated_paths_are_skipped() -> None:
    assert should_skip_file("frontend/node_modules/foo/index.js", is_binary_in_git=False)
    assert should_skip_file("backend/.venv/lib/site-packages/x.py", is_binary_in_git=False)


def test_binary_extensions_are_skipped() -> None:
    assert should_skip_file("docs/screenshot.png", is_binary_in_git=False)
    # Case-insensitive — uppercase extension still matches.
    assert should_skip_file("logo.SVG.PNG", is_binary_in_git=False)


def test_source_files_are_not_skipped() -> None:
    assert not should_skip_file("backend/app/main.py", is_binary_in_git=False)
    assert not should_skip_file("frontend/src/App.tsx", is_binary_in_git=False)


def test_merge_commits_are_skipped() -> None:
    assert not should_skip_commit(0)  # root
    assert not should_skip_commit(1)  # normal
    assert should_skip_commit(2)  # merge
