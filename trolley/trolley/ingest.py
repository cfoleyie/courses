"""Turning parsed receipts into purchase history.

The interesting decision is which item each receipt line belongs to. A raw name
that has been resolved before is looked up in the alias table first, so a
correction made by hand survives every later import and the normaliser's
guesswork is never re-run on a line the user has already ruled on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import normalise
from .catalogue import display
from .config import Config
from .db import Database
from .model import ParsedOrder, Stage


@dataclass
class Match:
    """One receipt line and where it ended up."""

    raw_name: str
    quantity: float
    item_key: str
    item_name: str
    #: "alias" (seen before), "staple", "fuzzy" (close to a known item) or "new".
    how: str


@dataclass
class IngestResult:
    orders: int = 0
    lines: int = 0
    added: int = 0
    duplicates: int = 0
    skipped_orders: int = 0
    replaced_orders: int = 0
    dry_run: bool = False
    new_items: list[str] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)

    def summary(self) -> str:
        def plural(count: int, noun: str) -> str:
            return f"{count} {noun}{'' if count == 1 else 's'}"

        if self.dry_run:
            parts = [plural(self.orders, "order"), f"{plural(self.lines, 'line')} would be recorded"]
        else:
            parts = [plural(self.orders, "order"), f"{plural(self.added, 'purchase')} recorded"]
            if self.duplicates:
                parts.append(f"{self.duplicates} already known")
        if self.replaced_orders:
            parts.append(f"{plural(self.replaced_orders, 'order')} updated from a later email")
        if self.skipped_orders:
            parts.append(f"{plural(self.skipped_orders, 'order')} already imported")
        if self.new_items:
            parts.append(f"{plural(len(self.new_items), 'new item')}")
        return ", ".join(parts)


def ingest(
    db: Database,
    orders: list[ParsedOrder],
    config: Config | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> IngestResult:
    """Store parsed orders, resolving each line to an item.

    With `dry_run` nothing is written, but every line is still matched, so the
    caller can show what an import would do before it does it.
    """
    config = config or Config()
    result = IngestResult(dry_run=dry_run)
    known: set[str] = {item.key for item in db.items()}

    # Oldest first, and within a day the earliest stage first, so a receipt is
    # always applied after the confirmation it supersedes.
    for order in sorted(orders, key=lambda o: (o.bought_on, int(o.stage))):
        ref = order.order_ref
        if ref and not force:
            seen_stage = db.order_stage(ref)
            if seen_stage is not None:
                if int(order.stage) <= seen_stage:
                    result.skipped_orders += 1
                    continue
                # A later email for the same order: what actually turned up
                # beats what was ordered, so replace rather than add to it.
                if not dry_run:
                    db.clear_order_purchases(ref)
                result.replaced_orders += 1
        result.orders += 1

        for line in order.lines:
            result.lines += 1
            raw_key = normalise.clean(line.raw_name) or line.raw_name.casefold()

            known_id = db.alias(raw_key)
            item = db.item(known_id) if known_id is not None else None
            if item is not None:
                result.matches.append(
                    Match(line.raw_name, line.quantity, item.key, item.name, "alias")
                )
                if not dry_run:
                    if db.add_purchase(
                        item.id, order.bought_on, line.quantity, line.raw_name, ref, order.source
                    ):
                        result.added += 1
                    else:
                        result.duplicates += 1
                continue

            key, name, how = normalise.resolve(line.raw_name, tuple(known), config.aliases)
            shown = display(key)
            if shown:
                name, category = shown
            else:
                category = "other"

            result.matches.append(Match(line.raw_name, line.quantity, key, name, how))
            if key not in known:
                known.add(key)
                result.new_items.append(name)
            if dry_run:
                continue

            item = db.upsert_item(key, name, category)
            db.set_alias(raw_key, item.id, "auto")
            if db.add_purchase(
                item.id, order.bought_on, line.quantity, line.raw_name, ref, order.source
            ):
                result.added += 1
            else:
                result.duplicates += 1

        if not dry_run and ref:
            db.record_order(ref, order.bought_on, order.source, len(order.lines), int(order.stage))

    return result


def relink(db: Database, raw_name: str, item_key: str) -> str:
    """Point a product name at a different item, and move its purchases over.

    This is the fix for a mis-merge: say "Oatly Oat Drink" should not count as
    milk, and every past line of it moves to its own item along with the rule
    for future imports.
    """
    target = db.item_by_key(item_key)
    if target is None:
        shown = display(item_key)
        target = db.upsert_item(
            item_key,
            shown[0] if shown else item_key.replace("-", " ").capitalize(),
            shown[1] if shown else "other",
        )

    raw_key = normalise.clean(raw_name) or raw_name.casefold()
    with db.connect() as conn:
        sources = [
            row["item_id"]
            for row in conn.execute(
                "SELECT DISTINCT item_id FROM purchases WHERE lower(raw_name) = lower(?)",
                (raw_name,),
            ).fetchall()
            if row["item_id"] != target.id
        ]
        moved = conn.execute(
            "UPDATE purchases SET item_id = ? WHERE lower(raw_name) = lower(?) AND item_id != ?",
            (target.id, raw_name, target.id),
        ).rowcount

    db.set_alias(raw_key, target.id, "manual")
    # An item that existed only to hold this product name is now empty, and an
    # empty item would sit in the list for ever saying "no pattern yet".
    for source_id in sources:
        if not db.purchases(source_id):
            db.delete_item(source_id)

    return f"{raw_name!r} now counts as {target.name} ({moved} past purchase(s) moved)"
