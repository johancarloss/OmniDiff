"""Token-aware chunker for file diffs.

Mirror of `core/src/chunker.rs` (Rust). The two implementations must
emit the same chunks for the same input — Phase 2-C will replace the
Python module with the Rust one and benchmark the speedup.

Strategy (per blueprint § 4.8):

    tokens <= SMALL_CHUNK_LIMIT     → 1 chunk per file (chunk_type='file')
    SMALL_CHUNK_LIMIT < tokens <= max_tokens
                                     → split by hunk markers (`@@ ... @@`)
    tokens > max_tokens              → split by hunk + subdivide hunks that
                                       still exceed max_tokens, with
                                       HUNK_OVERLAP_PCT of trailing lines
                                       carried into the next sub-chunk

Files marked is_binary or truncated are emitted as zero chunks (binary)
or a single stub chunk (truncated).
"""

from functools import lru_cache

import tiktoken

from app.schemas.ingest import Chunk, FileDiff

# Constants intentionally kept in sync with `core/src/chunker.rs`.
SMALL_CHUNK_LIMIT: int = 500
LARGE_CHUNK_LIMIT: int = 2000
HUNK_OVERLAP_PCT: float = 0.15
MAX_DIFF_BYTES: int = 10 * 1024 * 1024  # 10 MiB safety net


@lru_cache(maxsize=1)
def _encoder() -> tiktoken.Encoding:
    """Singleton encoder.

    `tiktoken.get_encoding('cl100k_base')` loads ~1MB of BPE tables on
    first call (~50ms). Without this cache, every `count_tokens` call
    would re-load — for a repo with 5K chunks that means 5K disk reads.
    """
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return the token count for `text` under cl100k_base BPE.

    Same tokenizer family used by Voyage and OpenAI; close enough to
    the real tokenizer of the embedding provider for chunking decisions
    (which only need to be approximately right — not exact).
    """
    if not text:
        return 0
    return len(_encoder().encode(text))


def _split_by_hunks(diff_content: str) -> list[str]:
    """Split a unified diff into hunks at lines starting with '@@'.

    The header (everything up to the first '@@' line) is prepended to
    the first hunk so the model still sees `diff --git a/X b/Y`,
    `--- a/X`, `+++ b/Y` context.

    For diffs that have no hunk markers (e.g., a pure rename with no
    content changes), returns a single-element list with the whole
    content.
    """
    lines = diff_content.splitlines(keepends=True)
    hunks: list[list[str]] = []
    current: list[str] = []
    seen_first_hunk = False

    for line in lines:
        if line.startswith("@@"):
            if seen_first_hunk:
                hunks.append(current)
                current = []
            else:
                # Header lines accumulated so far stay with the first hunk.
                seen_first_hunk = True
            current.append(line)
        else:
            current.append(line)

    if current:
        hunks.append(current)

    if not seen_first_hunk:
        # No hunk markers at all — keep as a single chunk.
        return [diff_content] if diff_content else []

    return ["".join(h) for h in hunks]


def _subdivide_with_overlap(hunk: str, max_tokens: int, *, overlap_pct: float) -> list[str]:
    """Break a hunk that exceeds `max_tokens` into sub-chunks.

    Each sub-chunk holds at most `max_tokens` worth of tokens. The next
    sub-chunk repeats the last `overlap_pct` of the previous chunk's
    lines so that context isn't lost at boundaries. Splits happen at
    line boundaries — never mid-line.
    """
    lines = hunk.splitlines(keepends=True)
    if not lines:
        return []

    # Pre-tokenize each line to avoid re-encoding on every accumulation.
    line_tokens: list[int] = [count_tokens(line) for line in lines]

    sub_chunks: list[str] = []
    start = 0
    n = len(lines)

    while start < n:
        # Greedily accumulate lines until adding the next one would exceed budget.
        end = start
        running = 0
        while end < n and running + line_tokens[end] <= max_tokens:
            running += line_tokens[end]
            end += 1

        # Always advance at least one line, even if a single line is over budget
        # (rare — e.g. a 5K-token minified blob inside a hunk).
        if end == start:
            end = start + 1

        sub_chunks.append("".join(lines[start:end]))

        if end >= n:
            break

        # Compute overlap for the next sub-chunk: walk backwards from `end`
        # collecting lines until we accumulate ~overlap_pct of max_tokens.
        target_overlap = int(max_tokens * overlap_pct)
        overlap_start = end
        overlap_running = 0
        while overlap_start > start and overlap_running < target_overlap:
            overlap_start -= 1
            overlap_running += line_tokens[overlap_start]

        # Move start forward past the consumed lines, but keep the overlap
        # region. Guard `start` strictly increasing so we don't loop forever.
        next_start = max(overlap_start, start + 1)
        start = next_start

    return sub_chunks


def chunk_file_diff(file_diff: FileDiff, *, max_tokens: int = LARGE_CHUNK_LIMIT) -> list[Chunk]:
    """Apply blueprint § 4.8 chunking rules to a single file's diff.

    Returns:
        - empty list if `file_diff.is_binary`
        - one stub chunk if `file_diff.truncated`
        - one ChunkType='file' chunk if total tokens <= SMALL_CHUNK_LIMIT
        - N ChunkType='hunk' chunks otherwise (subdivided with overlap if any
          hunk individually exceeds `max_tokens`)
    """
    if file_diff.is_binary:
        return []

    if file_diff.truncated:
        # Emit a marker chunk so the commit isn't completely silent in
        # the index, but skip embedding-quality content.
        return [
            Chunk(
                file_path=file_diff.file_path,
                old_path=file_diff.old_path,
                change_type=file_diff.change_type,
                chunk_type="file",
                diff_content="<truncated: diff exceeded MAX_DIFF_BYTES>",
                tokens_used=count_tokens("<truncated: diff exceeded MAX_DIFF_BYTES>"),
            )
        ]

    if not file_diff.diff_content:
        # Pure rename (R100) or other no-content delta — nothing to embed.
        return []

    total_tokens = count_tokens(file_diff.diff_content)

    if total_tokens <= SMALL_CHUNK_LIMIT:
        return [
            Chunk(
                file_path=file_diff.file_path,
                old_path=file_diff.old_path,
                change_type=file_diff.change_type,
                chunk_type="file",
                diff_content=file_diff.diff_content,
                tokens_used=total_tokens,
            )
        ]

    hunks = _split_by_hunks(file_diff.diff_content)
    chunks: list[Chunk] = []

    for hunk in hunks:
        hunk_tokens = count_tokens(hunk)
        if hunk_tokens <= max_tokens:
            chunks.append(
                Chunk(
                    file_path=file_diff.file_path,
                    old_path=file_diff.old_path,
                    change_type=file_diff.change_type,
                    chunk_type="hunk",
                    diff_content=hunk,
                    tokens_used=hunk_tokens,
                )
            )
        else:
            for sub in _subdivide_with_overlap(hunk, max_tokens, overlap_pct=HUNK_OVERLAP_PCT):
                chunks.append(
                    Chunk(
                        file_path=file_diff.file_path,
                        old_path=file_diff.old_path,
                        change_type=file_diff.change_type,
                        chunk_type="hunk",
                        diff_content=sub,
                        tokens_used=count_tokens(sub),
                    )
                )

    return chunks
