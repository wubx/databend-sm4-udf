import json
from pathlib import Path
import unittest
from sm4_udf import decrypt, encrypt

ROOT=Path(__file__).resolve().parents[1]


class SharedVectors(unittest.TestCase):
    def test_shared_vectors(self):
        fixture=json.loads((ROOT/'tests/vectors.json').read_text())
        def b(s):return None if s is None else bytes.fromhex(s)
        for v in fixture['cases']:
            with self.subTest(v['id']):
                fn=encrypt if v['operation']=='encrypt' else decrypt
                result=fn(b(v['data']),b(v['key']),b(v['iv']),v['mode'])
                self.assertEqual(None if result is None else result.hex(),v['expected'])

    def test_standard_block(self):
        key=bytes.fromhex('0123456789abcdeffedcba9876543210')
        self.assertEqual(encrypt(key,key,b'','ECB')[:16].hex(),'681edf34d206965e86b3e94f536e4246')


if __name__=='__main__':unittest.main()
