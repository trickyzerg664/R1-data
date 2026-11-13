import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import main
from synth.data import fixtures
from synth.engine import process
from synth.output import finalize,resume_pending_upload,upload
from synth.resources import ensure
from synth.errors import ConfigurationError
from synth.retriever import MockRetriever
from synth.store import Store
from synth.teacher import MockTeacher,Teacher


def http_error(status,headers=None):
    return urllib.error.HTTPError('https://fixture.invalid',status,'fixture',headers or {},io.BytesIO(b'{}'))


class UploadRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'output').mkdir()
        self.cfg=json.loads((ROOT/'config.json').read_text())
        self.cfg['target_accepted']=3
        self.cfg['teacher']['retries']=1
        self.cfg['upload'].update(retries=2,backoff_base=0,backoff_cap=0)
        self.store=Store(self.root/'output/state.sqlite3')
        self.env=patch.dict(os.environ,{'API_BASE_URL':'https://fixture.invalid/v1',
                                       'API_KEY':'fixture-key','HF_TOKEN':'fixture-token'})
        self.env.start()

    def tearDown(self):
        self.store.close();self.env.stop();self.temp.cleanup()

    def accept_one(self):
        process(next(fixtures()),self.store,MockTeacher(self.store),MockRetriever(),self.cfg)

    def test_network_failure_retries_then_succeeds(self):
        self.accept_one()
        with patch('synth.output._upload_once',side_effect=[OSError('offline'),TimeoutError(),{'status':'succeeded'}]) as send:
            stats=finalize(self.root,self.store,'target_reached',self.cfg['upload'])
        self.assertEqual(send.call_count,3)
        self.assertEqual(stats['upload']['status'],'succeeded')
        self.assertEqual(stats['upload_attempts'],3)
        self.assertFalse(self.store.meta('upload_pending'))

    def test_upload_429_respects_retry_after(self):
        delays=[]
        with patch('synth.output._upload_once',side_effect=[http_error(429,{'Retry-After':'0.025'}),{'status':'succeeded'}]):
            result=upload(self.root,self.store,self.cfg['upload'],sleep=delays.append)
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(delays,[0.025])

    def test_permanent_upload_error_does_not_retry(self):
        self.accept_one()
        with patch('synth.output._upload_once',side_effect=http_error(403)) as send:
            stats=finalize(self.root,self.store,'global_error',self.cfg['upload'])
        self.assertEqual(send.call_count,1)
        self.assertFalse(stats['upload']['recoverable'])
        self.assertTrue(self.store.meta('upload_pending'))

    def test_retry_exhaustion_preserves_accepted_and_archive(self):
        self.accept_one()
        with patch('synth.output._upload_once',side_effect=TimeoutError()) as send:
            result=finalize(self.root,self.store,'api_unavailable',self.cfg['upload'])
        self.assertEqual(send.call_count,3)
        self.assertEqual(result['upload']['status'],'failed')
        self.assertTrue(self.store.meta('upload_pending'))
        self.assertEqual(len((self.root/'output/accepted.jsonl').read_text().splitlines()),1)
        self.assertGreater((self.root/'output/result.zip').stat().st_size,0)

    def test_unrecoverable_api_error_uploads_only_accepted_rows(self):
        good=MockTeacher(self.store)
        def broken(*args,**kwargs): raise http_error(503)
        bad=Teacher(self.cfg['teacher'],self.store,opener=broken,sleep=lambda n:None)
        class Switch:
            def complete(inner,task,commit):
                return (good if task['id']=='mock:0' else bad).complete(task,commit)
        with patch('synth.output._upload_once',side_effect=[TimeoutError(),{'status':'succeeded'}]) as send:
            stats=main.run(self.root,self.cfg,fixtures(3),Switch(),MockRetriever(),self.store)
        rows=[json.loads(line) for line in (self.root/'output/accepted.jsonl').read_text().splitlines()]
        self.assertEqual(stats['stop_reason'],'api_unavailable')
        self.assertEqual([row['id'] for row in rows],['mock:0'])
        self.assertTrue(all(row['status']=='accepted' for row in rows))
        self.assertEqual(stats['api_calls'],4)
        self.assertEqual(send.call_count,2)

    def test_unexpected_model_exception_still_uploads(self):
        good=MockTeacher(self.store)
        class Broken:
            def complete(inner,task,commit):
                if task['id']=='mock:0': return good.complete(task,commit)
                raise RuntimeError('injected model failure')
        with patch('synth.output._upload_once',return_value={'status':'succeeded'}) as send:
            stats=main.run(self.root,self.cfg,fixtures(3),Broken(),MockRetriever(),self.store)
        self.assertEqual((stats['stop_reason'],stats['accepted']),('global_error',1))
        self.assertEqual(send.call_count,1)

    def test_restart_retries_upload_without_teacher_calls(self):
        self.accept_one()
        with patch('synth.output._upload_once',side_effect=OSError('offline')):
            finalize(self.root,self.store,'api_unavailable',self.cfg['upload'])
        calls=self.store.stats('test',{})['api_calls']
        self.store.close();self.store=Store(self.root/'output/state.sqlite3')
        with patch('synth.output._upload_once',return_value={'status':'succeeded'}):
            stats=resume_pending_upload(self.root,self.store,self.cfg['upload'])
        self.assertEqual(stats['api_calls'],calls)
        self.assertEqual(stats['accepted'],1)
        self.assertFalse(self.store.meta('upload_pending'))
        self.assertIsNone(resume_pending_upload(self.root,self.store,self.cfg['upload']))

    def test_pending_failed_upload_blocks_new_teacher_requests(self):
        self.accept_one();self.store.set_meta('upload_pending',True)
        with patch.object(main,'ensure_runtime',lambda *a:None),patch.object(main,'load',lambda:(self.root,copy.deepcopy(self.cfg))),patch.object(sys,'argv',['main.py']),patch.object(main,'Teacher') as teacher,patch('synth.output._upload_once',side_effect=TimeoutError()):
            code=main.main()
        self.assertEqual(code,3)
        teacher.assert_not_called()

    def test_upload_only_failure_returns_nonzero(self):
        self.accept_one()
        with patch.object(main,'ensure_runtime',lambda *a:None),patch.object(main,'load',lambda:(self.root,copy.deepcopy(self.cfg))),patch.object(sys,'argv',['main.py','--upload-only']),patch('synth.output._upload_once',side_effect=TimeoutError()):
            code=main.main()
        self.assertEqual(code,3)
        self.assertEqual(self.store.stats('test',{})['api_calls'],2)

    def test_interrupt_during_upload_preserves_pending(self):
        self.accept_one()
        with patch('synth.output._upload_once',side_effect=KeyboardInterrupt()):
            stats=finalize(self.root,self.store,'interrupted',self.cfg['upload'])
        self.assertEqual(stats['upload']['status'],'interrupted')
        self.assertTrue(self.store.meta('upload_pending'))
        self.assertTrue((self.root/'output/accepted.jsonl').is_file())

    def test_secret_not_in_failure_receipt(self):
        self.accept_one()
        with patch('synth.output._upload_once',side_effect=OSError('failed fixture-token fixture-key')):
            stats=finalize(self.root,self.store,'global_error',self.cfg['upload'])
        text=json.dumps(stats)
        self.assertNotIn('fixture-token',text)
        self.assertNotIn('fixture-key',text)

    def test_empty_run_does_not_upload(self):
        with patch('synth.output._upload_once') as send:
            stats=finalize(self.root,self.store,'configuration_error',self.cfg['upload'])
        send.assert_not_called()
        self.assertEqual(stats['upload']['status'],'skipped_empty')
        self.assertFalse(self.store.meta('upload_pending'))


class ResourceValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        wiki=self.root/'cache/wiki18';wiki.mkdir(parents=True)
        model=self.root/'cache/e5-base-v2';model.mkdir()
        header=bytearray(45);header[:4]=b'IxFI'
        struct.pack_into('<i',header,4,768);struct.pack_into('<q',header,8,1)
        struct.pack_into('<i',header,33,0);struct.pack_into('<q',header,37,768)
        (wiki/'e5_Flat.index').write_bytes(header+bytes(3072))
        (wiki/'wiki-18.jsonl').write_text(json.dumps({'id':'0','contents':'fixture'})+'\n')
        for name in ('config.json','tokenizer.json','model.safetensors'): (model/name).write_text('fixture')
        self.items={}
        for name,path in [('index','cache/wiki18/e5_Flat.index'),('corpus','cache/wiki18/wiki-18.jsonl'),('model','cache/e5-base-v2/model.safetensors')]:
            self.items[name]={'path':path,'sha256':hashlib.sha256((self.root/path).read_bytes()).hexdigest()}
        self.write_manifest()

    def write_manifest(self): (self.root/'assets.json').write_text(json.dumps(self.items))
    def tearDown(self): self.temp.cleanup()

    def test_bad_checksum_cannot_be_bypassed_after_restart(self):
        self.items['index']['sha256']='0'*64;self.write_manifest()
        for _ in range(2):
            with self.assertRaises(ConfigurationError): ensure(self.root,{})
        self.assertFalse((self.root/'cache/resource-verification.json').exists())

    def test_verified_cache_is_reused_until_file_changes(self):
        self.assertTrue(ensure(self.root,{})['index'])
        with patch('synth.resources.hashlib.sha256',side_effect=AssertionError('unnecessary rehash')):
            self.assertTrue(ensure(self.root,{})['index'])
        path=self.root/self.items['index']['path']
        data=bytearray(path.read_bytes());data[-1]=1;path.write_bytes(data)
        with self.assertRaises(ConfigurationError): ensure(self.root,{})
        self.assertFalse((self.root/'cache/resource-verification.json').exists())


if __name__=='__main__': unittest.main()
