"""Regression coverage for the exact README query and a stale deployed module."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import check_deployment


class DeploymentRegression(unittest.TestCase):
    def result(self,data):
        return {'query_id':'mock-test','server_ms':1,'data':data}

    def test_original_lowercase_regression_is_preserved(self):
        vectors={v['id']:v for v in json.loads((ROOT/'tests/vectors.json').read_text())['cases']}
        for mode in check_deployment.MODES:
            enc=vectors[f'readme-hello-{mode}-enc']
            dec=vectors[f'readme-hello-{mode}-dec']
            self.assertEqual(enc['data'],b'hello Databend'.hex())
            self.assertEqual(enc['key'],'0123456789abcdeffedcba9876543210')
            self.assertEqual(enc['iv'],'00112233445566778899aabbccddeeff')
            self.assertEqual(enc['expected'],'4bcf1a8aee7b4b3c742053f5ee965cbe')
            self.assertEqual(dec['data'],enc['expected'])
            self.assertEqual(dec['expected'],enc['data'])

    def test_capitalized_public_demo_vectors(self):
        vectors={v['id']:v for v in json.loads((ROOT/'tests/vectors.json').read_text())['cases']}
        for mode in check_deployment.MODES:
            enc=vectors[f'public-hello-{mode}-enc']
            dec=vectors[f'public-hello-{mode}-dec']
            self.assertEqual(enc['data'],b'Hello Databend'.hex())
            self.assertEqual(enc['expected'].upper(),check_deployment.EXPECTED_CIPHERTEXT)
            self.assertEqual(dec['expected'].upper(),check_deployment.EXPECTED_PLAINTEXT)

    def test_accepted_values_pass_for_all_backends(self):
        expected=[[check_deployment.EXPECTED_CIPHERTEXT,check_deployment.EXPECTED_PLAINTEXT]]
        for impl in ['js','wasm','python']:
            query=Mock(return_value=self.result(expected))
            checks=check_deployment.check(query,impl,'temp_')
            self.assertTrue(all(r['ok'] for r in checks))
            self.assertEqual(query.call_count,3)
            for mode,sql in check_deployment.build_queries(impl,'temp_'):
                self.assertIn(f"'{mode}'",sql)
                self.assertIn('temp_sm4_encrypt_'+impl,sql)
                self.assertIn('temp_sm4_decrypt_'+impl,sql)
                self.assertIn("to_binary('Hello Databend')",sql)

    def test_stale_module_bare_cbc_null_is_failure(self):
        expected=[[check_deployment.EXPECTED_CIPHERTEXT,check_deployment.EXPECTED_PLAINTEXT]]
        query=Mock(side_effect=[self.result([[None,None]]),self.result(expected),self.result(expected)])
        checks=check_deployment.check(query)
        self.assertEqual([r['ok'] for r in checks],[False,True,True])
        self.assertEqual(checks[0]['mode'],'CBC')

    def test_cli_returns_nonzero_for_null(self):
        query=Mock(return_value=self.result([[None,None]]))
        with patch.object(check_deployment,'Client') as client,patch.object(sys,'argv',['check_deployment.py']):
            client.return_value.query=query
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:check_deployment.main()
            self.assertEqual(raised.exception.code,1)

    def test_sql_fixture_matches_checker(self):
        self.assertEqual((ROOT/'tests/deployment_smoke.sql').read_text(),check_deployment.sql_file())

    def test_invalid_backend_and_prefix(self):
        self.assertRaises(ValueError,check_deployment.build_queries,'bad')
        self.assertRaises(ValueError,check_deployment.build_queries,'wasm',"bad';--")


if __name__=='__main__':unittest.main()
