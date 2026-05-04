"""initial schema

Creates the three core tables for the ingestion pipeline:
  - repositories (one row per Git repo being indexed)
  - commits (one row per commit)
  - commit_chunks (one row per indexable diff chunk; embedding/description
    populated in Phase 3)

Phase 2-A baseline. See docs/private/phases/active/PHASE-2A-GIT-INGEST.md.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The pgvector extension provides the `vector` type and HNSW indexing.
    # Autogenerate cannot detect this — must be added manually.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("default_branch", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CLONING",
                "INDEXING",
                "COMPLETED",
                "FAILED",
                name="indexingstatus",
            ),
            nullable=False,
        ),
        sa.Column("clone_path", sa.String(length=500), nullable=True),
        sa.Column("total_commits", sa.Integer(), nullable=False),
        sa.Column("indexed_commits", sa.Integer(), nullable=False),
        sa.Column("last_indexed_hash", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_index(
        "idx_repositories_status", "repositories", ["status"], unique=False
    )

    op.create_table(
        "commits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("hash", sa.String(length=40), nullable=False),
        sa.Column("author_name", sa.String(length=200), nullable=True),
        sa.Column("author_email", sa.String(length=200), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "parents",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("files_changed", sa.Integer(), nullable=False),
        sa.Column("insertions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["repositories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id", "hash", name="uq_commits_repo_hash"
        ),
    )
    op.create_index(
        "idx_commits_repo_committed_at",
        "commits",
        ["repository_id", "committed_at"],
        unique=False,
    )

    op.create_table(
        "commit_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commit_id", sa.Integer(), nullable=False),
        sa.Column(
            "chunk_type",
            sa.Enum("FILE", "HUNK", name="chunktype"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("old_path", sa.String(length=500), nullable=True),
        sa.Column("change_type", sa.String(length=1), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("description_nl", sa.Text(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "change_type IN ('A', 'M', 'D', 'R')",
            name="ck_chunks_change_type",
        ),
        sa.ForeignKeyConstraint(
            ["commit_id"], ["commits.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_chunks_commit_id", "commit_chunks", ["commit_id"], unique=False
    )
    op.create_index(
        "idx_chunks_embedding",
        "commit_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 128},
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_where=sa.text("embedding IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_chunks_embedding",
        table_name="commit_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 128},
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_where=sa.text("embedding IS NOT NULL"),
    )
    op.drop_index("idx_chunks_commit_id", table_name="commit_chunks")
    op.drop_table("commit_chunks")
    op.drop_index("idx_commits_repo_committed_at", table_name="commits")
    op.drop_table("commits")
    op.drop_index("idx_repositories_status", table_name="repositories")
    op.drop_table("repositories")

    # Drop ENUM types — autogenerate doesn't emit these on downgrade.
    op.execute("DROP TYPE IF EXISTS chunktype")
    op.execute("DROP TYPE IF EXISTS indexingstatus")

    # Note: we deliberately do NOT drop the `vector` extension on
    # downgrade — it may be used by other apps on the same database.
    # If you really want a clean slate, run manually:
    #   DROP EXTENSION vector CASCADE;
