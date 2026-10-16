"""Weak conditional validators include freshness, excluding response-generation time."""

from hashlib import sha256
import json

from fastapi import Request, Response

from app.api_models import Envelope

POLL_INTERVAL_SECONDS = 60


def conditional_response(request: Request, response: Response, body):
    if not isinstance(body, Envelope):
        return body  # Let FastAPI's declared response model reject malformed output.
    representation = body.model_dump(mode="json")
    representation["meta"].pop("generated_at")
    representation["meta"].pop("version")
    digest = "sha256:" + sha256(json.dumps(representation, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    tag = f'W/"{digest}"'
    headers = {"ETag": tag, "X-Poll-Interval": str(POLL_INTERVAL_SECONDS), "Cache-Control": "no-store", "Vary": "Authorization"}
    supplied = request.headers.get("if-none-match", "")
    # GET If-None-Match uses weak comparison; authenticate/read/validate first.
    if len(supplied) <= 8192 and any(token.strip() == "*" or token.strip().removeprefix("W/") == tag.removeprefix("W/") for token in supplied.split(",")):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return body.model_copy(update={"meta": body.meta.model_copy(update={"version": digest})})
