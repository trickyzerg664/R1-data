import gzip
import hashlib
import json
import shutil
import struct
import tarfile
from pathlib import Path
from .errors import ConfigurationError


def inspect(root):
    index, corpus, model = root/'cache/wiki18/e5_Flat.index', root/'cache/wiki18/wiki-18.jsonl', root/'cache/e5-base-v2'
    result = dict(index=False, corpus=False, model=False)
    if index.is_file():
        with index.open('rb') as f: header = f.read(45)
        if len(header) == 45 and header[:4] == b'IxFI':
            dim = struct.unpack_from('<i', header, 4)[0]
            n = struct.unpack_from('<q', header, 8)[0]
            metric = struct.unpack_from('<i', header, 33)[0]
            if dim == 768 and metric == 0 and index.stat().st_size == 45 + n*dim*4:
                result.update(index=True, index_vectors=n, index_bytes=index.stat().st_size)
    if corpus.is_file():
        try:
            with corpus.open(encoding='utf-8') as f: row = json.loads(f.readline())
            result['corpus'] = isinstance(row.get('contents'), str) and 'id' in row
            result['corpus_bytes'] = corpus.stat().st_size
        except (ValueError, OSError): pass
    result['model'] = all((model/f).is_file() for f in ('config.json', 'model.safetensors', 'tokenizer.json'))
    return result


def ensure(root, cfg):
    existing = inspect(root)
    if all(existing[k] for k in ('index','corpus','model')):
        verify(root)
        return existing
    # A partial or incompatible linked resource must never be overwritten.
    if (root/'cache/wiki18').is_symlink() or (root/'cache/e5-base-v2').is_symlink():
        raise ConfigurationError('链接的现有资源缺失或损坏，请检查资源完整性，不自动覆盖共享文件。')
    free = shutil.disk_usage(root/'cache').free / 10**9
    if free < cfg['min_free_gb']:
        raise ConfigurationError(f"下载准备空间不足：可用 {free:.1f} GB，要求 {cfg['min_free_gb']} GB；可先链接已有资源。")
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError: raise ConfigurationError('请先安装 requirements.txt。')
    if not all(cfg.get(k) for k in ('index_revision','corpus_revision','model_revision')):
        raise ConfigurationError('维护者须先固定索引、语料和模型的 revision；当前骨架不下载未固定版本的大文件。')
    wiki = root/'cache/wiki18'; wiki.mkdir(parents=True, exist_ok=True)
    if not existing['index']:
        parts = [Path(hf_hub_download(cfg['index_repo'], filename=name, repo_type='dataset',
                                     revision=cfg['index_revision'], local_dir=wiki)) for name in ('part_aa','part_ab')]
        tmp = wiki/'e5_Flat.index.partial'
        with tmp.open('wb') as out:
            for part in parts:
                with part.open('rb') as src: shutil.copyfileobj(src, out, 8*1024*1024)
        tmp.replace(wiki/'e5_Flat.index')
    if not existing['corpus']:
        archive = hf_hub_download(cfg['corpus_repo'], filename='wiki-18.jsonl.gz', repo_type='dataset',
                                  revision=cfg['corpus_revision'], local_dir=wiki)
        tmp = wiki/'wiki-18.jsonl.partial'
        # The original .gz is a tar.gz; copy exactly one JSONL member without extracting paths.
        if tarfile.is_tarfile(archive):
            with tarfile.open(archive, 'r:gz') as tar:
                members = [m for m in tar.getmembers() if m.isfile() and m.name.endswith('.jsonl')]
                if len(members) != 1: raise ConfigurationError('语料压缩包必须包含唯一 JSONL 文件。')
                with tar.extractfile(members[0]) as src, tmp.open('wb') as out: shutil.copyfileobj(src, out)
        else:
            with gzip.open(archive, 'rb') as src, tmp.open('wb') as out: shutil.copyfileobj(src, out)
        tmp.replace(wiki/'wiki-18.jsonl')
    if not existing['model']:
        snapshot_download(cfg['model_repo'], revision=cfg['model_revision'], local_dir=root/'cache/e5-base-v2',
                          allow_patterns=['*.json','model.safetensors','vocab.txt'])
    result = inspect(root)
    if not all(result[k] for k in ('index','corpus','model')):
        raise ConfigurationError('下载文件完整性检查失败，不启动 Retriever。')
    verify(root)
    return result


def verify(root):
    manifest=json.loads((root/'assets.json').read_text(encoding='utf-8'))
    items={name:item for name,item in manifest.items() if isinstance(item,dict)}
    def signature():
        result={}
        for name,item in items.items():
            stat=(root/item['path']).stat()
            result[name]=dict(path=item['path'],sha256=item['sha256'],size=stat.st_size,
                              mtime_ns=stat.st_mtime_ns,ctime_ns=stat.st_ctime_ns,
                              inode=stat.st_ino,device=stat.st_dev)
        return result
    before=signature()
    marker=root/'cache/resource-verification.json'
    if marker.is_file():
        try:
            if json.loads(marker.read_text())==before: return
        except (ValueError,OSError): pass
        marker.unlink()
    for name,item in items.items():
        print('Verifying resource SHA256: '+name,flush=True)
        h = hashlib.sha256()
        with (root/item['path']).open('rb') as f:
            for chunk in iter(lambda:f.read(8*1024*1024),b''): h.update(chunk)
        if h.hexdigest() != item['sha256']:
            raise ConfigurationError('下载资源 SHA256 校验失败：'+name)
    if signature()!=before: raise ConfigurationError('资源校验期间文件发生变化，请确认资源准备已完成后重试。')
    tmp=marker.with_suffix('.tmp')
    tmp.write_text(json.dumps(before,sort_keys=True)+'\n')
    tmp.replace(marker)
