"""Exercise actual HTTP clients and managed retriever process without external APIs."""
import copy
import json
import os
from pathlib import Path
import shutil
import threading
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .data import fixtures
from .engine import process
from .output import finalize
from .retriever import Retriever
from .store import Store
from .teacher import Teacher


def execute(root,cfg):
    import faiss,torch,transformers,uvicorn,fastapi,huggingface_hub
    import numpy
    folder=root/'output/self_test'/uuid.uuid4().hex[:12]
    (folder/'output').mkdir(parents=True)
    (folder/'scripts').mkdir()
    shutil.copyfile(root/'tests/fixture_retriever_server.py',folder/'scripts/retriever_server.py')
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append(req)
            if 'golden_answers' in json.dumps(req): raise RuntimeError('Gold leak')
            searched=any(m['content'].startswith('<information>') for m in req['messages'])
            text=('<think>Use the fixture evidence.</think><answer>fixture answer</answer>' if searched else
                  '<think>Find fixture evidence.</think><search>fixture evidence</search>')
            body=json.dumps({'choices':[{'message':{'content':text}}],
                             'usage':{'prompt_tokens':10,'completion_tokens':5},'fixture':True}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    old={k:os.environ.get(k) for k in ('API_BASE_URL','API_KEY','HF_TOKEN')}
    os.environ['API_BASE_URL']=f'http://127.0.0.1:{server.server_port}/v1'
    os.environ['API_KEY']='local-self-test-fixture'
    os.environ.pop('HF_TOKEN',None)
    store=Store(folder/'output/state.sqlite3')
    config=copy.deepcopy(cfg)
    config['retriever']['startup_timeout']=30
    try:
        teacher=Teacher(config['teacher'],store)
        with Retriever(folder,config['retriever']) as retriever:
            for q in fixtures(3): process(q,store,teacher,retriever,config)
            # Replay must skip the completed questions and issue no extra HTTP requests.
            for q in fixtures(3): process(q,store,teacher,retriever,config)
        def local_upload(*args):
            shutil.copy2(folder/'output/result.zip',folder/'upload_received.zip')
            return {'status':'succeeded_local_fixture','external_upload':False}
        stats=finalize(folder,store,'self_test_completed',{},uploader=local_upload)
        assert stats['accepted']==3 and stats['api_calls']==6 and stats['retrievals']==3
        assert len(received)==6
        assert (folder/'upload_received.zip').stat().st_size>0
        print(json.dumps({'self_test':'passed','accepted':3,'http_api_calls':len(received),
                          'faiss_retrievals':3,'resume_skipped_completed':True,
                          'external_api_calls':0,'output':str(folder.relative_to(root)),
                          'versions':{'python':__import__('platform').python_version(),'torch':torch.__version__,
                                      'faiss':faiss.__version__,'numpy':numpy.__version__,
                                      'transformers':transformers.__version__}},ensure_ascii=False,indent=2))
        return 0
    finally:
        store.close();server.shutdown();server.server_close();thread.join(timeout=5)
        for k,v in old.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=v
