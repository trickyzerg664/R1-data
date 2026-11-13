"""Build a small Git-trackable candidate bundle from existing prepared parquet."""
import argparse
import gzip
import hashlib
import itertools
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def key(text):
    return ' '.join(text.lower().strip().rstrip('?').split())


def build(assets):
    import pyarrow.parquet as pq
    assets = (ROOT / assets).resolve()
    folder = assets / 'datasets/nq_hotpotqa_train'
    excluded = set()
    test = folder / 'test.parquet'
    if test.exists():
        for b in pq.ParquetFile(test).iter_batches(columns=['question']):
            excluded.update(key(x) for x in b.column(0).to_pylist() if isinstance(x, str))
    groups = {'nq': [], 'hotpotqa': []}
    seen, counts = set(), Counter()
    train = folder / 'train.parquet'
    for b in pq.ParquetFile(train).iter_batches(columns=['id', 'question', 'golden_answers', 'data_source']):
        for row in b.to_pylist():
            counts['input'] += 1
            source, q = row['data_source'], row['question']
            if source not in groups or not isinstance(q, str) or not q.strip():
                counts['invalid'] += 1; continue
            answers = row['golden_answers'] or []
            if isinstance(answers, str): answers = [answers]
            answers = list(dict.fromkeys(a.strip() for a in answers if isinstance(a, str) and a.strip()))
            if not answers: counts['empty_answers'] += 1; continue
            canonical = key(q)
            if canonical in excluded: counts['evaluation_overlap'] += 1; continue
            if canonical in seen: counts['duplicate'] += 1; continue
            seen.add(canonical)
            identity = hashlib.sha256((source + '\n' + canonical).encode()).hexdigest()
            groups[source].append(dict(id=source + ':' + identity[:24], source=source,
                                       original_id=str(row['id']), question=q.strip(), golden_answers=answers))
    for rows in groups.values(): rows.sort(key=lambda r: r['id'])
    data = ROOT / 'data'; data.mkdir(exist_ok=True)
    target = data / 'candidates.jsonl.gz'
    with target.open('wb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as f:
            for pair in itertools.zip_longest(*groups.values()):
                for row in pair:
                    if row: f.write((json.dumps(row, ensure_ascii=False) + '\n').encode())
    manifest = dict(schema_version=1, source_repo='PeterJinGo/nq_hotpotqa_train',
                    source_revision='b7d80abfee334a7a91cb377544f09180d58b34f6',
                    original_dataset_family='RUC-NLPIR/FlashRAG_datasets',
                    source_configs=['nq', 'hotpotqa'], source_split='train',
                    provenance='Prepared Search-R1 dataset, source revision from existing asset manifest; input SHA256 verified separately.',
                    input_sha256=sha256(train),
                    evaluation_exclusion='Question text overlap with all sources in the supplied test.parquet',
                    filters=dict(counts), counts={k:len(v) for k,v in groups.items()},
                    total=sum(map(len, groups.values())), order='SHA256 deterministic per-source order, alternating NQ/HotpotQA',
                    bundle_sha256=sha256(target), bundle_bytes=target.stat().st_size,
                    target_accepted=3000, contains_gold=True,
                    redistribution='Preserve dataset-specific attribution and review upstream terms before publishing publicly.')
    (data / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', required=True, help='Asset directory relative to project root')
    args = parser.parse_args()
    build(args.assets)
