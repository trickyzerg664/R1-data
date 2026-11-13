#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { printf '环境包仅支持 Linux x86_64。\n' >&2; exit 2; }
manifest="$ROOT/runtime-manifest.json"
[[ -f "$manifest" ]] || { printf '缺少 runtime-manifest.json。\n' >&2; exit 2; }
name="$(sed -n 's/.*"filename": "\([^"]*\)".*/\1/p' "$manifest")"
sha="$(sed -n 's/.*"sha256": "\([^"]*\)".*/\1/p' "$manifest")"
url="$(sed -n 's/.*"download_url": "\([^"]*\)".*/\1/p' "$manifest")"
archive="$ROOT/$name"
if [[ ! -f "$archive" ]]; then
  token="${HF_TOKEN:-}"
  if [[ -z "$token" && -f "$ROOT/.env" ]]; then
    while IFS='=' read -r key value; do
      if [[ "$key" == HF_TOKEN ]]; then token="${value%$'\r'}";token="${token#\"}";token="${token%\"}";break;fi
    done < "$ROOT/.env"
  fi
  [[ "$token" == hf_* && -n "$url" ]] || { printf '请预配置 HF_TOKEN，或将配套环境包下载到项目根目录。\n' >&2;exit 2; }
  printf 'Downloading portable Python runtime...\n'
  # Keep the credential out of argv and shell tracing.
  printf 'header = "Authorization: Bearer %s"\n' "$token" | curl --config - --fail --location --retry 2 --connect-timeout 10 --max-time 1800 "$url" --output "$archive.partial"
  mv -- "$archive.partial" "$archive"
fi
printf '%s  %s\n' "$sha" "$archive" | sha256sum --check --status || { printf '环境包 SHA256 校验失败。\n' >&2;exit 2; }
tar -xzf "$archive" -C "$ROOT"
printf 'Portable Python runtime installed.\n'
