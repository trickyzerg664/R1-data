"""Link existing resources into ignored project cache; never modify the originals."""
import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def link(assets):
    base = (ROOT / assets).resolve()
    pairs = {'wiki18': base / 'retrieval/wiki18', 'e5-base-v2': base / 'models/e5-base-v2'}
    cache = ROOT / 'cache'; cache.mkdir(exist_ok=True)
    for name, target in pairs.items():
        if not target.is_dir(): raise SystemExit('Missing existing resource: ' + str(target))
        path = cache / name
        if path.exists() or path.is_symlink():
            if path.resolve() != target: raise SystemExit('Refusing to replace existing cache: ' + name)
        else:
            path.symlink_to(os.path.relpath(target, path.parent), target_is_directory=True)
        print(name + ': linked existing resources')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--assets', required=True, help='Relative to the project root')
    link(p.parse_args().assets)
