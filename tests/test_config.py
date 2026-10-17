"""Tests for configuration discovery, loading, and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_search_mcp.config import (
    CONFIG_PATH_ENV,
    AppConfig,
    ConfigError,
    describe_enabled_tools,
    load_config,
    resolve_config_path,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_PATH_ENV, raising=False)


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_defaults_without_any_config(tmp_path: Path) -> None:
    config, path = load_config(cwd=tmp_path)

    assert path is None
    assert config == AppConfig()
    assert config.tools.search.name == "web_search"
    assert config.tools.fetch.name == "web_fetch"
    assert config.api.base_url == "https://api.deepseek.com"
    assert config.api.timeout_seconds == 30.0
    assert config.api.max_retries == 2
    assert config.search.default_count == 10


def test_cwd_config_is_picked_up(tmp_path: Path) -> None:
    write_json(tmp_path / "config.json", {"tools": {"search": {"name": "ds_search"}}})

    config, path = load_config(cwd=tmp_path)

    assert path == tmp_path / "config.json"
    assert config.tools.search.name == "ds_search"
    assert config.tools.fetch.name == "web_fetch"


def test_env_var_beats_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_json(tmp_path / "config.json", {"tools": {"search": {"name": "from_cwd"}}})
    env_path = write_json(tmp_path / "other.json", {"tools": {"search": {"name": "from_env"}}})
    monkeypatch.setenv(CONFIG_PATH_ENV, str(env_path))

    config, path = load_config(cwd=tmp_path)

    assert path == env_path
    assert config.tools.search.name == "from_env"


def test_explicit_beats_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = write_json(tmp_path / "env.json", {"tools": {"search": {"name": "from_env"}}})
    cli_path = write_json(tmp_path / "cli.json", {"tools": {"search": {"name": "from_cli"}}})
    monkeypatch.setenv(CONFIG_PATH_ENV, str(env_path))

    config, path = load_config(str(cli_path), cwd=tmp_path)

    assert path == cli_path
    assert config.tools.search.name == "from_cli"


def test_cwd_config_absent_is_not_an_error(tmp_path: Path) -> None:
    assert resolve_config_path(cwd=tmp_path) is None


def test_explicit_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(str(tmp_path / "nope.json"))


def test_env_missing_path_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, str(tmp_path / "nope.json"))

    with pytest.raises(ConfigError, match="config file not found"):
        load_config(cwd=tmp_path)


def test_malformed_json_reports_position(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"api": {', encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(str(path))


def test_empty_file_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(str(path))


def test_non_object_root_is_invalid(tmp_path: Path) -> None:
    path = write_json(tmp_path / "config.json", [1, 2, 3])

    with pytest.raises(ConfigError, match="top-level JSON value must be an object"):
        load_config(str(path))


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = write_json(tmp_path / "config.json", {"api": {"timout_seconds": 5}})

    with pytest.raises(ConfigError) as excinfo:
        load_config(str(path))

    assert "timout_seconds" in str(excinfo.value)


def test_invalid_tool_name_is_rejected(tmp_path: Path) -> None:
    path = write_json(tmp_path / "config.json", {"tools": {"search": {"name": "bad name!"}}})

    with pytest.raises(ConfigError, match="tool names must match"):
        load_config(str(path))


def test_duplicate_enabled_tool_names_are_rejected(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "config.json",
        {"tools": {"search": {"name": "same"}, "fetch": {"name": "same"}}},
    )

    with pytest.raises(ConfigError, match="must be different"):
        load_config(str(path))


def test_duplicate_names_allowed_when_one_disabled(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "config.json",
        {
            "tools": {
                "search": {"name": "same"},
                "fetch": {"name": "same", "enabled": False},
            }
        },
    )

    config, _ = load_config(str(path))

    assert config.tools.fetch.enabled is False


def test_base_url_trailing_slash_is_stripped(tmp_path: Path) -> None:
    path = write_json(tmp_path / "config.json", {"api": {"base_url": "https://example.com/v1/"}})

    config, _ = load_config(str(path))

    assert config.api.base_url == "https://example.com/v1"


@pytest.mark.parametrize("base_url", ["ftp://example.com", "example.com", "https://"])
def test_invalid_base_url_is_rejected(tmp_path: Path, base_url: str) -> None:
    path = write_json(tmp_path / "config.json", {"api": {"base_url": base_url}})

    with pytest.raises(ConfigError, match="api.base_url"):
        load_config(str(path))


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("timeout_seconds", 0),
        ("timeout_seconds", 301),
        ("max_retries", -1),
        ("max_retries", 6),
    ],
)
def test_api_bounds_are_enforced(tmp_path: Path, section: str, value: float) -> None:
    path = write_json(tmp_path / "config.json", {"api": {section: value}})

    with pytest.raises(ConfigError):
        load_config(str(path))


@pytest.mark.parametrize("count", [0, 51])
def test_default_count_bounds_are_enforced(tmp_path: Path, count: int) -> None:
    path = write_json(tmp_path / "config.json", {"search": {"default_count": count}})

    with pytest.raises(ConfigError):
        load_config(str(path))


def test_valid_localization_is_accepted(tmp_path: Path) -> None:
    path = write_json(tmp_path / "config.json", {"search": {"localization": "1.2.3.4"}})

    config, _ = load_config(str(path))

    assert config.search.localization == "1.2.3.4"


def test_invalid_localization_is_rejected(tmp_path: Path) -> None:
    path = write_json(tmp_path / "config.json", {"search": {"localization": "not-an-ip"}})

    with pytest.raises(ConfigError, match="localization"):
        load_config(str(path))


def test_zero_max_content_chars_means_no_truncation(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "config.json",
        {"search": {"max_content_chars": 0}, "fetch": {"max_content_chars": 0}},
    )

    config, _ = load_config(str(path))

    assert config.search.max_content_chars == 0
    assert config.fetch.max_content_chars == 0


def test_describe_enabled_tools() -> None:
    assert describe_enabled_tools(AppConfig()) == "web_search, web_fetch"

    config = AppConfig.model_validate({"tools": {"fetch": {"enabled": False}}})
    assert describe_enabled_tools(config) == "web_search"

    config = AppConfig.model_validate(
        {"tools": {"search": {"enabled": False}, "fetch": {"enabled": False}}}
    )
    assert describe_enabled_tools(config) == "<none>"
