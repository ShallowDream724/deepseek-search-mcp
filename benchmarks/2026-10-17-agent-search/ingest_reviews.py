"""Import JSON reviews from this task's explicitly supplied collaboration transcript."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
START = re.compile(r'\[\s*\{\s*"id"\s*:\s*"[ADNST]\d+"\s*,\s*"label"')


def strings(value):
    if isinstance(value, str):
        yield value
        if value.startswith(('{', '[')):
            try:
                inner = json.loads(value)
            except ValueError:
                return
            if not isinstance(inner, str):
                yield from strings(inner)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('session_log', type=Path)
    args = parser.parse_args()
    reviews = {}
    decoder = json.JSONDecoder()
    for line in args.session_log.open(encoding='utf-8'):
        entry = json.loads(line)
        if entry.get('type') not in {'response_item', 'event_msg'}:
            continue
        for text in strings(entry.get('payload', {})):
            for match in START.finditer(text):
                try:
                    data, _ = decoder.raw_decode(text[match.start():])
                except ValueError:
                    continue
                if not data or not all(isinstance(r, dict) and {'id','label','r','q','u','coverage','constraint','note'} <= r.keys() for r in data):
                    continue
                for row in data:
                    reviews.setdefault((row['id'], row['label']), row)
    output = sorted(reviews.values(), key=lambda r: (r['id'],r['label']))
    (ROOT / 'reviews-initial.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Imported {len(output)} unique group reviews; no unrelated transcript data copied.')


if __name__ == '__main__':
    main()
