"""
Phase 2 — Brief Understanding

Parses a free-text advertiser brief into structured targeting signals:
  - hard_facets: categorical signals → SQL WHERE clauses
  - soft_facets: numeric/weak signals → scoring weights
  - age_range: target audience age
  - facet_confidence: per-dimension confidence scores
  - fts_keywords: keywords for full-text search
  - embedding_query: prose description embedded for ANN search
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
PROMPTS_DIR = ROOT / "prompts"

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


@dataclass
class BriefUnderstanding:
    hard_facets: dict
    soft_facets: dict
    age_range: dict
    facet_confidence: dict
    fts_keywords: str
    embedding_query: str          # matched against publisher fit descriptions
    persona_embedding_query: str  # matched against persona descriptions (future ANN use)


def _load_facets() -> dict:
    return json.loads((ROOT / "facets.json").read_text())



def _build_tool_schema(facets: dict) -> dict:
    return {
        "name": "structure_brief",
        "description": "Extract structured targeting signals from an advertiser brief.",
        "input_schema": {
            "type": "object",
            "required": [
                "hard_facets", "soft_facets", "age_range",
                "facet_confidence", "fts_keywords", "embedding_query", "persona_embedding_query",
            ],
            "properties": {
                "hard_facets": {
                    "type": "object",
                    "properties": {
                        "categories":   {"type": "array", "items": {"type": "string", "enum": facets["categories"]}},
                        "income_tiers": {"type": "array", "items": {"type": "string", "enum": facets["income_tiers"]}},
                        "geos":         {"type": "array", "items": {"type": "string", "enum": facets["geos"]}},
                    },
                },
                "soft_facets": {
                    "type": "object",
                    "properties": {
                        "aov_min_usd": {"type": ["number", "null"]},
                        "aov_max_usd": {"type": ["number", "null"]},
                        "gender_skew": {"type": ["string", "null"], "enum": ["female", "male", "balanced", None]},
                    },
                },
                "age_range": {
                    "type": "object",
                    "required": ["min", "max"],
                    "properties": {
                        "min": {"type": "integer"},
                        "max": {"type": "integer"},
                    },
                },
                "facet_confidence": {
                    "type": "object",
                    "description": "Confidence 0.0–1.0 per dimension. Dimensions scoring below 0.6 are treated as soft at query time and will not filter publishers out.",
                    "properties": {
                        "categories":   {"type": "number", "minimum": 0, "maximum": 1},
                        "income_tiers": {"type": "number", "minimum": 0, "maximum": 1},
                        "geos":         {"type": "number", "minimum": 0, "maximum": 1},
                        "age_range":    {"type": "number", "minimum": 0, "maximum": 1},
                        "gender_skew":  {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
                "fts_keywords": {"type": "string"},
                "embedding_query": {
                    "type": "string",
                    "description": "150–200 words of dense prose using publisher fit description vocabulary. No headers or bullets. Will be embedded and cosine-compared against publisher fit descriptions.",
                },
                "persona_embedding_query": {
                    "type": "string",
                    "description": "100–150 words of dense prose using persona description vocabulary. No headers or bullets. Will be embedded and compared against persona descriptions.",
                },
            },
        },
    }


def _build_system_prompt(facets: dict) -> str:
    template = (PROMPTS_DIR / "02_brief_understanding.txt").read_text()
    return template.format(
        categories=", ".join(facets["categories"]),
        income_tiers=", ".join(facets["income_tiers"]),
        geos=", ".join(facets["geos"]),
        subcategories=", ".join(facets["subcategories"]),
    )


def understand_brief(brief: str) -> BriefUnderstanding:
    facets = _load_facets()
    system_prompt = _build_system_prompt(facets)
    tool_schema = _build_tool_schema(facets)

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": brief}],
        tools=[tool_schema],
        tool_choice={"type": "tool", "name": "structure_brief"},
    )

    block = response.content[0]
    if block.type != "tool_use":
        raise ValueError(f"Expected tool_use block, got: {block.type}")
    tool_input: dict = block.input  # type: ignore[union-attr]

    return BriefUnderstanding(
        hard_facets=tool_input["hard_facets"],
        soft_facets=tool_input["soft_facets"],
        age_range=tool_input["age_range"],
        facet_confidence=tool_input["facet_confidence"],
        fts_keywords=tool_input["fts_keywords"],
        embedding_query=tool_input["embedding_query"],
        persona_embedding_query=tool_input["persona_embedding_query"],
    )


