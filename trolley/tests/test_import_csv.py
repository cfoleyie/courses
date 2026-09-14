"""CSV is the fallback for anyone whose email layout defeats the parser."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from trolley.importers import CsvImporter
from trolley.importers.base import ImportError_, detect
from trolley.importers.csv_import import parse_date


def write(tmp_path: Path, text: str, name: str = "history.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_plain_three_column_file_is_read(tmp_path: Path) -> None:
    path = write(tmp_path, "date,item,qty\n2026-09-14,Toilet roll,2\n2026-09-14,Milk,1\n")
    orders = CsvImporter().read(path)
    assert len(orders) == 1
    assert orders[0].bought_on == date(2026, 9, 14)
    assert {line.raw_name for line in orders[0].lines} == {"Toilet roll", "Milk"}


def test_column_names_do_not_have_to_be_exact(tmp_path: Path) -> None:
    path = write(tmp_path, "Delivery Date,Product Description,Quantity\n14/09/2026,Bread,1\n")
    order = CsvImporter().read(path)[0]
    assert order.bought_on == date(2026, 9, 14)
    assert order.lines[0].raw_name == "Bread"


def test_rows_are_grouped_into_one_order_per_day(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "date,item\n2026-09-14,Milk\n2026-09-18,Milk\n2026-09-18,Bread\n",
    )
    orders = CsvImporter().read(path)
    assert [len(order.lines) for order in orders] == [1, 2]


def test_an_order_column_keeps_separate_orders_apart(tmp_path: Path) -> None:
    path = write(tmp_path, "date,item,order\n2026-09-14,Milk,A1\n2026-09-14,Bread,A2\n")
    orders = CsvImporter().read(path)
    assert {order.order_ref for order in orders} == {"A1", "A2"}


def test_rows_without_a_date_or_a_name_are_skipped(tmp_path: Path) -> None:
    path = write(tmp_path, "date,item\n,Milk\n2026-09-14,\n2026-09-14,Bread\n")
    order = CsvImporter().read(path)[0]
    assert [line.raw_name for line in order.lines] == ["Bread"]


def test_a_missing_quantity_counts_as_one(tmp_path: Path) -> None:
    path = write(tmp_path, "date,item,qty\n2026-09-14,Milk,\n")
    assert CsvImporter().read(path)[0].lines[0].quantity == 1.0


def test_a_file_without_the_needed_columns_explains_itself(tmp_path: Path) -> None:
    path = write(tmp_path, "when,how much\n2026-09-14,3\n")
    with pytest.raises(ImportError_, match="date column and an item column"):
        CsvImporter().read(path)


def test_an_empty_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ImportError_):
        CsvImporter().read(write(tmp_path, "date,item\n"))


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-09-14", date(2026, 9, 14)),
        ("14/09/2026", date(2026, 9, 14)),
        ("14 September 2026", date(2026, 9, 14)),
        ("nonsense", None),
        ("", None),
    ],
)
def test_dates_are_read_in_the_formats_people_write(text: str, expected) -> None:
    assert parse_date(text) == expected


def test_an_unknown_extension_is_rejected_by_name(tmp_path: Path) -> None:
    with pytest.raises(ImportError_, match="no importer recognises"):
        detect(tmp_path / "orders.pdf", [CsvImporter()])
