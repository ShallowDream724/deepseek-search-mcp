"""Live end-to-end tests against the real DeepSeek API.

Opt in with ``pytest -m live`` and DEEPSEEK_API_KEY. Makes three successful
API calls (billed by DeepSeek) and one invalid-key request. Never reads key files.
"""

from __future__ import annotations

import os

import pytest

from deepseek_search_mcp.client import DeepSeekClient
from deepseek_search_mcp.config import AppConfig

pytestmark = pytest.mark.live

@pytest.fixture(scope="module")
def api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        pytest.skip("no DEEPSEEK_API_KEY")
    return key


async def test_live_search_returns_results(api_key: str) -> None:
    async with DeepSeekClient(AppConfig()) as client:
        result = await client.search(api_key=api_key, query="DeepSeek 官方文档", count=2)

    assert result["ok"] is True, result
    assert 1 <= len(result["results"]) <= 2
    first = result["results"][0]
    assert first["rank"] == 1
    assert first["url"].startswith("http")
    assert first["title"]


async def test_live_search_with_content(api_key: str) -> None:
    async with DeepSeekClient(AppConfig()) as client:
        result = await client.search(
            api_key=api_key,
            query="DeepSeek search API",
            count=1,
            need_content=True,
        )

    assert result["ok"] is True, result
    for hit in result["results"]:
        assert hit["content"] is None or isinstance(hit["content"], str)
        assert isinstance(hit["truncated"], bool)


async def test_live_fetch_returns_markdown(api_key: str) -> None:
    async with DeepSeekClient(AppConfig()) as client:
        result = await client.fetch(api_key=api_key, url="https://example.com")

    assert result["ok"] is True, result
    assert result["content"]


async def test_live_invalid_key_is_reported_without_leaking_it() -> None:
    bogus = "sk-this-key-is-not-real-000000000000"
    async with DeepSeekClient(AppConfig()) as client:
        result = await client.search(api_key=bogus, query="anything", count=1)

    assert result["ok"] is False
    assert result["error"]["status"] == "unauthorized"
    assert result["error"]["http_code"] == 401
    assert bogus not in result["error"]["message"]
