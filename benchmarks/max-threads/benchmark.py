#!/usr/bin/env python3
"""Opt-in max_threads scaling benchmark. SM4_URL must point to an authorized test node.

Unlike the single-thread reports, every scale gets its own multi-block Fuse table and the timed
SQL has no LIMIT, so Query can split the scan and the UDF across pipes. Creates unique temporary
functions, tables and a stage; always attempts cleanup. Only a complete run publishes the report.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import subprocess
import sys
import uuid

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from databend_http import Client
from generate_sql import generate

KEY,IV="'12312313123'","'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj'"
# (bytes per row, rows, implementation). JS runs only where a single-thread query still finishes in ~80 s.
CASES=[(1024,50000,'native_md5'),(1024,50000,'wasm_md5'),(1024,50000,'sm4_wasm'),(1024,50000,'sm4_js'),
       (1024,1000000,'native_md5'),(1024,1000000,'wasm_md5'),(1024,1000000,'sm4_wasm'),
       (16,1000000,'native_md5'),(16,1000000,'wasm_md5'),(16,1000000,'sm4_wasm')]
ROW_PER_BLOCK=8192


def utc():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sm4-wasm',type=Path,default=ROOT/'wasm/target/wasm32-wasip1/release/databend_sm4_udf.wasm')
    p.add_argument('--md5-wasm',type=Path,default=ROOT/'benchmarks/native-vs-wasm/wasm/target/wasm32-wasip1/release/databend_native_vs_wasm.wasm')
    p.add_argument('--threads',default='1,2,4,8,16')
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--output',type=Path,default=ROOT/'results/max-threads.json')
    p.add_argument('--report-dir',type=Path,default=ROOT/'reports/max-threads')
    args=p.parse_args()
    threads=list(map(int,args.threads.split(',')))
    assert threads[0]==1 and threads==sorted(set(threads)) and args.repeats>=3
    artifacts={'sm4':args.sm4_wasm.resolve(),'md5':args.md5_wasm.resolve()}
    assert all(a.is_file() and a.suffix=='.wasm' for a in artifacts.values())
    tag='max_threads_'+uuid.uuid4().hex[:10]
    admin=Client(threads=max(threads))
    cpu=platform.processor()
    if Path('/proc/cpuinfo').exists():
        cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),cpu)
    sources=[ROOT/'wasm/src/lib.rs',ROOT/'javascript/sm4.mjs',ROOT/'benchmarks/native-vs-wasm/wasm/src/lib.rs',Path(__file__)]
    record={'complete':False,'metadata':{'started_at':utc(),'version':admin.query('SELECT version()')['data'][0][0],
        'cpu':cpu,'logical_cpus':os.cpu_count(),'platform':platform.platform(),'threads':threads,
        'max_block_size':8192,'row_per_block':ROW_PER_BLOCK,'result_cache':False,'engine':'Fuse',
        'warmups':1,'repeats':args.repeats,'cases':[list(c) for c in CASES],'profile':'explicit_iv','mode':'CBC',
        'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),
        'sha256':{str(s.relative_to(ROOT)):sha(s) for s in sources},
        'wasm_sha256':{k:sha(v) for k,v in artifacts.items()}},
        'tables':{},'pipelines':{},'samples':[],'cleanup_errors':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2))
    names={'md5':tag+'_md5','enc':tag+'_enc_wasm','dec':tag+'_dec_wasm','js':tag+'_dec_js'}
    expression={'native_md5':'md5(data)','wasm_md5':f'{names["md5"]}(data)',
                'sm4_wasm':f"{names['dec']}(ct, {KEY}, {IV}, 'CBC')",'sm4_js':f"{names['js']}(ct, {KEY}, {IV}, 'CBC')"}
    functions=[];tables=[];stage=False
    try:
        admin.query(f'CREATE STAGE {tag}');stage=True
        for artifact in artifacts.values():admin.upload(tag,artifact)
        admin.query(f'''CREATE FUNCTION {names["md5"]}(STRING NULL) RETURNS STRING NULL LANGUAGE wasm
HANDLER = 'md5_wasm' AS $$@{tag}/{artifacts["md5"].name}$$''');functions.append(names['md5'])
        sql=generate(wasm_path=f'@{tag}/{artifacts["sm4"].name}',compat=True)
        wanted={'sm4_encrypt_explicit_iv_wasm':names['enc'],'sm4_decrypt_explicit_iv_wasm':names['dec'],
                'sm4_decrypt_explicit_iv_js':names['js']}
        for text in (sql['compat_wasm.sql'],sql['compat_js.sql']):
            for part in text.split('CREATE OR REPLACE FUNCTION ')[1:]:
                name=part.split(None,1)[0]
                if name in wanted:
                    admin.query('CREATE FUNCTION '+re.sub(r'^\S+',wanted[name],part).rsplit(';',1)[0])
                    functions.append(wanted[name])
        assert len(functions)==4,functions
        expected={}
        for length,count in sorted({(n,r) for n,r,_ in CASES}):
            table=f'{tag}_{length}_{count}'
            admin.query(f'CREATE TABLE {table} (id UINT64, data STRING, ct BINARY) ROW_PER_BLOCK = {ROW_PER_BLOCK}');tables.append(table)
            admin.query(f'''INSERT INTO {table} SELECT number, data, {names["enc"]}(to_binary(data), {KEY}, {IV}, 'CBC')
FROM (SELECT number, rpad(concat(lpad(to_string(number),7,'0'),'Hello Databend'),{length},' Hello Databend') AS data
      FROM numbers({count}))''',timeout=1800)
            blocks=admin.query(f"SELECT block_count,row_count FROM fuse_snapshot(currentDatabase(),'{table}') LIMIT 1")['data'][0]
            assert int(blocks[1])==count,blocks
            record['tables'][f'{length}x{count}']={'blocks':int(blocks[0]),'rows':count}
            r=admin.query(f'SELECT sum(siphash64(md5(data))),sum(siphash64(to_binary(data))) FROM {table}')['data'][0]
            expected[length,count,'md5'],expected[length,count,'sm4']=r
            # The encrypt used for setup must round-trip through both decrypt functions.
            ok=admin.query(f'''SELECT count_if(hex({expression["sm4_wasm"]})=hex(to_binary(data))),
count_if(hex({expression["sm4_js"]})=hex(to_binary(data))) FROM (SELECT * FROM {table} LIMIT 257)''')['data']
            assert ok==[[str(min(257,count))]*2],ok
        for t in threads:
            plan=Client(threads=t).query(f'EXPLAIN PIPELINE SELECT count(*),sum(siphash64({expression["wasm_md5"]})) FROM {tag}_1024_1000000')
            record['pipelines'][str(t)]=[re.sub(tag,'<tmp>',row[0]) for row in plan['data']]
        def run(job,phase,repeat):
            length,count,impl,t=job
            r=Client(threads=t).query(f'SELECT count(*),sum(siphash64({expression[impl]})) FROM {tag}_{length}_{count}',timeout=1800)
            want=expected[length,count,'md5' if impl.endswith('md5') else 'sm4']
            assert r['data']==[[str(count),want]],(job,r['data'])
            record['samples'].append({'length':length,'rows':count,'impl':impl,'threads':t,'phase':phase,'repeat':repeat,
                'server_ms':r['server_ms'],'wall_ms':r['wall_ms'],'checksum':want})
            save();print(phase,repeat,length,count,impl,t,r['server_ms'],flush=True)
        jobs=[(*case,t) for case in CASES for t in threads]
        for job in jobs:run(job,'warmup',0)
        rng=random.Random(20261019)
        for repeat in range(args.repeats):
            order=jobs.copy();rng.shuffle(order)
            for job in order:run(job,'measure',repeat)
        record['complete']=True
    finally:
        for table in reversed(tables):
            try:admin.query('DROP TABLE IF EXISTS '+table)
            except Exception as error:record['cleanup_errors'].append(str(error))
        for name in reversed(functions):
            try:admin.query('DROP FUNCTION IF EXISTS '+name)
            except Exception as error:record['cleanup_errors'].append(str(error))
        if stage:
            try:admin.query(f"REMOVE @{tag} PATTERN = '.*'");admin.query('DROP STAGE IF EXISTS '+tag)
            except Exception as error:record['cleanup_errors'].append(str(error))
        record['metadata']['finished_at']=utc();save()
    assert not record['cleanup_errors'],record['cleanup_errors']
    sys.path.insert(0,str(HERE))
    from report import publish
    publish(record,args.report_dir)
    print('COMPLETE:',args.report_dir/'REPORT.md',flush=True)


if __name__=='__main__':main()
