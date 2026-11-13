"""Self-test only: actual FAISS Flat over explicitly synthetic fixture documents."""
import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import faiss
import numpy as np


def vector(text):
    arr=np.frombuffer(hashlib.sha256(text.encode()).digest(),dtype=np.uint8).astype('float32')
    arr=arr.reshape(1,-1)
    faiss.normalize_L2(arr)
    return arr


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,required=True)
    p.add_argument('--identity',required=True)
    p.add_argument('--device')
    args=p.parse_args()
    index=faiss.IndexFlatIP(32)
    documents=[{'id':'fixture-'+str(i),'contents':'Synthetic fixture evidence: fixture answer'} for i in range(3)]
    index.add(np.concatenate([vector('fixture evidence '+str(i)) for i in range(3)]))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,obj):
            body=json.dumps(obj).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self): self.send({'ready':True,'identity':args.identity})
        def do_POST(self):
            req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            scores,ids=index.search(vector(req['queries'][0]),3)
            self.send({'result':[[{'document':documents[i],'score':float(s)} for i,s in zip(ids[0],scores[0])]]})
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()


if __name__=='__main__': main()
