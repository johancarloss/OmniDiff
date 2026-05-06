from datetime import datetime

from pydantic import BaseModel, Field


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


class IndexResult(BaseModel):
    """Outcome of a single `IngestService.index()` call."""

    repository_id: int
    total_commits_seen: int
    commits_inserted: int
    skipped_merges: int = 0
    duration_seconds: float
