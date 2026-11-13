import json
import os
import zipfile
from .errors import safe_message

FILES = ('trajectories.jsonl', 'accepted.jsonl', 'rejected.jsonl', 'api_calls.jsonl', 'stats.json')


def export(root, store, reason, upload):
    out = root/'output'
    for name, status in (('trajectories.jsonl',None), ('accepted.jsonl','accepted'), ('rejected.jsonl','rejected')):
        tmp = out/(name+'.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            for row in store.db.execute('SELECT status,payload FROM questions ORDER BY rowid'):
                if status is None or row[0] == status: f.write(row[1]+'\n')
        tmp.replace(out/name)
    tmp = out/'api_calls.jsonl.tmp'
    with tmp.open('w', encoding='utf-8') as f:
        for row in store.db.execute('SELECT * FROM calls ORDER BY rowid'):
            obj = dict(row); obj['payload'] = json.loads(obj['payload'])
            f.write(json.dumps(obj, ensure_ascii=False)+'\n')
    tmp.replace(out/'api_calls.jsonl')
    stats = store.stats(reason, upload)
    write_stats(root, stats)
    return stats


def write_stats(root, stats):
    path = root/'output/stats.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    tmp.replace(path)


def archive(root):
    out = root/'output'
    tmp = out/'result.zip.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in FILES: z.write(out/name, name)
    tmp.replace(out/'result.zip')


def upload(root, store, cfg):
    if not cfg.get('repo_id'): return {'status':'not_configured', 'message':'维护者尚未配置 Hugging Face Dataset 仓库。'}
    token = os.environ.get('HF_TOKEN', '')
    if not token: return {'status':'auth_missing', 'message':'缺少独立 HF 上传授权；教师 API Key 不用于上传。'}
    try:
        from huggingface_hub import HfApi
        # Repository must already exist; do not create or change visibility implicitly.
        result = HfApi(token=token).upload_folder(repo_id=cfg['repo_id'], repo_type='dataset',
            folder_path=str(root/'output'), path_in_repo='runs/'+store.meta('run_id'),
            allow_patterns=list(FILES)+['result.zip'], commit_message='Upload synthesis run results')
        return {'status':'succeeded', 'commit':getattr(result,'oid',str(result))}
    except Exception as exc:
        return {'status':'failed', 'message':safe_message(exc, [token, os.environ.get('API_KEY','')])}


def finalize(root, store, reason, cfg, uploader=upload):
    # Uploaded stats describe the immutable upload snapshot. Final local stats record receipt.
    stats = export(root, store, reason, {'status':'pending'})
    archive(root)
    try: receipt = uploader(root, store, cfg)
    except Exception as exc: receipt = {'status':'failed','message':safe_message(exc, [os.environ.get('API_KEY',''), os.environ.get('HF_TOKEN','')])}
    store.set_meta('upload', receipt)
    stats['upload'] = receipt
    write_stats(root, stats)
    (root/'output/upload_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    if receipt['status'] != 'succeeded':
        archive(root)
        print('Upload: '+receipt['status']+' '+receipt.get('message',''))
    return stats
