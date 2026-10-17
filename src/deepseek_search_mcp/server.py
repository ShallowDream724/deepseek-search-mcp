"""FastMCP server construction.

The server exposes exactly two tools: one for ``/v1/tools/search`` and one for
``/v1/tools/fetch``. Their MCP names come from ``config.json`` so they can be
renamed to avoid collisions with other tools in the same client.
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ValidationError as ToolValidationError
from fastmcp.server.middleware import Middleware, MiddlewareContext, CallNext
from fastmcp.tools import ToolResult
from pydantic import Field, StrictBool, StrictInt, ValidationError

from . import __version__
from .auth import resolve_api_key
from .client import DeepSeekClient
from .config import AppConfig
from .models import FetchResponse, SearchResponse, error_response

logger = logging.getLogger(__name__)

SERVER_NAME = "DeepSeek Web Search"

INSTRUCTIONS = (
    "Search returns ranked web sources and summaries. Fetch reads a URL as Markdown. "
    "If content is truncated, fetch the URL with a larger max_chars value or 0 for full text. "
    "Tool failures set isError and include error.status, message and retryable. "
    "An empty search result is a successful response with count=0."
)

SEARCH_TOOL_TITLE = "Web Search"
FETCH_TOOL_TITLE = "Web Fetch"

_SEARCH_DESCRIPTION = (
    "Search the web with DeepSeek. Returns ranked URLs, titles, snippets, summaries "
    "and source metadata. Use for current information or finding sources. "
    "query supports site:domain, -site:domain, -keyword, \"exact phrase\", "
    "-\"excluded phrase\", lang:zh,en, after:YYYY-MM-DD and before:YYYY-MM-DD "
    "(dates also accept a year). Combine sites with OR."
)

_FETCH_DESCRIPTION = (
    "Read a web page through DeepSeek and return its title and main content as Markdown. "
    "Use to read a supplied URL or examine a search result beyond its summary. "
    "Returns truncated and total_chars to indicate omitted content."
)


def _tool_result(payload: dict[str, Any], schema: type[SearchResponse] | type[FetchResponse]) -> ToolResult:
    if payload["ok"]:
        payload = schema.model_validate(payload).model_dump()
    return ToolResult(structured_content=payload, is_error=not payload["ok"])


class InputErrors(Middleware):
    """Give schema validation failures the same envelope without echoing input values."""

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> ToolResult:
        try:
            return await call_next(context)
        except ToolValidationError as exc:
            cause = exc.__cause__
            message = "Arguments do not match the tool input schema."
            if isinstance(cause, ValidationError):
                details = cause.errors(include_input=False, include_url=False)
                message = "; ".join(
                    f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                    for error in details
                )
            return ToolResult(
                structured_content=error_response("invalid_request", message), is_error=True
            )

def build_server(
    config: AppConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastMCP:
    """Create the FastMCP server for a validated config.

    ``transport`` is injectable so tests can script upstream HTTP responses.
    """
    client = DeepSeekClient(config, transport=transport)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {}
        finally:
            await client.aclose()

    mcp = FastMCP(
        name=SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        lifespan=lifespan,
        middleware=[InputErrors()],
        strict_input_validation=True,
        mask_error_details=True,
    )

    if config.tools.search.enabled:

        @mcp.tool(
            name=config.tools.search.name,
            description=_SEARCH_DESCRIPTION,
            output_schema=SearchResponse.model_json_schema(),
            annotations={
                "title": SEARCH_TOOL_TITLE,
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": True,
            },
        )
        async def search(
            query: Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=128,
                    pattern=r"\S",
                    description=(
                        "Search query, 1-128 characters. Supports search operators "
                        "such as site:, -site:, lang:, after:, before:, \"exact phrase\" "
                        "and -keyword."
                    )
                ),
            ],
            count: Annotated[
                StrictInt | None,
                Field(
                    description=f"Maximum results, 1-50. Omit or use null for {config.search.default_count}.",
                    ge=1,
                    le=50,
                ),
            ] = None,
            ori_question: Annotated[
                str | None,
                Field(
                    min_length=1,
                    max_length=128,
                    pattern=r"\S",
                    description=(
                        "Optional original user question (up to 128 characters) that helps "
                        "the search engine understand the intent behind the query."
                    )
                ),
            ] = None,
            need_content: Annotated[
                StrictBool,
                Field(
                    description=(
                        "Include available page text in each result. Default false. "
                        f"Text is limited to {config.search.max_content_chars} characters per result "
                        "(0 means unlimited); truncated marks shortened text."
                    )
                ),
            ] = False,
        ) -> ToolResult:
            """Search the web and return ranked results as JSON."""
            payload = await client.search(
                api_key=resolve_api_key(),
                query=query,
                count=count,
                ori_question=ori_question,
                need_content=need_content,
            )
            return _tool_result(payload, SearchResponse)

    if config.tools.fetch.enabled:

        @mcp.tool(
            name=config.tools.fetch.name,
            description=_FETCH_DESCRIPTION,
            output_schema=FetchResponse.model_json_schema(),
            annotations={
                "title": FETCH_TOOL_TITLE,
                "readOnlyHint": True,
                "destructiveHint": False,
                "openWorldHint": True,
            },
        )
        async def fetch(
            url: Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=8192,
                    pattern=r"\S",
                    description=(
                        "Absolute http(s) URL to fetch, up to 8192 characters. "
                        "Must not contain a username or password."
                    )
                ),
            ],
            max_chars: Annotated[
                StrictInt | None,
                Field(
                    description=(
                        "Maximum characters of Markdown to return. "
                        f"Omit or use null for {config.fetch.max_content_chars}; 0 returns full text."
                    ),
                    ge=0,
                ),
            ] = None,
        ) -> ToolResult:
            """Fetch one web page and return its Markdown body as JSON."""
            payload = await client.fetch(
                api_key=resolve_api_key(),
                url=url,
                max_chars=max_chars,
            )
            return _tool_result(payload, FetchResponse)

    logger.debug(
        "server built with tools: search=%s(%s) fetch=%s(%s)",
        config.tools.search.name,
        "on" if config.tools.search.enabled else "off",
        config.tools.fetch.name,
        "on" if config.tools.fetch.enabled else "off",
    )
    return mcp
