#!/usr/bin/env python3
"""Render the SVG charts used by docs/ARCHITECTURE.md from published report CSVs.

Dependency-free: reads reports/*/results.csv and writes docs/images/*.svg.
"""
from pathlib import Path
from xml.sax.saxutils import escape
import csv
import math

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/images'
FONT = "font-family='-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,Microsoft YaHei,sans-serif'"
COLORS = {'wasm': '#2f6fde', 'js': '#e8a33d', 'python': '#4c9a6a', 'native': '#7a52c7'}


def load(path):
    with (ROOT / path).open(newline='') as stream:
        return {(int(r['length']), int(r['rows']), r['impl']): float(r['median_ms']) for r in csv.DictReader(stream)}


def svg(width, height, title, desc, body):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' width='{width}' height='{height}' "
            f"role='img' aria-labelledby='t d' {FONT}>\n<title id='t'>{escape(title)}</title>\n<desc id='d'>{escape(desc)}</desc>\n"
            f"<rect width='100%' height='100%' fill='#ffffff'/>\n{body}</svg>\n")


def text(x, y, value, size=13, anchor='start', color='#333', weight='normal'):
    return f"<text x='{x:.1f}' y='{y:.1f}' font-size='{size}' text-anchor='{anchor}' fill='{color}' font-weight='{weight}'>{escape(value)}</text>\n"


def bar_chart(name, title, desc, bars, unit):
    """Horizontal bars: list of (label, value, color)."""
    width, left, right, top, row = 760, 150, 120, 56, 46
    height = top + row * len(bars) + 24
    peak = max(v for _, v, _ in bars)
    body = text(20, 30, title, 17, weight='bold')
    for i, (label, value, color) in enumerate(bars):
        y = top + i * row
        length = max(3, (width - left - right) * value / peak)
        body += text(left - 12, y + 21, label, 14, 'end')
        body += f"<rect x='{left}' y='{y + 6}' width='{length:.1f}' height='22' rx='3' fill='{color}'/>\n"
        body += text(left + length + 8, y + 22, f'{value:,.3f} {unit}', 13, weight='bold')
    (OUT / name).write_text(svg(width, height, title, desc, body))


def short(n):
    return f'{n // 1_000_000}M' if n >= 1_000_000 else f'{n // 1000}K' if n >= 1000 else str(n)


def line_chart(name, title, desc, xs, series, y_label, reference=None, ticks=None, label_right=False, x_label='行数（对数刻度）'):
    """Log-x line chart: series is list of (label, color, [y per x])."""
    width, height, left, right, top, bottom = 760, 380, 70, 170, 56, 64
    plot_w, plot_h = width - left - right, height - top - bottom
    peak = max(max(values) for _, _, values in series) * 1.1
    lo, hi = math.log10(xs[0]), math.log10(xs[-1])
    px = lambda x: left + plot_w * (math.log10(x) - lo) / (hi - lo)
    py = lambda y: top + plot_h * (1 - y / peak)
    step = 10 ** math.floor(math.log10(peak / 4))
    step = next(s * step for s in (1, 2, 5, 10) if peak / (s * step) <= 6)
    body = text(20, 30, title, 17, weight='bold')
    tick = 0.0
    while tick <= peak:
        body += f"<line x1='{left}' x2='{left + plot_w}' y1='{py(tick):.1f}' y2='{py(tick):.1f}' stroke='#e5e5e5'/>\n"
        body += text(left - 8, py(tick) + 4, f'{tick:g}', 12, 'end', '#666')
        tick += step
    if reference is not None:
        body += f"<line x1='{left}' x2='{left + plot_w}' y1='{py(reference):.1f}' y2='{py(reference):.1f}' stroke='#c0392b' stroke-dasharray='5 4'/>\n"
        body += text(left + plot_w - 6 if label_right else left + 6, py(reference) - 6, f'{reference:g}× 持平线', 12,
                     'end' if label_right else 'start', '#c0392b')
    for x in ticks or xs:
        body += text(px(x), top + plot_h + 20, short(x), 12, 'middle', '#666')
    body += text(left + plot_w / 2, height - 14, x_label, 12, 'middle', '#666')
    body += f"<text x='18' y='{top + plot_h / 2:.1f}' font-size='12' fill='#666' text-anchor='middle' transform='rotate(-90 18 {top + plot_h / 2:.1f})'>{escape(y_label)}</text>\n"
    for i, (label, color, values) in enumerate(series):
        points = ' '.join(f'{px(x):.1f},{py(y):.1f}' for x, y in zip(xs, values))
        body += f"<polyline points='{points}' fill='none' stroke='{color}' stroke-width='2.5'/>\n"
        body += ''.join(f"<circle cx='{px(x):.1f}' cy='{py(y):.1f}' r='4' fill='{color}'/>\n" for x, y in zip(xs, values))
        body += f"<rect x='{left + plot_w + 24}' y='{top + 8 + i * 24}' width='14' height='4' fill='{color}'/>\n"
        body += text(left + plot_w + 44, top + 14 + i * 24, f'{label}：{values[-1]:.1f}×', 12)
    (OUT / name).write_text(svg(width, height, title, desc, body))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sm4 = load('reports/sm4-backends/results.csv')
    bar_chart('sm4-1024b-50k.svg', 'SM4 CBC 解密：1,024 B × 50,000 行（耗时越短越好）',
              'WASM、JS、Python Server 三种 UDF 完成同一查询的中位耗时（秒）。',
              [('WASM', sm4[1024, 50000, 'wasm'] / 1000, COLORS['wasm']),
               ('JavaScript', sm4[1024, 50000, 'js'] / 1000, COLORS['js']),
               ('Python Server', sm4[1024, 50000, 'python'] / 1000, COLORS['python'])], 's')

    rows = sorted({r for _, r, _ in sm4})
    line_chart('sm4-wasm-vs-js.svg', 'SM4：WASM 比 JS 快多少倍（JS 耗时 ÷ WASM 耗时）',
               '不同明文长度下，随行数增加 WASM 相对 JS 的加速倍数；低于 1 表示 JS 更快。',
               rows, [(f'{n:,} B/行', c, [sm4[n, r, 'js'] / sm4[n, r, 'wasm'] for r in rows])
                      for n, c in [(16, '#9bbcf2'), (128, '#5a8fe6'), (1024, COLORS['wasm'])]],
               '加速倍数', reference=1, label_right=True)

    small, large = load('reports/md5-native-vs-wasm/rows-1-50k/results.csv'), load('reports/md5-native-vs-wasm/rows-100k-1m/results.csv')
    md5 = {**small, **large}
    md5_rows = sorted({r for n, r, i in md5 if i == 'native_md5'})
    line_chart('md5-native-vs-wasm.svg', 'MD5：WASM 耗时是内置函数的几倍（越接近 1 越好）',
               '1 到 100 万行时 WASM MD5 与内置 md5() 的耗时比；1–5 万行与 10–100 万行为两轮独立测量。',
               md5_rows, [(f'{n:,} B/行', c, [md5[n, r, 'wasm_md5'] / md5[n, r, 'native_md5'] for r in md5_rows])
                          for n, c in [(16, '#c3aee8'), (128, '#9d7fd8'), (1024, COLORS['native'])]],
               '耗时比（WASM ÷ 内置）', reference=1, ticks=[1, 100, 1000, 10000, 100000, 1000000])
    print('Generated', ', '.join(sorted(p.name for p in OUT.glob('*.svg'))))


if __name__ == '__main__':
    main()
