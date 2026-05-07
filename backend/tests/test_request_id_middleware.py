"""Unit tests for the request_id middleware.

We mount the middleware onto a tiny throwaway Starlette app rather than
the full FastAPI `app` — keeps these tests independent of the rest of
the API surface (and fast: no DB, no settings, no other middleware).
"""

from __future__ import annotations

import asyncio
import re

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.middleware.request_id import (
    REQUEST_ID_HEADER,
    RequestIDMiddleware,
    request_id_var,
)

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _build_app() -> Starlette:
    async def echo_request_id(request):  # type: ignore[no-untyped-def]
        # Reads back the contextvar so the test can verify it was set
        # *during* the handler invocation, not just on the response.
        return JSONResponse({"request_id": request_id_var.get()})

    async def boom(request):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated handler error")

    app = Starlette(
        routes=[
            Route("/echo", echo_request_id),
            Route("/boom", boom),
        ]
    )
    app.add_middleware(RequestIDMiddleware)
    return app


async def test_generates_uuid_when_header_missing() -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/echo")

    assert response.status_code == 200
    rid = response.headers[REQUEST_ID_HEADER]
    assert _UUID4_RE.match(rid), f"expected UUID4, got {rid!r}"
    # Body echoes the same value the contextvar held during the handler.
    assert response.json() == {"request_id": rid}


async def test_propagates_existing_header() -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/echo",
            headers={REQUEST_ID_HEADER: "client-trace-abc-123"},
        )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "client-trace-abc-123"
    assert response.json() == {"request_id": "client-trace-abc-123"}


async def test_request_id_var_resets_after_response() -> None:
    """Outside any request, the contextvar must read the default `-`.

    Without the `reset()` in the middleware's finally block, the value
    set during the request would bleed into whatever runs next on this
    task — a subtle cross-request leak.
    """
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/echo")

    assert request_id_var.get() == "-"


async def test_concurrent_requests_get_distinct_ids() -> None:
    """Two simultaneous requests must each see their own UUID, never
    each other's. Validates `ContextVar` isolation across asyncio tasks."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            client.get("/echo"),
            client.get("/echo"),
            client.get("/echo"),
        )

    ids = [r.json()["request_id"] for r in responses]
    assert len(set(ids)) == 3, f"expected 3 distinct ids, got {ids}"
    for r, rid in zip(responses, ids, strict=True):
        assert r.headers[REQUEST_ID_HEADER] == rid


async def test_handler_exception_still_resets_var() -> None:
    """Even if the handler crashes, the contextvar must be reset so
    the next request sees a clean slate."""
    app = _build_app()
    # ServerErrorMiddleware is installed by Starlette by default, so
    # the unhandled RuntimeError becomes a 500 response instead of
    # bubbling out of the ASGI app.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(RuntimeError):
            await client.get("/boom")

    assert request_id_var.get() == "-"
