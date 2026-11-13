import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from .errors import RetrieverUnavailable


class Retriever:
    def __init__(self, root, cfg):
        self.root, self.cfg, self.process = root, cfg, None
        self.identity = uuid.uuid4().hex

    def __enter__(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', self.cfg['port']))
            port = sock.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        self.log = (self.root/'output/retriever.log').open('a', encoding='utf-8')
        command = [sys.executable, '-I', str(self.root/'scripts/retriever_server.py'), '--port', str(port),
                   '--identity', self.identity, '--device', self.cfg['device']]
        self.process = subprocess.Popen(command, cwd=self.root, stdout=self.log, stderr=self.log)
        deadline = time.monotonic() + self.cfg['startup_timeout']
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None: raise RetrieverUnavailable('Retriever 启动失败，查看 output/retriever.log。')
                try:
                    with urllib.request.urlopen(self.url+'/health', timeout=2) as r:
                        if json.load(r).get('identity') == self.identity: return self
                except (OSError, ValueError): pass
                time.sleep(0.5)
            raise RetrieverUnavailable('Retriever 启动超时，保留进度。')
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def healthy(self):
        if self.process is None or self.process.poll() is not None:
            raise RetrieverUnavailable('Retriever 子进程已退出，暂停教师调用。')

    def search(self, query):
        for attempt in range(self.cfg['retries']+1):
            self.healthy()
            request = urllib.request.Request(self.url+'/retrieve', data=json.dumps(
                dict(queries=[query], topk=3, return_scores=True)).encode(), headers={'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=self.cfg['timeout']) as r: obj=json.load(r)
                docs = obj['result'][0]
                if not isinstance(docs,list): raise ValueError('not a document list')
                for d in docs:
                    if not isinstance(d['document']['contents'],str): raise ValueError('invalid document')
                return docs  # [] is a valid observation.
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                if attempt >= self.cfg['retries']: break
                time.sleep(min(2**attempt, 8))
        raise RetrieverUnavailable('检索临时错误重试耗尽，暂停教师调用。')

    def __exit__(self, *args):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
        if getattr(self,'log',None): self.log.close()


class MockRetriever:
    def healthy(self): pass
    def search(self, query): return [{'document':{'id':'fixture','contents':'Synthetic fixture: fixture answer'},'score':1.0}]
