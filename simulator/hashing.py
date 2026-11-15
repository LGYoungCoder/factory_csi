"""Content_Hash of a dataset directory."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from factory_data.schema import TABLE_ORDER, primary_key

ARTIFACTS = ("factory.db", "world_state.json", "ground_truth.json")


class HashError(ValueError):
    pass


def db_rows_digest(db_path: Path, h: hashlib._Hash) -> None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for table in TABLE_ORDER:
            pk = primary_key(table.name)
            cur = conn.execute(f'SELECT * FROM "{table.name}" ORDER BY "{pk}"')  # noqa: S608
            cols = [c[0] for c in cur.description]
            h.update(table.name.encode())
            for row in cur:
                h.update(json.dumps(dict(zip(cols, row, strict=True)), sort_keys=True).encode())
    finally:
        conn.close()


def content_hash(directory: str | Path, artifacts: tuple[str, ...] = ARTIFACTS) -> str:
    d = Path(directory)
    if not d.is_dir():
        raise HashError(f"dataset directory not found: {d}")
    for name in artifacts:
        if not (d / name).is_file():
            raise HashError(f"missing artifact {name} in {d.name}")
    h = hashlib.sha256()
    db_rows_digest(d / "factory.db", h)
    for name in artifacts:
        if name != "factory.db":
            h.update((d / name).read_bytes())
    return h.hexdigest()
