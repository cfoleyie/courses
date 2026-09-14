"""Built-in knowledge about supermarket staples.

Two things live here. First, the words that have to come off a product name
before two brands of the same thing look alike. Second, a starting guess at how
often a household buys each staple, so an item with one purchase behind it can
still be suggested instead of waiting months for a pattern to appear.

None of it is authoritative: `config.toml` overrides the intervals and the
alias table, and real purchase history overrules the priors as soon as there is
enough of it.
"""

from __future__ import annotations

#: Brand and range words that carry no meaning for "what is this".
BRANDS = (
    "tesco",
    "finest",
    "tesco finest",
    "stockwell",
    "stockwell & co",
    "creamfields",
    "hearty food co",
    "ms molly",
    "growers harvest",
    "eastmans",
    "redmere farms",
    "rosedene farms",
    "willow farms",
    "woodside farms",
    "boswell farms",
    "nightingale farms",
    "suntrail farms",
    "everyday value",
    "organic",
    "free from",
    "plant chef",
    "wicked kitchen",
    "own brand",
    "clubcard price",
)

#: Packaging and marketing words that vary between near-identical products.
NOISE = (
    "pack",
    "packs",
    "multipack",
    "value pack",
    "family pack",
    "large",
    "small",
    "medium",
    "mini",
    "jumbo",
    "giant",
    "extra",
    "new",
    "fresh",
    "frozen",
    "chilled",
    "bag",
    "bags",
    "bottle",
    "bottles",
    "carton",
    "cartons",
    "box",
    "tin",
    "tins",
    "can",
    "cans",
    "jar",
    "punnet",
    "loose",
    "each",
    "approx",
    "min",
    "class i",
    "per kg",
)

#: Canonical staples: key -> (display name, category, typical days between
#: purchases for a two-adult household, alias fragments).
#:
#: A raw product name matches a staple when it contains one of the alias
#: fragments. Fragments are matched on word boundaries after cleaning, longest
#: first, so "toilet roll" wins over "roll".
STAPLES: dict[str, tuple[str, str, float, tuple[str, ...]]] = {
    "milk": ("Milk", "dairy", 4, ("milk", "semi skimmed milk", "whole milk")),
    "bread": ("Bread", "bakery", 4, ("bread", "loaf", "sliced white", "sliced wholemeal", "sourdough")),
    "eggs": ("Eggs", "dairy", 9, ("eggs", "egg")),
    "butter": ("Butter", "dairy", 16, ("butter", "spreadable", "flora", "kerrygold")),
    "cheese": ("Cheese", "dairy", 12, ("cheddar", "cheese slices", "grated cheese", "mozzarella")),
    "yoghurt": ("Yoghurt", "dairy", 8, ("yoghurt", "yogurt", "greek style")),
    "toilet-roll": ("Toilet roll", "household", 17, ("toilet roll", "toilet tissue", "andrex", "cushelle", "velvet toilet")),
    "kitchen-roll": ("Kitchen roll", "household", 24, ("kitchen roll", "kitchen towel", "plenty")),
    "bin-bags": ("Bin bags", "household", 40, ("bin bag", "bin liner", "refuse sack", "swing bin")),
    "washing-up-liquid": ("Washing-up liquid", "household", 45, ("washing up liquid", "fairy liquid", "dish soap")),
    "dishwasher-tablets": ("Dishwasher tablets", "household", 40, ("dishwasher tablet", "finish", "dishwasher pod")),
    "laundry-detergent": ("Laundry detergent", "household", 45, ("laundry", "washing capsule", "washing powder", "non bio", "persil", "ariel", "surf")),
    "fabric-softener": ("Fabric softener", "household", 55, ("fabric conditioner", "fabric softener", "comfort", "lenor")),
    "cling-film": ("Cling film / foil", "household", 90, ("cling film", "kitchen foil", "tin foil", "baking paper", "food bags")),
    "surface-spray": ("Surface spray", "household", 60, ("surface cleaner", "antibacterial spray", "dettol", "cif", "flash spray")),
    "bleach": ("Bleach", "household", 70, ("bleach", "toilet cleaner", "domestos", "harpic")),
    "shampoo": ("Shampoo", "toiletries", 55, ("shampoo", "conditioner")),
    "shower-gel": ("Shower gel", "toiletries", 45, ("shower gel", "body wash", "soap bar", "hand wash")),
    "toothpaste": ("Toothpaste", "toiletries", 55, ("toothpaste", "colgate", "sensodyne")),
    "deodorant": ("Deodorant", "toiletries", 50, ("deodorant", "anti perspirant", "roll on")),
    "razors": ("Razors", "toiletries", 75, ("razor", "razor blade", "shaving gel")),
    "tea": ("Tea", "cupboard", 40, ("tea bag", "teabag", "barry's tea", "lyons tea", "pg tips")),
    "coffee": ("Coffee", "cupboard", 28, ("coffee", "nescafe", "coffee pods", "ground coffee")),
    "sugar": ("Sugar", "cupboard", 70, ("sugar",)),
    "pasta": ("Pasta", "cupboard", 24, ("pasta", "spaghetti", "penne", "fusilli", "tagliatelle")),
    "rice": ("Rice", "cupboard", 32, ("rice", "basmati", "long grain")),
    "cereal": ("Cereal", "cupboard", 18, ("cereal", "cornflakes", "weetabix", "porridge", "granola", "muesli")),
    "olive-oil": ("Oil", "cupboard", 70, ("olive oil", "vegetable oil", "sunflower oil", "rapeseed oil")),
    "tinned-tomatoes": ("Tinned tomatoes", "cupboard", 20, ("chopped tomato", "tinned tomato", "passata")),
    "beans": ("Baked beans", "cupboard", 22, ("baked bean", "heinz bean")),
    "stock": ("Stock cubes", "cupboard", 70, ("stock cube", "stock pot", "oxo")),
    "ketchup": ("Ketchup / sauces", "cupboard", 60, ("ketchup", "mayonnaise", "brown sauce", "bbq sauce")),
    "bananas": ("Bananas", "produce", 5, ("banana",)),
    "apples": ("Apples", "produce", 7, ("apple",)),
    "potatoes": ("Potatoes", "produce", 12, ("potato", "rooster", "maris piper")),
    "onions": ("Onions", "produce", 14, ("onion",)),
    "carrots": ("Carrots", "produce", 10, ("carrot",)),
    "salad": ("Salad", "produce", 5, ("lettuce", "salad bag", "rocket", "spinach")),
    "tomatoes": ("Tomatoes", "produce", 6, ("tomatoes", "cherry tomato", "vine tomato")),
    "chicken": ("Chicken", "meat", 7, ("chicken breast", "chicken fillet", "whole chicken", "chicken thigh")),
    "mince": ("Mince", "meat", 11, ("mince", "minced beef", "beef mince")),
    "bacon": ("Bacon", "meat", 10, ("bacon", "rashers")),
    "sausages": ("Sausages", "meat", 12, ("sausage",)),
    "ham": ("Ham", "meat", 8, ("ham slices", "cooked ham", "wafer thin")),
    "salmon": ("Salmon", "meat", 12, ("salmon", "salmon fillet")),
    "steak": ("Steak", "meat", 11, ("steak", "striploin", "ribeye", "rib eye", "sirloin")),
    "beer": ("Beer", "drinks", 10, ("beer", "lager", "ale", "cider", "stout",
                                     "heineken", "guinness", "corona", "budweiser", "peroni")),
    "wine": ("Wine", "drinks", 12, ("wine", "prosecco", "sauvignon", "merlot", "malbec",
                                     "rioja", "pinot", "chardonnay", "shiraz")),
    "nappies": ("Nappies", "baby", 12, ("nappies", "nappy", "pampers", "huggies")),
    "wipes": ("Wipes", "baby", 14, ("baby wipes", "wipes")),
    "cat-food": ("Cat food", "pets", 14, ("cat food", "whiskas", "felix", "sheba")),
    "dog-food": ("Dog food", "pets", 16, ("dog food", "pedigree", "bakers")),
    "dishcloths": ("Cloths / sponges", "household", 60, ("dishcloth", "sponge scourer", "j cloth")),
}


def alias_index() -> list[tuple[str, str]]:
    """Alias fragments paired with their staple key, longest fragment first.

    Longest-first ordering is what stops "roll" in "kitchen roll" from being
    claimed by "toilet roll", and it is why callers should take the first hit.
    """
    pairs = [(fragment, key) for key, (_, _, _, aliases) in STAPLES.items() for fragment in aliases]
    pairs.sort(key=lambda pair: (-len(pair[0]), pair[0]))
    return pairs


def prior_interval(key: str) -> float | None:
    """Typical days between purchases for a known staple, if it is one."""
    entry = STAPLES.get(key)
    return entry[2] if entry else None


def display(key: str) -> tuple[str, str] | None:
    """Display name and category for a known staple."""
    entry = STAPLES.get(key)
    return (entry[0], entry[1]) if entry else None
