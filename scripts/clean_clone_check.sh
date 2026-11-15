#!/usr/bin/env bash
# Clone the committed repository into a temp dir and verify it sets up and passes the fast checks.
# Usage: bash scripts/clean_clone_check.sh   (UV_DEFAULT_INDEX / npm registry env vars are honoured)
set -eu
SRC="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --quiet "$SRC" "$TMP/repo"
cd "$TMP/repo"
make setup
make seed
make test-fast
echo "clean clone OK: $(git rev-parse --short HEAD)"
