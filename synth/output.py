import json
import os
import time
import zipfile
from .errors import safe_message, retry_delay

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


def upload_succeeded(receipt):
    return receipt.get('status') in ('succeeded','skipped_mock','succeeded_local_fixture','skipped_empty')


def _upload_once(root, store, cfg):
    import requests
    from huggingface_hub import HfApi, configure_http_backend
    class TimedSession(requests.Session):
        def request(self,*args,**kwargs):
            if kwargs.get('timeout') is None:
                kwargs['timeout']=(cfg.get('connect_timeout',10),cfg.get('read_timeout',120))
            return super().request(*args,**kwargs)
    configure_http_backend(backend_factory=TimedSession)
    result = HfApi(token=os.environ['HF_TOKEN']).upload_folder(
        repo_id=cfg['repo_id'],repo_type='dataset',folder_path=str(root/'output'),
        path_in_repo='runs/'+store.meta('run_id'),allow_patterns=list(FILES)+['result.zip'],
        commit_message='Upload synthesis run results')
    return {'status':'succeeded','commit':getattr(result,'oid',str(result))}


def _upload_error(exc):
    response=getattr(exc,'response',None)
    status=getattr(response,'status_code',None) if response is not None else None
    status=status or getattr(exc,'code',None)
    headers=getattr(response,'headers',{}) if response is not None else getattr(exc,'headers',{})
    transient=(status in (408,409,425,429) or 500<=status<=599) if isinstance(status,int) else isinstance(exc,(OSError,TimeoutError,ConnectionError))
    return transient,headers or {},status


def upload(root, store, cfg, send=None, sleep=time.sleep):
    if not cfg.get('repo_id'): return {'status':'not_configured', 'message':'维护者尚未配置 Hugging Face Dataset 仓库。'}
    token = os.environ.get('HF_TOKEN', '')
    if not token: return {'status':'auth_missing', 'message':'缺少独立 HF 上传授权；教师 API Key 不用于上传。'}
    send=send or _upload_once
    for attempt in range(max(0,int(cfg.get('retries',4)))+1):
        total=(store.meta('upload_attempts_total') or 0)+1
        store.set_meta('upload_attempts_total',total)
        store.set_upload({'status':'uploading','attempts':attempt+1,'total_attempts':total},True)
        try:
            receipt=send(root,store,cfg)
            receipt.update(attempts=attempt+1,total_attempts=total)
            store.set_upload(receipt,not upload_succeeded(receipt))
            return receipt
        except KeyboardInterrupt:
            return {'status':'interrupted','attempts':attempt+1,'total_attempts':total,'message':'上传被中断，保留待重传状态。'}
        except Exception as exc:
            transient,headers,status=_upload_error(exc)
            store.error('upload_transient' if transient else 'upload_permanent')
            receipt={'status':'failed','attempts':attempt+1,'total_attempts':total,
                     'recoverable':transient,'http_status':status,
                     'message':safe_message(exc,[token,os.environ.get('API_KEY','')])}
            store.set_upload(receipt,True)
            if not transient or attempt>=cfg.get('retries',4): return receipt
            delay=retry_delay(headers,attempt,cfg.get('backoff_base',2),cfg.get('backoff_cap',60))
            print(f'Upload retry: {attempt+1}, waiting {delay:.1f}s',flush=True)
            try: sleep(delay)
            except KeyboardInterrupt:
                receipt.update(status='interrupted',message='重传等待被中断，保留待重传状态。')
                return receipt


def resume_pending_upload(root,store,cfg,uploader=None):
    pending=store.meta('upload_pending')
    previous=store.meta('upload')
    if pending is None: pending=bool(previous and not upload_succeeded(previous))
    if not pending: return None
    print('Pending results found; retrying upload before new teacher requests.',flush=True)
    return finalize(root,store,store.meta('stop_reason') or 'upload_pending',cfg,uploader=uploader)


def finalize(root, store, reason, cfg, uploader=None):
    # Uploaded stats describe the immutable upload snapshot. Final local stats record receipt.
    store.set_meta('stop_reason',reason)
    store.set_upload({'status':'pending'},True)
    stats = export(root, store, reason, {'status':'pending'})
    archive(root)
    has_data=store.db.execute('SELECT 1 FROM questions LIMIT 1').fetchone() or store.db.execute('SELECT 1 FROM calls LIMIT 1').fetchone()
    try:
        receipt=((uploader or upload)(root,store,cfg) if has_data else
                 {'status':'skipped_empty','message':'没有已生成数据，无需上传。'})
    except KeyboardInterrupt: receipt={'status':'interrupted','message':'上传被中断，保留本地结果。'}
    except Exception as exc: receipt = {'status':'failed','message':safe_message(exc, [os.environ.get('API_KEY',''), os.environ.get('HF_TOKEN','')])}
    store.set_upload(receipt,not upload_succeeded(receipt))
    stats['upload'] = receipt
    stats['upload_attempts']=store.meta('upload_attempts_total') or 0
    write_stats(root, stats)
    receipt_path=root/'output/upload_receipt.json'
    tmp=receipt_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(receipt_path)
    if not upload_succeeded(receipt):
        archive(root)
        print('Upload: '+receipt['status']+' '+receipt.get('message',''))
    else: print('Upload: '+receipt['status'],flush=True)
    return stats
