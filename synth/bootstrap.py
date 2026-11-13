"""Build an isolated CPU environment or use the relocatable Python bundle."""
import os
import hashlib
from pathlib import Path
import subprocess
import sys
import venv


def ensure_runtime(root, args):
    if any(flag in args for flag in ('--mock','--check','--help','-h')):
        return  # These remain standard-library-only diagnostics.
    root = Path(root)
    packed = root/'runtime/python/bin/python3'
    if packed.is_file():
        if Path(sys.prefix).resolve() == (root/'runtime/python').resolve(): return
        os.execv(str(packed), [str(packed),'-I',str(root/'main.py'),*args])
    env = root/'.venv'
    python = env/'bin/python'
    if sys.platform != 'linux':
        raise SystemExit('自动安装支持 Linux；其他系统可运行 --mock。')
    if sys.version_info[:2] not in ((3,10),(3,11)):
        raise SystemExit('请使用 Python 3.10/3.11，或解压配套 Linux Python 环境包。')
    marker = env/'.r1-ready'
    wheels=root/'cache/wheelhouse'
    req=root/'requirements-linux-cpu.lock'
    if not req.exists(): req=root/'requirements-cpu.txt'
    signature=hashlib.sha256(req.read_bytes()+str(sys.version_info[:2]).encode()).hexdigest()
    if not marker.is_file() or marker.read_text().strip()!=signature:
        print('Preparing isolated Python environment (first run only)...',flush=True)
        try:
            venv.EnvBuilder(with_pip=True).create(env)
        except (OSError,subprocess.CalledProcessError):
            raise SystemExit('系统 Python 缺少可用的 venv/ensurepip；请使用配套环境包运行 start.sh。')
        command=[str(python),'-I','-m','pip','install','--disable-pip-version-check','--no-cache-dir']
        if wheels.is_dir() and list(wheels.glob('*.whl')):
            command += ['--no-index','--find-links',str(wheels)]
        else: command += ['--extra-index-url','https://download.pytorch.org/whl/cpu']
        try:
            subprocess.run(command+['-r',str(req)],check=True,cwd=root)
            subprocess.run([str(python),'-I','-m','pip','check'],check=True,cwd=root)
        except subprocess.CalledProcessError:
            raise SystemExit('环境准备失败；请检查网络、磁盘和错误信息。下次启动会重试。')
        marker.write_text(signature+'\n')
    if Path(sys.prefix).resolve() != env.resolve():
        os.execv(str(python),[str(python),'-I',str(root/'main.py'),*args])
