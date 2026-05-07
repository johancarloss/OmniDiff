"""Request/response schemas for the indexing HTTP endpoint.

These are the public surface of `POST /api/v1/index` and
`GET /api/v1/index/{job_id}`. Kept separate from `schemas/ingest.py` so
the API contract isn't coupled to the internal pipeline DTOs (those
can churn freely; this can't, since clients depend on them).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IndexRequest(BaseModel):
    """Body of `POST /api/v1/index`.

    `repo_url` is intentionally `str`, not `pydantic.HttpUrl`: we accept
    `git@host:org/repo.git` (SSH-style, not a URL by RFC), `file://`
    (used in tests), and HTTPS — broader than what HttpUrl validates.
    Real validation is delegated to `ensure_local_clone`, which can
    actually attempt the operation.
    """

    repo_url: str = Field(min_length=1, max_length=500)
    branch: str | None = Field(default=None, max_length=200)


class IndexAcceptedResponse(BaseModel):
    """202 response of `POST /api/v1/index`.

    `job_id` reuses `repository.id` (see Slice 4 DT-1). Clients should
    treat it as opaque — int today, possibly UUID after multi-tenant.
    """

    job_id: int
    repo_url: str
    status: str
    message: str = "Indexing scheduled"


class JobStatusResponse(BaseModel):
    """Response of `GET /api/v1/index/{job_id}`.

    Mirrors the persistable `Repository` columns that callers care
    about. `error_message` is only populated when `status == "failed"`.
    """

    job_id: int
    repo_url: str
    status: str
    total_commits: int
    indexed_commits: int
    last_indexed_hash: str | None
    error_message: str | None
