import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('generate_sql',ROOT/'scripts/generate_sql.py')
gen=importlib.util.module_from_spec(spec);spec.loader.exec_module(gen)


class SqlGeneration(unittest.TestCase):
    def test_generated_files_match(self):
        for name,sql in {**gen.generate(),**gen.generate(compat=True)}.items():
            self.assertEqual((ROOT/'sql'/name).read_text(),sql,name)

    def test_all_six_handlers_and_null_types(self):
        for impl,sql in gen.generate().items():
            lang=impl.split('.')[0]
            self.assertEqual(sql.count('CREATE OR REPLACE FUNCTION'),2)
            self.assertEqual(sql.count('(BINARY NULL, BINARY NULL, BINARY NULL, STRING NULL)'),2)
            for op in ['encrypt','decrypt']:
                name=f'sm4_{op}_{lang}'
                self.assertIn(f'FUNCTION {name}',sql)
                self.assertIn(f"HANDLER = '{name}'",sql)

    def test_compatibility_handlers_and_types(self):
        for filename,sql in gen.generate(compat=True).items():
            impl=filename.removeprefix('compat_').removesuffix('.sql')
            self.assertEqual(sql.count('CREATE OR REPLACE FUNCTION'),4)
            self.assertEqual(sql.count('(BINARY NULL, STRING NULL, STRING NULL, STRING NULL)'),4)
            for profile in ['default_iv','explicit_iv']:
                for op in ['encrypt','decrypt']:
                    name=f'sm4_{op}_{profile}_{impl}'
                    self.assertIn(f'FUNCTION {name}',sql)
                    self.assertIn(f"HANDLER = '{name}'",sql)

    def test_configurable_deployment(self):
        result=gen.generate('https://udf.example.test:8815','@my_stage/releases/sm4.wasm')
        self.assertIn('https://udf.example.test:8815',result['python.sql'])
        self.assertIn('$$@my_stage/releases/sm4.wasm$$',result['wasm.sql'])

    def test_invalid_configuration(self):
        for address in ["http://host'; DROP TABLE t;--",'file:///tmp/a','https://u:p@host','https://host/path']:
            with self.subTest(address):self.assertRaises(ValueError,gen.generate,address)
        self.assertRaises(ValueError,gen.generate,wasm_path="@bad/a.wasm';--")


if __name__=='__main__':unittest.main()
