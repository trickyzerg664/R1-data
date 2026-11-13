import gzip
import hashlib
import json
from .errors import ConfigurationError


def candidates(root):
    path = root / 'data/candidates.jsonl.gz'
    if not path.is_file(): raise ConfigurationError('缺少打包候选题，请先运行 scripts/bundle_candidates.py。')
    manifest = json.loads((root / 'data/manifest.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != manifest['bundle_sha256']: raise ConfigurationError('候选题包校验失败。')
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        for line in f: yield json.loads(line)


def fixtures(n=3):
    for i in range(n):
        yield dict(id='mock:' + str(i), source='nq' if i % 2 == 0 else 'hotpotqa',
                   question='Synthetic fixture question?', golden_answers=['fixture answer'])
