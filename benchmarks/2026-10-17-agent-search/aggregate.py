"""Validate recorded judgments and reproduce the public benchmark data.

The public source-results.json keeps titles, URLs, ranks and measured metadata,
not copied page text. Initial judgments and every correction remain inspectable.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent
PROVIDERS = {'native': ('原生搜索', '#347B80'), 'anysearch': ('AnySearch', '#8174B5'), 'deepseek': ('DeepSeek Search', '#D58A53')}


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def score(g):
    if not g['r']:
        return 0.0
    return 35 * mean(g['r']) / 2 + 30 * mean(g['q']) / 3 + 25 * g['coverage'] / 4 + 10 * g['constraint'] / 2


def percentile(values, p):
    s = sorted(values)
    pos = (len(s) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def main():
    cases = read('cases.json')['cases']
    key = read('blind-key.json')
    public_path = ROOT / 'source-results.json'
    if not public_path.exists():
        records = read('normalized.json') + read('normalized-supplement.json')
        for record in records:
            for result in record['results']:
                result.pop('evidence', None)
        write('source-results.json', records)
    records = read('source-results.json')
    for record in records:
        for result in record['results']:
            original = result['title']
            title = ' '.join(original.strip().splitlines()[0].split()) if original.strip() else result['url']
            shortened = ' '.join(title.split()[:22])[:140].rstrip()
            if shortened != title or '\n' in original:
                title = shortened + '…'
                result['title_truncated'] = True
            result['title'] = title
    write('source-results.json', records)
    record_index = {(r['case_id'], r['provider']): r for r in records}
    assert len(records) == len(record_index) == 252
    grades = deepcopy(read('reviews-initial.json'))
    gi = {(g['id'], g['label']): g for g in grades}
    assert len(gi) == len(grades) == 252
    audits = []

    def amend(g, changes, reason):
        old = {k: deepcopy(g[k]) for k in changes}
        g.update(deepcopy(changes))
        audits.append({'id': g['id'], 'label': g['label'], 'before': old, 'after': changes, 'reason': reason})

    # Correct conflation of low evidence with demonstrated misinformation.
    # Keep the keyword-stuffed journal extract and the explicit incorrect
    # assertion that TaskGroup replaces gather at q=0.
    for g in grades:
        changes = {}
        q = list(g['q'])
        for i, value in enumerate(q):
            if value != 0 or (g['id'], g['label'], i) in {('A28', 'A', 2), ('T01', 'B', 2)}:
                continue
            q[i] = 1
            if (g['id'], g['label'], i) == ('A25', 'B', 3):
                q[i] = 3  # Original article; wrong topic is scored under relevance.
            if (g['id'], g['label'], i) == ('A25', 'C', 4):
                q[i] = 2  # Traceable paper mirror, outside requested date window.
        if q != g['q']:
            changes['q'] = q
            amend(g, changes, '缺乏证据、非官方或偏题不自动等于明确误导；质量与相关性分别评分。')
    for override in read('review-overrides.json'):
        amend(gi[override['id'], override['label']], override['changes'], override['reason'])

    rows = []
    for g in grades:
        provider = 'anysearch_general' if g['label'] == 'D' else key[g['id'] + ':' + g['label']]
        record = record_index[g['id'], provider]
        n = len(record['results'])
        for dim, maximum in [('r', 2), ('q', 3), ('u', 2)]:
            assert len(g[dim]) == n, (g['id'], provider, dim, n)
            assert all(type(v) is int and 0 <= v <= maximum for v in g[dim])
        assert 0 <= g['coverage'] <= 4 and 0 <= g['constraint'] <= 2
        rows.append({**g, 'provider': provider, 'score': round(score(g), 3), 'elapsed_ms': record['elapsed_ms'], 'text_chars': record['text_chars'], 'error': record['error']})
    write('reviews-final.json', rows)
    write('review-audit-log.json', audits)
    index = {(r['id'], r['provider']): r for r in rows}

    def average(provider, subset=cases):
        return round(mean(index[c['id'], provider]['score'] for c in subset), 1)

    stats = []
    for provider, (name, color) in PROVIDERS.items():
        selected = [index[c['id'], provider] for c in cases]
        rs = [v for r in selected for v in r['r']]
        qs = [v for r in selected for v in r['q']]
        us = [v for r in selected for v in r['u']]
        stats.append({'id': provider, 'name': name, 'color': color,
                      'score': average(provider),
                      'academic': average(provider, [c for c in cases if c['id'].startswith('A')]),
                      'news': average(provider, [c for c in cases if c['id'].startswith('N')]),
                      'seo': average(provider, [c for c in cases if c['id'].startswith('S')]),
                      'zh': average(provider, [c for c in cases if c['language'] == 'zh']),
                      'en': average(provider, [c for c in cases if c['language'] == 'en']),
                      'median_ms': round(median(r['elapsed_ms'] for r in selected)),
                      'p90_ms': round(percentile([r['elapsed_ms'] for r in selected], .9)),
                      'mean_chars': round(mean(r['text_chars'] for r in selected)),
                      'low_quality_pct': round(mean(q <= 1 for q in qs) * 100, 1),
                      'relevant_pct': round(mean(r == 2 for r in rs) * 100, 1),
                      'usable_pct': round(mean(u == 2 for u in us) * 100, 1),
                      'reliable_relevant_pct': round(mean(r == 2 and q >= 2 and u >= 1 for r,q,u in zip(rs,qs,us)) * 100, 1),
                      'strong_evidence_pct': round(mean(q == 3 for q in qs) * 100, 1),
                      'success_pct': round(mean(not r['error'] for r in selected) * 100, 1),
                      'result_count': len(rs),
                      'latest_academic_score': average(provider, [c for c in cases if c['id'] in ['A25','A26','A27','A28','A29','A30']])})
    categories = [{'name': category, 'values': {p: average(p, [c for c in cases if c['category'] == category]) for p in PROVIDERS}} for category in dict.fromkeys(c['category'] for c in cases)]
    academic = [c for c in cases if c['id'].startswith('A')]
    cohorts = [
        ('精确论文与DOI（4题）', [1,2,3,4]),
        ('方法与实证研究（10题）', [5,6,7,8,13,14,15,16,23,24]),
        ('数据与数字资源（4题）', [9,10,19,20]),
        ('撤稿与证据综述（6题）', [11,12,17,18,21,22]),
        ('2026年10月新论文（6题）', [25,26,27,28,29,30]),
    ]
    academic_breakdown = [{'name':name, 'case_ids':[f'A{i:02}' for i in ids], 'values':{p:average(p,[c for c in academic if int(c['id'][1:]) in ids]) for p in PROVIDERS}} for name,ids in cohorts]
    mix = mean(index[c['id'], 'anysearch_general' if c['id'].startswith('A') else 'anysearch']['score'] for c in cases)
    case_output = []
    for c in cases:
        groups = []
        for provider in list(PROVIDERS) + (['anysearch_general'] if c in academic else []):
            g = index[c['id'], provider]
            rec = record_index[c['id'], provider]
            results = [{**r, 'r': g['r'][i], 'q': g['q'][i], 'u': g['u'][i]} for i,r in enumerate(rec['results'])]
            groups.append({'provider': provider, 'name': PROVIDERS[provider][0] if provider in PROVIDERS else 'AnySearch 通用路由补测', **{k:g[k] for k in ['score','coverage','constraint','note']}, 'results': results})
        case_output.append({**{k:c[k] for k in ['id','category','language','query','criteria']}, 'groups': groups})

    findings = [
        {'title':'首轮检索：原生搜索领先，DeepSeek 居中', 'text':'主榜按74条查询等权平均，学术占30条。比较的是AI拿到的第一轮证据，未测试最终回答或多轮查询改写。', 'links':[]},
        {'title':'AnySearch 的路由选择影响很大', 'text':f'学术垂直路由 {average("anysearch", academic):.1f} 分；相同30题改用通用路由后 {average("anysearch_general", academic):.1f} 分。只替换学术部分的总体分为 {mix:.1f}。补测单列，未择优拼接主榜。', 'links':[]},
        {'title':'搜到当天报道，不代表拿到了原始发布', 'text':'测试包含10月17日Flash-1017与Search/Fetch API、近72小时OpenAI更新和9月29日DevDay。DeepSeek能检出当日消息，但不少结果是转载；直接定位官方文档仍需单独核验。', 'links':[{'title':'DeepSeek 更新日志','url':'https://api-docs.deepseek.com/updates/'},{'title':'OpenAI DevDay 回顾','url':'https://openai.com/index/devday-2026-recap/'}]},
        {'title':'最新学术研究仍是三者共同弱项', 'text':'A25–A30要求10月新论文、原始研究和明确日期。常见失败是旧论文、新闻转述、专题索引替代具体论文，以及把抓取日期当发表日期。精确DOI定位与这些任务应分开看。', 'links':[]},
        {'title':'没有证据支持“低质量结果已被消除”', 'text':'DeepSeek仍返回购物榜单、薄弱转载和与任务不符的期刊集合页；AnySearch也出现缺少研究支撑的健康内容。已打开部分原页检查，但这些观察不能证明发布者有SEO作弊意图，也不能反推出引擎内部机制。', 'links':[{'title':'榜单原页','url':'https://www.ithome.com/1/010/061.htm'},{'title':'健康内容原页','url':'https://humanhealth.com.hk/zh-hans/healthinfo/info_detail/liver-protection/'}]},
        {'title':'Fetch 测出了真实接口缺陷', 'text':'DeepSeek基线一次请求重试至92.1秒，错误理由为空。MCP已增加默认45秒总预算、清楚的超时原因及attempts/elapsed_ms；原始基线记录保持不变。PDF、JS站点和访问限制的表现另列。', 'links':[]}
    ]
    audit_examples = [
        ('S07','deepseek','https://www.ithome.com/1/010/061.htm','原页给出报告编号，但可见正文未链接原始报告，品牌导购与精确测量结论并存；保留低证据评级，不据此指控伪造。'),
        ('S03','anysearch','https://humanhealth.com.hk/zh-hans/healthinfo/info_detail/liver-protection/','原页乳蓟段落含强疗效表述，未列对应临床研究来源；证据不足。'),
        ('S04','native','https://www.isthereconsensus.org/consensus/nutrition-and-diet/do-detox-diets-and-cleanses-remove-toxins-or-improve-health','复核发现NCCIH及具体综述DOI，质量从1改为2；审查日期来源不明，不足以否定全部证据。'),
        ('S01','deepseek','https://vlc-player.github.io/vlc/index.zh_TW.html','非VideoLAN域名且摘录显示旧版本；原页访问失败，未确认恶意或假冒。'),
        ('S10','deepseek','https://zenodo.org/records/17968922','库中存档不等于同行评议；原页访问失败，无法验证新理论，保留待查。')
    ]
    data = {'meta': {'date':'2026-10-17', 'queries':74, 'academic_queries':30, 'zh':37, 'en':37, 'search_calls':222, 'supplement_calls':30, 'fetch_calls':30, 'baseline_commit':'aead844', 'rubric':'相关性35% + 来源质量30% + 覆盖度25% + 约束满足10%', 'limitations':[
        '本次为单次探索性评估；74条含中英文同主题查询，并非74个独立主题，不报告统计显著性。',
        '由AI评分代理阅读隐藏提供方标签的材料，主代理做有记录的抽查纠错；没有人类评委或全面双重评分。格式特征仍可能暴露提供方。',
        '每条证据超过2200字符时只给评审前1600和后600字符；全文返回在本地留存。评分不是对所有原页的完整事实核查。',
        '原生工具无法强制只返回5条；评分只看前5条，字符量按实际完整文本计算。AnySearch和DeepSeek请求5条。',
        '原生与AnySearch采集并发4，DeepSeek串行；延迟受并发、缓存和网络路径影响，仅是本次观察，不能当速度排名或SLA。',
        'AnySearch学术通用路由是事后补测；单列主榜和补测，不取两路最高分。',
        '低证据比例不等于SEO作弊比例；没有搜索引擎内部反作弊数据，也没有全网相关文档全集，不能测真实召回率。',
        '分数依赖本批任务配比和主观量表；未评价多轮代理成功率、费用、覆盖全部语种或动态浏览器交互。'
    ]}, 'providers':stats, 'categories':categories, 'academic_breakdown':academic_breakdown,
    'supplement':{'anysearch_vertical_score':average('anysearch',academic), 'anysearch_general_score':average('anysearch_general',academic), 'anysearch_general_mix_score':round(mix,1), 'note':'同样30条学术查询改用general路由；不对每题择优，44条非学术主结果保持原样。'},
    'findings':findings, 'fetch':read('fetch-review.json'), 'cases':case_output,
    'audits':[dict(zip(['case_id','provider','url','note'],a)) for a in audit_examples]}
    write('report-data.json', data)
    # Hash private first-pass evidence without publishing copied pages.
    if (ROOT/'raw').exists():
        files = sorted((ROOT/'raw').glob('*.json'))
        write('evidence-manifest.json', [{'file':f'raw/{p.name}','bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files])
    print(json.dumps({'providers':stats,'supplement':data['supplement'],'audit_entries':len(audits)},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
