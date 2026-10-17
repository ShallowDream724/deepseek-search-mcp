"""Async client for the DeepSeek Web Search & Fetch APIs.

The client owns one ``httpx.AsyncClient`` (created by :func:`build_server` and
closed by the server lifespan) and implements:

* request validation that fails locally instead of spending a billed API call;
* bounded retries for transient upstream failures (408/429/5xx and network errors)
  with exponential backoff that honours ``Retry-After``;
* conversion of every failure mode into the structured ``{ok: false}`` envelope;
* secret redaction so a key can never leak into a tool result.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from . import __version__
from .auth import redact
from .config import AppConfig
from .models import ErrorStatus, UpstreamFetch, UpstreamSearchHit, error_response, missing_api_key_error

logger = logging.getLogger(__name__)

SEARCH_PATH = "v1/tools/search"
FETCH_PATH = "v1/tools/fetch"

MAX_QUERY_CHARS = 128
MAX_ORI_QUESTION_CHARS = 128
MAX_URL_CHARS = 8192

RETRYABLE_STATUS_CODES = frozenset({408, 429, *range(500, 600)})
BASE_BACKOFF_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 10.0

STATUS_BY_CODE: dict[int, ErrorStatus] = {
    400: "invalid_request",
    401: "unauthorized",
    402: "insufficient_balance",
    403: "forbidden",
    404: "not_found",
    408: "upstream_timeout",
    413: "payload_too_large",
    429: "rate_limited",
    504: "upstream_timeout",
}

STATUS_HINTS: dict[ErrorStatus, str] = {
    "unauthorized": (
        "The API key is missing or invalid. Send it as "
        "'Authorization: Bearer <key>' with HTTP transports, "
        "or set the API key environment variable for stdio."
    ),
    "insufficient_balance": "The account has no remaining balance; top up and retry.",
    "forbidden": "The security policy rejected this Fetch request; try another URL.",
    "not_found": "No usable page content could be retrieved for this URL.",
    "rate_limited": (
        "The service limits Search and Fetch to 5 QPS per account; wait a moment and retry."
    ),
    "upstream_timeout": "The request timed out upstream; retry shortly.",
    "payload_too_large": "The request body exceeded the service size limit.",
    "server_error": "The service reported an internal error; retry shortly.",
}


def _status_for_code(code: int) -> ErrorStatus:
    if code in STATUS_BY_CODE:
        return STATUS_BY_CODE[code]
    return "server_error" if code >= 500 else "invalid_request"


def _upstream_error_message(response: httpx.Response, api_key: str) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return redact(text, api_key)[:300] if text else None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return redact(message.strip(), api_key)[:500]
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return redact(message.strip(), api_key)[:500]
    return None


def _compose_message(status: ErrorStatus, upstream: str | None, code: int) -> str:
    base = upstream or f"The service returned HTTP {code}."
    if not base.endswith((".", "!", "?")):
        base = f"{base}."
    hint = STATUS_HINTS.get(status)
    return f"{base} {hint}" if hint else base


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    try:
        seconds = float(raw)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())


def _backoff_seconds(attempt: int) -> float:
    return BASE_BACKOFF_SECONDS * (2**attempt)


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _search_problem(query: object, count: object, ori_question: object, need_content: object) -> str | None:
    if not isinstance(query, str) or not query.strip():
        return "query must be a non-empty string."
    if len(query) > MAX_QUERY_CHARS:
        return f"query must be at most {MAX_QUERY_CHARS} characters."
    if isinstance(count, bool) or not isinstance(count, int):
        return "count must be an integer between 1 and 50."
    if not 1 <= count <= 50:
        return "count must be between 1 and 50."
    if ori_question is not None:
        if not isinstance(ori_question, str) or not ori_question.strip():
            return "ori_question must be a non-empty string when provided."
        if len(ori_question) > MAX_ORI_QUESTION_CHARS:
            return f"ori_question must be at most {MAX_ORI_QUESTION_CHARS} characters."
    if not isinstance(need_content, bool):
        return "need_content must be a boolean."
    return None


def _url_problem(url: object) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return "url must be a non-empty string."
    value = url.strip()
    if len(url) > MAX_URL_CHARS:
        return f"url must be at most {MAX_URL_CHARS} characters."
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError:
        return "url must be a valid absolute HTTP(S) URL."
    if parts.scheme not in {"http", "https"}:
        return "url must use the http or https scheme."
    if not parts.hostname:
        return "url must include a host."
    if parts.username is not None or parts.password is not None:
        return "url must not contain a username or password."
    if any(char.isspace() or ord(char) < 32 for char in value):
        return "url must not contain whitespace or control characters."
    return None


def _map_search_hit(
    rank: int,
    item: object,
    *,
    need_content: bool,
    max_chars: int,
) -> dict[str, Any]:
    source = UpstreamSearchHit.model_validate(item)

    content: str | None = None
    truncated = False
    if need_content and source.content:
        content, truncated = _truncate(source.content, max_chars)

    return {
        **source.model_dump(exclude={"content"}),
        "rank": rank,
        "content": content,
        "truncated": truncated,
    }


class DeepSeekClient:
    """Thin async wrapper around ``POST /v1/tools/search`` and ``/v1/tools/fetch``."""

    def __init__(
        self,
        config: AppConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._http = httpx.AsyncClient(
            base_url=config.api.base_url,
            timeout=config.api.timeout_seconds,
            transport=transport,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": f"deepseek-search-mcp/{__version__}",
            },
        )
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "DeepSeekClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ search

    async def search(
        self,
        *,
        api_key: str | None,
        query: object,
        count: object = None,
        ori_question: object = None,
        need_content: object = False,
    ) -> dict[str, Any]:
        if api_key is None:
            return missing_api_key_error()

        resolved_count: Any = self.config.search.default_count if count is None else count
        problem = _search_problem(query, resolved_count, ori_question, need_content)
        if problem is not None:
            return error_response("invalid_request", problem)

        cleaned_query = str(query).strip()
        payload: dict[str, Any] = {
            "query": cleaned_query,
            "count": resolved_count,
            "need_content": need_content,
        }
        if isinstance(ori_question, str) and ori_question.strip():
            payload["ori_question"] = ori_question.strip()
        if self.config.search.localization:
            payload["localization"] = self.config.search.localization

        logger.debug("search request: count=%s need_content=%s", resolved_count, need_content)

        response, failure = await self._post(SEARCH_PATH, payload, api_key)
        if failure is not None:
            return failure

        body, failure = self._json_body(response)
        if failure is not None:
            return failure

        items = body.get("results")
        if not isinstance(items, list):
            return error_response(
                "invalid_response",
                "The search response did not contain a 'results' array.",
            )

        try:
            results = [
                _map_search_hit(index, item, need_content=need_content,
                                max_chars=self.config.search.max_content_chars)
                for index, item in enumerate(items, start=1)
            ]
        except ValidationError:
            return error_response("invalid_response", "The search response contained a malformed result.")

        return {
            "ok": True,
            "query": cleaned_query,
            "count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------- fetch

    async def fetch(
        self,
        *,
        api_key: str | None,
        url: object,
        max_chars: object = None,
    ) -> dict[str, Any]:
        if api_key is None:
            return missing_api_key_error()

        problem = _url_problem(url)
        if problem is not None:
            return error_response("invalid_request", problem)

        limit: Any = self.config.fetch.max_content_chars if max_chars is None else max_chars
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            return error_response("invalid_request", "max_chars must be an integer >= 0.")

        cleaned_url = str(url).strip()
        logger.debug("fetch request: max_chars=%s", limit)

        response, failure = await self._post(FETCH_PATH, {"url": cleaned_url}, api_key)
        if failure is not None:
            return failure

        body, failure = self._json_body(response)
        if failure is not None:
            return failure

        try:
            source = UpstreamFetch.model_validate(body)
        except ValidationError:
            return error_response("invalid_response", "The fetch response did not contain a valid title and non-empty content.")
        content, truncated = _truncate(source.content, limit)

        return {
            "ok": True,
            "url": cleaned_url,
            "title": source.title,
            "content": content,
            "truncated": truncated,
            "total_chars": len(source.content),
        }

    # ----------------------------------------------------------------- helpers

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        api_key: str,
    ) -> tuple[httpx.Response | None, dict[str, Any] | None]:
        """POST with bounded retries; returns ``(response, None)`` or ``(None, error)``."""
        headers = {"Authorization": f"Bearer {api_key}"}
        attempts = self.config.api.max_retries + 1
        last_failure: dict[str, Any] | None = None

        for attempt in range(attempts):
            retry_after: float | None = None
            try:
                response = await self._http.post(path, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                last_failure = error_response(
                    "upstream_timeout",
                    redact(f"Request timed out: {exc}", api_key),
                    retryable=True,
                )
            except httpx.HTTPError as exc:
                last_failure = error_response(
                    "network_error",
                    redact(f"Could not reach the search service: {exc}", api_key),
                    retryable=True,
                )
            else:
                if response.status_code == 200:
                    return response, None

                failure = self._failure_from_response(response, api_key)
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    return None, failure
                last_failure = failure
                retry_after = _retry_after_seconds(response)

            if attempt + 1 >= attempts:
                break
            delay = retry_after if retry_after is not None else _backoff_seconds(attempt)
            if delay > MAX_BACKOFF_SECONDS:
                # Do not retry earlier than allowed, or hold a tool call for hours.
                break
            logger.debug("retrying %s after %.2fs (attempt %s)", path, delay, attempt + 1)
            await self._sleep(delay)

        return None, last_failure

    def _failure_from_response(self, response: httpx.Response, api_key: str) -> dict[str, Any]:
        status = _status_for_code(response.status_code)
        message = _compose_message(
            status,
            _upstream_error_message(response, api_key),
            response.status_code,
        )
        return error_response(
            status,
            message,
            http_code=response.status_code,
            retryable=response.status_code in RETRYABLE_STATUS_CODES,
            retry_after_seconds=_retry_after_seconds(response),
        )

    def _json_body(
        self,
        response: httpx.Response,
    ) -> tuple[dict[str, Any], None] | tuple[None, dict[str, Any]]:
        try:
            payload = response.json()
        except ValueError:
            return None, error_response(
                "invalid_response",
                "The service returned a response that is not valid JSON.",
            )
        if not isinstance(payload, dict):
            return None, error_response(
                "invalid_response",
                "The service returned an unexpected response shape.",
            )
        return payload, None
