#!/usr/bin/env python3
"""Opt-in native md5 vs WASM MD5 benchmark. SM4_URL must point to an authorized test node.
Creates unique temporary functions, Memory tables and a stage; always attempts cleanup.
Raw records stay under ignored results/. Only a fully completed run publishes the report.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import uuid

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from databend_http import Client,quote

IMPLS=('native_md5','wasm_md5','sql_identity','wasm_identity')


def utc():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wasm-file',type=Path,default=HERE/'wasm/target/wasm32-wasip1/release/databend_native_vs_wasm.wasm')
    p.add_argument('--rows',default='1,100,1000,10000,30000,50000')
    p.add_argument('--lengths',default='16,128,1024')
    p.add_argument('--repeats',type=int,default=5)
    p.add_argument('--md5-only',action='store_true',help='Only compare native MD5 and WASM MD5; omit both identity baselines')
    p.add_argument('--output',type=Path,default=ROOT/'results/native-vs-wasm.json')
    p.add_argument('--report-dir',type=Path,default=HERE,help='Publish completed results here; use a separate directory for a different matrix')
    args=p.parse_args()
    counts=list(map(int,args.rows.split(',')));lengths=list(map(int,args.lengths.split(',')))
    assert all(n>0 for n in counts) and all(n>=16 for n in lengths) and args.repeats>=3
    assert len(set(counts))==len(counts) and len(set(lengths))==len(lengths)
    impls=('native_md5','wasm_md5') if args.md5_only else IMPLS
    artifact=args.wasm_file.resolve();assert artifact.is_file() and artifact.suffix=='.wasm'
    db=Client(threads=1);tag='md5_compare_'+uuid.uuid4().hex[:10]
    function=tag+'_md5';identity=tag+'_identity';tables=[];functions=[];stage=False
    cpu=platform.processor()
    if Path('/proc/cpuinfo').exists():
        cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),cpu)
    record={'complete':False,'metadata':{'started_at':utc(),'version':db.query('SELECT version()')['data'][0][0],
        'cpu':cpu,'logical_cpus':os.cpu_count(),'platform':platform.platform(),'max_threads':1,'max_block_size':8192,
        'result_cache':False,'engine':'Memory','rows':counts,'lengths':lengths,'warmups':1,'repeats':args.repeats,
        'implementations':list(impls),'md5_crate':'0.10.6','rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),
        'sha256':{str(path.relative_to(ROOT)):sha(path) for path in [HERE/'wasm/src/lib.rs',HERE/'wasm/Cargo.toml',HERE/'wasm/Cargo.lock',Path(__file__)]},
        'wasm_sha256':sha(artifact)},'validation':{},'samples':[],'cleanup_errors':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2))
    rng=random.Random(20261019)
    try:
        db.query(f'CREATE STAGE {tag}');stage=True;db.upload(tag,artifact)
        exports=[(function,'md5_wasm')] if args.md5_only else [(function,'md5_wasm'),(identity,'identity_wasm')]
        for name,handler in exports:
            db.query(f'''CREATE FUNCTION {name}(STRING NULL) RETURNS STRING NULL LANGUAGE wasm
HANDLER = '{handler}' AS $$@{tag}/{artifact.name}$$''')
            functions.append(name)
        case_table=tag+'_cases'
        db.query(f'CREATE TABLE {case_table} (id STRING,data STRING NULL,expected STRING NULL) ENGINE=Memory');tables.append(case_table)
        texts=[None,'','a','abc','message digest','Hello Databend','中文🙂','Hello\x00Databend',
               'Hello Databend '*100]
        texts += [('0123456789abcdef'*((n+15)//16))[:n] for n in [1,15,16,17,31,32,33,63,64,65,127,128,129,255,256,257,1024,4096]]
        values=[];expected={}
        for index,text in enumerate(texts):
            digest=None if text is None else hashlib.md5(text.encode('utf8'),usedforsecurity=False).hexdigest()
            expected[str(index)]=[digest,digest] if args.md5_only else [digest,digest,text]
            values.append('('+','.join([quote(str(index)),'NULL' if text is None else f"to_string(unhex('{text.encode('utf8').hex()}'))",'NULL' if digest is None else quote(digest)])+')')
        db.query(f'INSERT INTO {case_table} VALUES '+','.join(values))
        extra='' if args.md5_only else f',{identity}(data)'
        r=db.query(f'SELECT id,md5(data),{function}(data){extra} FROM {case_table}')
        assert {row[0]:row[1:] for row in r['data']}==expected,r
        record['validation']['edge_cases']=len(texts)
        print('PASS exact MD5 cases:',len(texts),'; implementations:',','.join(impls),flush=True)
        for length in lengths:
            name=f'{tag}_payload_{length}'
            db.query(f'CREATE TABLE {name} (id UINT64,data STRING) ENGINE=Memory');tables.append(name)
            db.query(f'''INSERT INTO {name} SELECT number,
rpad(concat(lpad(to_string(number),6,'0'),'Hello Databend'),{length},' Hello Databend') FROM numbers({max(counts)})''')
            extra='' if args.md5_only else f',count_if(data={identity}(data))'
            r=db.query(f'''SELECT count(*),count_if(md5(data)={function}(data)){extra}
FROM (SELECT * FROM {name} LIMIT {min(257,max(counts))})''')
            assert r['data']==[[str(min(257,max(counts)))]*(2 if args.md5_only else 3)],r
            record['validation'][f'{length}B_sample_rows']=min(257,max(counts))
        jobs=[(length,count,impl) for length in lengths for count in counts for impl in impls]
        checksums={}
        # Precompute matching exact aggregate expectations OUTSIDE timed runs.
        for length in lengths:
            for count in counts:
                extra='' if args.md5_only else ',sum(siphash64(data))'
                r=db.query(f'''SELECT count(*),sum(siphash64(md5(data))){extra}
FROM (SELECT data FROM {tag}_payload_{length} LIMIT {count})''')['data'][0]
                assert int(r[0])==count
                checksums[length,count,'md5']=r[1]
                if not args.md5_only:checksums[length,count,'identity']=r[2]
        def run(job,phase,repeat):
            length,count,impl=job
            expression={'native_md5':'md5(data)','wasm_md5':f'{function}(data)',
                        'sql_identity':'data','wasm_identity':f'{identity}(data)'}[impl]
            sql=f'''SELECT count(*),sum(siphash64({expression}))
FROM (SELECT data FROM {tag}_payload_{length} LIMIT {count})'''
            r=db.query(sql)
            kind='md5' if impl.endswith('md5') else 'identity'
            assert r['data']==[[str(count),checksums[length,count,kind]]],(job,r)
            assert r['server_ms']>=0
            record['samples'].append({'length':length,'rows':count,'impl':impl,'phase':phase,'repeat':repeat,'sql':sql,**r})
            save();print(phase,repeat,length,count,impl,r['server_ms'],flush=True)
        for job in jobs:run(job,'warmup',0)
        for repeat in range(args.repeats):
            order=jobs.copy();rng.shuffle(order)
            for job in order:run(job,'measure',repeat)
        record['complete']=True
    finally:
        for table in reversed(tables):
            try:db.query('DROP TABLE IF EXISTS '+table)
            except Exception as error:record['cleanup_errors'].append(str(error))
        for name in reversed(functions):
            try:db.query('DROP FUNCTION IF EXISTS '+name)
            except Exception as error:record['cleanup_errors'].append(str(error))
        if stage:
            try:db.query(f"REMOVE @{tag} PATTERN = '.*'");db.query('DROP STAGE IF EXISTS '+tag)
            except Exception as error:record['cleanup_errors'].append(str(error))
        record['metadata']['finished_at']=utc();save()
    assert not record['cleanup_errors'],record['cleanup_errors']
    from report import publish
    publish(record,args.report_dir)
    print('COMPLETE:',args.report_dir/'REPORT.md',flush=True)


if __name__=='__main__':main()
