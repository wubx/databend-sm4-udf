#!/usr/bin/env python3
"""Opt-in stage upload using SM4_URL. Does not register/replace UDFs."""
import argparse
from pathlib import Path
import re
from databend_http import Client

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',default='sm4_udf')
    p.add_argument('--file',type=Path,default=ROOT/'wasm/target/wasm32-wasip1/release/databend_sm4_udf.wasm')
    args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',args.stage):p.error('Invalid stage identifier')
    if not args.file.is_file() or not re.fullmatch(r'[A-Za-z0-9_.-]+\.wasm',args.file.name):p.error('Existing .wasm file with a safe filename required')
    db=Client();db.query(f'CREATE STAGE IF NOT EXISTS {args.stage}')
    print(db.upload(args.stage,args.file))
    print(f'Uploaded @{args.stage}/{args.file.name}; existing same-name stage files may be replaced.')


if __name__=='__main__':main()
