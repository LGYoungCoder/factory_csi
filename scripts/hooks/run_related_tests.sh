#!/usr/bin/env bash
# PostFileSave hook: ruff + related deterministic tests for a saved .py file.
# Usage: run_related_tests.sh [path] | run_related_tests.sh --print-targets <path>
set -u
. "$(dirname "$0")/_common.sh"
cd "$REPO_ROOT" || exit 1

map_targets() {
  case "$1" in
    simulator/*|factory_data/*) echo "tests/unit/simulator/" ;;
    industrial_mcp/*) echo "tests/integration/mcp/" ;;
    backend/*) echo "tests/unit/backend/" ;;
    evaluation/*) echo "tests/eval/" ;;
    tests/*) echo "$1" ;;
    *) echo "" ;;
  esac
}

if [ "${1:-}" = "--print-targets" ]; then
  map_targets "${2:-}"; exit 0
fi

FILE="$(resolve_saved_path "${1:-}")" || { echo "run_related_tests: no file path received"; exit 2; }
mkdir -p logs/hooks
LOG="logs/hooks/python-tests-on-save.log"
TARGET="$(map_targets "$FILE")"
rc=0
{
  echo "== ruff check $FILE"
  uv run --quiet ruff check "$FILE" || rc=1
  if [ -n "$TARGET" ] && [ -e "$TARGET" ]; then
    echo "== pytest -m 'not llm' $TARGET"
    uv run --quiet pytest -m "not llm" -q "$TARGET"
    prc=$?
    # exit code 5 = no tests collected yet; not a failure
    if [ $prc -ne 0 ] && [ $prc -ne 5 ]; then rc=1; fi
  else
    echo "no related tests found for $FILE"
  fi
} > "$LOG" 2>&1
if [ $rc -eq 0 ]; then
  echo "python-tests-on-save: $FILE passed (log: $LOG)"
else
  tail -n 30 "$LOG" >&2
  echo "python-tests-on-save: $FILE FAILED (log: $LOG)" >&2
fi
exit $rc
