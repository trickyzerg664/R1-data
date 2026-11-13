import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))

from synth.config import ROOT, load
from synth.bootstrap import ensure_runtime
from synth.data import candidates, fixtures
from synth.engine import process
from synth.errors import ConfigurationError, StopRun, safe_message
from synth.output import finalize, resume_pending_upload, upload_succeeded
from synth.resources import inspect, ensure
from synth.retriever import Retriever, MockRetriever
from synth.store import Store
from synth.teacher import Teacher, MockTeacher


def run(root, cfg, questions, teacher, retriever, store, uploader=None):
    reason = 'candidates_exhausted'
    try:
        if store.accepted() >= cfg['target_accepted']: reason = 'target_reached'
        else:
            for q in questions:
                process(q, store, teacher, retriever, cfg)
                stats = store.stats('running', {})
                print(f"Processed: {stats['processed']} | Accepted: {stats['accepted']} | Rejected: {stats['rejected']} | API calls: {stats['api_calls']} | Status: Running", flush=True)
                if stats['accepted'] >= cfg['target_accepted']:
                    reason = 'target_reached'; break
    except KeyboardInterrupt: reason = 'interrupted'
    except StopRun as exc:
        reason = exc.reason
        print(safe_message(exc, [os.environ.get('API_KEY',''),os.environ.get('HF_TOKEN','')]), file=sys.stderr)
    except Exception as exc:
        reason = 'global_error'
        store.error(type(exc).__name__)
        print('Global error: '+safe_message(exc, [os.environ.get('API_KEY',''),os.environ.get('HF_TOKEN','')]), file=sys.stderr)
    kwargs = {'uploader':uploader} if uploader else {}
    store.set_meta('stop_reason',reason)
    stats = finalize(root, store, reason, cfg['upload'], **kwargs)
    print('Status: '+reason, flush=True)
    return stats


def main():
    ensure_runtime(ROOT,sys.argv[1:])
    parser = argparse.ArgumentParser(description='Search-R1 standalone synthesis (target: 3000 accepted trajectories)')
    parser.add_argument('--mock', action='store_true', help='Only synthetic fixtures, no API, downloads or real retrieval')
    parser.add_argument('--check', action='store_true', help='Check packaged data and linked resources without API or downloads')
    parser.add_argument('--upload-only', action='store_true', help='Retry upload without generation')
    parser.add_argument('--self-test', action='store_true', help='Isolated local HTTP + FAISS pipeline; no credentials or external API')
    parser.add_argument('--retriever-smoke', action='store_true', help='Load real local resources and search once without teacher API')
    args = parser.parse_args()
    root, cfg = load()
    if args.self_test:
        from synth.selftest import execute
        return execute(root,cfg)
    if args.retriever_smoke:
        ensure(root,cfg['retriever'])
        print('Starting real Retriever (full Flat index; no teacher API)...',flush=True)
        with Retriever(root,cfg['retriever']) as retriever:
            docs=retriever.search('What is the capital of France?')
        if len(docs)!=3: raise SystemExit('Real retrieval smoke failed: expected three documents')
        result={'status':'passed','teacher_api_calls':0,'query':'What is the capital of France?',
                'documents':docs}
        (root/'output/retriever_smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'retriever_smoke':'passed','documents':len(docs),'teacher_api_calls':0},indent=2))
        return 0
    if args.mock:
        root = ROOT/'output/mock'
        (root/'output').mkdir(parents=True,exist_ok=True)
        cfg['target_accepted'] = 3
    if args.check:
        count = sum(1 for _ in candidates(root))
        print(json.dumps(dict(candidates=count, target=cfg['target_accepted'], resources=inspect(root),
                              teacher_model_configured=bool(cfg['teacher']['model']),
                              upload_repo_configured=bool(cfg['upload']['repo_id'])), indent=2))
        return 0
    store = Store(root/'output/state.sqlite3')
    try:
        if args.upload_only:
            stats=finalize(root,store,store.meta('stop_reason') or 'upload_only',cfg['upload'])
            return 0 if upload_succeeded(stats['upload']) else 3
        if args.mock:
            stats = run(root,cfg,fixtures(),MockTeacher(store),MockRetriever(),store,
                        uploader=lambda *a:{'status':'skipped_mock'})
        else:
            pending=resume_pending_upload(root,store,cfg['upload'])
            if pending is not None and not upload_succeeded(pending['upload']):
                print('待上传结果仍未送达，本次不发起新的教师 API 请求。',file=sys.stderr)
                return 3
            try:
                # Validate teacher configuration before any large download or paid request.
                teacher = Teacher(cfg['teacher'],store)
                qs = candidates(root)
                first = next(qs, None)
                if first is None: raise ConfigurationError('候选题包为空。')
                fingerprint = hashlib.sha256(json.dumps(dict(teacher=cfg['teacher'],max_turns=cfg['max_turns'],
                    min_searches=cfg['min_searches'],data=json.loads((root/'data/manifest.json').read_text())['bundle_sha256']),sort_keys=True).encode()).hexdigest()
                previous = store.meta('fingerprint')
                if previous and previous != fingerprint: raise ConfigurationError('运行配置或数据包已改变；请保留旧 output 并使用新的输出状态。')
                store.set_meta('fingerprint',fingerprint)
                if store.accepted() >= cfg['target_accepted']:
                    stats = finalize(root,store,'target_reached',cfg['upload'])
                else:
                    ensure(root,cfg['retriever'])
                    import itertools
                    with Retriever(root,cfg['retriever']) as retriever:
                        stats = run(root,cfg,itertools.chain([first],qs),teacher,retriever,store)
            except (StopRun, KeyboardInterrupt) as exc:
                reason = exc.reason if isinstance(exc,StopRun) else 'interrupted'
                print(safe_message(exc,[os.environ.get('API_KEY','')]), file=sys.stderr)
                stats = finalize(root,store,reason,cfg['upload'])
            except Exception as exc:
                store.error(type(exc).__name__)
                print('Global error: '+safe_message(exc,[os.environ.get('API_KEY',''),os.environ.get('HF_TOKEN','')]),file=sys.stderr)
                stats = finalize(root,store,'global_error',cfg['upload'])
        store.set_meta('stop_reason',stats['stop_reason'])
        if not upload_succeeded(stats['upload']): return 3
        return 0 if stats['stop_reason'] in ('target_reached','candidates_exhausted') else 2
    finally: store.close()


if __name__ == '__main__': raise SystemExit(main())
