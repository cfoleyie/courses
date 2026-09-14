"""Turning a shelf label into the thing you actually ran out of.

A receipt says "Tesco Toilet Tissue 9 Roll" one week and "Andrex Classic Clean
12 Rolls" the next. Treated literally those are two products bought once each,
which predicts nothing. Collapsing them onto one canonical item is what makes
the whole idea work, so this module is deliberately conservative: when it is
not confident, it leaves a product under its own name rather than merging it
into a staple and poisoning that staple's history.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .catalogue import BRANDS, NOISE, alias_index, display

#: Sizes, weights and counts: "500g", "2.272l", "4 x 415g", "9 roll", "12pk".
_SIZE = re.compile(
    r"""
    \b\d+(?:[.,]\d+)?\s*
    (?:kg|g|mg|ml|cl|l|litre|litres|ltr|pint|pints|oz|lb
      |pk|pack|packs|roll|rolls|sheet|sheets|tablet|tablets|capsule|capsules
      |wash|washes|bag|bags|tea\s?bags|ct|count|pieces?|slices?|cans?|tins?)\b
    """,
    re.VERBOSE,
)
_MULTIPLIER = re.compile(r"\b\d+\s*[x×]\s*\d*(?:[.,]\d+)?\s*[a-z]*\b")
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_LEADING_COUNT = re.compile(r"^\s*\d+\s*[x×]?\s+")
_PUNCT = re.compile(r"[^a-z0-9&'\s]+")
_SPACES = re.compile(r"\s+")

#: If any of these appear, the product is a treat or a variant rather than the
#: staple whose name it happens to contain. "Milk chocolate" is not milk.
VETO_PHRASES = (
    "chocolate",
    "biscuit",
    "cookie",
    "cake",
    "crisps",
    "dessert",
    "ice cream",
    "sweets",
    "candy",
    "pudding",
    "milkshake",
    "smoothie",
    "flavour",
    "flavoured",
    "scented candle",
    "air freshener",
)

#: Words that change what a staple is when they sit immediately in front of it.
#: "Peanut butter" is not butter; "garlic bread" is not bread.
PRECEDING_BLOCK = {
    "butter": ("peanut", "nut", "cocoa", "shea", "almond", "cashew"),
    "bread": ("garlic", "naan", "pitta", "pita", "flat", "ginger"),
    "milk": ("coconut", "almond", "soya", "soy", "oat", "condensed", "evaporated", "powdered"),
    "cheese": ("cream", "mac", "macaroni"),
    "rice": ("pudding", "paper"),
    "egg": ("easter", "scotch", "chocolate"),
    "eggs": ("easter", "scotch", "chocolate"),
    "apple": ("toffee", "juice"),
    "tea": ("iced", "ice"),
}

#: Below this, a single-word generic alias like "milk" is assumed to be an
#: incidental mention in a longer product name rather than the product itself,
#: unless it sits in the head-noun position. See `_alias_allowed`.
MIN_COVERAGE = 0.25

#: How many trailing words still count as "the thing itself". Product names put
#: the head noun near the end: "Tesco Free Range Large Eggs" is eggs, while
#: "Cadbury Dairy Milk Chocolate Bar" is not milk.
HEAD_WINDOW = 2

#: Packaging words that trail a name without changing what it is, so they are
#: ignored when deciding whether an alias sits in the head-noun position.
TRAILING_NOISE = frozenset(
    """loose each approx fresh chilled frozen large small medium mini jumbo giant
       extra new pack packs multipack bag bags box bottle bottles carton cartons
       jar punnet""".split()
)

#: How close two cleaned names must be to be treated as the same item.
FUZZY_THRESHOLD = 0.87


def _fragment_pattern(fragment: str) -> str:
    """Match an alias allowing the plural forms English actually uses."""
    return rf"\b{re.escape(fragment)}(?:e?s)?\b"


def clean(raw: str) -> str:
    """Strip a product name down to the words that say what it is."""
    text = unicodedata.normalize("NFKD", raw or "").casefold()
    text = text.replace("&amp;", "&").replace("/", " ")
    text = _BRACKETS.sub(" ", text)
    text = _LEADING_COUNT.sub(" ", text)
    text = _MULTIPLIER.sub(" ", text)
    text = _SIZE.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()

    for brand in sorted(BRANDS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(brand)}\b", " ", text)
    text = _SPACES.sub(" ", text).strip()
    # Sizes can hide behind a brand word ("tesco 6 pinta"); sweep once more.
    text = _SIZE.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def _vetoed(text: str) -> bool:
    return any(phrase in text for phrase in VETO_PHRASES)


def _alias_allowed(text: str, fragment: str) -> bool:
    """Whether a single-word alias is really this product or just a word in it.

    Accepted when the word sits at the end of the name, where product names put
    the thing being sold, or when it makes up a decent share of a short name.
    """
    if " " in fragment:
        return True
    tokens = text.split()
    while tokens and tokens[-1] in TRAILING_NOISE:
        tokens.pop()
    head = tokens[-HEAD_WINDOW:]
    if any(re.fullmatch(_fragment_pattern(fragment), token) for token in head):
        return True
    return len(fragment) / max(len(text), 1) >= MIN_COVERAGE


def _blocked_by_context(text: str, fragment: str, start: int) -> bool:
    """True when the word in front of the match changes the product."""
    head = fragment.split()[0]
    blockers = PRECEDING_BLOCK.get(head)
    if not blockers:
        return False
    before = text[:start].strip().split()
    return bool(before) and before[-1] in blockers


def slugify(text: str) -> str:
    """A stable key for a product that is not a known staple."""
    cleaned = clean(text)
    for word in NOISE:
        cleaned = re.sub(rf"\b{re.escape(word)}\b", " ", cleaned)
    cleaned = _SPACES.sub(" ", cleaned).strip()
    cleaned = cleaned or clean(text) or "item"
    return re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")[:60] or "item"


def match_staple(raw: str, extra_aliases: dict[str, str] | None = None) -> str | None:
    """Map a product name onto a catalogue staple key, or None if unsure.

    `extra_aliases` comes from the user's config and wins over the built-ins,
    which is the escape hatch for anything this gets wrong.
    """
    text = clean(raw)
    if not text:
        return None

    for fragment, key in sorted((extra_aliases or {}).items(), key=lambda kv: -len(kv[0])):
        if re.search(_fragment_pattern(clean(fragment)), text):
            return key

    if _vetoed(text):
        return None

    for fragment, key in alias_index():
        found = re.search(_fragment_pattern(fragment), text)
        if not found:
            continue
        if _blocked_by_context(text, fragment, found.start()):
            continue
        if not _alias_allowed(text, fragment):
            continue  # An incidental word inside a much longer name.
        return key
    return None


def resolve(
    raw: str,
    known_keys: tuple[str, ...] = (),
    extra_aliases: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Decide which item a receipt line belongs to.

    Returns the item key, a display name and how the decision was reached
    ("staple", "fuzzy" or "new"), so importers can show their working.
    """
    staple = match_staple(raw, extra_aliases)
    if staple:
        shown = display(staple)
        return staple, (shown[0] if shown else staple.replace("-", " ").title()), "staple"

    key = slugify(raw)
    best, best_score = None, 0.0
    for candidate in known_keys:
        score = SequenceMatcher(None, key, candidate).ratio()
        if score > best_score:
            best, best_score = candidate, score
    if best and best_score >= FUZZY_THRESHOLD:
        return best, best.replace("-", " ").capitalize(), "fuzzy"

    return key, key.replace("-", " ").capitalize(), "new"


def category_of(key: str) -> str:
    shown = display(key)
    return shown[1] if shown else "other"
