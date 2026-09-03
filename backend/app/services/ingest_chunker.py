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

Every count comes from one pass over the file's lines. The three sizes
the rules above need — whole file, hunk, sub-chunk — are sums over that
one pass rather than three separate trips through the tokeniser, and
hunk boundaries are line indices rather than substrings to re-measure.

`tokens_used` is therefore the sum of the chunk's line counts, which sits
slightly *above* the count of the same text taken whole: BPE merges a few
pairs across line breaks that per-line counting keeps apart. Measured
across 14.4k chunks of `pallets/flask`, 23% differ and the largest gap is
18 tokens. Erring high is the safe direction for a budget, and
`count_tokens` documents these numbers as approximate.
"""

from functools import lru_cache

import tiktoken

from app.schemas.ingest import Chunk, ChunkTypeCode, FileDiff

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


@lru_cache(maxsize=16384)
def _line_tokens(line: str) -> int:
    """Token count for a single diff line.

    Lines repeat heavily inside diffs. Across `pallets/flask`, only 12%
    of the lines in splittable diffs were distinct, and `"+\n"` alone
    accounted for 18% of all occurrences. A modest cache turns ~672k
    tokeniser calls into ~79k; a larger one measured no better.
    """
    return count_tokens(line)


def _hunk_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Line ranges of each hunk, as `[start, end)` index pairs.

    Everything before the first `@@` stays with the first hunk, so the
    model still sees `diff --git a/X b/Y`, `--- a/X`, `+++ b/Y` context.
    A diff with no hunk markers — a pure rename, say — is a single range
    covering the file.

    Ranges rather than substrings: the caller already holds a token count
    per line, and index slices keep those counts usable.
    """
    marks = [i for i, line in enumerate(lines) if line.startswith("@@")]
    if not marks:
        return [(0, len(lines))]

    starts = [0, *marks[1:]]
    return [
        (start, starts[i + 1] if i + 1 < len(starts) else len(lines))
        for i, start in enumerate(starts)
    ]


def _pack_with_overlap(
    line_tokens: list[int],
    start: int,
    end: int,
    max_tokens: int,
    *,
    overlap_pct: float,
) -> list[tuple[int, int]]:
    """Break `[start, end)` into sub-ranges of at most `max_tokens`.

    Each sub-range repeats the tail of the previous one — `overlap_pct`
    of the budget, in whole lines — so context isn't lost at boundaries.
    Splits happen at line boundaries, never mid-line.
    """
    ranges: list[tuple[int, int]] = []
    cursor = start

    while cursor < end:
        # Greedily accumulate lines until adding the next would exceed budget.
        stop = cursor
        running = 0
        while stop < end and running + line_tokens[stop] <= max_tokens:
            running += line_tokens[stop]
            stop += 1

        # Always advance at least one line, even if a single line is over
        # budget (rare — e.g. a 5K-token minified blob inside a hunk).
        if stop == cursor:
            stop = cursor + 1

        ranges.append((cursor, stop))
        if stop >= end:
            break

        # Walk back from `stop`, collecting lines until roughly
        # `overlap_pct` of the budget is covered.
        target_overlap = int(max_tokens * overlap_pct)
        overlap_start = stop
        overlap_running = 0
        while overlap_start > cursor and overlap_running < target_overlap:
            overlap_start -= 1
            overlap_running += line_tokens[overlap_start]

        # Keep the overlap region, but guard `cursor` strictly increasing
        # so we don't loop forever.
        cursor = max(overlap_start, cursor + 1)

    return ranges


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
        marker = "<truncated: diff exceeded MAX_DIFF_BYTES>"
        return [
            Chunk(
                file_path=file_diff.file_path,
                old_path=file_diff.old_path,
                change_type=file_diff.change_type,
                chunk_type="file",
                diff_content=marker,
                tokens_used=count_tokens(marker),
            )
        ]

    if not file_diff.diff_content:
        # Pure rename (R100) or other no-content delta — nothing to embed.
        return []

    # The single pass every size below is derived from.
    lines = file_diff.diff_content.splitlines(keepends=True)
    line_tokens = [_line_tokens(line) for line in lines]

    def build(chunk_type: ChunkTypeCode, start: int, end: int) -> Chunk:
        return Chunk(
            file_path=file_diff.file_path,
            old_path=file_diff.old_path,
            change_type=file_diff.change_type,
            chunk_type=chunk_type,
            diff_content="".join(lines[start:end]),
            tokens_used=sum(line_tokens[start:end]),
        )

    if sum(line_tokens) <= SMALL_CHUNK_LIMIT:
        return [build("file", 0, len(lines))]

    chunks: list[Chunk] = []
    for start, end in _hunk_ranges(lines):
        if sum(line_tokens[start:end]) <= max_tokens:
            chunks.append(build("hunk", start, end))
        else:
            chunks.extend(
                build("hunk", sub_start, sub_end)
                for sub_start, sub_end in _pack_with_overlap(
                    line_tokens, start, end, max_tokens, overlap_pct=HUNK_OVERLAP_PCT
                )
            )

    return chunks
