"""Group try-on product names into jewelry categories."""

from __future__ import annotations

import re

CATALOG_CATEGORIES: tuple[str, ...] = ("Earrings", "Necklaces", "Bangles", "Bracelets", "Rings")

_CATEGORY_TYPE = {
    "Earrings": "earring",
    "Necklaces": "necklace",
    "Bangles": "bangle",
    "Bracelets": "bracelet",
    "Rings": "ring",
}


def jewelry_type_for(category: str) -> str:
    return _CATEGORY_TYPE.get(category, "earring")


def category_matches(category: str, name: str) -> bool:
    text = name.strip().lower()
    if not text:
        return False
    if category == "Earrings":
        return "earring" in text
    if category == "Necklaces":
        return "necklace" in text
    if category == "Bangles":
        return "bangle" in text
    if category == "Bracelets":
        return "bracelet" in text
    if category == "Rings":
        return re.search(r"\bring\b", text) is not None and "earring" not in text
    return False


def names_for_category(category: str, alts: list[str]) -> list[str]:
    names: list[str] = []
    for alt in alts:
        name = str(alt or "").strip()
        if not name or name in names or not category_matches(category, name):
            continue
        names.append(name)
    return names


def group_catalog(entries: list[dict]) -> list[dict]:
    """Keep category order and drop empty groups. Each entry is {category, items}."""
    by_name = {str(entry.get("category") or ""): list(entry.get("items") or []) for entry in entries}
    grouped = []
    for category in CATALOG_CATEGORIES:
        items = names_for_category(category, [str(item) for item in by_name.get(category, [])])
        if items:
            grouped.append({"category": category, "items": items})
    return grouped
