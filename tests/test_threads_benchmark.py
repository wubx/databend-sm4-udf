"""Synthetic records validate the max_threads reporter, not measured performance."""
import csv
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('threads_report',ROOT/'benchmarks/max-threads/report.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)
PUBLISHED=report.DEFAULT_REPORT_DIR
CASES=[[16,1000,'native_md5'],[16,1000,'wasm_md5'],[16,1000,'sm4_wasm']]


def fixture():
    samples=[]
    for length,rows,impl in CASES:
        for threads in [1,4]:
            for i in range(4):
                samples.append({'length':length,'rows':rows,'impl':impl,'threads':threads,
                    'phase':'warmup' if i==0 else 'measure','repeat':0 if i==0 else i-1,
                    'server_ms':(i+1)*(8 if threads==1 else 2),'wall_ms':0,'checksum':impl[-3:]})
    return {'complete':True,'cleanup_errors':[],'metadata':{'threads':[1,4],'repeats':3,'warmups':1,
        'result_cache':False,'cases':CASES},'tables':{},'pipelines':{},'samples':samples}


class ThreadsBenchmark(unittest.TestCase):
    def test_summary_and_speedup(self):
        e=report.summarize(fixture())
        self.assertEqual(e['timed_query_count'],24)
        self.assertEqual(len(e['summary']),6)
        self.assertEqual({r['speedup'] for r in e['summary'] if r['threads']==4},{4.0})

    def test_incomplete_and_inconsistent_records_are_rejected(self):
        for kind in ['incomplete','partial','checksum','cleanup','repeat','threads']:
            with self.subTest(kind):
                r=fixture()
                if kind=='incomplete':r['complete']=False
                elif kind=='partial':r['samples'].pop()
                elif kind=='checksum':r['samples'][-1]['checksum']='wrong'
                elif kind=='cleanup':r['cleanup_errors']=['failed']
                elif kind=='repeat':r['samples'][3]['repeat']=1
                elif kind=='threads':r['metadata']['threads']=[2,4]
                self.assertRaises(AssertionError,report.summarize,r)

    def test_pipe_count_parsing(self):
        graph=['digraph {','    0 [ label = "Resize" ]','    1 [ label = "UDFScriptTransform" ]',
               '    2 [ label = "UDFScriptTransform" ]','    1 -> 2 [ label = "" ]','}']
        self.assertEqual(report.udf_pipes(graph),2)
        self.assertIsNone(report.udf_pipes(['    0 [ label = "AggregatorFinalTransform" ]']))

    def test_published_snapshot_matches_report(self):
        evidence=json.loads((PUBLISHED/'results.json').read_text())
        raw={k:evidence[k] for k in ['metadata','tables','pipelines','samples']}|{'complete':True,'cleanup_errors':[]}
        self.assertEqual(report.summarize(raw),evidence)
        self.assertEqual((PUBLISHED/'REPORT.md').read_text(),report.render(evidence))
        with (PUBLISHED/'results.csv').open(newline='') as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual([(int(r['threads']),float(r['median_ms'])) for r in rows],
                         [(r['threads'],r['median_ms']) for r in evidence['summary']])


if __name__=='__main__':unittest.main()
