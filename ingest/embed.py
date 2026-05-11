import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

haiku = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _build_fit_prompt(p: dict) -> str:
    template = (PROMPTS_DIR / "01_publisher_fit_description.txt").read_text()
    return template.format(
        category=p["category"],
        subcategories=", ".join(p["subcategories"]),
        min_age=p["min_age"],
        max_age=p["max_age"],
        income_tier=p["income_tier"],
        female_pct=p["gender_female_pct"],
        male_pct=p["gender_male_pct"],
        monthly_impressions=p["monthly_impressions"],
        aov_usd=p["aov_usd"],
        notes=p["notes"],
    )


def _generate_one(args: tuple) -> tuple:
    """Generate a fit description for a single publisher. Returns (index, name, description)."""
    i, p = args
    prompt = _build_fit_prompt(p)
    response = haiku.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=280,
        messages=[{"role": "user", "content": prompt}],
    )
    return i, p["name"], response.content[0].text.strip()


def generate_fit_descriptions(publishers: list[dict]) -> list[str]:
    """Call Haiku in parallel (one per publisher) to generate fit descriptions."""
    descriptions = [None] * len(publishers)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_generate_one, (i, p)): i for i, p in enumerate(publishers)}
        for future in as_completed(futures):
            i, name, desc = future.result()
            descriptions[i] = desc
            print(f"  [{i+1}/{len(publishers)}] {name}: {desc[:80]}...")
    return descriptions


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed all texts in a single batched OpenAI call."""
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    # response.data is ordered to match input
    return [item.embedding for item in response.data]


def enrich_publishers(publishers: list[dict]) -> list[dict]:
    """Attach fit_description and embedding to each publisher dict."""
    print("Generating fit descriptions with Haiku...")
    descriptions = generate_fit_descriptions(publishers)

    print("\nGenerating embeddings with OpenAI...")
    embeddings = generate_embeddings(descriptions)

    for p, desc, emb in zip(publishers, descriptions, embeddings):
        p["fit_description"] = desc
        p["embedding"] = emb

    print(f"Enriched {len(publishers)} publishers "
          f"(embedding dim: {len(embeddings[0])})")
    return publishers
