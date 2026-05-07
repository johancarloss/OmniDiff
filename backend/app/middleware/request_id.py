"""Per-request correlation ID middleware.

Generates (or accepts) an `X-Request-ID` header on each incoming
request and propagates it to:

    1. `request.state.request_id` — for handlers that want to read it
       explicitly (e.g. embed it in a response body or log message).
    2. The `request_id_var` ContextVar — for cross-cutting concerns
       (the JSON log formatter reads from here, so every log line in
       the handler's call stack carries the correlation ID without
       passing it through every function signature).
    3. The response's `X-Request-ID` header — so clients can correlate
       their logs with the server's.

`ContextVar` is the right primitive for this in async code:
`threading.local` would alias across coroutines (since one thread runs
many of them), but `ContextVar` is copied per-task by the asyncio
runtime, giving each request its own isolated slot.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Default "-" makes log lines emitted outside any request (startup,
# shutdown, background tasks) clearly distinguishable from request logs.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject `X-Request-ID` into the request/response lifecycle.

    If the client sends `X-Request-ID`, it is honored as-is (allows
    upstream proxies and CI runners to thread their own trace IDs
    through). Otherwise, a fresh UUID4 is generated.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            # Reset AFTER the handler runs so log lines emitted during
            # the request still see the right ID, but BEFORE this task
            # is reused by the event loop for unrelated work.
            request_id_var.reset(token)
