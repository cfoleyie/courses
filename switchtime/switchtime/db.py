"""SQLite persistence for the ledger and sync bookkeeping.

A connection is opened per operation rather than shared: the poller runs on a
background task while requests are served concurrently, and short-lived
connections in WAL mode sidestep the cross-thread rules entirely.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .ledger import Event, Kind, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kid_id      TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    minutes     INTEGER NOT NULL,
    day         TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    ref         TEXT,
    note        TEXT    NOT NULL DEFAULT ''
);

-- Dedupe key. IXL is polled repeatedly and will keep reporting the same
-- finished skill, so the same ref must never be credited twice.
CREATE UNIQUE INDEX IF NOT EXISTS events_kid_ref
    ON events (kid_id, ref) WHERE ref IS NOT NULL;

CREATE INDEX IF NOT EXISTS events_kid_day ON events (kid_id, day);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    # ----- events -------------------------------------------------------

    def add_event(self, event: Event) -> Event | None:
        """Insert an event, or return None if its ref was already recorded."""
        with self.connect() as conn:
            try:
                cur = conn.execute(
                    """INSERT INTO events (kid_id, kind, minutes, day, created_at, status, ref, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.kid_id,
                        str(event.kind),
                        int(event.minutes),
                        event.day,
                        event.created_at.isoformat(),
                        str(event.status),
                        event.ref,
                        event.note,
                    ),
                )
            except sqlite3.IntegrityError:
                return None
        return _with_id(event, cur.lastrowid)

    def events_for(self, kid_id: str, *, limit: int | None = None) -> list[Event]:
        sql = "SELECT * FROM events WHERE kid_id = ? ORDER BY id DESC"
        params: list[Any] = [kid_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            return [_row_to_event(r) for r in conn.execute(sql, params)]

    def pending(self, kid_id: str | None = None) -> list[Event]:
        sql = "SELECT * FROM events WHERE status = ?"
        params: list[Any] = [str(Status.PENDING)]
        if kid_id:
            sql += " AND kid_id = ?"
            params.append(kid_id)
        sql += " ORDER BY id ASC"
        with self.connect() as conn:
            return [_row_to_event(r) for r in conn.execute(sql, params)]

    def set_status(self, event_id: int, status: Status) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE events SET status = ? WHERE id = ? AND status = ?",
                (str(status), event_id, str(Status.PENDING)),
            )
        return cur.rowcount > 0

    def has_ref(self, kid_id: str, ref: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM events WHERE kid_id = ? AND ref = ? LIMIT 1", (kid_id, ref)
            ).fetchone()
        return row is not None

    def known_refs(self, kid_id: str) -> set[str]:
        with self.connect() as conn:
            return {
                r["ref"]
                for r in conn.execute(
                    "SELECT ref FROM events WHERE kid_id = ? AND ref IS NOT NULL", (kid_id,)
                )
            }

    # ----- key/value state ----------------------------------------------

    def get_state(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_state(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        kid_id=row["kid_id"],
        kind=Kind(row["kind"]),
        minutes=row["minutes"],
        day=row["day"],
        created_at=datetime.fromisoformat(row["created_at"]),
        status=Status(row["status"]),
        ref=row["ref"],
        note=row["note"],
    )


def _with_id(event: Event, new_id: int | None) -> Event:
    return replace(event, id=new_id)


__all__ = ["Database"]
