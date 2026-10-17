#!/usr/bin/env python3
"""Build the Chinese benchmark report from reviewed report-data.json.

Run from the repository root:
  .venv/Scripts/python.exe benchmarks/2026-10-17-agent-search/build_report.py

No network requests are made. The report embeds its charts, and each chart is
also exported as PNG and SVG in charts/. Missing measurements remain missing.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import MaxNLocator


HERE = Path(__file__).resolve().parent
INK = "#24313a"
MUTED = "#66717a"
GRID = "#e5e8e9"
PALETTE = ["#466d83", "#b77c51", "#638c78", "#8b799f"]


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def fmt(value: object, digits: int = 1, suffix: str = "") -> str:
    val = number(value)
    if val is None:
        return "—"
    return f"{val:,.{digits}f}{suffix}"


def text_value(value: object) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value or "")


def safe_url(value: object) -> str | None:
    url = str(value or "").strip()
    parts = urlsplit(url)
    if parts.scheme in ("https", "http") and parts.netloc:
        return url
    return None


def link(title: object, url: object, class_name: str = "") -> str:
    address = safe_url(url)
    if address is None:
        return f'<span class="{esc(class_name)}">{esc(title or url or "未提供链接")}</span>'
    return (
        f'<a class="{esc(class_name)}" href="{esc(address)}" '
        f'target="_blank" rel="noopener noreferrer">{esc(title or address)}</a>'
    )


def domain(url: object) -> str:
    address = safe_url(url)
    return urlsplit(address).netloc if address else "无可追溯网页地址"


def setup_fonts() -> None:
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ):
        if candidate.is_file():
            font_manager.fontManager.addfont(str(candidate))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(candidate)).get_name()
            break
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 10,
            "axes.labelcolor": MUTED,
            "text.color": INK,
            "xtick.color": MUTED,
            "ytick.color": INK,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "svg.fonttype": "path",
            "svg.hashsalt": "agent-search-benchmark",
        }
    )


def style_axis(ax, xmax: float = 100, xlabel: str = "得分 / 100 · 越高越好") -> None:
    ax.set_xlim(0, xmax)
    ax.set_xlabel(xlabel, labelpad=12)
    ax.grid(axis="x", color=GRID, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", length=0, pad=8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if xmax == 100:
        ax.set_xticks([0, 25, 50, 75, 100])
    else:
        ax.xaxis.set_major_locator(MaxNLocator(4))


def score_label(ax, value: float | None, y: float, xmax: float = 100, suffix: str = "", digits: int = 1) -> None:
    if value is None:
        ax.text(xmax * 0.02, y, "未测", va="center", fontsize=10, color=MUTED)
        return
    label = fmt(value, digits, suffix)
    if value > xmax * 0.86:
        ax.text(value - xmax * 0.02, y, label, va="center", ha="right", fontsize=10,
                color="white", fontweight="bold")
    else:
        ax.text(value + xmax * 0.018, y, label, va="center", fontsize=10, color=INK)


class Charts:
    def __init__(self, directory: Path, providers: list[dict]) -> None:
        self.directory = directory
        self.providers = providers
        self.directory.mkdir(parents=True, exist_ok=True)
        self.entries: dict[str, dict[str, str]] = {}

    def save(self, fig, key: str, alt: str) -> None:
        svg_path = self.directory / f"{key}.svg"
        png_path = self.directory / f"{key}.png"
        fig.savefig(svg_path, bbox_inches="tight", pad_inches=0.26, metadata={"Date": None})
        svg_path.write_text('\n'.join(line.rstrip() for line in svg_path.read_text(encoding='utf-8').splitlines()) + '\n', encoding='utf-8')
        fig.savefig(png_path, dpi=180, bbox_inches="tight", pad_inches=0.26)
        plt.close(fig)
        embedded = base64.b64encode(svg_path.read_bytes()).decode("ascii")
        self.entries[key] = {"alt": alt, "src": f"data:image/svg+xml;base64,{embedded}"}

    def element(self, key: str, caption: str) -> str:
        item = self.entries.get(key)
        if not item:
            return '<p class="empty">本项未提供测量数据。</p>'
        return (
            f'<figure><div class="chart-scroll"><img class="chart" src="{item["src"]}" alt="{esc(item["alt"])}"></div>'
            f'<figcaption><span>{esc(caption)}</span><span class="downloads">'
            f'<a href="charts/{esc(key)}.png" download>PNG</a>'
            f'<a href="charts/{esc(key)}.svg" download>SVG</a></span></figcaption></figure>'
        )

    def overall(self) -> None:
        items = sorted(self.providers, key=lambda p: number(p.get("score")) if number(p.get("score")) is not None else -1, reverse=True)
        fig, ax = plt.subplots(figsize=(11, max(2.7, len(items) * 0.68 + 1)))
        for index, provider in enumerate(items):
            value = number(provider.get("score"))
            if value is not None:
                ax.barh(index, value, height=0.43, color=provider["color"], zorder=3)
            score_label(ax, value, index)
        ax.set_yticks(range(len(items)), [p["name"] for p in items])
        ax.invert_yaxis()
        style_axis(ax)
        fig.tight_layout(pad=1.6)
        self.save(fig, "overall", "主实验总体得分横向条形图，满分100分，越高越好")

    def categories(self, categories: list[dict], key: str = 'categories') -> None:
        if not categories:
            return
        count = len(self.providers)
        gap = 1.2
        bar_height = min(0.22, 0.78 / max(count, 1))
        fig, ax = plt.subplots(figsize=(11, max(3.4, len(categories) * 1.05 + 1.1)))
        for pi, provider in enumerate(self.providers):
            offset = (pi - (count - 1) / 2) * (bar_height + 0.04)
            for ci, category in enumerate(categories):
                value = number(category.get("values", {}).get(provider["id"]))
                y = ci * gap + offset
                if value is not None:
                    ax.barh(y, value, height=bar_height, color=provider["color"], label=provider["name"] if ci == 0 else None, zorder=3)
                score_label(ax, value, y)
        ax.set_yticks([i * gap for i in range(len(categories))], [c["name"] for c in categories])
        ax.invert_yaxis()
        style_axis(ax)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.03), ncol=min(count, 3), frameon=False, borderaxespad=0)
        fig.tight_layout(pad=1.5)
        self.save(fig, key, "各查询场景的提供方得分对比，满分100分，越高越好")

    def languages(self) -> None:
        fig, axes = plt.subplots(1, 2, figsize=(11, max(2.8, len(self.providers) * 0.6 + 1.4)), sharey=True)
        for ax, key, title in zip(axes, ["zh", "en"], ["中文查询", "英文查询"]):
            for index, provider in enumerate(self.providers):
                value = number(provider.get(key))
                if value is not None:
                    ax.barh(index, value, height=0.42, color=provider["color"], zorder=3)
                score_label(ax, value, index)
            ax.set_yticks(range(len(self.providers)), [p["name"] for p in self.providers])
            style_axis(ax)
            ax.set_title(title, loc="left", pad=18, fontweight="bold")
        axes[0].invert_yaxis()
        fig.tight_layout(pad=1.5, w_pad=2.8)
        self.save(fig, "languages", "中文和英文查询得分对比，满分100分，越高越好")

    def quality(self) -> None:
        metrics = [("relevant_pct", "直接相关率", "比例 / % · 越高越好"),
                   ("usable_pct", "有用摘录比例", "比例 / % · 越高越好"),
                   ("low_quality_pct", "低证据来源比例", "比例 / % · 越低越好")]
        fig, axes = plt.subplots(1, 3, figsize=(13, max(2.9, len(self.providers) * 0.62 + 1.4)), sharey=True)
        for ax, (key, title, xlabel) in zip(axes, metrics):
            for index, provider in enumerate(self.providers):
                value = number(provider.get(key))
                if value is not None:
                    ax.barh(index, value, height=0.42, color=provider["color"], zorder=3)
                score_label(ax, value, index, suffix="%")
            ax.set_yticks(range(len(self.providers)), [p["name"] for p in self.providers])
            style_axis(ax, xlabel=xlabel)
            ax.set_title(title, loc="left", pad=18, fontweight="bold")
        axes[0].invert_yaxis()
        fig.tight_layout(pad=1.5, w_pad=2.3)
        self.save(fig, "source-quality", "直接相关率、有用摘录比例及低证据来源比例；前两项越高越好，低证据比例越低越好")

    def operations(self) -> None:
        metrics = [("median_ms", "中位延迟", 1000, "秒 · 越低越好", 1),
                   ("p90_ms", "P90 延迟", 1000, "秒 · 越低越好", 1),
                   ("mean_chars", "平均返回字符量", 1, "字符 · 描述返回体量", 0)]
        fig, axes = plt.subplots(1, 3, figsize=(13, max(2.9, len(self.providers) * 0.62 + 1.4)), sharey=True)
        for ax, (key, title, divisor, xlabel, digits) in zip(axes, metrics):
            values = [number(p.get(key)) for p in self.providers]
            values = [v / divisor if v is not None else None for v in values]
            xmax = max([v for v in values if v is not None] or [1]) * 1.38
            xmax = max(xmax, 1)
            for index, (provider, value) in enumerate(zip(self.providers, values)):
                if value is not None:
                    ax.barh(index, value, height=0.42, color=provider["color"], zorder=3)
                score_label(ax, value, index, xmax=xmax, digits=digits)
            ax.set_yticks(range(len(self.providers)), [p["name"] for p in self.providers])
            style_axis(ax, xmax=xmax, xlabel=xlabel)
            ax.set_title(title, loc="left", pad=18, fontweight="bold")
        axes[0].invert_yaxis()
        fig.tight_layout(pad=1.5, w_pad=2.6)
        self.save(fig, "operations", "中位延迟、P90延迟与平均返回字符量；延迟越低越好，字符量仅作描述")

    def supplement(self, supplement: dict) -> None:
        labels = supplement.get("labels", {})
        metrics = [("anysearch_vertical_score", "学术：垂直路由"),
                   ("anysearch_general_score", "学术：通用路由"),
                   ("anysearch_general_mix_score", "学术改用通用路由\n后的总体分（补测）")]
        if not any(number(supplement.get(key)) is not None for key, _ in metrics):
            return
        color = next((p["color"] for p in self.providers if p["id"] == "anysearch"), PALETTE[1])
        fig, ax = plt.subplots(figsize=(11, 3.5))
        for index, (key, _) in enumerate(metrics):
            value = number(supplement.get(key))
            if value is not None:
                ax.barh(index, value, height=0.44, color=color, alpha=0.65 if index == 2 else 1, zorder=3)
            score_label(ax, value, index)
        ax.set_yticks(range(len(metrics)), [labels.get(key, title) for key, title in metrics])
        ax.axhline(1.5, color=GRID, linestyle=(0, (3, 4)), linewidth=1)
        ax.invert_yaxis()
        style_axis(ax)
        fig.tight_layout(pad=1.5)
        self.save(fig, "academic-supplement", "AnySearch学术路由补测：学术垂直路由、学术通用路由及替换学术路由后的总体分")


CSS = r"""
:root{--ink:#24313a;--muted:#69747b;--line:#e1e5e5;--paper:#fff;--bg:#f5f5f2;--accent:#416c80;--soft:#eef2f2;--radius:18px}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:88px}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;font-size:15px;line-height:1.75}a{color:var(--accent);text-decoration:none;text-underline-offset:3px}a:hover{text-decoration:underline}button,input,select{font:inherit}button,a,input,select,summary{-webkit-tap-highlight-color:transparent}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #91b8ca;outline-offset:3px}button{cursor:pointer}main{width:min(1240px,calc(100% - 64px));margin:0 auto;padding:56px 0 64px}header{padding:0 4px 28px}.eyebrow{font-size:12px;letter-spacing:.12em;color:var(--muted);font-weight:600}h1{font-size:clamp(28px,3vw,40px);line-height:1.3;font-weight:650;letter-spacing:-.025em;margin:10px 0 14px}h2{font-size:23px;line-height:1.4;letter-spacing:-.02em;margin:0 0 6px;font-weight:650}h3{font-size:17px;line-height:1.5;margin:0 0 10px;font-weight:650}h4{font-size:15px;margin:0}p{margin:8px 0 14px}ul{padding-left:22px;margin:10px 0}li+li{margin-top:8px}.subtitle{max-width:850px;color:var(--muted);margin-bottom:20px}.provider-legend{display:flex;flex-wrap:wrap;gap:10px 22px;font-size:13px}.legend-item{display:inline-flex;align-items:center;gap:8px}.dot{width:9px;height:9px;border-radius:50%;background:var(--provider);flex:none}.meta-strip{margin-top:26px;padding:20px 0 0;border-top:1px solid var(--line);display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:18px}.meta-strip dl{margin:0}.meta-strip dt{font-size:12px;color:var(--muted);margin-bottom:3px}.meta-strip dd{margin:0;font-size:21px;font-variant-numeric:tabular-nums}.meta-strip dd small{font-size:12px;color:var(--muted);margin-left:4px}.nav-wrap{position:sticky;top:0;z-index:5;background:rgba(245,245,242,.97);border-bottom:1px solid var(--line);margin-bottom:30px}.nav{display:flex;gap:5px;overflow-x:auto;padding:12px 0;scrollbar-width:thin}.nav a{white-space:nowrap;padding:6px 13px;color:var(--muted);font-size:13px;border-radius:8px}.nav a:hover{color:var(--ink);background:#e9eded;text-decoration:none}.section{margin-top:24px;background:var(--paper);border:1px solid var(--line);border-radius:var(--radius);padding:30px 32px}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:18px}.section-head p{color:var(--muted);font-size:14px;margin:0;max-width:860px}.section-index{font-size:11px;color:var(--muted);letter-spacing:.08em;padding-top:5px;white-space:nowrap}.subsection{margin-top:28px;padding-top:24px;border-top:1px solid var(--line)}figure{margin:8px 0 0}.chart{display:block;width:100%;height:auto;min-width:0}figcaption{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;font-size:12px;color:var(--muted);padding:12px 0 2px;line-height:1.7}.downloads{display:flex;gap:12px;flex:none}.downloads a{font-weight:600}.table-scroll{overflow-x:auto;width:100%;border:1px solid var(--line);border-radius:12px;margin:18px 0 0}table{border-collapse:collapse;width:100%;font-size:13px}thead{background:#f6f7f7}th{text-align:left;font-weight:500;color:var(--muted);white-space:nowrap}th,td{padding:13px 15px;border-bottom:1px solid #e9ecec;vertical-align:top}tbody tr:last-child td{border-bottom:0}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}td strong{font-weight:650}.overview-table{min-width:720px}.note{font-size:13px;color:var(--muted);margin:14px 0 0}.notice{border-left:3px solid #9aaeb5;background:#f4f7f7;border-radius:0 10px 10px 0;padding:15px 18px;font-size:13px;color:#52636d;margin:18px 0 0;line-height:1.9}.findings{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 32px}.finding{padding:18px 0;border-top:1px solid var(--line)}.finding p{font-size:14px;color:#4f5d65;margin:6px 0 9px}.finding-links{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px}.finding-num{font-size:11px;color:var(--muted);letter-spacing:.08em;margin-bottom:6px}.fetch-table{min-width:900px;table-layout:fixed}.fetch-table th:first-child{width:19%}.fetch-title{display:block;font-weight:600;margin-bottom:3px}.small{font-size:12px;color:var(--muted)}.badge{display:inline-block;font-size:11px;line-height:1.6;padding:3px 8px;border-radius:6px;background:#eef1f2;color:#52636d;white-space:nowrap}.badge.ok{background:#e8f1eb;color:#35614b}.badge.error{background:#f7ece9;color:#985543}.badge.partial{background:#f7f0df;color:#896c2d}.fetch-note{font-size:12px;line-height:1.8;margin:7px 0;overflow-wrap:anywhere}.fetch-time{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}.filters{display:grid;grid-template-columns:minmax(230px,1fr) minmax(130px,180px) minmax(120px,150px);gap:12px;margin-top:22px}.field{display:grid;gap:6px;font-size:12px;color:var(--muted)}.field input,.field select{border:1px solid #ccd4d7;border-radius:9px;background:#fff;color:var(--ink);width:100%;padding:10px 12px;min-height:44px;font-size:13px}.filter-actions{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:14px 0 18px;color:var(--muted);font-size:12px}.action-group{display:flex;gap:8px;flex-wrap:wrap}.quiet-button{border:1px solid #d9dfe1;background:white;border-radius:7px;padding:5px 10px;color:#52636d;font-size:12px;line-height:1.7}.quiet-button:hover{background:#f2f5f5}.case-card{border:1px solid var(--line);border-radius:12px;margin:11px 0;overflow:hidden}.case-card>summary{display:flex;align-items:flex-start;gap:13px;padding:17px 19px;cursor:pointer;list-style:none;background:#fff}.case-card>summary::-webkit-details-marker{display:none}.case-card>summary:before{content:'+';font-size:20px;line-height:24px;color:#6e858f;flex:0 0 15px}.case-card[open]>summary:before{content:'−'}.case-card[open]>summary{background:#f7f9f9;border-bottom:1px solid var(--line)}.case-title{flex:1;min-width:0}.case-meta{display:flex;flex-wrap:wrap;gap:7px;align-items:center;font-size:11px;color:var(--muted);margin-bottom:5px}.case-id{font-variant-numeric:tabular-nums;color:#4a616d;font-weight:650}.case-query{font-size:14px;line-height:1.7;overflow-wrap:anywhere}.case-scores{display:flex;gap:14px;flex-wrap:wrap;justify-content:flex-end;max-width:40%;padding-top:5px}.mini-score{display:flex;gap:5px;align-items:center;font-size:12px;white-space:nowrap;font-variant-numeric:tabular-nums}.case-body{padding:20px}.criteria{font-size:13px;color:#54646d;margin:0 0 20px;line-height:1.9}.criteria strong{font-weight:600;color:#354851}.result-groups{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.result-group{border:1px solid var(--line);border-radius:10px;padding:16px;min-width:0}.group-head{display:flex;align-items:flex-start;gap:10px;justify-content:space-between}.group-name{display:flex;align-items:center;gap:7px;line-height:1.6;font-size:13px;font-weight:600}.group-score{font-size:20px;line-height:1.2;font-weight:650;font-variant-numeric:tabular-nums}.group-score small{font-size:10px;color:var(--muted);font-weight:400}.group-metrics{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin:12px 0}.group-note{font-size:12px;line-height:1.85;color:#53616b;margin:0 0 14px;overflow-wrap:anywhere}.result-list{padding:0;margin:0;list-style:none}.result-list>li{margin:0;padding:13px 0;border-top:1px solid var(--line)}.source-title{display:block;font-size:12px;line-height:1.8;font-weight:550;overflow-wrap:anywhere}.source-domain{font-size:10px;color:var(--muted);overflow-wrap:anywhere;margin:4px 0 7px}.rank{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;background:#eef2f3;color:#5d727d;font-size:10px;border-radius:4px;margin-right:5px;font-weight:600}.score-tags{display:flex;flex-wrap:wrap;gap:5px}.score-tags span{font-size:10px;line-height:1.7;color:#63747c;background:#f2f5f5;border-radius:4px;padding:1px 5px}.empty{padding:18px 0;color:var(--muted);font-size:13px}.empty-state{border:1px dashed #cdd5d8;border-radius:12px;padding:30px;text-align:center;color:var(--muted)}[hidden]{display:none!important}.audit-table{min-width:650px}.audit-table td{overflow-wrap:anywhere}.audit-table td:first-child{white-space:nowrap}.audit-details{margin-top:22px;border-top:1px solid var(--line);padding-top:18px}.audit-details>summary{font-size:14px;cursor:pointer;font-weight:600}.rubric{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;color:#4d5e67;font-size:14px;margin:15px 0 0}.method-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:28px}.method-grid p,.method-grid li{font-size:13px;color:#54646d}.method-grid ul{margin-bottom:0}.rubric-keys{display:flex;gap:8px 22px;flex-wrap:wrap;font-size:12px;color:var(--muted);padding-top:14px}.baseline{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11px;background:#eff3f3;border-radius:5px;padding:3px 6px;overflow-wrap:anywhere}footer{font-size:12px;color:var(--muted);margin:24px 4px 0;display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}.noscript{background:#fff3dc;padding:12px 16px;border-radius:8px;font-size:13px}.back-top{white-space:nowrap}.print-only{display:none}
@media(min-width:1400px){main{width:1240px}}
@media(max-width:1000px){main{width:calc(100% - 40px);padding-top:36px}.section{padding:25px 24px}.meta-strip{grid-template-columns:repeat(3,minmax(0,1fr));row-gap:20px}.result-groups{grid-template-columns:1fr}.group-head{align-items:center}.result-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 20px}.group-note{max-width:900px}.case-scores{max-width:44%}.method-grid{grid-template-columns:1fr;gap:20px}}
@media(max-width:680px){html{scroll-padding-top:74px}main{width:calc(100% - 24px);padding:26px 0 40px}header{padding:0 5px 22px}h1{font-size:28px}h2{font-size:20px}.subtitle{font-size:13px}.meta-strip{gap:17px 12px;margin-top:22px}.meta-strip dd{font-size:18px}.meta-strip dt{font-size:11px}.nav-wrap{margin-bottom:18px}.nav{padding:9px 0;gap:0}.nav a{font-size:12px;padding:6px 10px}.section{padding:22px 16px;margin-top:16px;border-radius:14px}.section-head{gap:12px}.section-head p{font-size:12px}.section-index{font-size:10px}.findings{grid-template-columns:1fr}.finding p{font-size:13px}.filters{grid-template-columns:1fr 1fr}.field:first-child{grid-column:1/-1}.filter-actions{align-items:flex-start;flex-direction:column;gap:10px}.case-card>summary{padding:14px 13px;gap:8px;flex-wrap:wrap}.case-title{flex-basis:calc(100% - 28px)}.case-scores{max-width:100%;justify-content:flex-start;padding-left:23px;padding-top:0;gap:12px}.case-query{font-size:13px}.case-body{padding:15px}.result-list{grid-template-columns:1fr}.result-group{padding:14px}.notice{padding:13px 14px;font-size:12px}figcaption{font-size:11px;flex-direction:column;gap:6px}.chart{min-height:0}.rubric-keys{gap:5px 14px}.section-head{margin-bottom:14px}}
.chart-scroll{overflow-x:auto;overscroll-behavior-x:contain;border-radius:8px}@media(max-width:680px){.chart{min-width:650px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:#fff;color:#111;font-size:11px}main{width:100%;padding:0}.nav-wrap,.filters,.filter-actions,.downloads,.back-top{display:none}.section{break-inside:avoid;page-break-inside:avoid;padding:20px;border-radius:0;margin:16px 0}.section-head{margin-bottom:8px}.chart{max-height:370px;object-fit:contain}.case-card{break-inside:avoid}.case-card[hidden]{display:block!important}.result-groups{grid-template-columns:1fr}.result-list{display:block}.print-only{display:block}a{color:inherit}.table-scroll{overflow:visible}.overview-table,.fetch-table,.audit-table{min-width:0}footer{font-size:10px}}
"""


JS = r"""
(() => {
  const cards = [...document.querySelectorAll('.case-card')];
  const search = document.getElementById('case-search');
  const category = document.getElementById('case-category');
  const language = document.getElementById('case-language');
  const counter = document.getElementById('case-counter');
  const empty = document.getElementById('case-empty');
  const normalize = value => value.normalize('NFKC').toLocaleLowerCase();
  const applyFilters = () => {
    const words = normalize(search.value.trim()).split(/\s+/).filter(Boolean);
    let visible = 0;
    cards.forEach(card => {
      const matches = (!category.value || card.dataset.category === category.value)
        && (!language.value || card.dataset.language === language.value)
        && words.every(word => normalize(card.dataset.search).includes(word));
      card.hidden = !matches;
      if (matches) visible += 1;
    });
    counter.textContent = `显示 ${visible} / ${cards.length} 道查询`;
    empty.hidden = visible !== 0;
  };
  [search, category, language].forEach(control => control.addEventListener('input', applyFilters));
  document.getElementById('expand-cases').addEventListener('click', () => cards.forEach(card => { if (!card.hidden) card.open = true; }));
  document.getElementById('collapse-cases').addEventListener('click', () => cards.forEach(card => { card.open = false; }));
  document.getElementById('reset-filters').addEventListener('click', () => {
    search.value = ''; category.value = ''; language.value = ''; applyFilters(); search.focus();
  });
  const openHash = () => {
    const id = decodeURIComponent(location.hash.slice(1));
    const target = document.getElementById(id);
    if (target && target.classList.contains('case-card')) {
      search.value = ''; category.value = ''; language.value = ''; applyFilters(); target.open = true;
      target.scrollIntoView({block:'start'});
    }
  };
  window.addEventListener('hashchange', openHash);
  applyFilters(); openHash();
})();
"""


def section_head(index: str, title: str, description: str) -> str:
    return f'<div class="section-head"><div><h2>{esc(title)}</h2><p>{esc(description)}</p></div><span class="section-index">{esc(index)}</span></div>'


def provider_label(provider: dict) -> str:
    return f'<span class="legend-item" style="--provider:{esc(provider["color"])}"><span class="dot"></span>{esc(provider["name"])}</span>'


def overview_table(providers: list[dict]) -> str:
    columns = [("score", "总体得分", ""), ("academic", "学术", ""), ("news", "新闻 / 时效", ""),
               ("seo", "低质内容场景", ""), ("zh", "中文", ""), ("en", "英文", ""), ("success_pct", "调用成功率", "%")]
    head = "".join(f'<th class="num">{esc(label)}</th>' for _, label, _ in columns)
    rows = []
    for provider in providers:
        cells = "".join(f'<td class="num">{"<strong>" if key == "score" else ""}{fmt(provider.get(key), suffix=suffix)}{"</strong>" if key == "score" else ""}</td>' for key, _, suffix in columns)
        rows.append(f'<tr><td>{provider_label(provider)}</td>{cells}</tr>')
    return f'<div class="table-scroll"><table class="overview-table"><thead><tr><th>工具</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def findings_html(findings: list[dict]) -> str:
    if not findings:
        return ""
    items = []
    for index, finding in enumerate(findings, 1):
        links = "".join(link(item.get("title"), item.get("url")) for item in finding.get("links", []))
        items.append(f'<article class="finding"><div class="finding-num">观察 {index:02d}</div><h3>{esc(finding.get("title"))}</h3><p>{esc(finding.get("text"))}</p><div class="finding-links">{links}</div></article>')
    return '<div class="subsection"><h3>主要观察</h3><div class="findings">' + "".join(items) + "</div></div>"


def fetch_html(rows: list[dict], providers: list[dict]) -> str:
    if not rows:
        return '<p class="empty">未提供网页读取记录。</p>'
    status_map = {"ok": ("成功", "ok"), "success": ("成功", "ok"), "supported": ("支持", "ok"),
                  "error": ("失败", "error"), "failed": ("失败", "error"), "unsupported": ("不支持", ""),
                  "unavailable": ("不可用", ""), "partial": ("部分可用", "partial"), "blocked": ("受阻", "partial"),
                  "timeout": ("超时", "error"), "not_tested": ("未测", ""), "not_supported": ("不支持", "")}
    body = []
    for row in rows:
        cells = []
        for provider in providers:
            result = row.get("values", {}).get(provider["id"], {})
            raw = str(result.get("status") or "未测")
            label, kind = status_map.get(raw.lower(), (raw, ""))
            elapsed = number(result.get("ms"))
            timing = f'<div class="fetch-time">{fmt(elapsed / 1000)} 秒</div>' if elapsed is not None else ""
            cells.append(f'<td><span class="badge {kind}">{esc(label)}</span><p class="fetch-note">{esc(result.get("note"))}</p>{timing}</td>')
        body.append(f'<tr><td><span class="fetch-title">{esc(row.get("name"))}</span><span class="small">{esc(row.get("id"))} · {esc(row.get("kind"))}</span></td>{"".join(cells)}</tr>')
    headers = "".join(f'<th>{provider_label(provider)}</th>' for provider in providers)
    return f'<div class="table-scroll"><table class="fetch-table"><thead><tr><th>读取样例</th>{headers}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def group_html(group: dict, provider: dict) -> str:
    results = []
    for result in group.get("results", []):
        title = result.get("title") or result.get("url") or "未提供标题"
        tags = "".join(f'<span title="{esc(description)}">{label} {fmt(result.get(key), 0)} / {maximum}</span>' for key, label, maximum, description in [
            ("r", "相关", 2, "直接相关性，0–2分"), ("q", "质量", 3, "证据与来源质量，0–3分"), ("u", "摘录", 2, "摘录可用性，0–2分")])
        results.append(f'<li><div class="source-title"><span class="rank">{esc(result.get("rank", ""))}</span>{link(title, result.get("url"))}</div><div class="source-domain">{esc(domain(result.get("url")))}</div><div class="score-tags">{tags}</div></li>')
    listing = f'<ol class="result-list">{"".join(results)}</ol>' if results else '<p class="empty">本组无返回结果。</p>'
    return (
        f'<article class="result-group"><div class="group-head"><div class="group-name">{provider_label(provider)}</div>'
        f'<div class="group-score">{fmt(group.get("score"))}<small> / 100</small></div></div>'
        f'<div class="group-metrics"><span>覆盖度 {fmt(group.get("coverage"), 0)} / 4</span><span>约束满足 {fmt(group.get("constraint"), 0)} / 2</span></div>'
        f'<p class="group-note">{esc(group.get("note"))}</p>{listing}</article>'
    )


def case_html(case: dict, providers: dict[str, dict]) -> str:
    groups = []
    scores = []
    for group in case.get("groups", []):
        provider = providers.get(group.get("provider"), {"name": group.get("name") or group.get("provider") or "未命名工具", "color": MUTED})
        groups.append(group_html(group, provider))
        scores.append(f'<span class="mini-score" style="--provider:{esc(provider["color"])}"><span class="dot"></span><span>{esc(provider["name"])} {fmt(group.get("score"))}</span></span>')
    lang = {"zh": "中文", "en": "英文"}.get(case.get("language"), case.get("language", ""))
    search_text = json.dumps(case, ensure_ascii=False)
    return (
        f'<details class="case-card" id="case-{esc(case.get("id"))}" data-category="{esc(case.get("category"))}" data-language="{esc(case.get("language"))}" data-search="{esc(search_text)}">'
        f'<summary><div class="case-title"><div class="case-meta"><span class="case-id">{esc(case.get("id"))}</span><span>·</span><span>{esc(case.get("category"))}</span><span>·</span><span>{esc(lang)}</span></div>'
        f'<div class="case-query">{esc(case.get("query"))}</div></div><div class="case-scores">{"".join(scores)}</div></summary>'
        f'<div class="case-body"><p class="criteria"><strong>核验条件</strong>　{esc(text_value(case.get("criteria")))}</p><div class="result-groups">{"".join(groups)}</div></div></details>'
    )


def cases_html(cases: list[dict], providers: list[dict]) -> str:
    categories = list(dict.fromkeys(str(case.get("category") or "") for case in cases))
    languages = list(dict.fromkeys(str(case.get("language") or "") for case in cases))
    options = "".join(f'<option value="{esc(category)}">{esc(category)}</option>' for category in categories)
    language_options = "".join(f'<option value="{esc(language)}">{esc({"zh": "中文", "en": "英文"}.get(language, language))}</option>' for language in languages)
    providers_by_id = {provider["id"]: provider for provider in providers}
    content = "".join(case_html(case, providers_by_id) for case in cases)
    return (
        '<noscript><p class="noscript">当前未启用 JavaScript。所有查询仍可展开查看，筛选功能需启用 JavaScript。</p></noscript>'
        '<div class="filters"><label class="field">检索逐题记录<input id="case-search" type="search" placeholder="查询、标题、域名、评分理由…" autocomplete="off"></label>'
        f'<label class="field">场景<select id="case-category"><option value="">全部场景</option>{options}</select></label>'
        f'<label class="field">语言<select id="case-language"><option value="">全部语言</option>{language_options}</select></label></div>'
        f'<div class="filter-actions"><span id="case-counter" role="status" aria-live="polite">显示 {len(cases)} / {len(cases)} 道查询</span>'
        '<div class="action-group"><button class="quiet-button" id="expand-cases" type="button">展开筛选结果</button><button class="quiet-button" id="collapse-cases" type="button">全部收起</button><button class="quiet-button" id="reset-filters" type="button">重置筛选</button></div></div>'
        f'<div id="case-list">{content}</div><p id="case-empty" class="empty-state" hidden>没有匹配的查询。请调整关键词或筛选条件。</p>'
    )


def audits_html(audits: list[dict], providers: list[dict]) -> str:
    if not audits:
        return ""
    names = {provider["id"]: provider["name"] for provider in providers}
    rows = []
    for audit in audits:
        cid = audit.get("case_id", "")
        rows.append(f'<tr><td><a href="#case-{esc(cid)}">{esc(cid)}</a><br><span class="small">{esc(names.get(audit.get("provider"), audit.get("provider", "")))}</span></td><td>{link(domain(audit.get("url")), audit.get("url"))}</td><td>{esc(audit.get("note"))}</td></tr>')
    return f'<details class="audit-details"><summary>来源复核记录 · {len(audits)} 条</summary><div class="table-scroll"><table class="audit-table"><thead><tr><th>查询 / 工具</th><th>来源</th><th>复核说明</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>'


def validate(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("报告数据必须为 JSON 对象")
    for key, expected in [("meta", dict), ("providers", list), ("cases", list)]:
        if not isinstance(data.get(key), expected):
            raise ValueError(f"缺少或无效的字段：{key}")
    if not data["providers"]:
        raise ValueError("providers 不能为空")
    identifiers = set()
    for index, provider in enumerate(data["providers"]):
        if not provider.get("id") or not provider.get("name"):
            raise ValueError("每个 provider 必须有 id 和 name")
        if provider["id"] in identifiers:
            raise ValueError(f"重复的 provider id：{provider['id']}")
        identifiers.add(provider["id"])
        color = provider.get("color")
        provider["color"] = color if isinstance(color, str) and len(color) in (4, 7) and color.startswith("#") and all(char in "0123456789abcdefABCDEF" for char in color[1:]) else PALETTE[index % len(PALETTE)]
        for key in ["score", "academic", "news", "seo", "zh", "en", "low_quality_pct", "relevant_pct", "usable_pct", "success_pct"]:
            value = number(provider.get(key))
            if value is not None and not 0 <= value <= 100:
                raise ValueError(f"{provider['id']}.{key} 必须在 0–100 范围内")
        for key in ["median_ms", "p90_ms", "mean_chars"]:
            value = number(provider.get(key))
            if value is not None and value < 0:
                raise ValueError(f"{provider['id']}.{key} 不得为负值")
    for category in data.get("categories", []):
        for key, raw in category.get("values", {}).items():
            value = number(raw)
            if value is not None and not 0 <= value <= 100:
                raise ValueError(f"分类 {category.get('name')} 的 {key} 得分超出 0–100")


def build(data: dict, destination: Path) -> Path:
    validate(data)
    setup_fonts()
    meta = data["meta"]
    providers = data["providers"]
    charts = Charts(destination / "charts", providers)
    charts.overall()
    charts.categories(data.get("categories", []))
    charts.categories(data.get("academic_breakdown", []), 'academic-breakdown')
    charts.languages()
    charts.quality()
    charts.operations()
    charts.supplement(data.get("supplement", {}))
    legend = "".join(provider_label(provider) for provider in providers)
    metrics = [("查询样本", fmt(meta.get("queries"), 0)), ("学术查询", fmt(meta.get("academic_queries"), 0)),
               ("中 / 英", f'{fmt(meta.get("zh"), 0)} / {fmt(meta.get("en"), 0)}'), ("主实验搜索调用", fmt(meta.get("search_calls"), 0)),
               ("补测搜索调用", fmt(meta.get("supplement_calls"), 0)), ("网页读取调用", fmt(meta.get("fetch_calls"), 0))]
    metrics_html = "".join(f'<dl><dt>{esc(label)}</dt><dd>{value}</dd></dl>' for label, value in metrics)
    rubric = text_value(meta.get("rubric"))
    limitations = "".join(f'<li>{esc(text_value(item))}</li>' for item in meta.get("limitations", []))
    supplement_note = text_value(data.get("supplement", {}).get("note"))
    supplement_explanation = "“学术改用通用路由后的总体分”将主实验学术题的 AnySearch 成绩替换为同查询通用搜索补测成绩，其余查询保持不变，再计算总体均分。它属于后续诊断，不属于同一次主实验，也不取两种路由的较高分。"
    content = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><meta name="description" content="搜索工具基准测试：首轮证据检索、来源质量、语言、时延与逐题核验记录。"><title>搜索工具基准测试 · {esc(meta.get("date"))}</title><style>{CSS}</style></head>
<body><main id="top">
<header><div class="eyebrow">BENCHMARK REPORT · {esc(meta.get("date"))}</div><h1>搜索工具基准测试</h1><p class="subtitle">围绕 AI 代理首轮证据检索，比较查询覆盖、来源质量与实际可用性。所有成绩仅描述本批样例，逐题理由和来源可在下方追溯。</p><div class="provider-legend">{legend}</div><div class="meta-strip">{metrics_html}</div></header>
<div class="nav-wrap"><nav class="nav" aria-label="报告章节"><a href="#overview">结果总览</a><a href="#scenarios">场景与语言</a><a href="#quality">来源质量</a><a href="#operations">延迟与体量</a><a href="#supplement">学术补测</a><a href="#fetch">网页读取</a><a href="#cases">逐题追溯</a><a href="#method">方法与限制</a></nav></div>
<section class="section" id="overview">{section_head("01", "结果总览", "主实验成绩按原始首轮路由计算。综合分为 0–100 分，越高表示本批查询中的证据检索表现越好。")}{charts.element("overall", "总体分为逐查询得分的均值。学术路由补测在独立章节展示，不覆盖主实验成绩。")}{overview_table(providers)}{findings_html(data.get("findings", []))}</section>
<section class="section" id="scenarios">{section_head("02", "场景与语言", "观察不同任务中的表现差异，结合具体查询判断工具是否适合当前工作。")}{charts.element("categories", "各场景得分按该场景查询汇总；全部得分轴从 0 开始。不同场景的查询难度与样本量可能不同。")}<div class="subsection"><h3>中文与英文</h3>{charts.element("languages", "中英文分别汇总。同主题查询存在配对关系，不将其视为完全独立样本进行显著性推断。")}</div></section>
<section class="section" id="quality">{section_head("03", "来源质量与摘录可用性", "从返回结果观察相关性、证据强弱和摘录能否支持下一步核验。")}{charts.element("source-quality", "直接相关：相关性=2；有用摘录：可用性=2；低证据来源：质量≤1。比例基于实际返回结果，不等同于全网召回率。")}<p class="note">低证据来源可能是转载、聚合或证据薄弱的商业内容；仅凭摘要和排名无法断言 SEO 动机或搜索引擎内部反作弊机制。</p></section>
<section class="section" id="operations">{section_head("04", "延迟与返回体量", "单次调用墙钟耗时反映本次运行体验；字符量用于描述代理收到的信息规模。")}{charts.element("operations", "延迟以秒显示；返回字符量不是精确 token 数，也不代表信息质量。各子图独立刻度，均从 0 开始。")}<p class="notice">原生与AnySearch采集并发4，DeepSeek串行，网络路径、缓存与工具调度也不同。这些数值仅描述本次运行，不能用作严格速度排名、稳定SLA或吞吐能力推断。</p></section>
<section class="section" id="supplement">{section_head("05", "学术任务与路由补测", "30条学术查询覆盖原始文献、方法、数据、撤稿、证据综述，以及2026年10月的新论文。")}{charts.element('academic-breakdown', '按任务性质分组展示主实验成绩；分组为描述性分析，样本量不同。具体题号见 report-data.json。')}<div class="subsection"><h3>AnySearch：同题通用路由补测</h3>{charts.element("academic-supplement", "前两项仅比较学术题；第三项是替换学术题路由后重新汇总的总体分，统计范围不同。") }</div><div class="notice">{esc(supplement_explanation)}{f'<br><br>{esc(supplement_note)}' if supplement_note else ''}</div></section>
<section class="section" id="fetch">{section_head("06", "网页读取与支持边界", "网页读取独立记录，不计入搜索综合分。状态和备注用于区分成功读取、工具限制与页面限制。")}{fetch_html(data.get("fetch", []), providers)}</section>
<section class="section" id="cases">{section_head("07", "逐题追溯", "按场景、语言或关键词筛选。展开查询可查看核验条件、评分理由与返回来源。") }<div class="rubric-keys"><span>相关性 0–2</span><span>来源质量 0–3</span><span>摘录可用性 0–2</span><span>覆盖度 0–4</span><span>约束满足 0–2</span></div>{cases_html(data["cases"], providers)}{audits_html(data.get("audits", []), providers)}</section>
<section class="section" id="method">{section_head("08", "方法与限制", "评分范围、计量口径与解释边界。结论应连同这些条件一并使用。") }<div class="method-grid"><div><h3>评分口径</h3><div class="rubric">{esc(rubric) if rubric else '本次数据未附评分公式，请结合逐题评审记录阅读。'}</div><p>逐结果记录相关性、来源质量、摘录可用性；逐查询记录覆盖度与约束满足。失败或空结果按评分协议处理，不以缺失值冒充已测结果。</p><p>复现基线　<code class="baseline">{esc(meta.get("baseline_commit") or '未提供')}</code></p></div><div><h3>解释边界</h3><ul>{limitations}</ul></div></div></section>
<footer><span>评测日期：{esc(meta.get("date"))} · 图表可导出 PNG / SVG · 页面内置图表，可离线阅读</span><a class="back-top" href="#top">返回顶部 ↑</a></footer>
</main><script>{JS}</script></body></html>'''
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / "report.html"
    output.write_text('\n'.join(line.rstrip() for line in content.splitlines()) + '\n', encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="从真实评审数据生成中文搜索基准报告与 PNG/SVG 图表")
    parser.add_argument("--input", type=Path, default=HERE / "report-data.json", help="输入报告数据 JSON")
    parser.add_argument("--output-dir", type=Path, default=HERE, help="report.html 与 charts/ 输出目录")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"真实报告数据尚未写入：{args.input}。请先提供 report-data.json；不会生成示例结果。")
    try:
        data = json.loads(args.input.read_text(encoding="utf-8-sig"))
        result = build(data, args.output_dir.resolve())
    except (ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(f"已生成报告：{result}")
    print(f"图表目录：{result.parent / 'charts'}")
    print(f"查询明细：{len(data['cases'])}；工具：{len(data['providers'])}")


if __name__ == "__main__":
    main()
