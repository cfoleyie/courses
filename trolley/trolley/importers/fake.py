"""A deterministic history generator, for trying the app before importing."""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from ..model import ParsedLine, ParsedOrder

#: Product name, how often it is bought (days), and how many go in the basket.
PATTERN = (
    ("Tesco British Semi Skimmed Milk 2.272L", 4, 1),
    ("Tesco White Sliced Bread 800G", 4, 1),
    ("Tesco Free Range Large Eggs 12 Pack", 10, 1),
    ("Tesco Toilet Tissue 9 Roll", 17, 1),
    ("Tesco Kitchen Towel 2 Roll", 24, 1),
    ("Tesco Bananas Loose", 5, 1),
    ("Tesco Irish Chicken Breast Fillets 600G", 7, 1),
    ("Tesco Salted Butter 250G", 16, 1),
    ("Finish All In 1 Dishwasher Tablets 60 Pack", 40, 1),
    ("Tesco Bin Liners 40 Pack", 40, 1),
    ("Barry's Tea 80 Tea Bags", 38, 1),
    ("Tesco Chopped Tomatoes 400G", 20, 4),
)


class FakeImporter:
    """Not an importer of files: it invents a plausible year of shopping."""

    name = "fake"

    def handles(self, path: Path) -> bool:
        return False

    def read(self, path: Path) -> list[ParsedOrder]:  # pragma: no cover - unused
        return self.generate()

    def generate(self, weeks: int = 52, today: date | None = None, seed: int = 7) -> list[ParsedOrder]:
        rng = random.Random(seed)
        today = today or date.today()
        # Walk backwards over Monday and Friday deliveries for the last year.
        days: list[date] = []
        cursor = today
        while len(days) < weeks * 2:
            if cursor.weekday() in (0, 4):
                days.append(cursor)
            cursor -= timedelta(days=1)
        days.reverse()

        due: dict[str, date] = {name: days[0] for name, _, _ in PATTERN}
        orders: list[ParsedOrder] = []
        for index, day in enumerate(days):
            lines: list[ParsedLine] = []
            for name, every, quantity in PATTERN:
                if due[name] <= day:
                    jitter = rng.choice((-1, 0, 0, 0, 1))
                    lines.append(ParsedLine(raw_name=name, quantity=float(quantity)))
                    due[name] = day + timedelta(days=max(every * quantity + jitter, 1))
            if lines:
                orders.append(
                    ParsedOrder(
                        bought_on=day,
                        lines=tuple(lines),
                        order_ref=f"fake-{index:04d}",
                        source="fake",
                    )
                )
        return orders
