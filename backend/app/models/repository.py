import enum
from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.commit import Commit


class IndexingStatus(enum.StrEnum):
    PENDING = "pending"
    CLONING = "cloning"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    status: Mapped[IndexingStatus] = mapped_column(default=IndexingStatus.PENDING)
    clone_path: Mapped[str | None] = mapped_column(String(500))
    total_commits: Mapped[int] = mapped_column(default=0)
    indexed_commits: Mapped[int] = mapped_column(default=0)
    # Hash of the most recent commit indexed for this repo. Populated by
    # IngestService at the end of a successful index() call. Used by the
    # incremental-indexing path (Slice 3) to compute `git log <hash>..HEAD`.
    last_indexed_hash: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(1000))

    commits: Mapped[list["Commit"]] = relationship(
        back_populates="repository",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("idx_repositories_status", "status"),)
