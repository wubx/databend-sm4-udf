"""Report validation tests use synthetic timing records, never claim benchmark results."""
import csv
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from report_results import REPORT_DIR,build,render,readme_summary


def inputs(row_counts=(1000,10000)):
    raw=json.loads((ROOT/'tests/vectors.json').read_text())['cases']
    compat=json.loads((ROOT/'tests/compat_vectors.json').read_text())['cases']
    queries=[]
    for impl in ['python','js','wasm']:
        queries.extend([
            {'sql':f"op='encrypt' x_sm4_encrypt_{impl}(data,k,iv,mode)",'data':[[v['id'],v['expected']] for v in raw]},
            {'sql':f'x_sm4_encrypt_default_iv_{impl}(data,k,iv,mode)','data':[[v['id'],v['expected']] for v in compat]},
            {'sql':f'AS case_id x_sm4_encrypt_explicit_iv_{impl}(','data':[['demo','Hello Databend','Hello Databend']]*7},
        ])
    integration={'passed':True,'benchmark_report_passed':True,'cleanup_errors':[],'version':'test-engine',
        'started_at':'test-start','finished_at':'test-end','wasm_sha256':'test-hash',
        'compatibility_vectors_passed':len(compat),'queries':queries,
        'deployment_regressions':[{'ok':True}]*9,'endpoint':'https://private.invalid','namespace':'secret-stage'}
    meta={'profile':'explicit_iv','modes':['CBC'],'operations':['decrypt'],'lengths':[16,128,1024],
          'rows':list(row_counts),'repeats':3,'threads':1,'max_block_size':8192,'query_cache':False,
          'version':[['test-engine']],'sha256':{'javascript/sm4.mjs':hashlib.sha256((ROOT/'javascript/sm4.mjs').read_bytes()).hexdigest()},
          'packages':{'gmssl':'test'},'python_version':'3.test','cpu':'test-cpu','logical_cpus':2,
          'platform':'test-platform','interface':'BINARY,STRING,STRING,STRING -> BINARY','plaintext_pattern':'Hello Databend'}
    samples=[]
    for length in meta['lengths']:
        for count in meta['rows']:
            for impl in ['python','js','wasm']:
                for repeat in range(4):
                    samples.append({'length':length,'rows':count,'impl':impl,'mode':'CBC','op':'decrypt',
                        'phase':'warmup' if repeat==0 else 'measure','repeat':0 if repeat==0 else repeat-1,
                        'data':[[str(count),'123']],'server_ms':100+repeat,'wall_ms':110+repeat,
                        'sql':'sensitive local SQL','query_id':'private-query'})
    benchmark={'complete':True,'metadata':meta,'samples':samples}
    unit={'checks':[{'name':'python','returncode':0,'stdout':'','stderr':'Ran 19 tests\nOK'}]+
          [{'name':name,'returncode':0} for name in ['javascript','javascript_adapters','rust','sql_generation']],
          'rustc':'test-rust','node':{'node':'test-node','openssl':'test-openssl'}}
    deploy={'status':'SUCCEEDED','vectors_per_backend':len(compat),'sha256':'test-hash','version':'test-engine',
        'article_checks':{impl:{'data':[['demo','Hello Databend','Hello Databend']]*7} for impl in ['wasm','js']},
        'strict_before':[['a','definition']],'strict_after':[['a','definition']]}
    return integration,benchmark,unit,deploy


class ReportChecks(unittest.TestCase):
    def test_completed_records_and_redaction(self):
        evidence=build(*inputs())
        self.assertEqual(evidence['benchmark']['timed_query_count'],72)
        self.assertEqual(len(evidence['benchmark']['summary']),18)
        self.assertEqual(evidence['correctness']['vector_assertions_across_three_backends'],1410)
        text=json.dumps(evidence)
        for forbidden in ['private.invalid','secret-stage','sensitive local SQL','private-query']:
            self.assertNotIn(forbidden,text)
        self.assertIn('测试报告',render(evidence))

    def test_published_snapshot_matches_renderer(self):
        evidence=json.loads((REPORT_DIR/'results.json').read_text())
        self.assertEqual((REPORT_DIR/'REPORT.md').read_text(),render(evidence))
        self.assertTrue(evidence['benchmark']['complete'])
        workloads=len(evidence['benchmark']['lengths'])*len(evidence['benchmark']['rows'])*3
        self.assertEqual(len(evidence['benchmark']['samples']),workloads*4)
        self.assertEqual(len(evidence['benchmark']['summary']),workloads)
        text=(ROOT/'README.md').read_text()
        summary=text.split('<!-- TEST_REPORT_SUMMARY_START -->',1)[1].split('<!-- TEST_REPORT_SUMMARY_END -->',1)[0].strip()
        self.assertEqual(summary,readme_summary(evidence))
        with (REPORT_DIR/'results.csv').open(newline='') as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),workloads)
        for row,expected in zip(rows,evidence['benchmark']['summary']):
            self.assertEqual(row['impl'],expected['impl'])
            for field in ['length','rows','median_ms','min_ms','max_ms','samples']:
                self.assertEqual(float(row[field]),expected[field])

    def test_tens_of_thousands_matrix_requires_all_repeats(self):
        records=inputs((1000,10000,30000,50000))
        evidence=build(*records)
        self.assertEqual(evidence['benchmark']['timed_query_count'],144)
        self.assertEqual(len(evidence['benchmark']['summary']),36)
        self.assertIn('50,000',render(evidence))
        self.assertIn('144 次计时查询',readme_summary(evidence))
        records[1]['samples'].pop()
        self.assertRaises(AssertionError,build,*records)

    def test_reject_incomplete_or_failed_run(self):
        for change in ['incomplete','cleanup','unit','sample_count','checksum','source','missing_repeat','bad_vector','artifact']:
            with self.subTest(change):
                i,b,u,d=inputs()
                if change=='incomplete':b['complete']=False
                elif change=='cleanup':i['cleanup_errors']=['failed']
                elif change=='unit':u['checks'][0]['returncode']=1
                elif change=='sample_count':b['samples'].pop()
                elif change=='checksum':b['samples'][0]['data'][0][1]='wrong'
                elif change=='source':b['metadata']['sha256']['javascript/sm4.mjs']='wrong'
                elif change=='missing_repeat':b['samples'][3]['repeat']=1
                elif change=='bad_vector':i['queries'][0]['data'][0][1]='wrong'
                elif change=='artifact':d['sha256']='wrong'
                self.assertRaises(AssertionError,build,i,b,u,d)


if __name__=='__main__':unittest.main()
