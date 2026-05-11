import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
ROOT_DIR = Path(__file__).parent.parent


def transform_publishers() -> list[dict]:
    raw = json.loads((DATA_DIR / "publishers.json").read_text())
    publishers = []

    for p in raw:
        min_age, max_age = map(int, p["audience"]["age_skew"].split("-"))

        publishers.append({
            "id": p["id"],
            "name": p["name"],
            "category": p["category"],
            "subcategories": p["subcategories"],
            "min_age": min_age,
            "max_age": max_age,
            "income_tier": p["audience"]["income_tier"],
            "top_geos": p["audience"]["top_geos"],
            "aov_usd": p["avg_order_value_usd"],
            "monthly_impressions": p["monthly_impressions"],
            "gender_female_pct": p["audience"]["gender_split"]["female"],
            "gender_male_pct": p["audience"]["gender_split"]["male"],
            "notes": p["notes"],
            # concatenated for tsvector — not stored as a column
            "search_text": " ".join([
                p["category"],
                " ".join(p["subcategories"]),
                p["notes"],
            ]),
        })

    return publishers


def derive_facets(publishers: list[dict]) -> dict:
    all_geos = set()
    all_subcategories = set()

    for p in publishers:
        all_geos.update(p["top_geos"])
        all_subcategories.update(p["subcategories"])

    facets = {
        "categories": sorted({p["category"] for p in publishers}),
        "income_tiers": ["low", "mid", "mid-high", "high"],  # ordered low→high
        "geos": sorted(all_geos),
        "subcategories": sorted(all_subcategories),
    }

    (ROOT_DIR / "facets.json").write_text(json.dumps(facets, indent=2))
    print(f"facets.json written — {len(facets['categories'])} categories, "
          f"{len(facets['geos'])} geos, {len(facets['subcategories'])} subcategories")

    return facets


if __name__ == "__main__":
    publishers = transform_publishers()
    derive_facets(publishers)
    print(f"Transformed {len(publishers)} publishers")
