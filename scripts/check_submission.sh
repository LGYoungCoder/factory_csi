#!/usr/bin/env bash
# Pre-submission compliance checklist (Kiroween 2026). Exit non-zero on any FAIL.
set -u
cd "$(dirname "$0")/.." || exit 1
fails=0
check() { # name, command...
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then printf "PASS  %s\n" "$name"; else printf "FAIL  %s\n" "$name"; fails=$((fails + 1)); fi
}
has() { grep -q "$2" "$1"; }

check "LICENSE exists and is MIT" has LICENSE "MIT License"
check ".kiro/specs present (7 specs)" test "$(ls -d .kiro/specs/*/ 2>/dev/null | wc -l | tr -d ' ')" -ge 7
check ".kiro/steering present" test -n "$(ls .kiro/steering/*.md 2>/dev/null)"
check ".kiro/hooks present" test -n "$(ls .kiro/hooks/*.json 2>/dev/null)"
check ".kiro/ not git-ignored" bash -c '! git check-ignore -q .kiro/ && ! git check-ignore -q .kiro/specs/ && ! git check-ignore -q .kiro/settings/mcp.json'
check ".kiro/ tracked in git" test -n "$(git ls-files .kiro | head -1)"
check ".env not tracked" bash -c '! git ls-files --error-unmatch .env'
check "no secrets in tracked files" bash scripts/hooks/secret_guard.sh --all
for s in "## Quick start" "## How it works" "## Kiro" "## Safety and limitations" "## License"; do
  check "README section: $s" has README.md "$s"
done
check "KIRO_USAGE.md exists" test -s KIRO_USAGE.md
check "docs/demo-script.md exists" test -s docs/demo-script.md
check "docs/architecture.md exists" test -s docs/architecture.md
check "import contracts (lint-imports)" uv run --quiet lint-imports
check "deterministic tests (pytest -m 'not llm')" uv run --quiet pytest -m "not llm" -q
echo
if [ $fails -eq 0 ]; then echo "All checks passed."; else echo "$fails check(s) failed."; fi
exit $fails
