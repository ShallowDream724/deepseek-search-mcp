"""Shared fixtures: a scripted fake DeepSeek upstream."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx

from deepseek_search_mcp.client import DeepSeekClient
from deepseek_search_mcp.config import AppConfig


class Upstream:
    """Scripted HTTP transport that records requests and replays responses."""

    def __init__(self, scripted: Iterable[httpx.Response | Exception] = ()) -> None:
        self._scripted = list(scripted)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._scripted:
            raise AssertionError(f"unexpected request to {request.url}")
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class Harness:
    client: DeepSeekClient
    upstream: Upstream
    sleeps: list[float] = field(default_factory=list)


@asynccontextmanager
async def harness(
    config: AppConfig | None = None,
    *scripted: httpx.Response | Exception,
) -> AsyncIterator[Harness]:
    upstream = Upstream(scripted)
    client = DeepSeekClient(config or AppConfig(), transport=httpx.MockTransport(upstream.handler))
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client._sleep = fake_sleep
    try:
        yield Harness(client=client, upstream=upstream, sleeps=sleeps)
    finally:
        await client.aclose()


def search_ok(*items: dict) -> httpx.Response:
    return httpx.Response(200, json={"results": list(items)})


def item(**overrides: object) -> dict:
    base = {
        "rerank_score": 2.4,
        "title": "DeepSeek V4 released",
        "url": "https://example.com/a",
        "snippet": "short snippet",
        "summary": "long summary",
        "content": "full page body",
        "site_name": "Example News",
        "site_icon": "https://example.com/favicon.ico",
        "date": "2026-06-01T00:00:00+00:00",
        "authority": 3,
    }
    base.update(overrides)
    return base
