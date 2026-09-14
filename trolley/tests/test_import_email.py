"""Reading a confirmation email without depending on Tesco's markup."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from trolley.importers import EmailImporter
from trolley.importers.base import ImportError_
from trolley.importers.email_import import (
    find_order_date,
    find_order_ref,
    html_to_text,
    parse_receipt_text,
)

HTML_RECEIPT = """
<html><body>
<h1>Your Tesco order confirmation</h1>
<p>Order number: 483920174</p>
<p>Your delivery is booked for Monday 14 September 2026 between 8am and 9am.</p>
<table>
<tr><th>Qty</th><th>Product</th><th>Price</th></tr>
<tr><td>2</td><td>Tesco British Semi Skimmed Milk 2.272L/4 Pints</td><td>&pound;2.50</td></tr>
<tr><td>1</td><td>Tesco Toilet Tissue 9 Roll</td><td>&pound;4.00</td></tr>
<tr><td>4</td><td>Tesco Chopped Tomatoes 400G</td><td>&pound;2.00</td></tr>
<tr><td>1</td><td>Delivery charge</td><td>&pound;0.00</td></tr>
<tr><td></td><td>Clubcard savings</td><td>&pound;3.20</td></tr>
<tr><td></td><td>Total</td><td>&pound;61.45</td></tr>
</table>
</body></html>
"""

TEXT_RECEIPT = """Tesco order confirmation
Order Number: 771234567
Delivery date: 18/09/2026

1 Tesco White Sliced Bread 800G  £1.20
3 Tesco Free Range Large Eggs 12 Pack  £8.85
Tesco Salted Butter 250G x 2  £4.40
Delivery charge  £4.50
Total to pay  £24.94
"""


def test_a_table_receipt_yields_products_with_quantities() -> None:
    order = parse_receipt_text(html_to_text(HTML_RECEIPT))
    assert order.bought_on == date(2026, 9, 14)
    assert order.order_ref == "483920174"
    assert [(line.raw_name, line.quantity) for line in order.lines] == [
        ("Tesco British Semi Skimmed Milk 2.272L/4 Pints", 2.0),
        ("Tesco Toilet Tissue 9 Roll", 1.0),
        ("Tesco Chopped Tomatoes 400G", 4.0),
    ]


def test_charges_and_totals_are_not_mistaken_for_products() -> None:
    order = parse_receipt_text(html_to_text(HTML_RECEIPT))
    names = " ".join(line.raw_name.casefold() for line in order.lines)
    for word in ("delivery charge", "clubcard", "total"):
        assert word not in names


def test_a_plain_text_receipt_works_too() -> None:
    order = parse_receipt_text(TEXT_RECEIPT)
    assert order.bought_on == date(2026, 9, 18)
    assert order.order_ref == "771234567"
    assert [(line.raw_name, line.quantity) for line in order.lines] == [
        ("Tesco White Sliced Bread 800G", 1.0),
        ("Tesco Free Range Large Eggs 12 Pack", 3.0),
        ("Tesco Salted Butter 250G", 2.0),  # quantity written into the description
    ]


def test_the_delivery_date_beats_other_dates_on_the_page() -> None:
    text = "Ordered on 1 September 2026\nDelivery date: 14 September 2026\n"
    assert find_order_date(text) == date(2026, 9, 14)


def test_the_words_before_the_number_are_not_the_order_number() -> None:
    """"Your Tesco order confirmation" has the same shape as "Order no: 1234"."""
    assert find_order_ref("Your Tesco order confirmation\nOrder number: 483920174") == "483920174"
    assert find_order_ref("Your Tesco order confirmation") is None


def test_a_receipt_with_no_date_is_rejected_clearly() -> None:
    with pytest.raises(ImportError_, match="date"):
        parse_receipt_text("1 Tesco Milk £1.20\n")


def test_a_page_with_a_date_but_no_products_says_so() -> None:
    with pytest.raises(ImportError_, match="product lines"):
        parse_receipt_text("Delivery date: 14 September 2026\nThanks for shopping with us.\n")


def test_an_eml_file_is_read_through_its_html_part(tmp_path: Path) -> None:
    eml = tmp_path / "order.eml"
    eml.write_bytes(
        (
            "From: Tesco <noreply@example.test>\r\n"
            "To: shopper@example.test\r\n"
            "Subject: Your order\r\n"
            "Date: Sun, 13 Sep 2026 18:00:00 +0100\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: text/html; charset=utf-8\r\n\r\n"
            + HTML_RECEIPT
        ).encode()
    )
    order = EmailImporter().read(eml)[0]
    assert order.bought_on == date(2026, 9, 14)
    assert len(order.lines) == 3


def test_the_importer_only_claims_files_it_can_read(tmp_path: Path) -> None:
    importer = EmailImporter()
    assert importer.handles(tmp_path / "a.eml")
    assert importer.handles(tmp_path / "a.html")
    assert not importer.handles(tmp_path / "a.csv")
