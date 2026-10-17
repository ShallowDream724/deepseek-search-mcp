"""Exercise MCP discovery and calls through real stdio and Streamable HTTP."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from .conftest import item

KEY = "test-credential-that-must-not-appear"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def upstream():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers.get("Authorization"), body))
            if body.get("query") == "fail":
                status, result = 401, {"error": {"message": f"Invalid key: {KEY}"}}
            elif self.path == "/v1/tools/search":
                status, result = 200, {"results": [item()]}
            else:
                status, result = 200, {"title": "Example", "content": "# Example\nBody"}
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def wait_for_port(port: int, process: subprocess.Popen) -> None:
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError("HTTP server exited before startup; inspect test server.log")
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.1)
        else:
            writer.close()
            await writer.wait_closed()
            return
    raise TimeoutError("HTTP server did not start within 15 seconds")


@pytest.mark.parametrize("transport_name", ["stdio", "http"])
async def test_wire_contract(transport_name, upstream, tmp_path):
    base_url, requests = upstream
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"api": {"base_url": base_url, "max_retries": 0}}))
    args = ["-m", "deepseek_search_mcp", "--config", str(config)]
    env = dict(os.environ)
    env.pop("DEEPSEEK_SEARCH_CONFIG", None)
    env["DEEPSEEK_API_KEY"] = KEY if transport_name == "stdio" else ""
    process = None
    log_path = tmp_path / "server.log"
    with log_path.open("w", encoding="utf-8") as log:
        try:
            if transport_name == "stdio":
                transport = StdioTransport(sys.executable, args, env=env, cwd=str(ROOT), log_file=log)
            else:
                port = free_port()
                process = subprocess.Popen(
                    [sys.executable, *args, "--transport", "http", "--port", str(port)],
                    env=env, cwd=ROOT, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                await wait_for_port(port, process)
                transport = StreamableHttpTransport(
                    f"http://127.0.0.1:{port}/mcp", headers={"Authorization": f"Bearer {KEY}"}
                )

            async with Client(transport, timeout=15) as client:
                tools = await client.list_tools()
                assert {tool.name for tool in tools} == {"search", "fetch"}
                assert all(tool.output_schema for tool in tools)
                search = await client.call_tool("search", {"query": "test", "count": 1})
                assert search.is_error is False
                assert search.structured_content["results"][0]["rerank_score"] == 2.4
                fetch = await client.call_tool("fetch", {"url": "https://example.com", "max_chars": 3})
                assert fetch.structured_content["truncated"] is True
                assert fetch.structured_content["total_chars"] == 14
                failed = await client.call_tool("search", {"query": "fail"}, raise_on_error=False)
                assert failed.is_error is True
                assert failed.structured_content["error"]["status"] == "unauthorized"
                assert KEY not in str(failed)
                invalid = await client.call_tool("search", {"query": "x", "need_content": "false"}, raise_on_error=False)
                assert invalid.is_error is True
                assert invalid.structured_content["error"]["status"] == "invalid_request"
                assert all(record[1] == f"Bearer {KEY}" for record in requests)
                assert len(requests) == 3  # Invalid arguments never reach the upstream.
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    assert KEY not in log_path.read_text(encoding="utf-8")
