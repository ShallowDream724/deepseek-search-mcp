"""Command line entry point for the DeepSeek Search MCP server.

Examples:
    deepseek-search-mcp                                  # stdio
    deepseek-search-mcp --transport http --port 8000     # Streamable HTTP at /mcp
    deepseek-search-mcp --transport sse --port 8000      # legacy SSE at /sse
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from . import __version__
from .config import ConfigError, describe_enabled_tools, load_config
from .server import build_server

TRANSPORT_CHOICES = ("stdio", "http", "streamable-http", "sse")
LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_HTTP_PATH = "/mcp"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepseek-search-mcp",
        description=(
            "MCP server exposing the DeepSeek Web Search and Fetch APIs. "
            "The DeepSeek API key is taken from the client request headers "
            "(HTTP transports) or the DEEPSEEK_API_KEY environment variable (stdio)."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=TRANSPORT_CHOICES,
        default="stdio",
        help="MCP transport to serve (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"host for HTTP/SSE transports (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"port for HTTP/SSE transports (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--path",
        default=DEFAULT_HTTP_PATH,
        help=f"Streamable HTTP endpoint path (default: {DEFAULT_HTTP_PATH})",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="path to config.json (default: $DEEPSEEK_SEARCH_CONFIG or ./config.json)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=LOG_LEVEL_CHOICES,
        help="log verbosity written to stderr (default: INFO)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def configure_logging(level: str) -> None:
    """Log to stderr only: stdout carries the stdio MCP protocol."""
    logging.basicConfig(
        level=getattr(logging, level),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    try:
        config, path = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 2

    source = str(path) if path is not None else "built-in defaults"
    print(
        f"[config] loaded {source} (tools: {describe_enabled_tools(config)})",
        file=sys.stderr,
        flush=True,
    )

    mcp = build_server(config)

    transport = "http" if args.transport == "streamable-http" else args.transport
    run_kwargs: dict[str, object] = {"show_banner": False}
    if transport in {"http", "sse"}:
        run_kwargs.update(host=args.host, port=args.port, log_level=args.log_level)
        if transport == "http":
            run_kwargs["path"] = args.path

    try:
        mcp.run(transport=transport, **run_kwargs)  # type: ignore[arg-type]
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
