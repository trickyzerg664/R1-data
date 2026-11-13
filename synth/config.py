import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(root=ROOT):
    root = Path(root).resolve()
    env = root / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))
    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    for folder in ('cache', 'output'):
        (root / folder).mkdir(exist_ok=True)
    os.environ['HF_HOME'] = str(root / 'cache/huggingface')
    os.environ['HF_HUB_CACHE'] = str(root / 'cache/huggingface/hub')
    os.environ['TORCH_HOME'] = str(root / 'cache/torch')
    return root, config
