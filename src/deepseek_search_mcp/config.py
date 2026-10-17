"""Configuration loading and validation for deepseek-search-mcp.

Resolution order (highest precedence first):

1. ``--config`` command line argument
2. ``DEEPSEEK_SEARCH_CONFIG`` environment variable
3. ``./config.json`` in the current working directory
4. Built-in defaults (no file required)

A missing *explicit* path is an error. A missing ``./config.json`` is not: the
server starts with defaults so that stdio clients work with zero setup.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

DEFAULT_CONFIG_FILENAME = "config.json"
CONFIG_PATH_ENV = "DEEPSEEK_SEARCH_CONFIG"
DEFAULT_BASE_URL = "https://api.deepseek.com"

TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ConfigError(Exception):
    """Raised when a configuration file is missing, unreadable, or invalid."""


class ToolConfig(BaseModel):
    """Name and enablement flag for one exposed MCP tool."""

    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = value.strip()
        if not TOOL_NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "tool names must match "
                f"{TOOL_NAME_PATTERN.pattern!r} (letters, digits, '_' and '-'; 1-64 chars), "
                f"got {value!r}"
            )
        return value


class SearchToolConfig(ToolConfig):
    """``tools.search``; keeps the default name so partial overrides work."""

    name: str = "search"


class FetchToolConfig(ToolConfig):
    """``tools.fetch``; keeps the default name so partial overrides work."""

    name: str = "fetch"

class ToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search: SearchToolConfig = Field(default_factory=SearchToolConfig)
    fetch: FetchToolConfig = Field(default_factory=FetchToolConfig)

    @model_validator(mode="after")
    def _names_must_be_unique(self) -> "ToolsConfig":
        enabled = [tool.name for tool in (self.search, self.fetch) if tool.enabled]
        if len(enabled) != len(set(enabled)):
            raise ValueError(
                "tools.search.name and tools.fetch.name must be different when both are enabled"
            )
        return self


class ApiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            raise ValueError("api.base_url must not be empty")
        try:
            parts = urlsplit(value)
            _ = parts.port
        except ValueError as exc:
            raise ValueError("api.base_url must be a valid absolute http(s) URL") from exc
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("api.base_url must be an absolute http(s) URL")
        if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
            raise ValueError("api.base_url must not contain credentials, a query or a fragment")
        if any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError("api.base_url must not contain whitespace or control characters")
        return value


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_count: int = Field(default=10, ge=1, le=50)
    max_content_chars: int = Field(default=20000, ge=0)
    localization: str = ""

    @field_validator("localization")
    @classmethod
    def _validate_localization(cls, value: str) -> str:
        value = value.strip()
        if value:
            try:
                ipaddress.ip_address(value)
            except ValueError as exc:
                raise ValueError(
                    f"search.localization must be empty or a valid IPv4/IPv6 address, got {value!r}"
                ) from exc
        return value


class FetchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_content_chars: int = Field(default=30000, ge=0)


class AppConfig(BaseModel):
    """Validated view of the whole configuration file."""

    model_config = ConfigDict(extra="forbid")

    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)


def resolve_config_path(
    explicit: str | Path | None = None,
    *,
    cwd: Path | None = None,
) -> Path | None:
    """Return the config path implied by the arguments/env/cwd, or ``None``.

    ``None`` means "no explicit configuration was requested and no
    ``./config.json`` exists", i.e. built-in defaults apply.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    env_value = os.environ.get(CONFIG_PATH_ENV)
    if env_value:
        return Path(env_value).expanduser()
    candidate = (cwd or Path.cwd()) / DEFAULT_CONFIG_FILENAME
    return candidate if candidate.is_file() else None


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        location = "/".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  - {location}: {error['msg']}")
    return "\n".join(lines)


def load_config(
    explicit: str | Path | None = None,
    *,
    cwd: Path | None = None,
) -> tuple[AppConfig, Path | None]:
    """Load and validate the configuration.

    Returns the validated config plus the path it came from (``None`` when the
    built-in defaults were used). Raises :class:`ConfigError` for an unreadable
    file, invalid JSON, or values that fail validation.
    """
    path = resolve_config_path(explicit, cwd=cwd)
    if path is None:
        return AppConfig(), None
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"invalid config in {path}: top-level JSON value must be an object")
    try:
        config = AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            f"invalid config in {path}:\n{_format_validation_error(exc)}"
        ) from exc
    return config, path


def describe_enabled_tools(config: AppConfig) -> str:
    """Human readable summary of enabled tool names, for startup logging."""
    names = [
        tool.name
        for tool in (config.tools.search, config.tools.fetch)
        if tool.enabled
    ]
    return ", ".join(names) if names else "<none>"
