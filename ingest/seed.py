"""
Entry point for Phase 1 ingestion.

Usage:
    python ingest/seed.py

Requires:
    DATABASE_URL, ANTHROPIC_API_KEY, OPENAI_API_KEY in .env
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psycopg2.extras import execute_values

from db.connection import get_connection
from ingest.transform import transform_publishers, derive_facets
from ingest.embed import enrich_publishers


UPSERT_SQL = """
INSERT INTO publishers (
    id, name, category, subcategories,
    min_age, max_age, income_tier, top_geos,
    aov_usd, monthly_impressions,
    gender_female_pct, gender_male_pct,
    notes, search_tsv, fit_description, embedding
)
VALUES %s
ON CONFLICT (id) DO UPDATE SET
    name               = EXCLUDED.name,
    category           = EXCLUDED.category,
    subcategories      = EXCLUDED.subcategories,
    min_age            = EXCLUDED.min_age,
    max_age            = EXCLUDED.max_age,
    income_tier        = EXCLUDED.income_tier,
    top_geos           = EXCLUDED.top_geos,
    aov_usd            = EXCLUDED.aov_usd,
    monthly_impressions = EXCLUDED.monthly_impressions,
    gender_female_pct  = EXCLUDED.gender_female_pct,
    gender_male_pct    = EXCLUDED.gender_male_pct,
    notes              = EXCLUDED.notes,
    search_tsv         = EXCLUDED.search_tsv,
    fit_description    = EXCLUDED.fit_description,
    embedding          = EXCLUDED.embedding;
"""


def build_row(p: dict) -> tuple:
    return (
        p["id"],
        p["name"],
        p["category"],
        p["subcategories"],
        p["min_age"],
        p["max_age"],
        p["income_tier"],
        p["top_geos"],
        p["aov_usd"],
        p["monthly_impressions"],
        p["gender_female_pct"],
        p["gender_male_pct"],
        p["notes"],
        p["search_text"],       # passed as plain text; tsvector cast applied via template
        p["fit_description"],
        p["embedding"],
    )


def seed():
    print("=== Phase 1: Ingestion ===\n")

    print("Step 1/3 — Transforming publishers.json...")
    publishers = transform_publishers()
    derive_facets(publishers)
    print(f"  {len(publishers)} publishers transformed\n")

    print("Step 2/3 — Generating descriptions and embeddings...")
    publishers = enrich_publishers(publishers)
    print()

    print("Step 3/3 — Upserting into Postgres...")
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                rows = [build_row(p) for p in publishers]

                # Use a template to cast search_text → tsvector and embedding → vector
                execute_values(
                    cur,
                    UPSERT_SQL,
                    rows,
                    template=(
                        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                        " to_tsvector('english', %s), %s, %s::vector)"
                    ),
                )
                cur.execute("SELECT COUNT(*) FROM publishers;")
                count = cur.fetchone()[0]

        print(f"  {count} publishers in DB\n")
        print("=== Ingestion complete ===")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
