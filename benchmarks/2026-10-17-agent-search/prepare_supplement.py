import json
from pathlib import Path
from normalize import normalize

ROOT=Path(__file__).resolve().parent
cases=json.loads((ROOT/'cases.json').read_text(encoding='utf-8'))['cases']
rows=[]
for c in cases:
    if not c['id'].startswith('A'): continue
    r=normalize(json.loads((ROOT/'raw'/f"anysearch_general-{c['id']}.json").read_text(encoding='utf-8')))
    rows.append(r)
    item={k:c[k] for k in ['id','query','criteria','scenario','anchor']}
    item['groups']=[{'label':'D','results':r['results'],'call_error':r['error']}]
    folder=ROOT/'blind'/('supplement_1' if int(c['id'][1:])<=15 else 'supplement_2')
    folder.mkdir(exist_ok=True)
    (folder/(c['id']+'.json')).write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'normalized-supplement.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('Prepared 30 supplemental query reviews.')
