from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    # Timezone-aware: commits arrive from git with timezone offsets, and
    # mixing tz-aware (commits.committed_at) with tz-naive (created_at)
    # in the same query crashes with "can't subtract offset-naive and
    # offset-aware datetimes".
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
