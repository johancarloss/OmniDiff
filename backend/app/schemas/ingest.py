from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# One-letter codes matching `git diff --name-status` output.
ChangeTypeCode = Literal["A", "M", "D", "R"]
ChunkTypeCode = Literal["file", "hunk"]


class CommitMeta(BaseModel):
    """Metadata of a single commit extracted from `git log`.

    The schema mirrors the persistable subset of `models.Commit` columns
    (excluding FKs, timestamps, and surrogate IDs). It is what the
    subprocess parser produces and what `CommitRepo.bulk_upsert_by_hash`
    consumes.
    """

    hash: str = Field(min_length=40, max_length=40)
    author_name: str | None = None
    author_email: str | None = None
    message: str
    committed_at: datetime
    parents: list[str] = Field(default_factory=list)
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


class FileDiff(BaseModel):
    """One file's diff inside a commit.

    Output of `_git_subprocess.extract_file_diffs`, input to the chunker.
    Mirrors the Rust struct `core::diff::FileDiff`.
    """

    file_path: str
    # old_path is set only when change_type == "R" (rename).
    old_path: str | None = None
    change_type: ChangeTypeCode
    diff_content: str
    is_binary: bool = False
    # Set by the diff extractor when `len(diff_content) > MAX_DIFF_BYTES`.
    # The chunker translates this into a stub chunk so embedding is skipped.
    truncated: bool = False


class Chunk(BaseModel):
    """An embeddable slice of a file's diff.

    Output of the chunker, input to `ChunkRepo.bulk_insert`. Maps 1:1 to
    a row in `commit_chunks` (minus FK and surrogate id).
    """

    file_path: str
    old_path: str | None = None
    change_type: ChangeTypeCode
    chunk_type: ChunkTypeCode
    diff_content: str
    tokens_used: int


class WalkResult(BaseModel):
    """Output of the walker — used by `IngestService` to populate
    `IndexResult.skipped_merges` accurately."""

    metas: list[CommitMeta]
    skipped_merges: int = 0


class IndexResult(BaseModel):
    """Outcome of a single `IngestService.index()` call."""

    repository_id: int
    total_commits_seen: int
    commits_inserted: int
    chunks_inserted: int = 0
    skipped_merges: int = 0
    duration_seconds: float
    # True when the run started from `Repository.last_indexed_hash` rather
    # than from the beginning of history. Surfaced so CLI and HTTP layers
    # can distinguish cold-start from warm runs in their reports.
    was_incremental: bool = False
    # The hash used as the resume point when `was_incremental` is True;
    # None for cold-start runs. Useful for debugging "why did this run
    # process N commits?" questions.
    since_hash: str | None = None
