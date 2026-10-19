"""Synthetic records validate the benchmark reporter, not measured performance."""
import csv
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY=ROOT/'benchmarks/native-vs-wasm'
spec=importlib.util.spec_from_file_location('native_benchmark_report',DIRECTORY/'report.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)
SMALL=report.DEFAULT_REPORT_DIR
LARGE=report.LARGE_REPORT_DIR


def fixture():
    samples=[]
    for impl in report.IMPLS:
        for i in range(4):
            samples.append({'length':16,'rows':1000,'impl':impl,'phase':'warmup' if i==0 else 'measure',
                'repeat':0 if i==0 else i-1,'data':[['1000','1' if impl.endswith('md5') else '2']],
                'server_ms':i,'wall_ms':i+1,'sql':'private SQL','query_id':'private id'})
    return {'complete':True,'cleanup_errors':[],'metadata':{'lengths':[16],'rows':[1000],
        'repeats':3,'warmups':1,'max_threads':1,'result_cache':False},'validation':{},'samples':samples}


class NativeBenchmark(unittest.TestCase):
    def test_completed_record_is_sanitized(self):
        e=report.summarize(fixture())
        self.assertEqual(e['timed_query_count'],16)
        self.assertEqual(len(e['summary']),4)
        self.assertEqual(e['summary'][0]['median_ms'],2)
        self.assertNotIn('private SQL',json.dumps(e))
        self.assertNotIn('private id',json.dumps(e))

    def test_published_snapshot_matches_samples_and_report(self):
        for directory in [SMALL,LARGE]:
            with self.subTest(directory.name):
                evidence=json.loads((directory/'results.json').read_text())
                raw={'complete':True,'cleanup_errors':[],'metadata':evidence['metadata'],
                     'validation':evidence['validation'],'samples':[
                         {**s,'data':[[str(s['rows']),s['checksum']]]} for s in evidence['samples']]}
                self.assertEqual(report.summarize(raw),evidence)
                self.assertEqual((directory/'REPORT.md').read_text(),report.render(evidence))
                with (directory/'results.csv').open(newline='') as stream:
                    rows=list(csv.DictReader(stream))
                self.assertEqual(len(rows),len(evidence['summary']))
                for row,result in zip(rows,evidence['summary']):
                    self.assertEqual(row['impl'],result['impl'])
                    self.assertEqual(float(row['median_ms']),result['median_ms'])
        large=json.loads((LARGE/'results.json').read_text())
        self.assertEqual(large['metadata']['rows'],[100000,300000,1000000])
        self.assertEqual(large['metadata']['implementations'],['native_md5','wasm_md5'])
        self.assertEqual(large['timed_query_count'],108)
        self.assertEqual(len(large['summary']),18)

    def test_md5_only_excludes_identity(self):
        r=fixture()
        r['metadata']['implementations']=['native_md5','wasm_md5']
        r['samples']=[s for s in r['samples'] if s['impl'].endswith('md5')]
        e=report.summarize(r)
        self.assertEqual(e['timed_query_count'],8)
        self.assertEqual({s['impl'] for s in e['samples']},{'native_md5','wasm_md5'})
        self.assertEqual(len(e['summary']),2)
        r['samples'].pop()
        self.assertRaises(AssertionError,report.summarize,r)

    def test_separate_report_directory_preserves_old_snapshot(self):
        before={name:(SMALL/name).read_bytes() for name in ['REPORT.md','results.json','results.csv']}
        with tempfile.TemporaryDirectory() as tmp,patch.object(report,'render',return_value='Synthetic test report\n'):
            target=Path(tmp)/'large'
            report.publish(fixture(),target)
            self.assertEqual((target/'REPORT.md').read_text(),'Synthetic test report\n')
            self.assertEqual(len(json.loads((target/'results.json').read_text())['summary']),4)
            self.assertTrue((target/'results.csv').is_file())
        for name,data in before.items():self.assertEqual((SMALL/name).read_bytes(),data)

    def test_incomplete_wrong_results_and_cleanup_are_rejected(self):
        for kind in ['incomplete','partial','checksum','cleanup','repeat']:
            with self.subTest(kind):
                r=fixture()
                if kind=='incomplete':r['complete']=False
                elif kind=='partial':r['samples'].pop()
                elif kind=='checksum':r['samples'][0]['data'][0][1]='wrong'
                elif kind=='cleanup':r['cleanup_errors']=['failed']
                elif kind=='repeat':r['samples'][3]['repeat']=1
                self.assertRaises(AssertionError,report.summarize,r)


if __name__=='__main__':unittest.main()
