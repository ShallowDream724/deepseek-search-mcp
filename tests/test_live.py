"""Live end-to-end tests against the real DeepSeek API.

These are opt-in: ``pytest -m live``. They read ``DEEPSEEK_API_KEY`` first and
fall back to ``.temp/test-key.txt``. Each search/fetch call is billed at
0.005 CNY per 1000 requests, so the suite deliberately makes very few calls.
"""

from __future__ import annotations

import re
import os
from pathlib import Path

import pytest

from deepseek_search_mcp.client import DeepSeekClient
from deepseek_search_mcp.config import AppConfig

pytestmark = pytest.mark.live

KEY_FILE = Path(__file__).resolve().parents[1] / ".temp" / "test-key.txt"

KEY_TOKEN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def _extract(text: str) -> str | None:
    match = KEY_TOKEN.search(text)
    return match.group(0) if match else None


def _load_key() -> str | None:
    env_key = _extract(os.environ.get("DEEPSEEK_API_KEY", ""))
    if env_key:
        return env_key
    if KEY_FILE.is_file():
        return _extract(KEY_FILE.read_text(encoding="utf-8"))
    return None


@pytest.fixture(scope="module")
def api_key() -> str:
    key = _load_key()
    if not key:
        pytest.skip("no DEEPSEEK_API_KEY and no .temp/test-key.txt")
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
    if result["results"]:
        assert result["results"][0]["content"]


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
