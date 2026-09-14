"""SQLite storage for items, purchases and the list being built.

Connections are opened per operation and closed again. The app serves requests
concurrently while a background task checks the calendar, and short-lived
connections in WAL mode avoid SQLite's cross-thread rules without a pool.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from .model import Item, Purchase

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    key               TEXT    NOT NULL UNIQUE,
    name              TEXT    NOT NULL,
    category          TEXT    NOT NULL DEFAULT 'other',
    unit              TEXT    NOT NULL DEFAULT 'pack',
    interval_override REAL,
    paused            INTEGER NOT NULL DEFAULT 0,
    snoozed_until     TEXT,
    nudge             REAL    NOT NULL DEFAULT 1.0,
    created_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    bought_on  TEXT    NOT NULL,
    quantity   REAL    NOT NULL DEFAULT 1.0,
    raw_name   TEXT    NOT NULL DEFAULT '',
    order_ref  TEXT,
    source     TEXT    NOT NULL DEFAULT 'manual'
);

-- Re-importing the same confirmation email must not double-count a line.
CREATE UNIQUE INDEX IF NOT EXISTS purchases_dedupe
    ON purchases (item_id, order_ref, raw_name) WHERE order_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS purchases_item ON purchases (item_id, bought_on);

-- Raw product names that have been resolved before, including by hand, so a
-- correction sticks for every future import.
CREATE TABLE IF NOT EXISTS aliases (
    raw_key  TEXT PRIMARY KEY,
    item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    source   TEXT NOT NULL DEFAULT 'auto'
);

CREATE TABLE IF NOT EXISTS orders (
    ref         TEXT PRIMARY KEY,
    bought_on   TEXT NOT NULL,
    source      TEXT NOT NULL,
    lines       INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL,
    -- Which of the order's emails this came from; see model.Stage.
    stage       INTEGER NOT NULL DEFAULT 1
);

-- What has been ticked onto the list for an upcoming delivery.
CREATE TABLE IF NOT EXISTS list_entries (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_day  TEXT    NOT NULL,
    item_id   INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    quantity  REAL    NOT NULL DEFAULT 1.0,
    note      TEXT    NOT NULL DEFAULT '',
    added_at  TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS list_unique ON list_entries (slot_day, item_id);

-- Every yes/no on a suggestion, which is how the engine learns it is wrong.
CREATE TABLE IF NOT EXISTS decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    slot_day   TEXT    NOT NULL,
    action     TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


#: (table, column, definition) for columns added after the first release.
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("orders", "stage", "INTEGER NOT NULL DEFAULT 1"),
)


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        key=row["key"],
        name=row["name"],
        category=row["category"],
        unit=row["unit"],
        interval_override=row["interval_override"],
        paused=bool(row["paused"]),
        snoozed_until=_as_date(row["snoozed_until"]),
        nudge=row["nudge"],
    )


def _purchase(row: sqlite3.Row) -> Purchase:
    return Purchase(
        id=row["id"],
        item_id=row["item_id"],
        bought_on=_as_date(row["bought_on"]),
        quantity=row["quantity"],
        raw_name=row["raw_name"],
        order_ref=row["order_ref"],
        source=row["source"],
    )


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns that later versions introduced.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
        exists, so a database made by an earlier version would otherwise be
        missing the new column and fail on the next write.
        """
        for table, column, definition in MIGRATIONS:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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

    # ----- items --------------------------------------------------------

    def upsert_item(self, key: str, name: str, category: str = "other", unit: str = "pack") -> Item:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO items (key, name, category, unit, created_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO NOTHING""",
                (key, name, category, unit, datetime.now().isoformat(timespec="seconds")),
            )
            row = conn.execute("SELECT * FROM items WHERE key = ?", (key,)).fetchone()
        return _item(row)

    def item(self, item_id: int) -> Item | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _item(row) if row else None

    def item_by_key(self, key: str) -> Item | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE key = ?", (key,)).fetchone()
        return _item(row) if row else None

    def items(self) -> list[Item]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM items ORDER BY name").fetchall()
        return [_item(row) for row in rows]

    def update_item(self, item_id: int, **fields: Any) -> Item | None:
        allowed = {"name", "category", "unit", "interval_override", "paused", "snoozed_until", "nudge"}
        changes = {key: value for key, value in fields.items() if key in allowed}
        if not changes:
            return self.item(item_id)
        if isinstance(changes.get("snoozed_until"), date):
            changes["snoozed_until"] = changes["snoozed_until"].isoformat()
        if "paused" in changes:
            changes["paused"] = int(bool(changes["paused"]))
        assignments = ", ".join(f"{key} = ?" for key in changes)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE items SET {assignments} WHERE id = ?", (*changes.values(), item_id)
            )
        return self.item(item_id)

    def delete_item(self, item_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))

    # ----- aliases ------------------------------------------------------

    def alias(self, raw_key: str) -> int | None:
        with self.connect() as conn:
            row = conn.execute("SELECT item_id FROM aliases WHERE raw_key = ?", (raw_key,)).fetchone()
        return row["item_id"] if row else None

    def set_alias(self, raw_key: str, item_id: int, source: str = "auto") -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO aliases (raw_key, item_id, source) VALUES (?, ?, ?)
                   ON CONFLICT(raw_key) DO UPDATE SET item_id = excluded.item_id,
                                                      source  = excluded.source""",
                (raw_key, item_id, source),
            )

    # ----- purchases ----------------------------------------------------

    def add_purchase(
        self,
        item_id: int,
        bought_on: date,
        quantity: float = 1.0,
        raw_name: str = "",
        order_ref: str | None = None,
        source: str = "manual",
    ) -> bool:
        """Record a purchase. Returns False when it was already known."""
        with self.connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO purchases
                   (item_id, bought_on, quantity, raw_name, order_ref, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (item_id, bought_on.isoformat(), quantity, raw_name, order_ref, source),
            )
            return cursor.rowcount > 0

    def purchases(self, item_id: int | None = None) -> list[Purchase]:
        query = "SELECT * FROM purchases"
        params: tuple[Any, ...] = ()
        if item_id is not None:
            query += " WHERE item_id = ?"
            params = (item_id,)
        query += " ORDER BY bought_on"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_purchase(row) for row in rows]

    def purchases_by_item(self) -> dict[int, list[Purchase]]:
        grouped: dict[int, list[Purchase]] = {}
        for purchase in self.purchases():
            grouped.setdefault(purchase.item_id, []).append(purchase)
        return grouped

    # ----- orders -------------------------------------------------------

    def order_seen(self, ref: str) -> bool:
        return self.order_stage(ref) is not None

    def order_stage(self, ref: str) -> int | None:
        """Which email this order was last imported from, or None if unseen."""
        with self.connect() as conn:
            row = conn.execute("SELECT stage FROM orders WHERE ref = ?", (ref,)).fetchone()
        return row["stage"] if row else None

    def record_order(
        self, ref: str, bought_on: date, source: str, lines: int, stage: int = 1
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO orders (ref, bought_on, source, lines, imported_at, stage)
                   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(ref) DO UPDATE SET
                       bought_on   = excluded.bought_on,
                       lines       = excluded.lines,
                       imported_at = excluded.imported_at,
                       stage       = excluded.stage""",
                (
                    ref,
                    bought_on.isoformat(),
                    source,
                    lines,
                    datetime.now().isoformat(timespec="seconds"),
                    int(stage),
                ),
            )

    def clear_order_purchases(self, ref: str) -> int:
        """Forget what an order contained, before importing a better version."""
        with self.connect() as conn:
            return conn.execute("DELETE FROM purchases WHERE order_ref = ?", (ref,)).rowcount

    def orders(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM orders ORDER BY bought_on DESC").fetchall()
        return [dict(row) for row in rows]

    # ----- the working list ---------------------------------------------

    def add_to_list(self, slot_day: date, item_id: int, quantity: float = 1.0, note: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO list_entries (slot_day, item_id, quantity, note, added_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(slot_day, item_id) DO UPDATE SET
                       quantity = excluded.quantity, note = excluded.note""",
                (
                    slot_day.isoformat(),
                    item_id,
                    quantity,
                    note,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def remove_from_list(self, slot_day: date, item_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM list_entries WHERE slot_day = ? AND item_id = ?",
                (slot_day.isoformat(), item_id),
            )

    def list_for(self, slot_day: date) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT l.item_id, l.quantity, l.note, i.name, i.category, i.unit
                   FROM list_entries l JOIN items i ON i.id = l.item_id
                   WHERE l.slot_day = ? ORDER BY i.category, i.name""",
                (slot_day.isoformat(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_list(self, slot_day: date) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM list_entries WHERE slot_day = ?", (slot_day.isoformat(),))

    # ----- decisions ----------------------------------------------------

    def record_decision(self, item_id: int, slot_day: date, action: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO decisions (item_id, slot_day, action, created_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    item_id,
                    slot_day.isoformat(),
                    action,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def decisions(self, item_id: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM decisions"
        params: tuple[Any, ...] = ()
        if item_id is not None:
            query += " WHERE item_id = ?"
            params = (item_id,)
        query += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # ----- misc ---------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO state (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )
