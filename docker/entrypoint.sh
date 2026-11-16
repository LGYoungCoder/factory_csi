#!/bin/sh
# Generate any missing dataset (all three artifacts), then start the API.
set -e
for pair in baseline:ds-00 a:ds-01 b:ds-02 c:ds-03; do
  key=${pair%%:*}; ds=${pair##*:}
  if [ ! -f "$DATA_DIR/$ds/factory.db" ]; then
    echo "generating $ds"
    python -m simulator generate --scenario "$key" --out "$DATA_DIR"
  fi
done
exec uvicorn backend.api.app:app --host "${HOST:-0.0.0.0}" --port "${PORT:-18474}"
