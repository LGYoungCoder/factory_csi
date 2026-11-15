#!/usr/bin/env bash
# PostFileSave hook: typecheck the frontend and eslint the saved file.
set -u
. "$(dirname "$0")/_common.sh"
cd "$REPO_ROOT" || exit 1
FILE="$(resolve_saved_path "${1:-}")" || { echo "frontend_check: no file path received"; exit 2; }
mkdir -p logs/hooks
LOG="logs/hooks/frontend-typecheck-on-save.log"
REL="${FILE#frontend/}"
rc=0
{
  echo "== tsc"
  (cd frontend && npm run --silent typecheck) || rc=1
  echo "== eslint $REL"
  (cd frontend && npx --no-install eslint "$REL") || rc=1
} > "$LOG" 2>&1
if [ $rc -eq 0 ]; then
  echo "frontend-typecheck-on-save: $FILE passed (log: $LOG)"
else
  tail -n 30 "$LOG" >&2
  echo "frontend-typecheck-on-save: $FILE FAILED (log: $LOG)" >&2
fi
exit $rc
