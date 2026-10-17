"""Typed result envelopes returned by the MCP tools.

Every tool returns a plain ``dict`` so that FastMCP can expose it both as JSON
text and as ``structuredContent``. These ``TypedDict`` definitions are used for
static typing only: nothing is validated at runtime, so an unexpected upstream
payload can never turn a successful search into an exception.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

ErrorStatus = Literal[
    "missing_api_key",
    "invalid_request",
    "unauthorized",
    "insufficient_balance",
    "forbidden",
    "not_found",
    "upstream_timeout",
    "payload_too_large",
    "rate_limited",
    "server_error",
    "network_error",
    "invalid_response",
]


class ErrorInfo(TypedDict):
    status: ErrorStatus
    http_code: int | None
    message: str
    retryable: bool


class ErrorResponse(TypedDict):
    ok: Literal[False]
    error: ErrorInfo


class SearchHit(TypedDict):
    rank: int
    score: float | None
    title: str
    url: str
    snippet: str
    summary: str
    site: str | None
    date: str | None
    authority: int | None
    content: str | None
    truncated: bool


class SearchResponse(TypedDict):
    ok: Literal[True]
    query: str
    count: int
    results: list[SearchHit]


class FetchResponse(TypedDict):
    ok: Literal[True]
    url: str
    title: str
    content: str
    truncated: bool


def error_response(
    status: ErrorStatus,
    message: str,
    *,
    http_code: int | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """Build the structured error envelope used by every failure path."""
    return {
        "ok": False,
        "error": {
            "status": status,
            "http_code": http_code,
            "message": message,
            "retryable": retryable,
        },
    }


MISSING_API_KEY_MESSAGE = (
    "No API key provided. On HTTP transports send "
    "'Authorization: Bearer <key>' with the request; when running over stdio, set the "
    "server's API key environment variable."
)


def missing_api_key_error() -> dict[str, Any]:
    return error_response("missing_api_key", MISSING_API_KEY_MESSAGE)
