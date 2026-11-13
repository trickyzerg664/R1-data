"""Package only the standalone interpreter prefix; never credentials or project output."""
import hashlib
import json
from pathlib import Path
import platform
import tarfile

ROOT=Path(__file__).resolve().parents[1]
prefix=(ROOT/'runtime/python').resolve()
if not (prefix/'bin/python3').exists(): raise SystemExit('Prepare runtime/python first')
out=ROOT/'cache/artifacts';out.mkdir(parents=True,exist_ok=True)
path=out/'runtime-linux-x86_64-py310-cpu.tar.gz'
with tarfile.open(path,'w:gz') as archive:
    archive.add(prefix,arcname='runtime/python',filter=lambda info:None if '__pycache__' in info.name.split('/') else info)
digest=hashlib.sha256()
with path.open('rb') as f:
    for block in iter(lambda:f.read(8*1024*1024),b''):digest.update(block)
manifest=dict(filename=path.name,bytes=path.stat().st_size,sha256=digest.hexdigest(),
              python='3.10.16',platform='linux-x86_64',torch='2.5.1+cpu',
              tested_glibc=platform.libc_ver()[1],includes=['Python interpreter','all runtime dependencies'],
              excludes=['API credentials','HF credentials','questions','models','corpus','FAISS index'],
              hf_repo='tr1ckyzerg/R1-sft',hf_path='runtime/'+path.name)
(ROOT/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
