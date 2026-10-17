"""API key intake and secret redaction.

The DeepSeek key is never stored, cached, or written anywhere. It is read from
the current HTTP request (or the environment for stdio) and forwarded verbatim
to DeepSeek as ``Authorization: Bearer <key>``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from fastmcp.server.dependencies import get_http_headers

API_KEY_ENV = "DEEPSEEK_API_KEY"
AUTHORIZATION_HEADER = "authorization"
API_KEY_ALIAS_HEADER = "x-deepseek-api-key"

_BEARER_PREFIX = "bearer "

_SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{8,}"),
)


def _lowercase_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        str(key).lower(): str(value).strip()
        for key, value in (headers or {}).items()
    }


def extract_api_key(headers: Mapping[str, str] | None) -> str | None:
    """Pull a key out of request headers.

    Accepts ``Authorization: Bearer <key>`` (case-insensitive scheme) and the
    ``X-DeepSeek-API-Key`` alias used by clients that cannot set Authorization.
    """
    normalized = _lowercase_headers(headers or {})

    authorization = normalized.get(AUTHORIZATION_HEADER, "")
    if authorization[: len(_BEARER_PREFIX)].lower() == _BEARER_PREFIX:
        token = authorization[len(_BEARER_PREFIX) :].strip()
        if token:
            return token

    alias = normalized.get(API_KEY_ALIAS_HEADER, "")
    return alias or None


def resolve_api_key() -> str | None:
    """Resolve the key for the current call: request headers first, env second."""
    try:
        headers = get_http_headers(include={AUTHORIZATION_HEADER, API_KEY_ALIAS_HEADER})
    except Exception:  # pragma: no cover - defensive: never fail a call for this
        headers = {}
    key = extract_api_key(headers)
    if key:
        return key
    env_key = os.environ.get(API_KEY_ENV, "").strip()
    return env_key or None


def redact(text: str, secret: str | None = None) -> str:
    """Mask anything that looks like an API key or bearer token."""
    if secret:
        text = text.replace(secret, "sk-***" if secret.startswith("sk-") else "***")
    redacted = _SECRET_PATTERNS[0].sub("sk-***", text)
    return _SECRET_PATTERNS[1].sub(r"\1***", redacted)
