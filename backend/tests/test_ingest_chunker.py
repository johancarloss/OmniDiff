"""Unit tests for the token-aware chunker.

These tests run without DB and without git — pure Python with synthetic
FileDiff inputs. The goal is to cover the four chunking branches
explicitly: small file, hunk-split, hunk-subdivide, binary skip,
truncated stub.
"""

from app.schemas.ingest import FileDiff
from app.services.ingest_chunker import (
    HUNK_OVERLAP_PCT,
    LARGE_CHUNK_LIMIT,
    SMALL_CHUNK_LIMIT,
    chunk_file_diff,
    count_tokens,
)

# A small valid unified-diff snippet (well under SMALL_CHUNK_LIMIT).
SMALL_DIFF = """\
diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def hello():
-    return 1
+    return 2
+
"""


def _make_diff(content: str, *, change: str = "M", binary: bool = False) -> FileDiff:
    return FileDiff(
        file_path="path/to/file.py",
        change_type=change,  # type: ignore[arg-type]
        diff_content=content,
        is_binary=binary,
    )


def test_small_diff_returns_one_file_chunk() -> None:
    """Diff with fewer than SMALL_CHUNK_LIMIT tokens stays whole."""
    chunks = chunk_file_diff(_make_diff(SMALL_DIFF))
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "file"
    assert chunks[0].tokens_used == count_tokens(SMALL_DIFF)
    assert chunks[0].tokens_used <= SMALL_CHUNK_LIMIT


def test_medium_diff_splits_per_hunk() -> None:
    """Diff with multiple hunks, each below LARGE_CHUNK_LIMIT, but total
    above SMALL_CHUNK_LIMIT, becomes one chunk per hunk."""
    # Build a diff with 3 hunks. We pad each hunk to push total above the
    # small-chunk threshold while keeping each hunk well below max.
    padding = "\n".join("+ filler line " + str(i) for i in range(60))
    multi_hunk = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,1 @@\n"
        f"{padding}\n"
        "@@ -10,1 +10,1 @@\n"
        f"{padding}\n"
        "@@ -20,1 +20,1 @@\n"
        f"{padding}\n"
    )

    total = count_tokens(multi_hunk)
    assert total > SMALL_CHUNK_LIMIT, "fixture must trigger hunk-splitting"

    chunks = chunk_file_diff(_make_diff(multi_hunk))
    # Header attaches to first hunk → still 3 hunks emitted.
    assert len(chunks) == 3
    assert all(c.chunk_type == "hunk" for c in chunks)


def test_large_hunk_subdivides_with_overlap() -> None:
    """A single hunk that exceeds max_tokens splits into multiple
    sub-chunks; adjacent sub-chunks share at least one line of overlap."""
    # ~3000 tokens of content in a single hunk — guaranteed split.
    huge_lines = "\n".join("+ a moderately long line of content " + str(i) for i in range(800))
    huge_hunk = (
        f"diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,1 @@\n{huge_lines}\n"
    )

    assert count_tokens(huge_hunk) > LARGE_CHUNK_LIMIT, "fixture must exceed max_tokens"

    chunks = chunk_file_diff(_make_diff(huge_hunk))
    assert len(chunks) >= 2, "huge hunk must split into >= 2 sub-chunks"
    assert all(c.chunk_type == "hunk" for c in chunks)

    # Every emitted chunk must respect the budget (with a small slack for
    # the overlap region itself, which is intentional).
    max_allowed = int(LARGE_CHUNK_LIMIT * (1.0 + HUNK_OVERLAP_PCT))
    assert all(c.tokens_used <= max_allowed for c in chunks)

    # Overlap check: at least one trailing line of chunk N appears at the
    # head of chunk N+1.
    for i in range(len(chunks) - 1):
        prev_lines = chunks[i].diff_content.splitlines()
        next_lines = chunks[i + 1].diff_content.splitlines()
        if not prev_lines or not next_lines:
            continue
        # Some prefix of next chunk's lines must appear at the tail of prev.
        overlap_found = any(
            prev_lines[-k:] == next_lines[:k]
            for k in range(1, min(len(prev_lines), len(next_lines)) + 1)
        )
        assert overlap_found, f"chunk {i} and {i + 1} must share at least one boundary line"


def test_binary_file_returns_no_chunks() -> None:
    chunks = chunk_file_diff(_make_diff("", binary=True))
    assert chunks == []


def test_truncated_file_returns_stub_chunk() -> None:
    fd = FileDiff(
        file_path="huge.bin",
        change_type="A",
        diff_content="",  # extractor cleared it on truncation
        is_binary=False,
        truncated=True,
    )
    chunks = chunk_file_diff(fd)
    assert len(chunks) == 1
    assert "truncated" in chunks[0].diff_content.lower()


def test_empty_diff_content_returns_no_chunks() -> None:
    """Pure rename with no content delta → nothing to embed."""
    fd = FileDiff(
        file_path="new/path.py",
        old_path="old/path.py",
        change_type="R",
        diff_content="",
        is_binary=False,
    )
    assert chunk_file_diff(fd) == []
