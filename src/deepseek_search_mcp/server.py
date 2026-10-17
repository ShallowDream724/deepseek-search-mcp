"""FastMCP server construction.

The server exposes exactly two tools: one for ``/v1/tools/search`` and one for
``/v1/tools/fetch``. Their MCP names come from ``config.json`` so they can be
renamed to avoid collisions with other tools in the same client.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator

import httpx
from fastmcp import FastMCP
from pydantic import Field

from . import __version__
from .auth import resolve_api_key
from .client import DeepSeekClient
from .config import AppConfig

logger = logging.getLogger(__name__)

SERVER_NAME = "Web Search"

INSTRUCTIONS = """\
This server provides live web search and page fetching.

- Use the search tool when an answer needs current information from the web.
  It returns ranked results with rank, score (0-3 relevance), title, url,
  snippet, summary, site, date and authority (0-4). Scores >= 1.5 are high
  quality; authority >= 3 is very authoritative. Set need_content=true only
  when full page text is required, because responses become much larger.
- Use the fetch tool to read a specific URL as Markdown when search snippets or
  summaries are not enough. It also works on URLs the user pasted directly.

Both tools always return JSON. Success is {"ok": true, ...}; failure is
{"ok": false, "error": {"status", "http_code", "message", "retryable"}}.
When "retryable" is true the same call may succeed if you try again; when it is
false, change the request or ask the user to fix the API key or balance instead.

An API key is supplied by the MCP client or the server environment; it is never
passed through tool arguments.
"""

SEARCH_TOOL_TITLE = "Web Search"
FETCH_TOOL_TITLE = "Web Fetch"

_SEARCH_DESCRIPTION = """\
Search the web and return ranked results.

Search operators are passed through inside `query`:
  site:github.com           restrict to one site (several: site:a OR site:b)
  -site:example.com         exclude a site
  -keyword                  exclude pages containing a keyword
  "exact phrase"            require an exact phrase
  -"exact phrase"           exclude an exact phrase
  lang:zh,en                restrict by language
  after:2025, before:2026   restrict by publish date (year or YYYY-MM-DD)
"""

_FETCH_DESCRIPTION = """\
Fetch one web page and return its main content as Markdown. Use this when search
snippets or summaries are not enough, or when the user pasted a URL that should
be read.
"""

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
    )

    if config.tools.search.enabled:

        @mcp.tool(
            name=config.tools.search.name,
            description=_SEARCH_DESCRIPTION,
            annotations={
                "title": SEARCH_TOOL_TITLE,
                "readOnlyHint": True,
                "openWorldHint": True,
            },
        )
        async def web_search(
            query: Annotated[
                str,
                Field(
                    description=(
                        "Search query, 1-128 characters. Supports search operators "
                        "such as site:, -site:, lang:, after:, before:, \"exact phrase\" "
                        "and -keyword."
                    )
                ),
            ],
            count: Annotated[
                int | None,
                Field(
                    description="Number of results to return, 1-50. Defaults to the server setting.",
                    ge=1,
                    le=50,
                ),
            ] = None,
            ori_question: Annotated[
                str | None,
                Field(
                    description=(
                        "Optional original user question (up to 128 characters) that helps "
                        "the search engine understand the intent behind the query."
                    )
                ),
            ] = None,
            need_content: Annotated[
                bool,
                Field(
                    description=(
                        "When true, include the extracted page body in every result. "
                        "Off by default because it makes responses much larger."
                    )
                ),
            ] = False,
        ) -> dict[str, Any]:
            """Search the web and return ranked results as JSON."""
            return await client.search(
                api_key=resolve_api_key(),
                query=query,
                count=count,
                ori_question=ori_question,
                need_content=need_content,
            )

    if config.tools.fetch.enabled:

        @mcp.tool(
            name=config.tools.fetch.name,
            description=_FETCH_DESCRIPTION,
            annotations={
                "title": FETCH_TOOL_TITLE,
                "readOnlyHint": True,
                "openWorldHint": True,
            },
        )
        async def web_fetch(
            url: Annotated[
                str,
                Field(
                    description=(
                        "Absolute http(s) URL to fetch, up to 8192 characters. "
                        "Must not contain a username or password."
                    )
                ),
            ],
            max_chars: Annotated[
                int | None,
                Field(
                    description=(
                        "Maximum characters of Markdown to return. Defaults to the server "
                        "setting; 0 means no truncation."
                    ),
                    ge=0,
                ),
            ] = None,
        ) -> dict[str, Any]:
            """Fetch one web page and return its Markdown body as JSON."""
            return await client.fetch(
                api_key=resolve_api_key(),
                url=url,
                max_chars=max_chars,
            )

    logger.debug(
        "server built with tools: search=%s(%s) fetch=%s(%s)",
        config.tools.search.name,
        "on" if config.tools.search.enabled else "off",
        config.tools.fetch.name,
        "on" if config.tools.fetch.enabled else "off",
    )
    return mcp
