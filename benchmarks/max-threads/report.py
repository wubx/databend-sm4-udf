#!/usr/bin/env python3
"""Validate a complete max_threads run and publish a sanitized snapshot."""
import argparse
import csv
import json
from pathlib import Path
import re
import statistics

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
DEFAULT_REPORT_DIR=ROOT/'reports/max-threads'
LABELS={'native_md5':'内置 MD5','wasm_md5':'WASM MD5','sm4_wasm':'WASM SM4','sm4_js':'JS SM4'}


def summarize(record):
    assert record.get('complete') is True,'Benchmark incomplete'
    assert record.get('cleanup_errors')==[],'Cleanup failed'
    m=record['metadata'];assert m['result_cache'] is False and m['warmups']==1 and m['repeats']>=3
    assert m['threads'][0]==1
    cases=[tuple(c) for c in m['cases']]
    count=len(cases)*len(m['threads'])*(m['repeats']+1)
    assert len(record['samples'])==count,'Missing measured queries'
    rows=[]
    for length,n,impl in cases:
        checksums=set()
        for t in m['threads']:
            samples=[s for s in record['samples'] if (s['length'],s['rows'],s['impl'],s['threads'])==(length,n,impl,t)]
            warm=[s for s in samples if s['phase']=='warmup'];formal=[s for s in samples if s['phase']=='measure']
            assert len(warm)==1 and len(formal)==m['repeats']
            assert {s['repeat'] for s in formal}==set(range(m['repeats']))
            checksums|={s['checksum'] for s in samples}
            times=[s['server_ms'] for s in formal];median=statistics.median(times)
            assert min(times)>=0
            rows.append({'length':length,'rows':n,'impl':impl,'threads':t,'median_ms':median,
                'min_ms':min(times),'max_ms':max(times),'samples':len(times)})
        assert len(checksums)==1,'Checksum differs between thread counts'
    base={(r['length'],r['rows'],r['impl']):r['median_ms'] for r in rows if r['threads']==1}
    for r in rows:r['speedup']=round(base[r['length'],r['rows'],r['impl']]/r['median_ms'],3)
    return {'schema':1,'complete':True,'metadata':m,'tables':record['tables'],'pipelines':record['pipelines'],
            'timed_query_count':count,'summary':rows,'samples':record['samples']}


def table(head,rows):
    return '\n'.join(['| '+' | '.join(head)+' |','| '+' | '.join(['---']*len(head))+' |']+
        ['| '+' | '.join(map(str,r))+' |' for r in rows])


def udf_pipes(lines):
    """Number of parallel UDF processors in an `EXPLAIN PIPELINE` graph (one node per pipe)."""
    count=sum(1 for line in lines if re.search(r'label = "UDF\w*Transform"',line))
    return count or None


def render(e):
    m=e['metadata'];threads=m['threads'];cases=[tuple(c) for c in m['cases']]
    idx={(r['length'],r['rows'],r['impl'],r['threads']):r for r in e['summary']}
    head=['实现','B/行','行数',*[f'{t} 线程' for t in threads],'最大提升']
    timing=[];speed=[];ranges=[]
    for length,n,impl in cases:
        values=[idx[length,n,impl,t] for t in threads]
        best=max(values,key=lambda r:r['speedup'])
        label=[LABELS[impl],f'{length:,}',f'{n:,}']
        timing.append(label+[f'{r["median_ms"]:,.0f}' for r in values]+[f'{best["speedup"]:.2f}×（{best["threads"]} 线程）'])
        speed.append(label+[f'{r["speedup"]:.2f}×' for r in values])
        ranges.append(label+[f'{r["min_ms"]:,}–{r["max_ms"]:,}' for r in values])
    gaps=[]
    for length,n in sorted({(c[0],c[1]) for c in cases}):
        gaps.append([f'{length:,}',f'{n:,}']+[f'{idx[length,n,"wasm_md5",t]["median_ms"]/idx[length,n,"native_md5",t]["median_ms"]:.2f}×' for t in threads])
    blocks=[[f'{int(k.split("x")[0]):,} B × {v["rows"]:,} 行',v['blocks']] for k,v in e['tables'].items()]
    pipes=[[t,udf_pipes(e['pipelines'][str(t)]) or '未识别'] for t in threads]
    thread_args=','.join(map(str,threads))
    text=[f'# max_threads 扩展：{threads[0]}–{threads[-1]} 线程\n',
        '**状态：完整测量已结束，所有线程数下的结果校验一致，临时对象已清理。** '
        '单线程对比见 [SM4 三端](../sm4-backends/REPORT.md) 和 [MD5 内置 vs WASM](../md5-native-vs-wasm/rows-100k-1m/REPORT.md)，'
        '其他报告见 [报告索引](../README.md)。\n',
        '## 1. 测试目标与环境\n',
        '同一条 SQL 只改 `max_threads`，观察内置函数、WASM UDF 和 JS UDF 能否随线程数并行加速，以及加线程后内置与 WASM 的差距如何变化。\n',
        table(['项目','值'],[['Databend',m['version']],['CPU',m['cpu']],['宿主逻辑 CPU',m['logical_cpus']],
            ['max_threads',thread_args],['max_block_size',m['max_block_size']],
            ['表引擎',f'Fuse，`ROW_PER_BLOCK = {m["row_per_block"]}`'],['结果缓存','关闭'],
            ['SM4 用例',f'`{m["profile"]}`、{m["mode"]} 解密'],['Rust',m['rustc']],
            ['开始 UTC',m['started_at']],['结束 UTC',m['finished_at']]]),
        '\n- 每个规模单独建表并写成多个数据块；计时 SQL 为 `SELECT count(*), sum(siphash64(expr)) FROM t`，不带 `LIMIT`，'
        '让扫描和 UDF 能分给多个线程。单线程报告使用 Memory 表加 `LIMIT`，两者的 SQL 形态不同。',
        f'- 每组预热 1 次、正式 {m["repeats"]} 次，正式顺序用固定种子打乱，取服务端 SQL 耗时中位数。'
        '建表、写数据、上传和注册不计时。',
        '- 每次查询的 count 与 checksum 都和预先计算的期望值一致：MD5 对照内置 `md5()`，SM4 解密对照原文；'
        '写入前用 WASM 加密，并抽查 257 行确认 WASM 与 JS 解密都还原原文。',
        f'- 共 {e["timed_query_count"]} 次计时查询。JS 只测 1,024 B × 5 万行，单线程约 80 秒。\n',
        table(['表','数据块数'],blocks),
        '\n`EXPLAIN PIPELINE` 中 WASM MD5 查询的 UDF 处理器个数：\n',
        table(['max_threads','UDF 处理器'],pipes),
        '\n## 2. 耗时中位数（毫秒）\n',
        table(head,timing),
        '\n## 3. 相对 1 线程的加速倍数\n',
        table(head[:-1],speed),
        '\n## 4. WASM MD5 / 内置 MD5 耗时比\n',
        table(['B/行','行数',*[f'{t} 线程' for t in threads]],gaps),
        '\n比值越大，WASM 相对内置越慢。\n',
        '## 5. 正式测量 min–max（毫秒）\n',
        table(head[:-1],ranges),
        '\n## 6. 如何解读\n',
        '- 数据量越大，加线程越有用：每次查询的 WASM 运行时创建和模块编译是固定开销，只发生一次，加线程摊不掉；'
        '数据块数少于线程数时，多出的线程也没有活干。',
        '- 内置函数的并行扩展最好，WASM 次之，所以线程越多，内置与 WASM 的耗时比越大。'
        'WASM 在 8 线程之后提升变小的原因没有在本测试中定位。',
        '- Databend 每次查询创建一个 WASM 运行时，各线程从同一运行时的实例池中取实例执行（依据本地 Databend 源码）。',
        '- 单机测量，未绑核，最多测到 16 线程；未测并发 QPS、峰值内存或多节点。\n',
        '## 7. 复现\n',
        '先构建两个 WASM 工件（见 [README](../../README.md) 与 [MD5 实验说明](../../benchmarks/native-vs-wasm/README.md)），'
        '然后在有管理员批准的独立测试实例运行：\n',
        f'```bash\nexport SM4_URL=http://127.0.0.1:8000\nexport SM4_USER=root\nexport SM4_PASSWORD=\'\'\n'
        f'.venv/bin/python benchmarks/max-threads/benchmark.py --threads {thread_args} --repeats {m["repeats"]}\n```\n',
        '1,024 B × 100 万行约 1 GiB 原文，加上密文列约 2 GiB，请预留存储与内存。自定义 `CARGO_TARGET_DIR` 时用 '
        '`--sm4-wasm` / `--md5-wasm` 指定工件。用完整原始记录重新生成本页：\n',
        '```bash\n.venv/bin/python benchmarks/max-threads/report.py --input results/max-threads.json\n```\n',
        f'- WASM SHA256：SM4 `{m["wasm_sha256"]["sm4"]}`，MD5 `{m["wasm_sha256"]["md5"]}`。'
        '源码指纹、完整 `EXPLAIN PIPELINE` 和逐次计时见 [results.json](results.json)。\n']
    return '\n'.join(text).rstrip()+'\n'


def publish(record,directory=DEFAULT_REPORT_DIR):
    evidence=summarize(record)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'results.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')
    (directory/'REPORT.md').write_text(render(evidence))
    fields=['length','rows','impl','threads','median_ms','min_ms','max_ms','samples','speedup']
    with (directory/'results.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(evidence['summary'])
    return evidence


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--report-dir',type=Path,default=DEFAULT_REPORT_DIR)
    args=p.parse_args();publish(json.loads(args.input.read_text()),args.report_dir)
