"""Brand-switching is the thing that breaks naive versions of this app, so the
cases below are mostly about two names meaning one item, and about the near
misses that must *not* be merged."""

from __future__ import annotations

import pytest

from trolley.normalise import clean, match_staple, resolve, slugify


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Tesco Toilet Tissue 9 Roll", "toilet tissue"),
        ("Tesco British Semi Skimmed Milk 2.272L/4 Pints", "british semi skimmed milk"),
        ("Heinz Baked Beans In Tomato Sauce 4X415G", "heinz baked beans in tomato sauce"),
        ("Tesco Finest Cheddar 350G", "cheddar"),
        ("Tesco Bananas Loose", "bananas loose"),
    ],
)
def test_clean_strips_brands_and_sizes(raw: str, expected: str) -> None:
    assert clean(raw) == expected


@pytest.mark.parametrize(
    "raw, key",
    [
        # Different brands, different pack sizes, one item.
        ("Tesco Toilet Tissue 9 Roll", "toilet-roll"),
        ("Andrex Classic Clean Toilet Tissue 12 Rolls", "toilet-roll"),
        ("Cushelle Quilted Toilet Roll 9 Rolls", "toilet-roll"),
        # Head-noun position rescues a generic word in a long name.
        ("Tesco Free Range Large Eggs 12 Pack", "eggs"),
        ("Tesco British Semi Skimmed Milk 2.272L", "milk"),
        # Plurals that are not just a trailing "s".
        ("Tesco Chopped Tomatoes 400G", "tinned-tomatoes"),
        ("Tesco Rooster Potatoes 2.5Kg", "potatoes"),
        ("Finish All In 1 Dishwasher Tablets 60 Pack", "dishwasher-tablets"),
    ],
)
def test_staples_are_recognised(raw: str, key: str) -> None:
    assert match_staple(raw) == key


@pytest.mark.parametrize(
    "raw",
    [
        "Cadbury Dairy Milk Chocolate Bar 110G",  # contains "milk", is not milk
        "Meridian Smooth Peanut Butter 280G",  # contains "butter", is not butter
        "Tesco Garlic Bread 2 Pack",  # contains "bread", is not bread
        "Ben & Jerry's Cookie Dough Ice Cream 465Ml",
        "Oatly Oat Drink Whole 1L",
    ],
)
def test_lookalikes_are_not_merged_into_staples(raw: str) -> None:
    assert match_staple(raw) is None


def test_config_aliases_win_over_the_catalogue() -> None:
    assert match_staple("Oatly Oat Drink Whole 1L") is None
    assert match_staple("Oatly Oat Drink Whole 1L", {"oat drink": "milk"}) == "milk"


def test_unknown_products_keep_their_own_identity() -> None:
    key, name, how = resolve("Tesco Chilli & Lime Tortilla Chips 150G")
    assert how == "new"
    assert key == "chilli-lime-tortilla-chips"
    assert name == "Chilli lime tortilla chips"


def test_near_identical_names_collapse_onto_a_known_item() -> None:
    key, _, how = resolve("Tesco Tortilla Chip 150G", known_keys=("tortilla-chips",))
    assert (key, how) == ("tortilla-chips", "fuzzy")


def test_slugify_is_stable_across_pack_sizes() -> None:
    assert slugify("Tesco Tortilla Chips 150G") == slugify("Tesco Tortilla Chips 300G")


def test_empty_names_do_not_explode() -> None:
    assert match_staple("") is None
    assert slugify("") == "item"
