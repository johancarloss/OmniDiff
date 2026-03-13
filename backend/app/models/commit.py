from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Commit(Base, TimestampMixin):
    __tablename__ = "commits"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    hash: Mapped[str] = mapped_column(String(40), nullable=False)
    author_name: Mapped[str] = mapped_column(String(200), nullable=False)
    author_email: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(nullable=False)

    repository: Mapped["Repository"] = relationship(  # noqa: F821
        back_populates="commits",
    )
    chunks: Mapped[list["CommitChunk"]] = relationship(
        back_populates="commit",
        lazy="raise",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_commits_repo_hash", "repository_id", "hash", unique=True),
    )


class CommitChunk(Base, TimestampMixin):
    __tablename__ = "commit_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    commit_id: Mapped[int] = mapped_column(
        ForeignKey("commits.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    description_nl: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[Any | None] = mapped_column(Vector(1024), nullable=True)

    commit: Mapped["Commit"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index(
            "idx_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 128},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
        Index("idx_chunks_commit_id", "commit_id"),
    )
