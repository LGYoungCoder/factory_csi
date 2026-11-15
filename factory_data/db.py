"""SQLite engine helpers with foreign keys always enabled."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def _enable_fk(dbapi_conn, _record) -> None:  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def make_engine(path: str | Path, *, read_only: bool = False) -> Engine:
    """Engine for a factory.db file. Foreign key enforcement is on for every connection."""
    p = Path(path).resolve()
    if read_only:
        url = f"sqlite:///file:{p}?mode=ro&uri=true"
    else:
        url = f"sqlite:///{p}"
    engine = create_engine(url, future=True)
    event.listen(engine, "connect", _enable_fk)
    return engine
