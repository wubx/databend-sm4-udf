#!/usr/bin/env python3
"""Publish a sanitized, reproducible report from completed local test/benchmark runs.
Input files are local evidence, never read implicitly from a database. Refuses partial
runs, mismatched checksums, missing repeats or source/vector fingerprint mismatches.
Does not copy endpoints, private stage names, SQL function prefixes or full raw logs.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT=Path(__file__).resolve().parents[1]
REPORT_DIR=ROOT/'reports/sm4-backends'
IMPLS=('python','js','wasm')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def md_table(head,rows):
    return '\n'.join(['| '+' | '.join(head)+' |','| '+' | '.join(['---']*len(head))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])


def build(integration,benchmark,unit,deployment):
    assert integration.get('passed') is True and integration.get('benchmark_report_passed') is True,'Incomplete integration run'
    assert integration.get('cleanup_errors')==[],'Cleanup did not finish cleanly'
    assert all(c['returncode']==0 for c in unit['checks']) and len(unit['checks'])==5,'Unit check failure/missing check'
    assert benchmark.get('complete') is True,'Benchmark incomplete'
    meta=benchmark['metadata']
    assert meta['profile']=='explicit_iv' and meta['modes']==['CBC'] and meta['operations']==['decrypt'],'Unexpected workload'
    assert meta['lengths']==[16,128,1024] and meta['repeats']==3,'Unexpected matrix'
    assert meta['rows'] in ([1000,10000],[1000,10000,30000,50000]),'Unexpected row-count matrix'
    workloads=len(meta['lengths'])*len(meta['rows'])*len(IMPLS)
    assert meta['threads']==1 and meta['max_block_size']==8192 and meta['query_cache'] is False
    assert integration['version']==meta['version'][0][0],'Mixed benchmark/correctness engine versions'
    for file,value in meta['sha256'].items():assert sha(ROOT/file)==value,'Source changed since benchmark: '+file
    raw=read(ROOT/'tests/vectors.json')['cases'];compat=read(ROOT/'tests/compat_vectors.json')['cases']
    assert integration['compatibility_vectors_passed']==len(compat)
    for impl in IMPLS:
        candidates=[q for q in integration['queries'] if f'_sm4_encrypt_{impl}(data,k,iv,mode)' in q['sql']
                    and "op='encrypt'" in q['sql']]
        assert len(candidates)==1 and len(candidates[0]['data'])==len(raw),(impl,'missing strict vector result')
        def normalized(rows):return {r[0]:None if r[1] is None else r[1].lower() for r in rows}
        assert normalized(candidates[0]['data'])=={v['id']:v['expected'] for v in raw},(impl,'strict expectations differ')
        adapters=[q for q in integration['queries'] if f'_sm4_encrypt_default_iv_{impl}(data,k,iv,mode)' in q['sql']]
        assert len(adapters)==1 and normalized(adapters[0]['data'])=={v['id']:v['expected'] for v in compat},(impl,'adapter expectations differ')
        articles=[q for q in integration['queries'] if 'AS case_id' in q['sql'] and f'_sm4_encrypt_explicit_iv_{impl}(' in q['sql']]
        assert len(articles)==1 and len(articles[0]['data'])==7 and all(r[1]==r[2] for r in articles[0]['data'])
    regressions=integration['deployment_regressions']
    assert len(regressions)==9 and all(r['ok'] for r in regressions),'Public SQL regression failed'
    assert deployment['status']=='SUCCEEDED' and deployment['vectors_per_backend']==len(compat)
    assert deployment['sha256']==integration['wasm_sha256'],'Deployment/validation artifact differs'
    for impl in ['wasm','js']:
        rows=deployment['article_checks'][impl]['data']
        assert len(rows)==7 and all(row[1]==row[2] for row in rows)
    assert dict(deployment['strict_before'])==dict(deployment['strict_after'])
    samples=benchmark['samples'];assert len(samples)==workloads*(meta['repeats']+1),'Missing or unexpected timed query records'
    grouped={};public_samples=[]
    for s in samples:
        assert s['impl'] in IMPLS and s['mode']=='CBC' and s['op']=='decrypt'
        assert s['phase'] in ('warmup','measure') and len(s['data'])==1
        assert int(s['data'][0][0])==s['rows'] and s['data'][0][1] is not None
        assert s['server_ms']>0
        grouped.setdefault((s['length'],s['rows'],s['impl']),[]).append(s)
        public_samples.append({k:s[k] for k in ['length','rows','mode','op','impl','phase','repeat','server_ms','wall_ms']}|
                              {'checksum':s['data'][0][1]})
    summary=[]
    for length in meta['lengths']:
        for count in meta['rows']:
            all_checksums=set()
            for impl in IMPLS:
                group=grouped[length,count,impl]
                warm=[s for s in group if s['phase']=='warmup'];formal=[s for s in group if s['phase']=='measure']
                assert len(warm)==1 and len(formal)==3 and {s['repeat'] for s in formal}=={0,1,2}
                all_checksums.update(s['data'][0][1] for s in group)
                times=[s['server_ms'] for s in formal];median=statistics.median(times)
                summary.append({'length':length,'rows':count,'impl':impl,'median_ms':median,
                    'min_ms':min(times),'max_ms':max(times),'samples':3,
                    'rows_per_second':count*1000/median,'plaintext_mib_per_second':length*count*1000/median/2**20})
            assert len(all_checksums)==1,(length,count,'backend/repeat checksum mismatch')
    assert len(grouped)==workloads
    python_log=next(c for c in unit['checks'] if c['name']=='python')
    match=re.search(r'Ran (\d+) tests',python_log['stdout']+python_log['stderr']);assert match
    evidence={'schema':1,'generated_at':datetime.now(timezone.utc).isoformat(),
        'test_interval':{'started_at':integration['started_at'],'finished_at':integration['finished_at']},
        'environment':{k:meta[k] for k in ['version','packages','python_version','cpu','logical_cpus','platform','threads','max_block_size']},
        'toolchain':{'rustc':unit['rustc'],**unit['node'],
            'arrow_udf_revision':re.search(r'rev\s*=\s*"([^"]+)"',(ROOT/'wasm/Cargo.toml').read_text())[1]},
        'correctness':{'passed':True,'python_unittest_methods':int(match[1]),
            'unit_check_commands':[c['name'] for c in unit['checks']],
            'strict_vectors_per_backend':len(raw),'adapter_vectors_per_backend':len(compat),
            'vector_assertions_across_three_backends':(len(raw)+len(compat))*3,
            'public_deployment_regressions':9,'public_article_rows_per_backend':7,
            'isolated_function_count':18,'cleanup_errors':[]},
        'deployment':{'version':deployment['version'],'validated_backends':['wasm','js'],
            'adapter_vectors_per_backend':len(compat),'article_rows_per_backend':7,
            'strict_definitions_unchanged':True,'python_registered_on_current_instance':False,
            'wasm_sha256':deployment['sha256']},
        'fingerprints':{'source':meta['sha256'],
            'vectors':{p:sha(ROOT/p) for p in ['tests/vectors.json','tests/compat_vectors.json']},
            'wasm_sha256':integration['wasm_sha256']},
        'benchmark':{'complete':True,'profile':'explicit_iv','mode':'CBC','operation':'decrypt',
            'interface':meta['interface'],'lengths':meta['lengths'],'rows':meta['rows'],
            'warmups':1,'repeats':3,'timed_query_count':len(samples),'query_cache':False,
            'plaintext_pattern':meta['plaintext_pattern'],'samples':public_samples,'summary':summary}}
    return evidence


def render(e):
    env=e['environment'];c=e['correctness'];b=e['benchmark'];tools=e['toolchain']
    index={(r['length'],r['rows'],r['impl']):r for r in b['summary']}
    row_spec=','.join(map(str,b['rows']))
    row_description='/'.join(f'{n:,}' for n in b['rows'])
    scales=len(b['lengths'])*len(b['rows'])
    workloads=scales*len(IMPLS)
    timing=[];spread=[];throughput=[]
    for length in b['lengths']:
        for count in b['rows']:
            p,j,w=[index[length,count,impl] for impl in IMPLS]
            timing.append([length,f'{count:,}',*[f'{r["median_ms"]/1000:.3f}' for r in [p,j,w]],
                           f'{p["median_ms"]/w["median_ms"]:.1f}×',f'{j["median_ms"]/w["median_ms"]:.1f}×'])
            spread.append([length,f'{count:,}',*[f'{r["min_ms"]/1000:.3f}–{r["max_ms"]/1000:.3f}' for r in [p,j,w]]])
            throughput.append([length,f'{count:,}',*[f'{r["rows_per_second"]:,.0f}' for r in [p,j,w]]])
    text=['# SM4 三端测试报告\n',
        '**结论：当前源码快照的三端正确性检查通过，以下性能矩阵已完整跑完。**\n',
        f'- 测试时间（UTC）：`{e["test_interval"]["started_at"]}` 至 `{e["test_interval"]["finished_at"]}`。',
        '- 数据：[results.json](results.json)；性能汇总：[results.csv](results.csv)；'
        '测试口径：[BENCHMARKS](../../docs/BENCHMARKS.md)；其他报告：[报告索引](../README.md)。\n',
        '## 1. 环境\n',
        md_table(['项目','值'],[
            ['隔离测试 Databend',env['version'][0][0]],['CPU',env['cpu']],['宿主逻辑 CPU 数',env['logical_cpus']],
            ['Query max_threads',env['threads']],['max_block_size',env['max_block_size']],['表引擎','Memory'],
            ['结果缓存','关闭'],['Python',env['python_version']],
            *[[package,version] for package,version in env['packages'].items()],
            ['Rust',tools['rustc']],['Node.js（仅测试参考）',tools['node']],['OpenSSL（仅测试参考）',tools['openssl']],
            ['Arrow UDF revision',tools['arrow_udf_revision']]]),
        '\nPython Server 与 Query 同机，通过 loopback Flight RPC 调用；三种实现顺序执行，不并发、不绑核。\n',
        '## 2. 正确性覆盖\n',
        md_table(['检查','结果'],[
            ['Python unittest 方法',f'{c["python_unittest_methods"]} 个通过（内部循环共享向量）'],
            ['严格字节接口共享向量',f'{c["strict_vectors_per_backend"]} × JS/WASM/Python，全部通过'],
            ['字符串 key/IV 策略共享向量',f'{c["adapter_vectors_per_backend"]} × JS/WASM/Python，全部通过'],
            ['三端共享向量断言合计',f'{c["vector_assertions_across_three_backends"]:,} 条'],
            ['SQL 示例常量及三种模式别名','9 条查询通过，均非 NULL 且密文/明文符合预期'],
            ['Hello Databend 文章示例','每端 7 行 actual = expected，三端全部通过'],
            ['基准工具冒烟','raw/default_iv/explicit_iv，各三端加密和解密均完成'],
            ['临时对象清理','18 个函数及测试表/stage 已清理，Python Server 已停止']]),
        '\n覆盖 ECB、CBC、CFB128、OFB 的加密/解密；空数据、分组边界、UTF-8、任意二进制和尾部控制字节；'
        'NULL、非法模式、key/IV 长度、密文长度、PKCS#7 每个填充字节；字符串 key 的补零/循环 XOR 和短/长/默认 IV。\n',
        '独立预期来自 Node/OpenSSL、标准 SM4 分组向量及锁定的已知密文。标准分组向量测试 ECB 首块，'
        'PKCS#7 接口的完整输出仍包含额外填充分组。内部固定回归和公开 `Hello Databend` 示例分别保留。\n',
        '## 3. 三方性能\n',
        '- 固定 `explicit_iv`，CBC **解密**；三端都用 `(BINARY, STRING, STRING, STRING) -> BINARY`。',
        f'- 16/128/1,024 B × {row_description} 行，共 {scales} 个规模；每种实现预热一次、正式 3 次，顺序确定性打乱。',
        '- 明文按 `Hello Databend` 模式重复/截断，带固定宽度行号保证各行不同；16 B 时文字会被截断。',
        '- 密文预生成、写表和 Python 进程启动不计时；每行仍执行相同的 key/IV 处理，无密钥缓存。',
        '- 结果按 count/hash 聚合消费，每次与明文基线校验；不返回大量明文，避免客户端渲染主导。',
        '- 时间是完整服务端 SQL 耗时，含扫描/hash、运行时创建/编译、Arrow 转换及 Python RPC。\n',
        '### 完整 SQL 耗时中位数（秒）\n',
        md_table(['明文 B/行','行数','Python Server','JS','WASM','Python/WASM','JS/WASM'],timing),
        '\n### 三次正式测量范围（秒）\n',
        md_table(['明文 B/行','行数','Python min–max','JS min–max','WASM min–max'],spread),
        '\n### 按中位数折算吞吐（行/秒）\n',
        md_table(['明文 B/行','行数','Python Server','JS','WASM'],throughput),
        f'\n共 {b["timed_query_count"]} 次计时查询：{workloads} 次预热、{workloads*b["repeats"]} 次正式测量。所有 workload 均有完整三次正式结果，checksum 一致。\n',
        '## 4. 当前实例部署验证\n',
        f'- 部署实例版本：`{e["deployment"]["version"]}`，与上面的隔离性能实例版本可能不同。',
        '- 本节只验证已部署的中性命名 JS/WASM 字符串入口。',
        f'- JS/WASM 各 {e["deployment"]["adapter_vectors_per_backend"]} 个适配向量及 7 行文章 SQL 均通过。',
        '- 原严格字节函数定义未改变。当前实例没有注册本项目 Python 入口；三端完整验证在独立实例完成。',
        f'- 新部署/隔离测试工件 SHA256：`{e["fingerprints"]["wasm_sha256"]}`。\n',
        '## 5. 复现\n',
        '先按 [README](../../README.md) 安装依赖、构建 WASM，在有权限的专用实例配置 UDF 访问策略：\n',
        f'```bash\nmake test\nmake wasm\nexport SM4_URL=http://127.0.0.1:8000\nexport SM4_USER=root\nexport SM4_PASSWORD=\'\'\n.venv/bin/python scripts/integration.py --benchmark-smoke --benchmark-report \\\n  --benchmark-report-rows {row_spec}\n```\n',
        '此命令创建随机前缀的临时函数和表，完成后自动清理，不更改实例安全设置。'
        '如果只跑性能且已注册公开函数、Python Server 也已启动：\n',
        f'```bash\n.venv/bin/python scripts/benchmark.py --profile explicit_iv \\\n  --lengths 16,128,1024 --rows {row_spec} --modes CBC \\\n  --operations decrypt --repeats 3\n```\n',
        '原始 `results/` 仍被 Git 忽略。`scripts/report_results.py` 接受完整本地记录，校验完成标志、'
        '重复次数、checksum 和源码指纹，输出本报告及脱敏摘要。\n',
        '## 6. 边界与安全\n',
        '- 未测：压力并发、峰值 RSS、跨机网络、TLS、高可用。',
        '- 兼容性范围见 [参数约定](../../docs/COMPATIBILITY.md) 和固定参考向量。',
        '- 默认 IV 是固定兼容值，不适合作为生产 IV 策略；示例密钥公开，不用于真实数据。',
        '- ECB/CBC/CFB128/OFB 不提供认证；解密非 NULL 不证明数据未篡改或密钥正确。',
        '- 实现未保证常数时间，未经密码学安全审计；详见 [SECURITY](../../SECURITY.md)。',
        '- 修改实现后需重新测量。\n']
    return '\n'.join(text).rstrip()+'\n'


def readme_summary(e):
    b=e['benchmark'];c=e['correctness']
    index={(r['length'],r['rows'],r['impl']):r for r in b['summary']}
    length,count=max(b['lengths']),max(b['rows'])
    largest={impl:index[length,count,impl]['median_ms']/1000 for impl in IMPLS}
    rows=f'{min(b["rows"]):,}–{count:,}'
    return (
        '**[SM4 三端](reports/sm4-backends/REPORT.md)**（[CSV](reports/sm4-backends/results.csv) · '
        '[JSON](reports/sm4-backends/results.json)）\n\n'
        f'- 正确性：严格接口 {c["strict_vectors_per_backend"]} + 字符串 key/IV {c["adapter_vectors_per_backend"]} 个向量 × 三端，'
        f'共 **{c["vector_assertions_across_three_backends"]:,} 条断言通过**。\n'
        f'- 性能：`explicit_iv`、CBC 解密，16/128/1,024 B × {rows} 行，{b["timed_query_count"]} 次计时查询。'
        f'{length:,} B × {count:,} 行中位耗时 WASM **{largest["wasm"]:.3f} s**、'
        f'JS {largest["js"]:.3f} s、Python {largest["python"]:.3f} s。'
    )


def update_readme(e):
    path=ROOT/'README.md';text=path.read_text()
    start='<!-- TEST_REPORT_SUMMARY_START -->';end='<!-- TEST_REPORT_SUMMARY_END -->'
    assert text.count(start)==1 and text.count(end)==1,'README report markers missing/ambiguous'
    head,tail=text.split(start);_,tail=tail.split(end)
    path.write_text(head+start+'\n'+readme_summary(e)+'\n'+end+tail)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['integration','benchmark','unit','deployment']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--update-readme',action='store_true',help='Refresh the README report summary only after full validation')
    args=p.parse_args()
    evidence=build(read(args.integration),read(args.benchmark),read(args.unit),read(args.deployment))
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    (REPORT_DIR/'results.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    (REPORT_DIR/'REPORT.md').write_text(render(evidence))
    fields=['length','rows','impl','median_ms','min_ms','max_ms','samples','rows_per_second','plaintext_mib_per_second']
    with (REPORT_DIR/'results.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(evidence['benchmark']['summary'])
    if args.update_readme:
        update_readme(evidence)
    print('Generated',', '.join(str((REPORT_DIR/name).relative_to(ROOT)) for name in ['REPORT.md','results.json','results.csv']))


if __name__=='__main__':main()
