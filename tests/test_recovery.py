import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from main import run
from synth.data import fixtures
from synth.engine import process
from synth.errors import ConfigurationError, classify
from synth.output import finalize
from synth.retriever import Retriever, MockRetriever
from synth.store import Store
from synth.teacher import Teacher, MockTeacher


def response(text):
    return io.BytesIO(json.dumps({'choices':[{'message':{'content':text}}],
                                  'usage':{'prompt_tokens':10,'completion_tokens':5}}).encode())


def http_error(status, body, headers=None):
    return urllib.error.HTTPError('https://fixture.invalid',status,'fixture',headers or {},
                                  io.BytesIO(json.dumps(body).encode()))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'output').mkdir()
        self.cfg = json.loads((ROOT/'config.json').read_text())
        self.cfg['target_accepted'] = 3
        self.cfg['teacher']['model'] = 'fixture-model'
        self.cfg['teacher']['retries'] = 1
        self.store = Store(self.root/'output/state.sqlite3')
        self.env = patch.dict(os.environ,{'API_BASE_URL':'https://fixture.invalid/v1','API_KEY':'TEST-SECRET'})
        self.env.start()

    def tearDown(self):
        self.store.close(); self.env.stop(); self.tmp.cleanup()

    def execute(self, teacher=None, retriever=None, uploader=None):
        return run(self.root,self.cfg,fixtures(3),teacher or MockTeacher(self.store),
                   retriever or MockRetriever(),self.store,uploader or (lambda *a:{'status':'succeeded'}))

    def test_multiturn_and_target(self):
        stats = self.execute()
        self.assertEqual((stats['accepted'],stats['api_calls'],stats['retrievals']),(3,6,3))
        self.assertEqual(stats['stop_reason'],'target_reached')
        q = self.store.get('mock:0')
        self.assertIsNotNone(q['turns'][0]['observation'])
        self.assertNotIn('golden_answers',json.dumps(q['turns'][0]['request']))
        self.assertEqual(stats['input_tokens'],60)

    def test_429_waits_and_continues(self):
        delays, calls = [], []
        def opener(req, **kw):
            calls.append(req)
            if len(calls)==1: raise http_error(429,{'error':{'message':'rate limit'}},{'Retry-After':'0.01'})
            text = '<think>look</think><search>fixture</search>' if len(calls)==2 else '<think>done</think><answer>fixture answer</answer>'
            return response(text)
        teacher = Teacher(self.cfg['teacher'],self.store,opener=opener,sleep=delays.append)
        process(next(fixtures()),self.store,teacher,MockRetriever(),self.cfg)
        self.assertEqual(delays,[0.01])
        self.assertEqual(self.store.accepted(),1)
        self.assertEqual(len(calls),3)

    def test_quota_stops_saves_and_uploads(self):
        normal = MockTeacher(self.store)
        def opener(*a,**kw): raise http_error(429,{'error':{'code':'insufficient_quota'}})
        failed = Teacher(self.cfg['teacher'],self.store,opener=opener)
        class Switch:
            def complete(inner,task,commit):
                return (normal if task['id']=='mock:0' else failed).complete(task,commit)
        uploaded = []
        stats=self.execute(Switch(),uploader=lambda *a:uploaded.append(1) or {'status':'succeeded'})
        self.assertEqual((stats['accepted'],stats['stop_reason']),(1,'quota_exhausted'))
        self.assertEqual(uploaded,[1])
        self.assertTrue((self.root/'output/accepted.jsonl').stat().st_size)

    def test_invalid_key_not_retried(self):
        calls=[]
        def opener(*a,**kw): calls.append(1); raise http_error(401,{'error':{'message':'invalid key'}})
        stats=self.execute(Teacher(self.cfg['teacher'],self.store,opener=opener))
        self.assertEqual(len(calls),1)
        self.assertEqual(stats['stop_reason'],'configuration_error')

    def test_bad_question_does_not_stop_batch(self):
        normal = MockTeacher(self.store)
        class BadFirst:
            def complete(inner,task,commit):
                if task['id']!='mock:0': return normal.complete(task,commit)
                req={'messages':task['messages']}
                call=self.store.begin_call(task['id'],req,'fixture')
                commit({'choices':[{'message':{'content':'malformed'}}]},req,call)
        stats=self.execute(BadFirst())
        self.assertEqual((stats['accepted'],stats['rejected']),(2,1))
        self.assertEqual(self.store.get('mock:0')['attempt'],3)

    def test_dead_retriever_stops_before_teacher(self):
        dead=Retriever(self.root,self.cfg['retriever'])
        dead.process=subprocess.Popen([sys.executable,'-c','pass'])
        dead.process.wait()
        stats=self.execute(retriever=dead)
        self.assertEqual(stats['stop_reason'],'retriever_unavailable')
        self.assertEqual(stats['api_calls'],0)

    def test_interruption_resumes_after_teacher_without_rebilling(self):
        class Interrupt(MockRetriever):
            def search(inner,q): raise KeyboardInterrupt()
        stats=self.execute(retriever=Interrupt())
        self.assertEqual(stats['stop_reason'],'interrupted')
        self.assertEqual(stats['api_calls'],1)
        self.store.close(); self.store=Store(self.root/'output/state.sqlite3')
        stats=self.execute()
        self.assertEqual((stats['accepted'],stats['api_calls']),(3,6))
        self.execute()
        self.assertEqual(self.store.stats('done',{})['api_calls'],6)

    def test_upload_failure_keeps_data_and_retry_does_not_generate(self):
        def fail(*a): raise OSError('upload failed')
        stats=self.execute(uploader=fail)
        self.assertEqual(stats['upload']['status'],'failed')
        for name in ('accepted.jsonl','trajectories.jsonl','result.zip','stats.json'):
            self.assertTrue((self.root/'output'/name).stat().st_size)
        result=finalize(self.root,self.store,'target_reached',{},uploader=lambda *a:{'status':'succeeded'})
        self.assertEqual(result['api_calls'],6)

    def test_other_working_directory(self):
        folder=self.root/'project'; folder.mkdir()
        shutil.copy(ROOT/'main.py',folder)
        shutil.copy(ROOT/'config.json',folder)
        shutil.copytree(ROOT/'synth',folder/'synth',ignore=shutil.ignore_patterns('__pycache__'))
        result=subprocess.run([sys.executable,str(folder/'main.py'),'--mock'],cwd=self.root,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        stats=json.loads((folder/'output/mock/output/stats.json').read_text())
        self.assertEqual(stats['accepted'],3)
        self.assertFalse((self.root/'cache').exists())

    def test_timeout_is_uncertain_and_bounded(self):
        def opener(*a,**kw): raise TimeoutError()
        teacher=Teacher(self.cfg['teacher'],self.store,opener=opener,sleep=lambda n:None)
        stats=self.execute(teacher)
        self.assertEqual(stats['api_calls'],2)
        self.assertEqual(stats['uncertain_requests'],2)
        self.assertEqual(stats['stop_reason'],'api_unavailable')

    def test_pending_call_recovered_as_uncertain(self):
        self.store.begin_call('mock:0',{'messages':[]},'logical')
        self.store.close(); self.store=Store(self.root/'output/state.sqlite3')
        self.assertEqual(self.store.stats('done',{})['uncertain_requests'],1)

    def test_empty_retrieval_is_valid(self):
        class Empty(MockRetriever):
            def search(inner,q): return []
        stats=self.execute(retriever=Empty())
        self.assertEqual(stats['accepted'],3)
        self.assertEqual(self.store.get('mock:0')['turns'][0]['observation'],[])

    def test_429_is_not_quota_without_explicit_evidence(self):
        self.assertEqual(classify(429,'{"error":{"message":"Too many requests"}}'),'recoverable')
        self.assertEqual(classify(402,'{"error":{"message":"余额不足"}}'),'quota_exhausted')

    def test_deepseek_402_without_body_stops_and_uploads(self):
        calls=[]
        def opener(*a,**kw):
            calls.append(1)
            raise http_error(402,{})
        teacher=Teacher(self.cfg['teacher'],self.store,opener=opener)
        uploaded=[]
        stats=self.execute(teacher,uploader=lambda *a:uploaded.append(1) or {'status':'succeeded'})
        self.assertEqual(stats['stop_reason'],'quota_exhausted')
        self.assertEqual(calls,[1])
        self.assertEqual(uploaded,[1])
        self.assertEqual(classify(402,'{}',provider='other'),'configuration_error')

    def test_deepseek_sends_disabled_thinking_and_keeps_raw_content(self):
        payloads=[]
        def opener(req,**kw):
            payloads.append(json.loads(req.data))
            text='<think>look</think><search>fixture</search>' if len(payloads)==1 else '<think>done</think><answer>fixture answer</answer>'
            return response(text)
        process(next(fixtures()),self.store,Teacher(self.cfg['teacher'],self.store,opener=opener),MockRetriever(),self.cfg)
        self.assertTrue(all(p['thinking']=={'type':'disabled'} for p in payloads))
        self.assertEqual(self.store.get('mock:0')['turns'][0]['response']['choices'][0]['message']['content'],
                         '<think>look</think><search>fixture</search>')


if __name__ == '__main__': unittest.main()
