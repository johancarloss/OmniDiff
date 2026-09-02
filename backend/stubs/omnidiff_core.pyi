"""Type stub for the Rust extension built from `core/`.

Hand-written and kept in step with `core/src/lib.rs` — the crate ships no
stub of its own. Every value listed here is a plain Python type: the
Rust/Python boundary passes primitives and dicts only, never opaque
handles, so the Python side stays mockable in tests.
"""

from typing import TypedDict

__version__: str

class FileDiffDict(TypedDict):
    """One entry of `extract_file_diffs`. Mirrors `FileDiff` in
    `app/schemas/ingest.py`."""

    file_path: str
    old_path: str | None
    change_type: str
    diff_content: str
    is_binary: bool
    truncated: bool

def should_skip_file(path: str, *, is_binary_in_git: bool) -> bool: ...
def should_skip_commit(parent_count: int) -> bool: ...
def commit_stats(repo_path: str, commit_hash: str) -> tuple[int, int, int]: ...
def commit_stats_batch(
    repo_path: str, commit_hashes: list[str]
) -> list[tuple[int, int, int]]: ...
def extract_file_diffs(repo_path: str, commit_hash: str) -> list[FileDiffDict]: ...
def extract_file_diffs_batch(
    repo_path: str, commit_hashes: list[str]
) -> list[list[FileDiffDict]]: ...
