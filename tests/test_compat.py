import json
from pathlib import Path
import unittest
from sm4_udf.compat import database_crypt

ROOT=Path(__file__).resolve().parents[1]


class DatabaseAdapters(unittest.TestCase):
    def test_shared_vectors(self):
        for v in json.loads((ROOT/'tests/compat_vectors.json').read_text())['cases']:
            with self.subTest(v['id']):
                result=database_crypt(None if v['data'] is None else bytes.fromhex(v['data']),
                    v['key'],v['iv'],v['mode'],v['operation']=='decrypt',v['profile'])
                self.assertEqual(None if result is None else result.hex(),v['expected'])


if __name__=='__main__':unittest.main()
