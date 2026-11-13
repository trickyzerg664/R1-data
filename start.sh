#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ -x runtime/python/bin/python3 ]]; then
  exec runtime/python/bin/python3 -I main.py "$@"
fi
if [[ -f runtime-linux-x86_64-py310-cpu.tar.gz || -n "${HF_TOKEN:-}" ]] || { [[ -f .env ]] && grep -q '^HF_TOKEN=hf_' .env; }; then
  bash "$ROOT/install_runtime.sh"
  exec runtime/python/bin/python3 -I main.py "$@"
fi
for py in python3.10 python3.11 python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" -I main.py "$@"
  fi
done
printf '需要 Python 3.10/3.11，或先解压配套环境包到项目根目录。\n' >&2
exit 2
