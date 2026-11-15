#!/usr/bin/env bash
# Secret guard: scan a saved file (hook mode) or all git-tracked files (--all)
# for API keys. Never prints a full secret (only the last 4 characters).
set -u
. "$(dirname "$0")/_common.sh"
cd "$REPO_ROOT" || exit 1

scan() {
  # args: files...; prints findings, returns number of findings via exit code (capped)
  python3 - "$@" <<'PY'
import re, subprocess, sys
patterns = [
    ("sk-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("google-key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("generic-api-key", re.compile(r"api[_-]?key\s*[:=]\s*\S{16,}", re.I)),
]
ALLOW = "secret-guard: allow"
def ignored(path):
    r = subprocess.run(["git", "check-ignore", "-q", path], capture_output=True)
    return r.returncode == 0
def mask(v):
    return "*" * max(len(v) - 4, 4) + v[-4:]
count = 0
for path in sys.argv[1:]:
    try:
        if ignored(path):
            continue
        with open(path, "rb") as fh:
            raw = fh.read()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        continue
    if b"\0" in raw[:8192]:
        continue
    text = raw.decode("utf-8", "replace")
    for no, line in enumerate(text.splitlines(), 1):
        if path.endswith(".env.example"):
            m = re.match(r"\s*#?\s*[A-Z_]+=\s*(.*)$", line)
            if m and (m.group(1).strip() == "" or re.fullmatch(r"<[^>]*>", m.group(1).strip())):
                continue
        for name, rx in patterns:
            if name == "generic-api-key" and ALLOW in line:
                continue
            for m in rx.finditer(line):
                count += 1
                print(f"{path}:{no}: {name}: {mask(m.group(0))}")
sys.exit(min(count, 100))
PY
}

if [ "${1:-}" = "--all" ]; then
  files=()
  while IFS= read -r f; do files+=("$f"); done < <(git ls-files)
  [ ${#files[@]} -eq 0 ] && { echo "secret_guard: scanned 0 files"; exit 0; }
  out="$(scan "${files[@]}")"; n=$?
  if [ $n -eq 0 ]; then echo "secret_guard: scanned ${#files[@]} files, no secrets found"; exit 0; fi
  echo "$out"; echo "secret_guard: $n finding(s)"; exit 1
fi

FILE="$(resolve_saved_path "${1:-}")" || { echo "secret_guard: no file path received"; exit 2; }
mkdir -p logs/hooks
LOG="logs/hooks/secret-guard.log"
out="$(scan "$FILE")"; n=$?
printf '%s\n' "$out" > "$LOG"
if [ $n -eq 0 ]; then exit 0; fi
echo "$out" >&2
echo "secret_guard: $n finding(s) in $FILE (log: $LOG)" >&2
exit 1
