"""Tests for API key extraction and secret redaction."""

from __future__ import annotations

import pytest

from deepseek_search_mcp.auth import (
    API_KEY_ENV,
    extract_api_key,
    redact,
    resolve_api_key,
)

KEY = "sk-abcdef0123456789"


@pytest.mark.parametrize(
    "headers",
    [
        {"authorization": f"Bearer {KEY}"},
        {"authorization": f"bearer {KEY}"},
        {"authorization": f"BEARER {KEY}"},
        {"Authorization": f"Bearer {KEY}"},
        {"authorization": f"  Bearer   {KEY}  "},
    ],
)
def test_bearer_header_is_accepted(headers: dict[str, str]) -> None:
    assert extract_api_key(headers) == KEY


def test_alias_header_is_accepted() -> None:
    assert extract_api_key({"x-deepseek-api-key": KEY}) == KEY
    assert extract_api_key({"X-DeepSeek-API-Key": f"  {KEY} "}) == KEY


def test_bearer_header_wins_over_alias() -> None:
    headers = {"authorization": f"Bearer {KEY}", "x-deepseek-api-key": "other-key-1234"}
    assert extract_api_key(headers) == KEY


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"authorization": ""},
        {"authorization": "Basic dXNlcjpwYXNz"},
        {"authorization": "Bearer"},
        {"authorization": "Bearer    "},
        {"authorization": KEY},
        {"x-deepseek-api-key": "   "},
    ],
)
def test_non_key_headers_return_none(headers: dict[str, str]) -> None:
    assert extract_api_key(headers) is None


def test_extract_handles_none() -> None:
    assert extract_api_key(None) is None


def test_resolve_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, f"  {KEY}  ")
    assert resolve_api_key() == KEY


def test_resolve_returns_none_without_headers_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    assert resolve_api_key() is None


def test_redact_masks_sk_tokens() -> None:
    assert KEY not in redact(f"bad key {KEY}")


def test_redact_masks_bearer_tokens() -> None:
    redacted = redact("Authorization: Bearer abcdef1234567890")
    assert "abcdef1234567890" not in redacted
    assert "Bearer ***" in redacted


def test_redact_leaves_normal_text_alone() -> None:
    text = "DeepSeek returned HTTP 429; retry later."
    assert redact(text) == text
