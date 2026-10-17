"""Normalize top-five results and build provider-blinded review packets."""
import hashlib
import json
from pathlib import Path
import random
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def text_content(value):
    if isinstance(value, str):
        return value
    return '\n'.join(c.get('text', '') for c in value.get('content', []) if c.get('type') == 'text')


def excerpt(text):
    text = re.sub(r'\ue200cite\ue202[^\ue201]+\ue201', '', text)
    text = re.sub(r'\[wordlim: \d+\]', '', text)
    if len(text) <= 2200:
        return text.strip()
    return text[:1600].strip() + '\n[评审摘录省略中段；完整返回已保存]\n' + text[-600:].strip()


def normalize(record):
    response = record.get('response', {})
    raw_text = text_content(response)
    results = []
    provider = record['provider']
    if provider == 'deepseek':
        body = response.get('structuredContent') or {}
        for item in body.get('results', [])[:5]:
            evidence = '\n'.join([item.get('snippet') or '', item.get('summary') or ''])
            if item.get('date'):
                evidence = 'Returned date: ' + item['date'] + '\n' + evidence
            results.append({'title': item['title'], 'url': item['url'], 'evidence': excerpt(evidence)})
    elif provider.startswith('anysearch'):
        for block in re.split(r'(?m)^### \d+\. ', raw_text)[1:6]:
            title, _, rest = block.partition('\n')
            match = re.search(r'\*\*URL\*\*:\s*(\S+)', rest)
            if match:
                evidence = rest[match.end():].strip().removeprefix('- ').strip()
                results.append({'title': title.strip(), 'url': match.group(1), 'evidence': excerpt(evidence)})
    else:
        for block in re.split(r'-{20,}\n', raw_text):
            match = re.match(r'^(.*?) \((https?://[^\n]*)\)\n(.*)', block.strip(), flags=re.S)
            if match:
                results.append({'title': match.group(1), 'url': match.group(2), 'evidence': excerpt(match.group(3))})
            if len(results) == 5:
                break
    error = record.get('transport_error')
    if isinstance(response, dict):
        error = error or response.get('isError') or response.get('structuredContent', {}).get('error')
    return {'case_id': record['case_id'], 'provider': provider, 'elapsed_ms': record['elapsed_ms'], 'text_chars': len(raw_text), 'returned_results': len(results), 'error': bool(error), 'results': [{'rank': i + 1, **r} for i, r in enumerate(results)]}


def main():
    cases = json.loads((ROOT / 'cases.json').read_text(encoding='utf-8'))['cases']
    records = []
    for case in cases:
        for provider in ['native', 'anysearch', 'deepseek']:
            path = ROOT / 'raw' / f"{provider}-{case['id']}.json"
            if path.exists():
                records.append(normalize(json.loads(path.read_text(encoding='utf-8'))))
    (ROOT / 'normalized.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    index = {(r['case_id'], r['provider']): r for r in records}
    packets = {'academic_1': [], 'academic_2': [], 'academic_3': [], 'daily_tech': [], 'freshness': [], 'seo': []}
    key = {}
    for case in cases:
        case_id = case['id']
        providers = ['native', 'anysearch', 'deepseek']
        random.Random(int(hashlib.sha256(('bench-v1:' + case_id).encode()).hexdigest()[:12], 16)).shuffle(providers)
        groups = []
        for label, provider in zip('ABC', providers):
            record = index.get((case_id, provider))
            if record:
                groups.append({'label': label, 'results': record['results'], 'call_error': record['error']})
                key[f'{case_id}:{label}'] = provider
        item = {k: case[k] for k in ['id', 'language', 'query', 'criteria', 'scenario', 'anchor']}
        item['groups'] = groups
        if case_id.startswith('A'):
            packet = 'academic_' + str((int(case_id[1:]) - 1) // 10 + 1)
        elif case_id.startswith('N'):
            packet = 'freshness'
        elif case_id.startswith('S'):
            packet = 'seo'
        else:
            packet = 'daily_tech'
        packets[packet].append(item)
    (ROOT / 'blind').mkdir(exist_ok=True)
    for name, items in packets.items():
        # One case per file keeps reads small and review completion auditable.
        folder = ROOT / 'blind' / name
        folder.mkdir(exist_ok=True)
        for item in items:
            (folder / (item['id'] + '.json')).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'blind-key.json').write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'records': len(records), 'expected': len(cases) * 3, 'empty_by_provider': {p: [r['case_id'] for r in records if r['provider'] == p and not r['results']] for p in ['native','anysearch','deepseek']}, 'text_chars': sum(r['text_chars'] for r in records)}))


if __name__ == '__main__':
    main()
