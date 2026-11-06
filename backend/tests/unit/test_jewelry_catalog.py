from app.services.jewelry_catalog import group_catalog, names_for_category


def test_product_names_stay_with_their_category():
    assert names_for_category(
        "Earrings",
        ["Gold Diamond Bezel Stud Earring", "Ruby Necklace", "Gold Diamond Bezel Stud Earring"],
    ) == ["Gold Diamond Bezel Stud Earring"]
    assert names_for_category("Rings", ["Gold Earring", "Pearl Ring"]) == ["Pearl Ring"]
    assert names_for_category("Bangles", ["Temple Bangle"]) == ["Temple Bangle"]


def test_catalog_groups_keep_category_order_and_skip_empty_groups():
    grouped = group_catalog(
        [
            {"category": "Rings", "items": ["Pearl Ring"]},
            {"category": "Earrings", "items": ["Stud Earring"]},
            {"category": "Necklaces", "items": []},
            {"category": "Bangles", "items": ["Temple Bangle"]},
        ]
    )
    assert grouped == [
        {"category": "Earrings", "items": ["Stud Earring"]},
        {"category": "Bangles", "items": ["Temple Bangle"]},
        {"category": "Rings", "items": ["Pearl Ring"]},
    ]
