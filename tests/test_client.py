"""Tests for the DeepSeek HTTP client: payloads, truncation, retries, errors."""

from __future__ import annotations

import asyncio
import json
from time import monotonic

import httpx
import pytest

from deepseek_search_mcp.client import DeepSeekClient
from deepseek_search_mcp.config import AppConfig
from deepseek_search_mcp.models import MISSING_API_KEY_MESSAGE

from .conftest import harness, item, search_ok

API_KEY = "sk-test-key-do-not-leak-0123456789"


def config_with(**overrides: object) -> AppConfig:
    payload: dict = {}
    for dotted, value in overrides.items():
        section, _, field = dotted.partition("__")
        payload.setdefault(section, {})[field] = value
    return AppConfig.model_validate(payload)


# --------------------------------------------------------------------- payload


async def test_search_sends_documented_payload() -> None:
    async with harness(AppConfig(), search_ok(item())) as h:
        await h.client.search(api_key=API_KEY, query="DeepSeek V4", need_content=True)

    request = h.upstream.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.deepseek.com/v1/tools/search"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["user-agent"].startswith("deepseek-search-mcp/")
    assert json.loads(request.content) == {
        "query": "DeepSeek V4",
        "count": 10,
        "need_content": True,
    }


async def test_search_uses_default_count_from_config() -> None:
    config = config_with(search__default_count=3)
    async with harness(config, search_ok()) as h:
        await h.client.search(api_key=API_KEY, query="q")

    assert json.loads(h.upstream.requests[0].content)["count"] == 3


async def test_search_count_argument_overrides_default() -> None:
    async with harness(AppConfig(), search_ok()) as h:
        await h.client.search(api_key=API_KEY, query="q", count=2)

    assert json.loads(h.upstream.requests[0].content)["count"] == 2


async def test_search_includes_ori_question_when_provided() -> None:
    async with harness(AppConfig(), search_ok()) as h:
        await h.client.search(api_key=API_KEY, query="q", ori_question="why is the sky blue")

    assert json.loads(h.upstream.requests[0].content)["ori_question"] == "why is the sky blue"


async def test_search_omits_null_ori_question() -> None:
    async with harness(AppConfig(), search_ok()) as h:
        await h.client.search(api_key=API_KEY, query="q", ori_question=None)

    assert "ori_question" not in json.loads(h.upstream.requests[0].content)


async def test_search_includes_localization_only_when_configured() -> None:
    async with harness(AppConfig(), search_ok()) as h:
        await h.client.search(api_key=API_KEY, query="q")
    assert "localization" not in json.loads(h.upstream.requests[0].content)

    config = config_with(search__localization="1.2.3.4")
    async with harness(config, search_ok()) as h:
        await h.client.search(api_key=API_KEY, query="q")
    assert json.loads(h.upstream.requests[0].content)["localization"] == "1.2.3.4"


async def test_base_url_prefix_is_preserved() -> None:
    config = config_with(api__base_url="https://gateway.example.com/deepseek")
    async with harness(config, search_ok()) as h:
        await h.client.search(api_key=API_KEY, query="q")

    assert str(h.upstream.requests[0].url) == (
        "https://gateway.example.com/deepseek/v1/tools/search"
    )


# ---------------------------------------------------------------------- mapping


async def test_search_preserves_documented_metadata() -> None:
    async with harness(AppConfig(), search_ok(item())) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert result["ok"] is True
    assert result["query"] == "q"
    assert result["count"] == 1
    hit = result["results"][0]
    assert hit == {
        "rank": 1,
        "rerank_score": 2.4,
        "title": "DeepSeek V4 released",
        "url": "https://example.com/a",
        "snippet": "short snippet",
        "summary": "long summary",
        "site_name": "Example News",
        "site_icon": "https://example.com/favicon.ico",
        "date": "2026-06-01T00:00:00+00:00",
        "authority": 3,
        "content": None,
        "truncated": False,
    }


async def test_search_ranks_results_in_order() -> None:
    async with harness(
        AppConfig(),
        search_ok(item(url="https://a.example"), item(url="https://b.example")),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert [hit["rank"] for hit in result["results"]] == [1, 2]
    assert [hit["url"] for hit in result["results"]] == [
        "https://a.example",
        "https://b.example",
    ]


async def test_search_returns_content_when_requested() -> None:
    async with harness(AppConfig(), search_ok(item(content="body text"))) as h:
        result = await h.client.search(api_key=API_KEY, query="q", need_content=True)

    assert result["results"][0]["content"] == "body text"
    assert result["results"][0]["truncated"] is False


async def test_search_truncates_content_at_config_limit() -> None:
    config = config_with(search__max_content_chars=5)
    async with harness(config, search_ok(item(content="0123456789"))) as h:
        result = await h.client.search(api_key=API_KEY, query="q", need_content=True)

    assert result["results"][0]["content"] == "01234"
    assert result["results"][0]["truncated"] is True


async def test_zero_content_limit_means_no_truncation() -> None:
    config = config_with(search__max_content_chars=0)
    async with harness(config, search_ok(item(content="x" * 100))) as h:
        result = await h.client.search(api_key=API_KEY, query="q", need_content=True)

    assert result["results"][0]["content"] == "x" * 100
    assert result["results"][0]["truncated"] is False


async def test_empty_content_becomes_null() -> None:
    async with harness(AppConfig(), search_ok(item(content=""))) as h:
        result = await h.client.search(api_key=API_KEY, query="q", need_content=True)

    assert result["results"][0]["content"] is None


async def test_malformed_hit_is_not_silently_discarded() -> None:
    async with harness(
        AppConfig(),
        search_ok(item(url=""), item(url="https://ok.example")),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert result["error"]["status"] == "invalid_response"


async def test_missing_optional_fields_degrade_to_null() -> None:
    async with harness(
        AppConfig(),
        search_ok({key: value for key, value in item().items() if key not in {"site_name", "site_icon", "date"}}),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    hit = result["results"][0]
    assert hit["site_name"] is None
    assert hit["site_icon"] is None
    assert hit["date"] is None


async def test_empty_result_list_is_ok() -> None:
    async with harness(AppConfig(), search_ok()) as h:
        result = await h.client.search(api_key=API_KEY, query="nothing matches")

    assert result == {"ok": True, "query": "nothing matches", "count": 0, "results": []}


# ----------------------------------------------------------------------- retry


async def test_retries_429_then_succeeds() -> None:
    async with harness(
        AppConfig(),
        httpx.Response(429, json={"error": {"message": "slow down"}}),
        search_ok(item()),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert result["ok"] is True
    assert len(h.upstream.requests) == 2
    assert h.sleeps == [0.5]


async def test_retry_uses_retry_after_header() -> None:
    async with harness(
        AppConfig(),
        httpx.Response(429, headers={"retry-after": "2"}),
        search_ok(item()),
    ) as h:
        await h.client.search(api_key=API_KEY, query="q")

    assert h.sleeps == [2.0]


async def test_long_retry_after_returns_without_retrying_early() -> None:
    async with harness(
        AppConfig(),
        httpx.Response(503, headers={"retry-after": "3600"}),
        search_ok(item()),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert h.sleeps == []
    assert len(h.upstream.requests) == 1
    assert result["error"]["retry_after_seconds"] == 3600


async def test_backoff_doubles_and_respects_max_retries() -> None:
    config = config_with(api__max_retries=2)
    async with harness(
        config,
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(503),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert len(h.upstream.requests) == 3
    assert h.sleeps == [0.5, 1.0]
    assert result["ok"] is False
    assert result["error"]["status"] == "server_error"
    assert result["error"]["retryable"] is True


async def test_zero_max_retries_disables_retrying() -> None:
    config = config_with(api__max_retries=0)
    async with harness(config, httpx.Response(429)) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert len(h.upstream.requests) == 1
    assert h.sleeps == []
    assert result["error"]["status"] == "rate_limited"


async def test_client_errors_are_not_retried() -> None:
    async with harness(AppConfig(), httpx.Response(401, json={"error": {"message": "bad key"}})) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert len(h.upstream.requests) == 1
    assert result["error"]["status"] == "unauthorized"
    assert result["error"]["attempts"] == 1
    assert result["error"]["elapsed_ms"] >= 0


async def test_network_error_is_retried_then_reported() -> None:
    async with harness(
        AppConfig(),
        httpx.ConnectError("connection refused"),
        httpx.ConnectError("connection refused"),
        httpx.ConnectError("connection refused"),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert len(h.upstream.requests) == 3
    assert result["error"]["status"] == "network_error"
    assert result["error"]["retryable"] is True


# ---------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    ("status_code", "expected_status"),
    [
        (400, "invalid_request"),
        (401, "unauthorized"),
        (402, "insufficient_balance"),
        (403, "forbidden"),
        (404, "not_found"),
        (413, "payload_too_large"),
        (500, "server_error"),
        (504, "upstream_timeout"),
    ],
)
async def test_http_status_maps_to_error_status(status_code: int, expected_status: str) -> None:
    config = config_with(api__max_retries=0)
    async with harness(config, httpx.Response(status_code, json={"error": {"message": "x"}})) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert result["ok"] is False
    assert result["error"]["status"] == expected_status
    assert result["error"]["http_code"] == status_code


async def test_error_message_uses_upstream_text_and_hint() -> None:
    async with harness(
        AppConfig(),
        httpx.Response(400, json={"error": {"message": "'count' must be between 1 and 50"}}),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    message = result["error"]["message"]
    assert "'count' must be between 1 and 50" in message


async def test_unauthorized_message_explains_how_to_pass_the_key() -> None:
    async with harness(AppConfig(), httpx.Response(401)) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    message = result["error"]["message"]
    assert "Authorization: Bearer" in message
    assert "environment variable" in message

async def test_fetch_404_maps_to_not_found_with_hint() -> None:
    async with harness(AppConfig(), httpx.Response(404)) as h:
        result = await h.client.fetch(api_key=API_KEY, url="https://example.com/missing")

    assert result["error"]["status"] == "not_found"
    assert "page content" in result["error"]["message"]

async def test_error_messages_do_not_contain_credentials() -> None:
    messages = [MISSING_API_KEY_MESSAGE]
    no_retry = config_with(api__max_retries=0)

    async with harness(AppConfig()) as h:
        missing = await h.client.search(api_key=None, query="q")
    messages.append(missing["error"]["message"])

    for status_code in (400, 401, 402, 403, 404, 408, 413, 429, 500, 504):
        async with harness(no_retry, httpx.Response(status_code)) as h:
            result = await h.client.search(api_key=API_KEY, query="q")
        messages.append(result["error"]["message"])

    async with harness(no_retry, httpx.ConnectError("refused")) as h:
        network = await h.client.search(api_key=API_KEY, query="q")
    messages.append(network["error"]["message"])

    async with harness(no_retry, httpx.ReadTimeout("slow")) as h:
        timeout = await h.client.search(api_key=API_KEY, query="q")
    messages.append(timeout["error"]["message"])

    async with harness(no_retry, httpx.Response(200, text="nope")) as h:
        bad_json = await h.client.search(api_key=API_KEY, query="q")
    messages.append(bad_json["error"]["message"])

    async with harness(no_retry, httpx.Response(200, json={"data": []})) as h:
        bad_shape = await h.client.search(api_key=API_KEY, query="q")
    messages.append(bad_shape["error"]["message"])

    for message in messages:
        assert API_KEY not in message


async def test_error_message_never_contains_the_api_key() -> None:
    leaky = f"invalid token {API_KEY}"
    async with harness(
        AppConfig(),
        httpx.Response(401, json={"error": {"message": leaky}}),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert API_KEY not in result["error"]["message"]
    assert "sk-***" in result["error"]["message"]


async def test_non_json_200_is_invalid_response() -> None:
    async with harness(AppConfig(), httpx.Response(200, text="<html>nope</html>")) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert result["error"]["status"] == "invalid_response"


async def test_missing_results_array_is_invalid_response() -> None:
    async with harness(AppConfig(), httpx.Response(200, json={"data": []})) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert result["error"]["status"] == "invalid_response"


async def test_timeout_is_reported_after_retries() -> None:
    async with harness(
        AppConfig(),
        httpx.ReadTimeout("too slow"),
        httpx.ReadTimeout("too slow"),
        httpx.ReadTimeout("too slow"),
    ) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert len(h.upstream.requests) == 3
    assert result["error"]["status"] == "upstream_timeout"
    assert result["error"]["retryable"] is True
    assert result["error"]["attempts"] == 3


@pytest.mark.parametrize("streaming", [False, True])
async def test_total_budget_cancels_slow_response_without_retrying(streaming: bool) -> None:
    requests = 0
    cancelled = asyncio.Event()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                while True:
                    await asyncio.sleep(0.005)
                    yield b" "
            finally:
                cancelled.set()

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if streaming:
            return httpx.Response(200, stream=SlowStream())
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
        return search_ok()

    config = config_with(api__total_timeout_seconds=0.04)
    async with DeepSeekClient(config, transport=httpx.MockTransport(slow)) as client:
        started = monotonic()
        result = await asyncio.wait_for(
            client.fetch(api_key=API_KEY, url="https://example.com"), timeout=0.5,
        )

    assert monotonic() - started < 0.5
    assert cancelled.is_set()
    assert requests == 1
    assert result["error"]["status"] == "upstream_timeout"
    assert result["error"]["attempts"] == 1
    assert result["error"]["elapsed_ms"] >= 30
    assert "total timeout budget of 0.04s" in result["error"]["message"]


async def test_total_budget_is_shared_across_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = 0
    cancelled = asyncio.Event()
    monkeypatch.setattr("deepseek_search_mcp.client._backoff_seconds", lambda attempt: 0.005)

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            await asyncio.sleep(0.06)
            return httpx.Response(503)
        try:
            # Fits a fresh budget but not what remains after the first attempt.
            await asyncio.sleep(0.08)
        finally:
            cancelled.set()
        return search_ok()

    config = config_with(api__total_timeout_seconds=0.11)
    async with DeepSeekClient(config, transport=httpx.MockTransport(slow)) as client:
        result = await asyncio.wait_for(client.search(api_key=API_KEY, query="q"), timeout=0.5)

    assert requests == 2
    assert cancelled.is_set()
    assert result["error"]["attempts"] == 2
    assert result["error"]["status"] == "upstream_timeout"
    assert 80 <= result["error"]["elapsed_ms"] < 500


@pytest.mark.parametrize("retry_after", [None, "0.2"])
async def test_retry_delay_must_fit_remaining_budget(retry_after: str | None) -> None:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    config = config_with(api__total_timeout_seconds=0.1)
    async with harness(config, httpx.Response(429, headers=headers)) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert len(h.upstream.requests) == 1
    assert h.sleeps == []
    assert result["error"]["status"] == "rate_limited"
    assert result["error"]["attempts"] == 1
    assert "remaining total timeout budget" in result["error"]["message"]
    if retry_after is not None:
        assert result["error"]["retry_after_seconds"] == 0.2


async def test_total_budget_also_cancels_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deepseek_search_mcp.client._backoff_seconds", lambda attempt: 0.005)
    cancelled = asyncio.Event()

    async def slow_sleep(delay: float) -> None:
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    config = config_with(api__total_timeout_seconds=0.04)
    async with harness(config, httpx.Response(503)) as h:
        h.client._sleep = slow_sleep
        result = await asyncio.wait_for(h.client.search(api_key=API_KEY, query="q"), timeout=0.5)

    assert cancelled.is_set()
    assert len(h.upstream.requests) == 1
    assert result["error"]["status"] == "upstream_timeout"


@pytest.mark.parametrize("exception", [httpx.ReadTimeout(""), httpx.ConnectError("")])
async def test_empty_transport_exception_has_readable_diagnostics(exception: httpx.HTTPError) -> None:
    config = config_with(api__max_retries=0)
    async with harness(config, exception) as h:
        result = await h.client.search(api_key=API_KEY, query="q")

    assert type(exception).__name__ in result["error"]["message"]
    assert result["error"]["attempts"] == 1
    assert isinstance(result["error"]["elapsed_ms"], int)
    assert API_KEY not in str(result)


async def test_caller_cancellation_propagates_without_retrying() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    requests = 0

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
        return search_ok()

    async with DeepSeekClient(AppConfig(), transport=httpx.MockTransport(slow)) as client:
        task = asyncio.create_task(client.search(api_key=API_KEY, query="q"))
        await asyncio.wait_for(started.wait(), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert cancelled.is_set()
    assert requests == 1


async def test_missing_api_key_short_circuits_without_request() -> None:
    async with harness(AppConfig()) as h:
        result = await h.client.search(api_key=None, query="q")

    assert h.upstream.requests == []
    assert result["error"]["status"] == "missing_api_key"
    assert result["error"]["message"] == MISSING_API_KEY_MESSAGE


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"query": ""}, "query must be a non-empty string"),
        ({"query": "   "}, "query must be a non-empty string"),
        ({"query": "x" * 129}, "at most 128 characters"),
        ({"query": "q", "count": 0}, "count must be between 1 and 50"),
        ({"query": "q", "count": 51}, "count must be between 1 and 50"),
        ({"query": "q", "ori_question": "y" * 129}, "ori_question must be at most 128"),
        ({"query": "q", "ori_question": " "}, "non-empty"),
        ({"query": "q", "need_content": "false"}, "boolean"),
        ({"query": "q", "count": True}, "integer"),
    ],
)
async def test_invalid_search_arguments_fail_before_any_request(
    kwargs: dict, fragment: str
) -> None:
    async with harness(AppConfig()) as h:
        result = await h.client.search(api_key=API_KEY, **kwargs)

    assert h.upstream.requests == []
    assert result["error"]["status"] == "invalid_request"
    assert fragment in result["error"]["message"]


@pytest.mark.parametrize(
    ("url", "fragment"),
    [
        ("", "url must be a non-empty string"),
        ("ftp://example.com/x", "http or https"),
        ("https:///nohost", "must include a host"),
        ("https://user:pass@example.com/x", "username or password"),
        ("https://example.com/" + "x" * 9000, "at most 8192 characters"),
        ("http://[", "valid absolute"),
        ("https://example.com:abc", "valid absolute"),
        ("https://@example.com", "username or password"),
        ("https://example.com/a b", "whitespace"),
    ],
)
async def test_invalid_fetch_urls_fail_before_any_request(url: str, fragment: str) -> None:
    async with harness(AppConfig()) as h:
        result = await h.client.fetch(api_key=API_KEY, url=url)

    assert h.upstream.requests == []
    assert result["error"]["status"] == "invalid_request"
    assert fragment in result["error"]["message"]


# ----------------------------------------------------------------------- fetch


async def test_fetch_sends_url_and_returns_content() -> None:
    async with harness(
        AppConfig(),
        httpx.Response(200, json={"title": "Example", "content": "# Example\n\nBody"}),
    ) as h:
        result = await h.client.fetch(api_key=API_KEY, url="https://example.com/a")

    request = h.upstream.requests[0]
    assert str(request.url) == "https://api.deepseek.com/v1/tools/fetch"
    assert json.loads(request.content) == {"url": "https://example.com/a"}
    assert result == {
        "ok": True,
        "url": "https://example.com/a",
        "title": "Example",
        "content": "# Example\n\nBody",
        "truncated": False,
        "total_chars": len("# Example\n\nBody"),
    }


async def test_fetch_truncates_at_config_limit() -> None:
    config = config_with(fetch__max_content_chars=4)
    body = {"title": "t", "content": "0123456789"}
    async with harness(config, httpx.Response(200, json=body)) as h:
        result = await h.client.fetch(api_key=API_KEY, url="https://example.com/a")

    assert result["content"] == "0123"
    assert result["truncated"] is True


async def test_fetch_max_chars_argument_overrides_config() -> None:
    config = config_with(fetch__max_content_chars=4)
    body = {"title": "t", "content": "0123456789"}
    async with harness(config, httpx.Response(200, json=body)) as h:
        result = await h.client.fetch(
            api_key=API_KEY, url="https://example.com/a", max_chars=8
        )

    assert result["content"] == "01234567"
    assert result["truncated"] is True


async def test_fetch_accepts_zero_max_chars() -> None:
    body = {"title": "t", "content": "0123456789"}
    async with harness(AppConfig(), httpx.Response(200, json=body)) as h:
        result = await h.client.fetch(
            api_key=API_KEY, url="https://example.com/a", max_chars=0
        )

    assert result["content"] == "0123456789"
    assert result["truncated"] is False


@pytest.mark.parametrize("max_chars", [-1, 1.5, True, "10"])
async def test_fetch_rejects_invalid_max_chars(max_chars: object) -> None:
    async with harness(AppConfig()) as h:
        result = await h.client.fetch(
            api_key=API_KEY, url="https://example.com/a", max_chars=max_chars
        )

    assert h.upstream.requests == []
    assert result["error"]["status"] == "invalid_request"


@pytest.mark.parametrize("body", [{"title": None}, {"title": "t", "content": ""}, {"title": "t", "content": []}, {"title": "t", "content": "  "}])
async def test_malformed_fetch_is_an_error(body: dict) -> None:
    async with harness(AppConfig(), httpx.Response(200, json=body)) as h:
        result = await h.client.fetch(api_key=API_KEY, url="https://example.com/a")

    assert result["error"]["status"] == "invalid_response"


async def test_client_closes_underlying_http_client() -> None:
    client = DeepSeekClient(AppConfig(), transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    await client.aclose()
    assert client._http.is_closed


@pytest.mark.parametrize("bad_hit", [None, {}, item(rerank_score=True), item(authority="3"), item(summary=None)])
async def test_malformed_search_results_are_errors(bad_hit):
    async with harness(AppConfig(), search_ok(bad_hit)) as h:
        result = await h.client.search(api_key=API_KEY, query="q")
    assert result["error"]["status"] == "invalid_response"


@pytest.mark.parametrize("retry_after", ["NaN", "inf", "not a date"])
async def test_bad_retry_after_uses_backoff(retry_after):
    async with harness(AppConfig(), httpx.Response(429, headers={"Retry-After": retry_after}), search_ok()) as h:
        result = await h.client.search(api_key=API_KEY, query="q")
    assert result["ok"] is True
    assert h.sleeps == [0.5]


async def test_nonstandard_key_is_redacted_before_message_truncation():
    secret = "custom-token-123456789"
    async with harness(AppConfig(), httpx.Response(401, text="x" * 290 + secret)) as h:
        result = await h.client.search(api_key=secret, query="q")
    assert secret not in str(result)
    assert "custom-token" not in str(result)


async def test_cancellation_is_not_retried():
    import asyncio

    async def cancelled(request):
        raise asyncio.CancelledError

    async with DeepSeekClient(AppConfig(), transport=httpx.MockTransport(cancelled)) as client:
        with pytest.raises(asyncio.CancelledError):
            await client.search(api_key=API_KEY, query="q")
