"""Validated upstream payloads and the public MCP result contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class UpstreamSearchHit(BaseModel):
    """Keep documented fields; tolerate new upstream fields, not malformed values."""

    model_config = ConfigDict(strict=True, extra="ignore", allow_inf_nan=False)

    rerank_score: float
    title: str
    url: str = Field(min_length=1, pattern=r"\S")
    snippet: str
    summary: str
    content: str = ""
    site_name: str | None = None
    site_icon: str | None = None
    date: str | None = None
    authority: int


class UpstreamFetch(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    title: str
    content: str = Field(min_length=1, pattern=r"\S")


class ResultModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class SearchHit(ResultModel):
    rank: int = Field(ge=1)
    rerank_score: float = Field(description="Relevance score reported by DeepSeek (0–3).")
    title: str
    url: str
    snippet: str
    summary: str
    site_name: str | None
    site_icon: str | None
    date: str | None
    authority: int = Field(description="Source authority reported by DeepSeek (0–4; -1 unknown).")
    content: str | None = Field(description="Page text if requested and available; otherwise null.")
    truncated: bool = Field(description="Whether content was cut at the character limit.")


class SearchResponse(ResultModel):
    ok: Literal[True]
    query: str
    count: int = Field(ge=0, description="Number of results returned.")
    results: list[SearchHit]


class FetchResponse(ResultModel):
    ok: Literal[True]
    url: str
    title: str
    content: str
    truncated: bool
    total_chars: int = Field(ge=1, description="Content length before truncation.")


def error_response(
    status: ErrorStatus,
    message: str,
    *,
    http_code: int | None = None,
    retryable: bool = False,
    retry_after_seconds: float | None = None,
) -> dict[str, Any]:
    """Build the structured error envelope used by every failure path."""
    error: dict[str, Any] = {
        "status": status,
        "http_code": http_code,
        "message": message,
        "retryable": retryable,
    }
    if retry_after_seconds is not None:
        error["retry_after_seconds"] = retry_after_seconds
    return {"ok": False, "error": error}


MISSING_API_KEY_MESSAGE = (
    "No API key provided. Set DEEPSEEK_API_KEY in the server environment, "
    "or send Authorization: Bearer <key> with HTTP requests."
)


def missing_api_key_error() -> dict[str, Any]:
    return error_response("missing_api_key", MISSING_API_KEY_MESSAGE)
