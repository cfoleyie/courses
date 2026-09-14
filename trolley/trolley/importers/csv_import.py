"""CSV import: the fallback that always works.

Column names are matched loosely because the file might be exported from a
spreadsheet someone keeps by hand, a bank statement tidied up, or written out
by the email importer's `--dry-run`.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from ..model import ParsedLine, ParsedOrder
from .base import ImportError_

DATE_COLUMNS = ("date", "bought_on", "bought", "ordered", "order_date", "delivery_date", "day")
NAME_COLUMNS = ("item", "name", "product", "description", "raw_name", "line")
QTY_COLUMNS = ("qty", "quantity", "count", "units", "number")
REF_COLUMNS = ("order", "order_ref", "ref", "order_number", "reference")

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y/%m/%d",
    "%m/%d/%Y",
)


def parse_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text[:19]).date()
    except ValueError:
        return None


def _pick(fieldnames: list[str], options: tuple[str, ...]) -> str | None:
    lowered = {name.strip().casefold(): name for name in fieldnames if name}
    for option in options:
        if option in lowered:
            return lowered[option]
    for key, original in lowered.items():
        if any(option in key for option in options):
            return original
    return None


class CsvImporter:
    name = "csv"

    def handles(self, path: Path) -> bool:
        return path.suffix.casefold() in {".csv", ".tsv"}

    def read(self, path: Path) -> list[ParsedOrder]:
        delimiter = "\t" if path.suffix.casefold() == ".tsv" else ","
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                raise ImportError_(f"{path.name}: no header row")
            date_col = _pick(reader.fieldnames, DATE_COLUMNS)
            name_col = _pick(reader.fieldnames, NAME_COLUMNS)
            if not date_col or not name_col:
                raise ImportError_(
                    f"{path.name}: need a date column and an item column; "
                    f"found {', '.join(reader.fieldnames)}"
                )
            qty_col = _pick(reader.fieldnames, QTY_COLUMNS)
            ref_col = _pick(reader.fieldnames, REF_COLUMNS)

            grouped: dict[tuple[date, str | None], list[ParsedLine]] = {}
            for row in reader:
                bought_on = parse_date(row.get(date_col, ""))
                raw_name = (row.get(name_col) or "").strip()
                if not bought_on or not raw_name:
                    continue
                try:
                    quantity = float((row.get(qty_col) or "1").strip() or 1) if qty_col else 1.0
                except ValueError:
                    quantity = 1.0
                ref = (row.get(ref_col) or "").strip() if ref_col else ""
                key = (bought_on, ref or None)
                grouped.setdefault(key, []).append(
                    ParsedLine(raw_name=raw_name, quantity=max(quantity, 0.1))
                )

        if not grouped:
            raise ImportError_(f"{path.name}: no rows with both a date and an item")
        return [
            ParsedOrder(
                bought_on=day,
                lines=tuple(lines),
                order_ref=ref or f"csv:{day.isoformat()}",
                source="csv",
            )
            for (day, ref), lines in sorted(grouped.items())
        ]
