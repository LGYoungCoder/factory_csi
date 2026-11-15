#!/usr/bin/env bash
# Shared helpers for Kiro hook scripts (bash 3.2 compatible).
# Kiro passes the hook event as JSON on STDIN. The field carrying the saved
# file path is not named in the current hook docs (checked 2026-11-15), so we
# accept the path as $1 and otherwise search common keys:
# file_path, filePath, path, file, files[0], tool_input.path.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

resolve_saved_path() {
  # $1 = optional explicit path
  local p="${1:-}"
  if [ -z "$p" ] && [ ! -t 0 ]; then
    p="$(python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
def find(d):
    if isinstance(d, dict):
        for k in ("file_path", "filePath", "path", "file"):
            v = d.get(k)
            if isinstance(v, str) and v:
                return v
        files = d.get("files")
        if isinstance(files, list) and files and isinstance(files[0], str):
            return files[0]
        for v in d.values():
            r = find(v)
            if r:
                return r
    return None
r = find(data)
print(r or "")
' 2>/dev/null || true)"
  fi
  [ -z "$p" ] && return 1
  case "$p" in
    "$REPO_ROOT"/*) p="${p#"$REPO_ROOT"/}" ;;
  esac
  printf '%s' "$p"
}
