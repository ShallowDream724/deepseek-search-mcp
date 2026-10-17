"""Run the frozen cases through the installed stdio MCP; never persist credentials."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import tomllib

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parent


async def main():
    config = tomllib.loads((Path.home() / '.codex/config.toml').read_text(encoding='utf-8-sig'))
    server = config['mcp_servers']['deepseek-search']
    transport = StdioTransport(server['command'], server['args'], cwd=server['cwd'])
    cases = json.loads((ROOT / 'cases.json').read_text(encoding='utf-8'))['cases']
    (ROOT / 'raw').mkdir(exist_ok=True)
    async with Client(transport, timeout=120) as client:
        for case in cases:
            path = ROOT / 'raw' / f"deepseek-{case['id']}.json"
            if path.exists():
                continue
            start = time.perf_counter()
            record = {'provider': 'deepseek', 'case_id': case['id'], 'query': case['query'], 'started_at': datetime.now(timezone.utc).isoformat()}
            try:
                result = await client.call_tool('search', {'query': case['query'], 'count': 5, 'need_content': False}, raise_on_error=False)
                record['response'] = {'isError': result.is_error, 'structuredContent': result.structured_content, 'content': [c.model_dump(mode='json') for c in result.content]}
            except Exception as exc:
                record['transport_error'] = type(exc).__name__
            record['elapsed_ms'] = round((time.perf_counter() - start) * 1000)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            print(case['id'], record['elapsed_ms'], flush=True)
            await asyncio.sleep(0.25)


if __name__ == '__main__':
    asyncio.run(main())
