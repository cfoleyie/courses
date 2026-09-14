"""Reading a Tesco order confirmation.

Tesco has no public API, so the history that already exists lives in years of
confirmation emails. Their markup changes over time and differs between the
HTML and plain-text parts, so nothing here depends on a particular class name
or table position. Instead it looks for the shape every receipt has: a line
carrying a product description, usually a quantity, and a price.

That is a heuristic, and heuristics deserve to be checked. `trolley import
--dry-run` prints exactly what was pulled out of a file and what each line was
matched to, which is the intended way to try this against a real email before
letting it write anything.
"""

from __future__ import annotations

import email
import email.policy
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from ..model import ParsedLine, ParsedOrder, Stage
from .base import ImportError_

#: Lines that look like products but are really receipt furniture.
STOP_WORDS = (
    "subtotal",
    "sub total",
    "total",
    "delivery charge",
    "delivery saver",
    "service charge",
    "bag charge",
    "carrier bag",
    "voucher",
    "clubcard",
    "you saved",
    "savings",
    "vat",
    "payment",
    "card ending",
    "amount due",
    "order summary",
    "guide price",
    "substitut",
    "unavailable",
    "out of stock",
    "refund",
    "balance",
    "tesco.com",
    "unsubscribe",
    "privacy policy",
    "terms and conditions",
    "contact us",
    "view your order",
    "manage your",
)

_PRICE = re.compile(r"^[£€$]?\s*\d{1,4}[.,]\d{2}$")
_INT = re.compile(r"^(?:x\s*)?(\d{1,3})(?:\s*x)?$", re.IGNORECASE)
_WEIGHT = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:kg|g)$", re.IGNORECASE)
_HAS_LETTERS = re.compile(r"[A-Za-z]{3}")

#: "3 Tesco Semi Skimmed Milk ... £3.45" and "Tesco Bananas x2 £1.10".
_LINE_LEADING_QTY = re.compile(
    r"^(?P<qty>\d{1,3})\s*[x×]?\s+(?P<name>[A-Za-z][^£€$]{2,90}?)\s+[£€$]\s*\d{1,4}[.,]\d{2}\s*$"
)
_LINE_TRAILING_QTY = re.compile(
    r"^(?P<name>[A-Za-z][^£€$]{2,90}?)\s+[x×]\s*(?P<qty>\d{1,3})\s+[£€$]\s*\d{1,4}[.,]\d{2}\s*$"
)
_LINE_PRICE_ONLY = re.compile(
    r"^(?P<name>[A-Za-z][^£€$]{2,90}?)\s+[£€$]\s*\d{1,4}[.,]\d{2}\s*$"
)

#: Which email in an order's life this is. The subject line is the reliable
#: signal, so it is matched leniently; the body only gets a strict second look,
#: because a confirmation's footer happily talks about receipts and deliveries.
_STAGE_SUBJECT: tuple[tuple[Stage, str], ...] = (
    (Stage.DELIVERED, r"receipt|delivered|thanks for shopping"),
    (Stage.AMENDED, r"amend|chang|updated"),
    (Stage.BOOKED, r"confirm|thanks for your order|booked|we'?ve got your order"),
)
_STAGE_BODY: tuple[tuple[Stage, str], ...] = (
    (Stage.DELIVERED, r"(has been|was) delivered|here'?s your receipt|thanks for shopping with us"),
    (Stage.AMENDED, r"(you'?ve|you have) changed your order|your order has changed|amended order"),
)

_ORDER_REF = re.compile(
    r"order\s*(?:number|no\.?|reference|ref|id)?\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9-]{4,24})",
    re.IGNORECASE,
)

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_DATE_WORDS = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})\s+(\d{{4}})\b", re.IGNORECASE)
_DATE_SLASH = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DELIVERY_HINT = re.compile(r"deliver|delivery|arriv|collect", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    """Flatten HTML while keeping table structure as tabs and newlines."""

    SKIP = {"script", "style", "head", "title"}
    CELL = {"td", "th"}
    BREAK = {"tr", "p", "div", "br", "li", "table", "h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skipping += 1
        elif tag in self.CELL:
            self.parts.append("\t")
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skipping = max(0, self._skipping - 1)
        elif tag in self.BREAK or tag in self.CELL:
            self.parts.append("\n" if tag in self.BREAK else "\t")

    def handle_data(self, data: str) -> None:
        if not self._skipping and data.strip():
            self.parts.append(re.sub(r"[ \xa0]+", " ", data.strip()))

    def text(self) -> str:
        joined = "".join(self.parts)
        joined = re.sub(r"[ \t]*\n[ \t\n]*", "\n", joined)
        joined = re.sub(r"\t+", "\t", joined)
        return joined.strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def _month_number(name: str) -> int:
    name = name.casefold()[:3]
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(
        name
    ) + 1


def _dates_in(text: str) -> list[date]:
    found: list[date] = []
    for day, month, year in _DATE_WORDS.findall(text):
        try:
            found.append(date(int(year), _month_number(month), int(day)))
        except (ValueError, IndexError):
            continue
    for day, month, year in _DATE_SLASH.findall(text):
        try:
            found.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    for year, month, day in _DATE_ISO.findall(text):
        try:
            found.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return found


def find_order_date(text: str, fallback: date | None = None) -> date | None:
    """Prefer a date on a line that mentions delivery; otherwise take the first."""
    for line in text.splitlines():
        if _DELIVERY_HINT.search(line):
            dates = _dates_in(line)
            if dates:
                return dates[0]
    dates = _dates_in(text)
    return dates[0] if dates else fallback


def find_order_ref(text: str) -> str | None:
    """The first order number that is actually a number.

    "Your Tesco order confirmation" matches the same shape as "Order number:
    483920174", so candidates without enough digits are passed over rather than
    taken as the reference.
    """
    for match in _ORDER_REF.finditer(text):
        candidate = match.group(1)
        if sum(char.isdigit() for char in candidate) >= 5:
            return candidate
    return None


def find_stage(text: str) -> Stage:
    """Which of an order's emails this is, so a later one can replace an earlier.

    Getting this wrong in one direction is worse than the other: labelling a
    confirmation as a receipt would block the real receipt from replacing it.
    So the subject line decides where it can, and the body is only consulted
    for phrases a confirmation would not use about itself.
    """
    subject, _, body = text.partition("\n")
    subject = subject.casefold()
    for stage, pattern in _STAGE_SUBJECT:
        if re.search(pattern, subject):
            return stage

    head = body[:1500].casefold()
    for stage, pattern in _STAGE_BODY:
        if re.search(pattern, head):
            return stage
    return Stage.BOOKED


def _looks_like_product(name: str) -> bool:
    lowered = name.casefold()
    if not _HAS_LETTERS.search(name) or len(name) < 3 or len(name) > 120:
        return False
    return not any(word in lowered for word in STOP_WORDS)


def _line_from_cells(cells: list[str]) -> ParsedLine | None:
    """Interpret one table row: find the price, the count and the description."""
    if not any(_PRICE.match(cell) for cell in cells):
        return None
    quantity = 1.0
    name = ""
    for cell in cells:
        if _PRICE.match(cell):
            continue
        int_match = _INT.match(cell)
        if int_match:
            quantity = float(int_match.group(1))
            continue
        weight_match = _WEIGHT.match(cell)
        if weight_match:
            continue
        if len(cell) > len(name):
            name = cell
    # A quantity written into the description ("Tesco Milk x 2") wins, because
    # the separate count column is sometimes the number of substitutions.
    inline = re.search(r"\s[x×]\s*(\d{1,3})\s*$", name)
    if inline:
        quantity = float(inline.group(1))
        name = name[: inline.start()].strip()
    if not _looks_like_product(name):
        return None
    return ParsedLine(raw_name=name, quantity=max(quantity, 1.0))


def parse_receipt_text(text: str, fallback_date: date | None = None) -> ParsedOrder:
    """Pull the date, reference and product lines out of a flattened receipt."""
    bought_on = find_order_date(text, fallback_date)
    if bought_on is None:
        raise ImportError_("could not find an order or delivery date in the message")

    lines: list[ParsedLine] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parsed: ParsedLine | None = None
        if "\t" in raw:
            parsed = _line_from_cells([cell.strip() for cell in raw.split("\t") if cell.strip()])
        if parsed is None:
            for pattern in (_LINE_LEADING_QTY, _LINE_TRAILING_QTY, _LINE_PRICE_ONLY):
                match = pattern.match(raw)
                if not match:
                    continue
                name = match.group("name").strip(" -–—·.")
                if not _looks_like_product(name):
                    break
                quantity = float(match.groupdict().get("qty") or 1)
                parsed = ParsedLine(raw_name=name, quantity=max(quantity, 1.0))
                break
        if parsed is None:
            continue
        marker = parsed.raw_name.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        lines.append(parsed)

    if not lines:
        raise ImportError_(
            "found a date but no product lines; run with --dry-run --show-text to see "
            "what was read, and add an [aliases] entry or use a CSV if the layout is unusual"
        )
    return ParsedOrder(
        bought_on=bought_on,
        lines=tuple(lines),
        order_ref=find_order_ref(text) or f"email:{bought_on.isoformat()}",
        source="email",
        stage=find_stage(text),
    )


def message_to_text(raw: bytes) -> tuple[str, date | None]:
    """Flatten an .eml into text, with the Date header as a fallback date."""
    message = email.message_from_bytes(raw, policy=email.policy.default)
    sent: date | None = None
    try:
        header = message.get("Date")
        if header:
            parsed = email.utils.parsedate_to_datetime(header)
            sent = parsed.date() if isinstance(parsed, datetime) else None
    except (TypeError, ValueError):
        sent = None

    html_parts: list[str] = []
    text_parts: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() != "text":
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):
            continue
        if part.get_content_subtype() == "html":
            html_parts.append(content)
        else:
            text_parts.append(content)

    subject = str(message.get("Subject") or "")
    if html_parts:
        return f"{subject}\n" + "\n".join(html_to_text(part) for part in html_parts), sent
    return f"{subject}\n" + "\n".join(text_parts), sent


class EmailImporter:
    name = "email"

    def handles(self, path: Path) -> bool:
        return path.suffix.casefold() in {".eml", ".html", ".htm", ".txt", ".msg"}

    def read(self, path: Path) -> list[ParsedOrder]:
        raw = path.read_bytes()
        suffix = path.suffix.casefold()
        if suffix in {".eml", ".msg"}:
            text, sent = message_to_text(raw)
        else:
            decoded = raw.decode("utf-8", errors="replace")
            text = html_to_text(decoded) if suffix in {".html", ".htm"} else decoded
            sent = None
        return [parse_receipt_text(text, sent)]

    def flatten(self, path: Path) -> str:
        """The text the parser actually sees, for `--show-text`."""
        raw = path.read_bytes()
        suffix = path.suffix.casefold()
        if suffix in {".eml", ".msg"}:
            return message_to_text(raw)[0]
        decoded = raw.decode("utf-8", errors="replace")
        return html_to_text(decoded) if suffix in {".html", ".htm"} else decoded
