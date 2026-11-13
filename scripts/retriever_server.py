"""Minimal local E5 + CPU FAISS Flat server. No RL dependencies."""
import argparse
import array
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--identity', required=True)
    p.add_argument('--device', choices=['auto','cpu','cuda'], default='auto')
    args = p.parse_args()
    os.environ['HF_HOME'] = str(ROOT/'cache/huggingface')
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    import faiss
    import numpy as np
    import torch
    import uvicorn
    from fastapi import FastAPI
    from pydantic import BaseModel
    from transformers import AutoTokenizer, AutoModel

    index = faiss.read_index(str(ROOT/'cache/wiki18/e5_Flat.index'))
    if not isinstance(index, faiss.IndexFlatIP) or index.d != 768:
        raise RuntimeError('Expected 768-dimensional E5 Flat inner-product index')
    device = 'cuda' if args.device == 'auto' and torch.cuda.is_available() else args.device
    if device == 'auto': device = 'cpu'
    model_dir = ROOT/'cache/e5-base-v2'
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModel.from_pretrained(model_dir, local_files_only=True).eval().to(device)
    corpus_path = ROOT/'cache/wiki18/wiki-18.jsonl'
    offsets_path = ROOT/'cache/corpus_offsets.npy'
    meta_path = ROOT/'cache/corpus_offsets.meta.json'
    identity = dict(size=corpus_path.stat().st_size, mtime=corpus_path.stat().st_mtime_ns, vectors=index.ntotal)
    valid = meta_path.is_file() and offsets_path.is_file() and json.loads(meta_path.read_text()) == identity
    if not valid:
        offsets = array.array('Q')
        with corpus_path.open('rb') as f:
            while True:
                pos = f.tell()
                line = f.readline()
                if not line: break
                json.loads(line)  # detect truncated or non-JSON corpus before becoming ready
                offsets.append(pos)
        if len(offsets) != index.ntotal: raise RuntimeError('Corpus/index row counts do not match')
        temp = offsets_path.with_suffix('.partial')
        with temp.open('wb') as f: np.save(f, np.frombuffer(offsets, dtype=np.uint64))
        temp.replace(offsets_path)
        meta_path.write_text(json.dumps(identity))
    offsets = np.load(offsets_path, mmap_mode='r')
    app = FastAPI()

    class Query(BaseModel):
        queries: list[str]
        topk: int = 3
        return_scores: bool = True

    @app.get('/health')
    def health(): return {'identity': args.identity, 'ready': True}

    @app.post('/retrieve')
    def retrieve(request: Query):
        if request.topk != 3: raise ValueError('Only topk=3 is supported')
        results = []
        for query in request.queries:
            inputs = tokenizer(['query: '+query], max_length=256, truncation=True, padding=True, return_tensors='pt').to(device)
            with torch.no_grad():
                hidden = model(**inputs).last_hidden_state
                mask = inputs['attention_mask'].bool()
                hidden = hidden.masked_fill(~mask[...,None], 0.0)
                emb = hidden.sum(1) / mask.sum(1)[...,None]
                emb = torch.nn.functional.normalize(emb, dim=-1).cpu().numpy().astype('float32')
            scores, ids = index.search(emb, 3)
            docs = []
            with corpus_path.open('rb') as f:
                for score, idx in zip(scores[0], ids[0]):
                    if idx < 0: continue
                    f.seek(int(offsets[idx])); doc = json.loads(f.readline())
                    docs.append({'document':doc, 'score':float(score)})
            results.append(docs)
        return {'result':results}

    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__': main()
