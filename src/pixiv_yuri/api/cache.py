"""Private conditional caching shared by minimized read models."""

from __future__ import annotations

import hashlib

from fastapi import Request, Response, status
from pydantic import BaseModel


def private_cached[ModelT: BaseModel](
    request: Request,
    response: Response,
    payload: ModelT,
    *,
    max_age: int,
) -> ModelT | Response:
    """Return a deterministic private ETag response without shared-cache exposure."""
    digest = hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()
    etag = f'"{digest}"'
    headers = {"Cache-Control": f"private, max-age={max_age}", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    response.headers.update(headers)
    return payload
