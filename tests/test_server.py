"""Tests for MCP server construction: tool names, schemas, and tool calls."""

from __future__ import annotations

import httpx
import pytest
from fastmcp import Client

from deepseek_search_mcp.auth import API_KEY_ENV
from deepseek_search_mcp.config import AppConfig
from deepseek_search_mcp.server import build_server

from .conftest import item, search_ok

API_KEY = "sk-test-key-do-not-leak-0123456789"


def config_with(**overrides: object) -> AppConfig:
    payload: dict = {}
    for dotted, value in overrides.items():
        section, _, field = dotted.partition("__")
        payload.setdefault(section, {})[field] = value
    return AppConfig.model_validate(payload)


async def list_tools(config: AppConfig, *scripted: httpx.Response):
    mcp = build_server(config, transport=httpx.MockTransport(_handler(scripted)))
    async with Client(mcp) as client:
        return await client.list_tools()


def _handler(scripted: tuple[httpx.Response, ...]):
    queue = list(scripted)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            raise AssertionError(f"unexpected request to {request.url}")
        return queue.pop(0)

    return handler


async def test_default_tool_names() -> None:
    tools = await list_tools(AppConfig())
    assert [tool.name for tool in tools] == ["search", "fetch"]


async def test_tools_can_be_renamed_via_config() -> None:
    config = config_with(
        tools__search={"name": "ds_search", "enabled": True},
        tools__fetch={"name": "ds_fetch", "enabled": True},
    )

    tools = await list_tools(config)

    assert [tool.name for tool in tools] == ["ds_search", "ds_fetch"]


async def test_disabled_tool_is_not_registered() -> None:
    config = config_with(tools__fetch={"name": "fetch", "enabled": False})

    tools = await list_tools(config)

    assert [tool.name for tool in tools] == ["search"]


async def test_both_tools_can_be_disabled() -> None:
    config = config_with(
        tools__search={"enabled": False},
        tools__fetch={"enabled": False},
    )

    assert await list_tools(config) == []


async def test_search_schema_exposes_curated_parameters() -> None:
    tools = await list_tools(AppConfig())
    search = next(tool for tool in tools if tool.name == "search")
    schema = search.input_schema
    properties = schema["properties"]

    assert list(properties) == ["query", "count", "ori_question", "need_content"]
    assert "localization" not in properties
    assert schema["required"] == ["query"]
    count_branches = properties["count"]["anyOf"]
    integer_branch = next(branch for branch in count_branches if branch.get("type") == "integer")
    assert integer_branch["minimum"] == 1
    assert integer_branch["maximum"] == 50
    assert "site:" in search.description


async def test_fetch_schema_exposes_url_and_max_chars() -> None:
    tools = await list_tools(AppConfig())
    fetch = next(tool for tool in tools if tool.name == "fetch")

    assert list(fetch.input_schema["properties"]) == ["url", "max_chars"]
    assert fetch.input_schema["required"] == ["url"]


async def test_tools_are_marked_read_only() -> None:
    tools = await list_tools(AppConfig())

    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True


async def test_search_tool_returns_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    mcp = build_server(AppConfig(), transport=httpx.MockTransport(_handler((search_ok(item()),))))

    async with Client(mcp) as client:
        result = await client.call_tool("search", {"query": "DeepSeek V4"})

    assert result.is_error is False
    assert result.structured_content["ok"] is True
    assert result.structured_content["results"][0]["url"] == "https://example.com/a"


async def test_fetch_tool_returns_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    body = httpx.Response(200, json={"title": "Example", "content": "# Body"})
    mcp = build_server(AppConfig(), transport=httpx.MockTransport(_handler((body,))))

    async with Client(mcp) as client:
        result = await client.call_tool("fetch", {"url": "https://example.com/a"})

    assert result.structured_content == {
        "ok": True,
        "url": "https://example.com/a",
        "title": "Example",
        "content": "# Body",
        "truncated": False,
        "total_chars": 6,
    }


async def test_tool_without_api_key_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    mcp = build_server(AppConfig(), transport=httpx.MockTransport(_handler(())))

    async with Client(mcp) as client:
        result = await client.call_tool("search", {"query": "q"}, raise_on_error=False)

    assert result.is_error is True
    assert result.structured_content["ok"] is False
    assert result.structured_content["error"]["status"] == "missing_api_key"


async def test_tool_validation_error_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    mcp = build_server(AppConfig(), transport=httpx.MockTransport(_handler(())))

    async with Client(mcp) as client:
        result = await client.call_tool("search", {"query": "   "}, raise_on_error=False)

    assert result.structured_content["error"]["status"] == "invalid_request"
    assert result.is_error is True


@pytest.mark.parametrize("tool,arguments", [
    ("search", {"query": "x" * 129}),
    ("search", {"query": "q", "count": True}),
    ("search", {"query": "q", "count": 1.5}),
    ("search", {"query": "q", "need_content": "false"}),
    ("search", {"query": "q", "ori_question": ""}),
    ("search", {"query": "q", "unexpected": "value"}),
    ("fetch", {"url": "http://["}),
    ("fetch", {"url": "https://example.com", "max_chars": True}),
])
async def test_invalid_arguments_never_reach_upstream(tool, arguments, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    mcp = build_server(AppConfig(), transport=httpx.MockTransport(_handler(())))
    async with Client(mcp) as client:
        result = await client.call_tool(tool, arguments, raise_on_error=False)
    assert result.is_error is True
    assert result.structured_content["error"]["status"] == "invalid_request"


async def test_empty_search_is_a_success(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    mcp = build_server(AppConfig(), transport=httpx.MockTransport(_handler((search_ok(),))))
    async with Client(mcp) as client:
        result = await client.call_tool("search", {"query": "q"})
    assert result.is_error is False
    assert result.structured_content["count"] == 0


@pytest.mark.parametrize("response,status", [
    (httpx.Response(429), "rate_limited"),
    (httpx.Response(504), "upstream_timeout"),
    (httpx.Response(200, json={"results": [None]}), "invalid_response"),
])
async def test_upstream_errors_reach_mcp_error_flag(response, status, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, API_KEY)
    mcp = build_server(config_with(api__max_retries=0), transport=httpx.MockTransport(_handler((response,))))
    async with Client(mcp) as client:
        result = await client.call_tool("search", {"query": "q"}, raise_on_error=False)
    assert result.is_error is True
    assert result.structured_content["error"]["status"] == status


async def test_server_instructions_are_exposed() -> None:
    mcp = build_server(AppConfig(), transport=httpx.MockTransport(_handler(())))

    async with Client(mcp) as client:
        instructions = client.instructions
        server_name = client.server_info.name

    assert server_name == "DeepSeek Web Search"
    assert "retryable" in (instructions or "")


async def test_discovery_has_output_schemas_and_compact_instructions() -> None:
    mcp = build_server(AppConfig(), transport=httpx.MockTransport(_handler(())))

    async with Client(mcp) as client:
        tools = await client.list_tools()
        instructions = client.instructions or ""
        server_name = client.server_info.name

    visible: list[str] = [server_name, instructions]
    for tool in tools:
        visible.extend(
            [
                tool.name,
                tool.title or "",
                tool.description or "",
                *(
                    str(prop.get("description", ""))
                    for prop in tool.input_schema.get("properties", {}).values()
                ),
            ]
        )

    assert len(instructions) <= 512
    assert all(tool.output_schema["properties"]["ok"]["const"] is True for tool in tools)
    assert API_KEY not in "\n".join(visible)
