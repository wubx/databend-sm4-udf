#!/usr/bin/env python3
"""Opt-in live test on SM4_URL. Creates only unique temporary functions/table/stage.
Requires stage/UDF privileges, Memory engine, Python UDF allowlist for localhost:8815,
and built wasm/target/wasm32-wasip1/release/databend_sm4_udf.wasm.
Never changes server security settings. Do not use on production without approval.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
from databend_http import Client,quote
from generate_sql import generate
from check_deployment import check as check_deployment

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--benchmark-smoke',action='store_true',help='Also test the benchmark runner with 10 rows before cleanup')
    p.add_argument('--benchmark-report',action='store_true',help='Run report matrix: explicit_iv CBC decrypt, 16/128/1024 B, 3 repetitions')
    p.add_argument('--benchmark-report-rows',default='1000,10000',
                   choices=['1000,10000','1000,10000,30000,50000'],
                   help='Report row-count matrix; the extended option can take tens of minutes')
    p.add_argument('--wasm-file',type=Path,default=ROOT/'wasm/target/wasm32-wasip1/release/databend_sm4_udf.wasm',
                   help='Optional prebuilt artifact path (e.g. from an external CARGO_TARGET_DIR)')
    args=p.parse_args()
    db=Client()
    tag='sm4_test_'+uuid.uuid4().hex[:10]
    artifact=args.wasm_file.resolve()
    if not artifact.is_file():raise FileNotFoundError('Run make wasm or specify --wasm-file')
    if artifact.suffix!='.wasm' or not all(c.isalnum() or c in '._-' for c in artifact.name):
        raise ValueError('Expected a .wasm artifact with a safe filename')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',8815))==0:raise RuntimeError('Port 8815 occupied; refusing to replace server')
    env={**os.environ,'PYTHONPATH':str(ROOT/'python')}
    process=subprocess.Popen([sys.executable,'-m','sm4_udf.server'],cwd=ROOT,env=env)
    created=[];stage_created=False;table_created=False
    record={'endpoint':db.url,'namespace':tag,'queries':[],
            'started_at':datetime.now(timezone.utc).isoformat(),
            'wasm_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
    def query(sql):
        result=db.query(sql);record['queries'].append({'sql':sql,**result});return result
    try:
        deadline=time.monotonic()+20
        while True:
            if process.poll() is not None:raise RuntimeError('Python server startup failed')
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1',8815))==0:break
            if time.monotonic()>deadline:raise TimeoutError('Python server startup')
            time.sleep(.1)
        record['version']=query('SELECT version()')['data'][0][0]
        query(f'CREATE STAGE {tag}');stage_created=True
        db.upload(tag,artifact)
        sqls=generate(wasm_path=f'@{tag}/{artifact.name}')
        sqls.update(generate(wasm_path=f'@{tag}/{artifact.name}',compat=True))
        # Generate per function to keep JS $$ bodies intact (do NOT split on semicolons).
        for impl,sql in sqls.items():
            for statement in sql.split('CREATE OR REPLACE FUNCTION ')[1:]:
                name=statement.split('(',1)[0].strip()
                function=tag+'_'+name
                query('CREATE OR REPLACE FUNCTION '+function+statement[len(name):])
                created.append(function)
        query(f'CREATE TABLE {tag} (id STRING,data BINARY NULL,k BINARY NULL,iv BINARY NULL,mode STRING NULL,op STRING) ENGINE=Memory')
        table_created=True
        vectors=json.loads((ROOT/'tests/vectors.json').read_text())['cases']
        def binary(v):return 'NULL' if v is None else f'unhex({quote(v)})'
        for offset in range(0,len(vectors),24):
            values=[]
            for v in vectors[offset:offset+24]:
                values.append('('+','.join([quote(v['id']),binary(v['data']),binary(v['key']),binary(v['iv']),
                    'NULL' if v['mode'] is None else quote(v['mode']),quote(v['operation'])])+')')
            query(f'INSERT INTO {tag} VALUES '+','.join(values))
        expected={v['id']:v['expected'] for v in vectors}
        for impl in ['js','wasm','python']:
            sql=f'''SELECT id,hex(CASE WHEN op='encrypt' THEN {tag}_sm4_encrypt_{impl}(data,k,iv,mode)
ELSE {tag}_sm4_decrypt_{impl}(data,k,iv,mode) END) FROM {tag}'''
            result=query(sql)
            actual={row[0]:None if row[1] is None else row[1].lower() for row in result['data']}
            assert actual==expected,(impl,[(k,actual.get(k),v) for k,v in expected.items() if actual.get(k)!=v])
            print(f'PASS Databend {impl}: {len(vectors)} mixed valid/invalid/NULL vectors',flush=True)
        # DB adapters use original STRING key/IV arguments; validate independently of strict API.
        compat_table=tag+'_compat'
        try:
            query(f'CREATE TABLE {compat_table} (id STRING,data BINARY NULL,k STRING NULL,iv STRING NULL,mode STRING NULL,op STRING,profile STRING) ENGINE=Memory')
            compat_vectors=json.loads((ROOT/'tests/compat_vectors.json').read_text())['cases']
            def text(v):return 'NULL' if v is None else quote(v)
            for offset in range(0,len(compat_vectors),24):
                values=[]
                for v in compat_vectors[offset:offset+24]:
                    values.append('('+','.join([quote(v['id']),binary(v['data']),text(v['key']),text(v['iv']),
                        text(v['mode']),quote(v['operation']),quote(v['profile'])])+')')
                query(f'INSERT INTO {compat_table} VALUES '+','.join(values))
            expected={v['id']:v['expected'] for v in compat_vectors}
            for impl in ['js','wasm','python']:
                expr='CASE '+''.join(f"WHEN profile='{profile}' AND op='{op}' THEN {tag}_sm4_{op}_{profile}_{impl}(data,k,iv,mode) "
                    for profile in ['default_iv','explicit_iv'] for op in ['encrypt','decrypt'])+'END'
                r=query(f'SELECT id,hex({expr}) FROM {compat_table}')
                actual={row[0]:None if row[1] is None else row[1].lower() for row in r['data']}
                assert actual==expected,(impl,'database compatibility vectors',[(k,actual.get(k),v) for k,v in expected.items() if actual.get(k)!=v])
                # Also run article SQL with literal text inputs, including implicit text->BINARY cast.
                sql=(ROOT/'tests/compat_smoke.sql').read_text()
                for profile in ['explicit_iv','default_iv']:
                    for op in ['encrypt','decrypt']:
                        sql=sql.replace(f'sm4_{op}_{profile}_wasm',f'{tag}_sm4_{op}_{profile}_{impl}')
                rows=query(sql)['data']
                assert len(rows)==7 and all(row[1]==row[2] for row in rows),(impl,rows)
                print(f'PASS DB adapters {impl}: {len(compat_vectors)} vectors + 7 article SQL checks',flush=True)
            record['compatibility_vectors_passed']=len(compat_vectors)
        finally:
            db.query(f'DROP TABLE IF EXISTS {compat_table}')
        record['deployment_regressions']=[]
        for impl in ['js','wasm','python']:
            checks=check_deployment(query,impl,tag+'_')
            record['deployment_regressions'].extend(checks)
            assert all(r['ok'] for r in checks),(impl,checks)
            print(f'PASS README SQL {impl}: CBC and both prefixed aliases',flush=True)
        if args.benchmark_smoke:
            for profile in ['raw','default_iv','explicit_iv']:
                subprocess.run([sys.executable,str(ROOT/'scripts/benchmark.py'),
                    '--lengths','16','--rows','10','--modes','CBC','--repeats','1','--profile',profile,
                    '--function-prefix',tag+'_','--output',str(ROOT/f'results/benchmark-smoke-{profile}.json')],
                    cwd=ROOT,env=env,check=True)
            print('PASS benchmark runner: 3 profiles, encryption/decryption, 3 implementations, 10 rows',flush=True)
        if args.benchmark_report:
            subprocess.run([sys.executable,str(ROOT/'scripts/benchmark.py'),
                '--lengths','16,128,1024','--rows',args.benchmark_report_rows,'--modes','CBC',
                '--operations','decrypt','--repeats','3','--profile','explicit_iv',
                '--function-prefix',tag+'_','--output',str(ROOT/'results/benchmark-report.json')],
                cwd=ROOT,env=env,check=True)
            record['benchmark_report_passed']=True
        record['passed']=True
    finally:
        cleanup_errors=[]
        for name in created:
            try:db.query(f'DROP FUNCTION IF EXISTS {name}')
            except Exception as error:cleanup_errors.append(str(error))
        if table_created:
            try:db.query(f'DROP TABLE IF EXISTS {tag}')
            except Exception as error:cleanup_errors.append(str(error))
        if stage_created:
            try:db.query(f"REMOVE @{tag} PATTERN = '.*'");db.query(f'DROP STAGE IF EXISTS {tag}')
            except Exception as error:cleanup_errors.append(str(error))
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        record['cleanup_errors']=cleanup_errors
        record['finished_at']=datetime.now(timezone.utc).isoformat()
        (ROOT/'results').mkdir(exist_ok=True)
        (ROOT/'results/integration.json').write_text(json.dumps(record,indent=2))
        if cleanup_errors:print('WARNING cleanup:',cleanup_errors,file=sys.stderr)


if __name__=='__main__':main()
