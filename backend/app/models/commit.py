import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository


class ChunkType(enum.StrEnum):
    FILE = "file"
    HUNK = "hunk"


class Commit(Base, TimestampMixin):
    __tablename__ = "commits"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    hash: Mapped[str] = mapped_column(String(40), nullable=False)
    # author_name and author_email are nullable because git permits commits
    # without an author identity (extremely rare, but real). Defensive.
    author_name: Mapped[str | None] = mapped_column(String(200))
    author_email: Mapped[str | None] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Parents as a Postgres array of hashes. Empty for root commits, one
    # element for normal commits, two+ for merges (we currently filter
    # merges out before persisting, but the column stays generic).
    parents: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)),
        nullable=False,
        server_default=text("'{}'::varchar[]"),
    )
    files_changed: Mapped[int] = mapped_column(default=0, nullable=False)
    insertions: Mapped[int] = mapped_column(default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(default=0, nullable=False)

    repository: Mapped["Repository"] = relationship(back_populates="commits")
    chunks: Mapped[list["CommitChunk"]] = relationship(
        back_populates="commit",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("repository_id", "hash", name="uq_commits_repo_hash"),
        Index(
            "idx_commits_repo_committed_at",
            "repository_id",
            "committed_at",
        ),
    )


class CommitChunk(Base, TimestampMixin):
    __tablename__ = "commit_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    commit_id: Mapped[int] = mapped_column(
        ForeignKey("commits.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_type: Mapped[ChunkType] = mapped_column(nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # old_path is populated when the chunk represents a renamed file
    # (change_type == 'R'); references the file's previous path.
    old_path: Mapped[str | None] = mapped_column(String(500))
    # 'A' add | 'M' modify | 'D' delete | 'R' rename — one-letter code
    # matching `git diff --name-status` output.
    change_type: Mapped[str] = mapped_column(String(1), nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    # description_nl, tokens_used, embedding are populated in Phase 3
    # (embedding pipeline). They live in the schema from day one to avoid
    # later migrations on a hot table.
    description_nl: Mapped[str | None] = mapped_column(Text)
    tokens_used: Mapped[int] = mapped_column(default=0, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector(1024), nullable=True)

    commit: Mapped["Commit"] = relationship(back_populates="chunks")

    __table_args__ = (
        CheckConstraint(
            "change_type IN ('A', 'M', 'D', 'R')",
            name="ck_chunks_change_type",
        ),
        Index("idx_chunks_commit_id", "commit_id"),
        Index(
            "idx_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 128},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
    )
