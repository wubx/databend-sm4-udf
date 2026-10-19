#!/usr/bin/env python3
"""Validate a complete native-vs-WASM run and publish a sanitized snapshot."""
import argparse
import csv
import json
from pathlib import Path
import statistics

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
REPORTS=ROOT/'reports/md5-native-vs-wasm'
DEFAULT_REPORT_DIR=REPORTS/'rows-1-50k'
LARGE_REPORT_DIR=REPORTS/'rows-100k-1m'
IMPLS=('native_md5','wasm_md5','sql_identity','wasm_identity')


def summarize(record):
    assert record.get('complete') is True,'Benchmark incomplete'
    assert record.get('cleanup_errors')==[],'Cleanup failed'
    m=record['metadata'];assert m['max_threads']==1 and m['result_cache'] is False
    assert m['repeats']>=3 and m['warmups']==1
    impls=tuple(m.get('implementations',IMPLS))
    assert impls in (IMPLS,('native_md5','wasm_md5')),'Unsupported implementation set'
    count=len(m['rows'])*len(m['lengths'])*len(impls)*(m['repeats']+1)
    assert len(record['samples'])==count,'Missing measured queries'
    rows=[];public=[]
    for length in m['lengths']:
        for n in m['rows']:
            checksums={'md5':set(),'identity':set()}
            for impl in impls:
                samples=[s for s in record['samples'] if (s['length'],s['rows'],s['impl'])==(length,n,impl)]
                warm=[s for s in samples if s['phase']=='warmup'];formal=[s for s in samples if s['phase']=='measure']
                assert len(warm)==1 and len(formal)==m['repeats']
                assert {s['repeat'] for s in formal}==set(range(m['repeats']))
                for s in samples:
                    assert len(s['data'])==1 and s['data'][0][0]==str(n) and s['data'][0][1] is not None
                    checksums['md5' if impl.endswith('md5') else 'identity'].add(s['data'][0][1])
                    public.append({k:s[k] for k in ['length','rows','impl','phase','repeat','server_ms','wall_ms']}|
                                  {'checksum':s['data'][0][1]})
                times=[s['server_ms'] for s in formal];median=statistics.median(times)
                assert min(times)>=0
                rows.append({'length':length,'rows':n,'impl':impl,'median_ms':median,'min_ms':min(times),
                    'max_ms':max(times),'samples':len(times),'rows_per_second':None if median==0 else n*1000/median})
            assert len(checksums['md5'])==1,'MD5 checksum mismatch'
            if 'wasm_identity' in impls:assert len(checksums['identity'])==1,'Identity checksum mismatch'
    return {'schema':1,'complete':True,'metadata':m,'validation':record['validation'],
            'timed_query_count':count,'summary':rows,'samples':public}


def table(head,rows):
    return '\n'.join(['| '+' | '.join(head)+' |','| '+' | '.join(['---']*len(head))+' |']+
        ['| '+' | '.join(map(str,r))+' |' for r in rows])


def render(e):
    if tuple(e['metadata'].get('implementations',IMPLS))==('native_md5','wasm_md5'):
        return render_md5_only(e)
    m=e['metadata'];idx={(r['length'],r['rows'],r['impl']):r for r in e['summary']}
    timings=[];identity=[];spreads=[]
    for length in m['lengths']:
        for count in m['rows']:
            n,w,b,i=[idx[length,count,impl] for impl in IMPLS]
            ratio='不可分辨' if n['median_ms']==0 else f'{w["median_ms"]/n["median_ms"]:.1f}×'
            timings.append([length,f'{count:,}',n['median_ms'],w['median_ms'],ratio])
            identity.append([length,f'{count:,}',b['median_ms'],i['median_ms']])
            spreads.append([length,f'{count:,}',f'{n["min_ms"]}–{n["max_ms"]}',f'{w["min_ms"]}–{w["max_ms"]}'])
    text=['# Databend 内置 MD5 与 WASM UDF：1–5 万行\n',
        '**状态：完整测试已结束，所有结果校验一致。** MD5 仅作为计算样本，不用于安全用途。'
        '10 万至 100 万行见 [大行数报告](../rows-100k-1m/REPORT.md)，其他报告见 [报告索引](../../README.md)。\n',
        '## 1. 对比什么\n',
        '- 内置：`md5(data)`，Query 原生 Rust 表达式内执行。',
        '- WASM：`md5_wasm(data)`，`md-5 = 0.10.6`、同一算法库，输出相同的小写 32 字符 Hex STRING。',
        '- SQL 基线：直接返回 `data`，无 UDF、无 MD5。',
        '- WASM identity：`identity_wasm(data)`，不计算 MD5，仅按相同 STRING ABI 返回输入。',
        '- 实际测试注册唯一前缀的临时名字，不替换内置函数或当前 SM4 函数。输入均 STRING，NULL 向下传播。\n',
        '库版本对齐依据本地 Databend 源码和 Cargo.lock，未重编译原生 Query。Native 与 WASM 的 target/编译配置、内存/结果构建路径不同：原生按列写入结果 buffer，WASM 标量返回 String。\n',
        '## 2. 环境与方法\n',
        table(['项目','值'],[['Databend',m['version']],['CPU',m['cpu']],['逻辑 CPU',m['logical_cpus']],
            ['Query max_threads',m['max_threads']],['max_block_size',m['max_block_size']],['表引擎',m['engine']],
            ['结果缓存','关闭'],['Rust',m['rustc']],['开始 UTC',m['started_at']],['结束 UTC',m['finished_at']]]),
        f'\n- 输入长度 `{m["lengths"]}` B，行数 `{m["rows"]}`；由带行号的 `Hello Databend` 模式生成，截断/重复到目标字节数。',
        f'- 每组预热 1 次，正式 {m["repeats"]} 次；正式顺序用固定种子打乱，取服务端 SQL 中位数。',
        '- 准备数据、上传/注册不计时；每次 SQL 的 WASM 初始化/编译、Arrow 转换、扫描/hash 聚合都计时。',
        '- `count(*)` 和 `sum(siphash64(result))` 消费结果，避免表达式被裁剪，且不返回大结果集到客户端。',
        '- MD5 两端每次 checksum 与原生预计算值一致；identity 两端每次与原文 checksum 一致。',
        f'- {e["validation"]["edge_cases"]} 个空值/空串/标准文本/中文/emoji/零字节/长度边界用例，对照 Python hashlib 独立期望。',
        '- 每种长度另抽查最多 257 行逐行结果；计时中校验完整数据的 count/hash。',
        f'- 共 {e["timed_query_count"]} 次计时查询；原始记录在忽略的 results/ 下，脱敏快照为 results.json。\n',
        '## 3. 完整 SQL 耗时中位数（毫秒）\n',
        table(['输入 B/行','行数','内置 md5','WASM md5','WASM/内置耗时'],timings),
        '\n最后一列越大表示 WASM 相对耗时越高；极小查询受毫秒计时精度、调度和固定成本影响较大。\n',
        '## 4. 无 MD5 计算的基线（毫秒）\n',
        table(['输入 B/行','行数','SQL 原文基线','WASM identity'],identity),
        '\nIdentity 用于观察执行边界开销。MD5 输出固定 32 字符，identity 输出与输入等长，两者输出量和内存分配不同。\n',
        '## 5. 正式测量 min–max（毫秒）\n',
        table(['输入 B/行','行数','内置 md5 范围','WASM md5 范围'],spreads),
        '\n## 6. 如何解读\n',
        '- 原生内置函数没有 WASM 边界，能直接使用 Query 的列式执行和结果 buffer；已有语义满足需求时应优先使用内置函数。',
        '- WASM 比当前纯 Python/JS SM4 快，但比原生函数慢。',
        '- 小规模由 WASM 固定成本主导；更大输入会摊薄固定成本，逐行 ABI、分配和编译 target 的差异仍然存在。',
        '- 计时为完整 SQL；未测并发 QPS、多线程、冷进程启动或纯计算占比。',
        '- 单机共享开发环境、单线程设置、没有绑核；硬件/版本/数据变化后需重新测量。\n',
        '## 7. 复现\n',
        '```bash\n# 项目根目录；不改变主 SM4 工件\nrustup target add wasm32-wasip1\ncargo test --locked --manifest-path benchmarks/native-vs-wasm/wasm/Cargo.toml\ncargo build --locked --release --target wasm32-wasip1 \\\n  --manifest-path benchmarks/native-vs-wasm/wasm/Cargo.toml\nexport SM4_URL=http://127.0.0.1:8000\nexport SM4_USER=root\nexport SM4_PASSWORD=\'\'\n.venv/bin/python benchmarks/native-vs-wasm/benchmark.py\n```\n',
        '需要管理员批准的专用测试节点、UDF/stage/Memory 表权限；脚本不会改安全配置。'
        '设置了 CARGO_TARGET_DIR 时，通过 `--wasm-file` 指定真实工件路径。结束时清理临时函数/表/stage；'
        '失败或强制 kill 后需按日志确认残留。不要未经批准在生产执行。\n',
        '使用已完成的原始数据重新生成：\n',
        '```bash\n.venv/bin/python benchmarks/native-vs-wasm/report.py \\\n  --input results/native-vs-wasm.json\n```\n',
        f'WASM SHA256：`{m["wasm_sha256"]}`。源码、Cargo.lock、工具链指纹和逐次计时见 [results.json](results.json)。\n']
    return '\n'.join(text).rstrip()+'\n'


def render_md5_only(e):
    m=e['metadata'];idx={(r['length'],r['rows'],r['impl']):r for r in e['summary']}
    timing=[];ranges=[];throughput=[];increments=[]
    counts=sorted(m['rows']);low,high=counts[0],counts[-1]
    for length in m['lengths']:
        for count in m['rows']:
            native,wasm=[idx[length,count,impl] for impl in ('native_md5','wasm_md5')]
            ratio='不可分辨' if native['median_ms']==0 else f'{wasm["median_ms"]/native["median_ms"]:.2f}×'
            timing.append([length,f'{count:,}',native['median_ms'],wasm['median_ms'],ratio])
            ranges.append([length,f'{count:,}',*[f'{r["min_ms"]}–{r["max_ms"]}' for r in [native,wasm]]])
            throughput.append([length,f'{count:,}',*[f'{r["rows_per_second"]:,.0f}' if r['rows_per_second'] is not None else '不可分辨' for r in [native,wasm]]])
        if high>low:
            delta=[idx[length,high,impl]['median_ms']-idx[length,low,impl]['median_ms'] for impl in ('native_md5','wasm_md5')]
            increments.append([length,*[f'{d*1000/(high-low):.3f}' for d in delta],
                '不可分辨' if delta[0]<=0 else f'{delta[1]/delta[0]:.2f}×'])
    row_args=','.join(map(str,m['rows']));length_args=','.join(map(str,m['lengths']))
    text=['# 内置 MD5 与 WASM MD5：10–100 万行\n',
        '**状态：完整测量已结束，结果一致且清理成功。** 此轮只测两种 MD5，不含 identity 和 SM4。'
        '小规模结果见 [1–5 万行报告](../rows-1-50k/REPORT.md)，两轮独立测量；'
        '其他报告见 [报告索引](../../README.md)。\n',
        '## 1. 测试目标与环境\n',
        '检验扩大行数后，WASM 的固定加载/初始化成本是否被摊薄，以及完整 SQL 的相对差距如何变化。\n',
        table(['项目','值'],[['Databend',m['version']],['CPU',m['cpu']],['宿主逻辑 CPU',m['logical_cpus']],
            ['Query max_threads',m['max_threads']],['max_block_size',m['max_block_size']],['表引擎',m['engine']],
            ['结果缓存','关闭'],['实现','内置 md5() / WASM MD5，STRING → 小写 Hex STRING'],
            ['MD5 库','md-5 0.10.6；原生版本依据本地源码/锁文件，未重编译 Query 控制全部变量'],
            ['Rust',m['rustc']],['开始 UTC',m['started_at']],['结束 UTC',m['finished_at']]]),
        f'\n- 明文字节数 `{m["lengths"]}`；行数 `{m["rows"]}`；每组预热 1 次、正式 {m["repeats"]} 次，正式顺序交错打乱。',
        '- 输入在 Memory 表中预生成，固定宽度行号使每行不同，文本使用重复/截断的 Hello Databend 模式。',
        '- 生成、写表、上传、注册不计时。每次 SQL 的初始化/编译、列式数据扫描、转换、MD5 和 hash 聚合全部计时。',
        '- `count(*)` 与 `sum(siphash64(result))` 消费返回值，且每次全量 count/checksum 与原生预计算结果一致。',
        f'- {e["validation"]["edge_cases"]} 个 NULL/空串/标准向量/UTF-8/零字节/边界用例，独立期望来自 Python hashlib；每种长度额外逐行核对 257 行。',
        f'- 共 {e["timed_query_count"]} 次计时查询，没有 identity 测量。固定工件仍含旧 identity 导出，但本轮未注册或调用它。\n',
        '## 2. 完整 SQL 耗时中位数（毫秒）\n',
        table(['输入 B/行','行数','内置 MD5','WASM MD5','WASM/内置耗时'],timing),
        '\n最后一列是耗时比，大于 1 表示 WASM 更慢。\n',
        '## 3. 三次以上正式测量的范围（毫秒）\n',
        table(['输入 B/行','行数','内置 min–max','WASM min–max'],ranges),
        '\n## 4. 按中位数折算吞吐（行/秒）\n',
        table(['输入 B/行','行数','内置 MD5','WASM MD5'],throughput),
        '\n## 5. 规模增量观察\n',
        f'以下取 {low:,} → {high:,} 行的中位数差，再除以增加的行数，单位为每增加一行的平均增量微秒。\n',
        table(['输入 B/行','内置增量 µs/行','WASM 增量 µs/行','WASM/内置增量比'],increments),
        '\n耗时比随规模下降，与固定成本占比下降一致；剩余差距还包含 native/WASM target 的编译差异、结果 buffer/String 分配和执行边界。\n',
        '## 6. 复现\n',
        '从项目根目录构建后，在有管理员批准的独立测试实例运行：\n',
        f'```bash\nexport SM4_URL=http://127.0.0.1:8000\nexport SM4_USER=root\nexport SM4_PASSWORD=\'\'\n.venv/bin/python benchmarks/native-vs-wasm/benchmark.py --md5-only \\\n  --rows {row_args} --lengths {length_args} --repeats {m["repeats"]} \\\n  --output results/native-vs-wasm-large.json \\\n  --report-dir reports/md5-native-vs-wasm/rows-100k-1m\n```\n',
        'WASM 工件构建方法见 [实验说明](../../../benchmarks/native-vs-wasm/README.md)；自定义 CARGO_TARGET_DIR 时传 --wasm-file。'
        '1,024 B × 100 万行仅原文就约 0.95 GiB，应预留输入表、运行时和中间结果的内存。不要未经批准在生产运行。\n',
        '用完整原始记录重新生成本页，不覆盖上一轮：\n',
        '```bash\n.venv/bin/python benchmarks/native-vs-wasm/report.py \\\n  --input results/native-vs-wasm-large.json \\\n  --report-dir reports/md5-native-vs-wasm/rows-100k-1m\n```\n',
        '- 未测并发 QPS、峰值 RSS、多线程扩展、冷进程启动或纯内核计算。单机共享环境、无绑核。',
        '- 未尝试模块缓存等运行时优化。',
        '- 没有修改已部署 SM4；临时函数、表、stage 正常退出时清理。',
        f'- WASM SHA256：`{m["wasm_sha256"]}`。完整脱敏证据与工件/源码指纹见 [results.json](results.json)。\n']
    return '\n'.join(text).rstrip()+'\n'


def publish(record,directory=DEFAULT_REPORT_DIR):
    evidence=summarize(record)
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'results.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')
    (directory/'REPORT.md').write_text(render(evidence))
    fields=['length','rows','impl','median_ms','min_ms','max_ms','samples','rows_per_second']
    with (directory/'results.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(evidence['summary'])
    return evidence


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--report-dir',type=Path,default=DEFAULT_REPORT_DIR)
    args=p.parse_args();publish(json.loads(args.input.read_text()),args.report_dir)
