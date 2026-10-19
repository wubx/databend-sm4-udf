#!/usr/bin/env python3
"""Read-only regression check of ALREADY REGISTERED functions on SM4_URL.
Unlike integration.py, never builds/uploads WASM or creates/replaces functions.
Tests the README's exact constant inputs, including bare CBC and prefixed aliases.
"""
import argparse
from pathlib import Path
import re
import sys
from databend_http import Client

ROOT=Path(__file__).resolve().parents[1]
MODES=('CBC','sm4-cbc','SM4_128_CBC')
EXPECTED_CIPHERTEXT='DA12F33F321D4D551A76D8800F5AE244'
EXPECTED_PLAINTEXT='48656C6C6F204461746162656E64'
KEY="unhex('0123456789abcdeffedcba9876543210')"
IV="unhex('00112233445566778899aabbccddeeff')"


def build_queries(impl='wasm',prefix=''):
    if impl not in ('js','wasm','python'):raise ValueError('Invalid implementation')
    if prefix and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',prefix):raise ValueError('Invalid function prefix')
    return [(mode,f'''SELECT
  upper(hex({prefix}sm4_encrypt_{impl}(to_binary('Hello Databend'), {KEY}, {IV}, '{mode}'))) AS ciphertext_hex,
  upper(hex({prefix}sm4_decrypt_{impl}(unhex('{EXPECTED_CIPHERTEXT}'), {KEY}, {IV}, '{mode}'))) AS plaintext_hex;''') for mode in MODES]


def sql_file():
    return ('-- Read-only WASM deployment regression. All rows must equal the expected pair.\n'
            f'-- Expected ciphertext_hex: {EXPECTED_CIPHERTEXT}\n'
            f'-- Expected plaintext_hex:  {EXPECTED_PLAINTEXT}\n'
            '-- NULL is a failure, not a valid encryption result for these inputs.\n\n'+
            '\n\n'.join(sql for _,sql in build_queries())+'\n')


def check(query,impl='wasm',prefix=''):
    checks=[]
    expected=[[EXPECTED_CIPHERTEXT,EXPECTED_PLAINTEXT]]
    for mode,sql in build_queries(impl,prefix):
        result=query(sql)
        checks.append({'impl':impl,'mode':mode,'ok':result['data']==expected,
                       'expected':expected,'sql':sql,**result})
    return checks


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--impl',choices=['js','wasm','python','all'],default='wasm')
    p.add_argument('--function-prefix',default='')
    p.add_argument('--print-sql',action='store_true',help='Print selected checks without connecting')
    args=p.parse_args()
    impls=['js','wasm','python'] if args.impl=='all' else [args.impl]
    if args.print_sql:
        for impl in impls:
            for _,sql in build_queries(impl,args.function_prefix):print(sql+'\n')
        return
    db=Client();failed=False
    try:
        for impl in impls:
            for r in check(db.query,impl,args.function_prefix):
                print('PASS' if r['ok'] else 'FAIL',impl,r['mode'],r['data'],flush=True)
                if not r['ok']:failed=True
    except Exception as error:
        print('FAIL deployment check:',error,file=sys.stderr);failed=True
    if failed:
        print('Expected:',[EXPECTED_CIPHERTEXT,EXPECTED_PLAINTEXT],file=sys.stderr)
        print('Check system.user_functions.definition and the deployed WASM path/version; no functions were changed.',file=sys.stderr)
        sys.exit(1)


if __name__=='__main__':main()
