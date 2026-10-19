#!/usr/bin/env python3
"""Opt-in sequential SQL benchmark on existing public SM4 functions.
SM4_URL required. Function registration is NOT performed by this script.
Creates a unique Memory table; always drops it. Reuse public sample keys only.
"""
import argparse
import datetime
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
import platform
from pathlib import Path
import random
import re
import statistics
import uuid
from databend_http import Client

ROOT=Path(__file__).resolve().parents[1]
KEY="unhex('0123456789abcdeffedcba9876543210')"
IV="unhex('00112233445566778899aabbccddeeff')"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lengths',default='16,128,1024')
    p.add_argument('--rows',default='1000,10000,50000')
    p.add_argument('--modes',default='ECB,CBC,CFB128,OFB')
    p.add_argument('--operations',default='encrypt,decrypt')
    p.add_argument('--profile',choices=['raw','default_iv','explicit_iv'],default='raw',help='Use the strict byte API or a matching DB-style adapter in all backends')
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--threads',type=int,default=1)
    p.add_argument('--function-prefix',default='',help='Optional prefix for already registered SQL functions')
    p.add_argument('--output',type=Path,default=ROOT/'results/benchmark.json')
    args=p.parse_args()
    lengths=[int(n) for n in args.lengths.split(',')];rows=[int(n) for n in args.rows.split(',')]
    modes=args.modes.split(',');ops=args.operations.split(',')
    if not (all(n>=16 for n in lengths) and all(n>0 for n in rows) and args.repeats>0):p.error('length >=16, rows/repeats >0 required')
    if not set(modes)<=set(['ECB','CBC','CFB128','OFB']) or not set(ops)<=set(['encrypt','decrypt']):p.error('unsupported mode/operation')
    if args.function_prefix and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',args.function_prefix):p.error('Invalid function prefix')
    profile_prefix='' if args.profile=='raw' else args.profile+'_'
    key,iv=KEY,IV
    if args.profile=='default_iv':key,iv="'F3229A0B371ED2D9441B830D21A390C3'","''"
    if args.profile=='explicit_iv':key,iv="'12312313123'","'asdasdkljasdkljalskdjaklsdjaklsjdaklsdjlaksdj'"
    db=Client(threads=args.threads);name='sm4_bench_'+uuid.uuid4().hex[:10]
    packages={}
    for package in ['databend-udf','gmssl','pyarrow']:
        try:packages[package]=version(package)
        except PackageNotFoundError:packages[package]=None
    cpu=platform.processor() or None
    if Path('/proc/cpuinfo').exists():
        cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),cpu)
    record={'metadata':{'version':db.query('SELECT version()')['data'],
        'packages':packages,'python_version':platform.python_version(),
        'cpu':cpu,'logical_cpus':os.cpu_count(),
        'plaintext_pattern':'6-digit row number + Hello Databend, repeated/truncated to fixed ASCII length',
        'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'platform':platform.platform(),'threads':args.threads,'max_block_size':8192,'query_cache':False,
        'lengths':lengths,'rows':rows,'modes':modes,'operations':ops,'repeats':args.repeats,
        'profile':args.profile,
        'interface':'BINARY,BINARY,BINARY,STRING -> BINARY' if args.profile=='raw' else 'BINARY,STRING,STRING,STRING -> BINARY',
        'sha256':{file:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in
                  ['javascript/sm4.mjs','python/sm4_udf/core.py','python/sm4_udf/compat.py','python/sm4_udf/server.py',
                   'wasm/src/lib.rs','scripts/benchmark.py','scripts/generate_sql.py']}},'samples':[]}
    samples=record['samples'];checksums={};rng=random.Random(42)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        groups={}
        for s in samples:
            if s['phase']=='measure':groups.setdefault((s['length'],s['rows'],s['mode'],s['op'],s['impl']),[]).append(s['server_ms'])
        record['summary']=[{'length':k[0],'rows':k[1],'mode':k[2],'operation':k[3],'impl':k[4],
            'median_ms':statistics.median(v),'min_ms':min(v),'max_ms':max(v),'samples':len(v)} for k,v in groups.items()]
        args.output.write_text(json.dumps(record,indent=2))
    created=False
    try:
        db.query(f'CREATE TABLE {name} (id UINT64,data BINARY,ct BINARY) ENGINE=Memory');created=True
        for length in lengths:
            for mode in modes:
                db.query(f'TRUNCATE TABLE {name}')
                # Plaintexts vary per row; encryption is outside timed runs.
                db.query(f'''INSERT INTO {name}
SELECT number,data,{args.function_prefix}sm4_encrypt_{profile_prefix}wasm(data,{key},{iv},'{mode}')
FROM (SELECT number,to_binary(rpad(concat(lpad(to_string(number),6,'0'),'Hello Databend'),{length},' Hello Databend')) AS data FROM numbers({max(rows)}))''')
                for count in rows:
                    baseline=db.query(f'SELECT count(*),sum(siphash64(data)),sum(siphash64(ct)) FROM (SELECT * FROM {name} LIMIT {count})')['data'][0]
                    assert int(baseline[0])==count
                    checksums[count,'decrypt']=baseline[1];checksums[count,'encrypt']=baseline[2]
                def run(job,phase,repeat):
                    count,op,impl=job
                    col='data' if op=='encrypt' else 'ct'
                    sql=f'''SELECT count(*),sum(siphash64({args.function_prefix}sm4_{op}_{profile_prefix}{impl}({col},{key},{iv},'{mode}')))
FROM (SELECT * FROM {name} LIMIT {count})'''
                    r=db.query(sql)
                    assert r['data']==[[str(count),checksums[count,op]]],(job,r)
                    samples.append({'length':length,'rows':count,'mode':mode,'op':op,'impl':impl,'phase':phase,'repeat':repeat,'sql':sql,**r})
                    save();print(phase,length,count,mode,op,impl,r['server_ms'],flush=True)
                jobs=[(n,op,impl) for n in rows for op in ops for impl in ['js','wasm','python']]
                for job in jobs:run(job,'warmup',0)
                for repeat in range(args.repeats):
                    order=jobs.copy();rng.shuffle(order)
                    for job in order:run(job,'measure',repeat)
        record['complete']=True;save()
    finally:
        if created:db.query(f'DROP TABLE IF EXISTS {name}')


if __name__=='__main__':main()
