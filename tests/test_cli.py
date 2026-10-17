"""Tests for the CLI: argument parsing, config errors, transport mapping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_search_mcp import cli
from deepseek_search_mcp.cli import build_parser, main


class FakeServer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> FakeServer:
    server = FakeServer()
    monkeypatch.setattr(cli, "build_server", lambda config, **kwargs: server)
    return server


@pytest.fixture(autouse=True)
def _no_ambient_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_SEARCH_CONFIG", raising=False)


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])

    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.path == "/mcp"
    assert args.config is None
    assert args.log_level == "INFO"


def test_version_action_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert "deepseek-search-mcp" in capsys.readouterr().out


def test_stdio_run_has_no_network_arguments(fake_server: FakeServer) -> None:
    assert main([]) == 0

    assert fake_server.calls == [{"show_banner": False, "transport": "stdio"}]


def test_http_transport_passes_network_arguments(fake_server: FakeServer) -> None:
    assert main(["--transport", "http", "--host", "0.0.0.0", "--port", "9000"]) == 0

    assert fake_server.calls == [
        {
            "show_banner": False,
            "transport": "http",
            "host": "0.0.0.0",
            "port": 9000,
            "log_level": "INFO",
            "path": "/mcp",
        }
    ]


def test_streamable_http_alias_maps_to_http(fake_server: FakeServer) -> None:
    assert main(["--transport", "streamable-http"]) == 0

    assert fake_server.calls[0]["transport"] == "http"


def test_sse_transport_omits_path(fake_server: FakeServer) -> None:
    assert main(["--transport", "sse", "--port", "9100"]) == 0

    call = fake_server.calls[0]
    assert call["transport"] == "sse"
    assert call["port"] == 9100
    assert "path" not in call


def test_custom_http_path(fake_server: FakeServer) -> None:
    assert main(["--transport", "http", "--path", "/custom"]) == 0

    assert fake_server.calls[0]["path"] == "/custom"


def test_missing_explicit_config_returns_2(
    capsys: pytest.CaptureFixture[str],
    fake_server: FakeServer,
) -> None:
    exit_code = main(["--config", "missing.json"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "error:" in captured.err
    assert "config file not found" in captured.err
    assert fake_server.calls == []


def test_invalid_config_returns_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fake_server: FakeServer,
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    exit_code = main(["--config", str(bad)])

    assert exit_code == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_config_source_is_logged_to_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fake_server: FakeServer,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tools": {"search": {"name": "ds_search"}}}),
        encoding="utf-8",
    )

    main([])

    err = capsys.readouterr().err
    assert "[config] loaded" in err
    assert "ds_search" in err


def test_built_in_defaults_are_logged_when_no_config(
    capsys: pytest.CaptureFixture[str],
    fake_server: FakeServer,
) -> None:
    main([])

    err = capsys.readouterr().err
    assert "built-in defaults" in err
    assert "web_search, web_fetch" in err
