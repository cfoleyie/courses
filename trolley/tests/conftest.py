from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trolley.config import Config, NotifyConfig, ServerConfig, SuggestConfig
from trolley.db import Database
from trolley.model import Item, Purchase
from trolley.slots import SlotSpec

DUBLIN = ZoneInfo("Europe/Dublin")

#: A Monday, so the fixtures read the way the calendar does.
TODAY = date(2026, 9, 14)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        server=ServerConfig(database=str(tmp_path / "test.db"), timezone="Europe/Dublin"),
        suggest=SuggestConfig(),
        notify=NotifyConfig(enabled=False, channel="console"),
        slots=(
            SlotSpec(day="monday", at="08:00", label="Monday delivery"),
            SlotSpec(day="friday", at="08:00", label="Friday delivery"),
        ),
    )


@pytest.fixture
def db(config: Config) -> Database:
    return Database(config.server.database)


@pytest.fixture
def item() -> Item:
    return Item(id=1, key="toilet-roll", name="Toilet roll", category="household")


def purchases_every(days: int, count: int, *, last: date = TODAY, quantity: float = 1.0,
                    item_id: int = 1) -> list[Purchase]:
    """A tidy history: `count` purchases, `days` apart, ending on `last`."""
    return [
        Purchase(
            id=None,
            item_id=item_id,
            bought_on=last - timedelta(days=days * offset),
            quantity=quantity,
        )
        for offset in reversed(range(count))
    ]


@pytest.fixture
def sunday_evening() -> datetime:
    """The moment the Monday order is usually put together."""
    return datetime(2026, 9, 13, 19, 0, tzinfo=DUBLIN)
