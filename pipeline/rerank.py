"""
Phase 4 — LLM Rerank + Reasoning

Takes top-30 candidate publishers from Phase 3 and produces:
  - recommended: ranked publishers with fit scores and reasoning
  - excluded: remaining publishers with explicit exclusion reasons
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from dotenv import load_dotenv

if TYPE_CHECKING:
    from pipeline.understand import BriefUnderstanding

load_dotenv()

ROOT = Path(__file__).parent.parent
PROMPTS_DIR = ROOT / "prompts"

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


@dataclass
class RankedPublisher:
    publisher_id: str
    name: str
    category: str
    fit_score: int          # 1–10
    fit_reasoning: str
    record: dict            # full publisher record from DB


@dataclass
class ExcludedPublisher:
    publisher_id: str
    name: str
    exclusion_reason: str


@dataclass
class RankedPersona:
    id: str
    name: str
    reasoning: str


@dataclass
class RerankedResult:
    recommended: list[RankedPublisher]
    excluded: list[ExcludedPublisher]
    ranked_personas: list[RankedPersona] = field(default_factory=list)


def _format_publisher(pub: dict) -> str:
    return (
        f"{pub['id']} | {pub['name']} | {pub['category']} | "
        f"{', '.join(pub['subcategories'])} | "
        f"age {pub['min_age']}–{pub['max_age']} | "
        f"income: {pub['income_tier']} | "
        f"AOV: ${pub['aov_usd']} | "
        f"gender: {int(pub['gender_female_pct'] * 100)}% female | "
        f"geos: {', '.join(pub['top_geos'])} | "
        f"notes: {pub['notes']} | "
        f"RRF score: {pub['rrf_score']:.4f}"
    )


def _build_tool_schema(candidate_ids: list[str]) -> dict:
    return {
        "name": "rank_publishers",
        "description": (
            "Rank candidate publishers by fit for the advertiser brief. "
            "Use this tool to output all fields — do not respond in plain text."
        ),
        "input_schema": {
            "type": "object",
            "required": ["ranked_personas", "recommended", "excluded"],
            "properties": {
                "ranked_personas": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 5,
                    "description": (
                        "REQUIRED. Shopper personas most likely to respond to this advertiser, "
                        "ranked best-fit first. Must contain 2–5 entries. Mandatory on every "
                        "response and independent of publisher ranking quality."
                    ),
                    "items": {
                        "type": "object",
                        "required": ["id", "name", "reasoning"],
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "reasoning": {
                                "type": "string",
                                "description": "One sentence: why this persona fits this advertiser.",
                            },
                        },
                    },
                },
                "recommended": {
                    "type": "array",
                    "description": "Publishers recommended for this advertiser, ordered best-fit first.",
                    "items": {
                        "type": "object",
                        "required": ["publisher_id", "fit_score", "fit_reasoning"],
                        "properties": {
                            "publisher_id": {
                                "type": "string",
                                "enum": candidate_ids,
                            },
                            "fit_score": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 10,
                                "description": "Overall fit quality 1–10.",
                            },
                            "fit_reasoning": {
                                "type": "string",
                                "description": (
                                    "2–3 sentences explaining why this publisher fits: "
                                    "reference the audience, AOV, notes, and persona overlap specifically."
                                ),
                            },
                        },
                    },
                },
                "excluded": {
                    "type": "array",
                    "description": "Publishers not recommended, with honest exclusion reasons.",
                    "items": {
                        "type": "object",
                        "required": ["publisher_id", "exclusion_reason"],
                        "properties": {
                            "publisher_id": {
                                "type": "string",
                                "enum": candidate_ids,
                            },
                            "exclusion_reason": {
                                "type": "string",
                                "description": (
                                    "One sentence: specific mismatch — category, audience, "
                                    "AOV, or messaging environment."
                                ),
                            },
                        },
                    },
                },
            },
        },
    }


def rerank(
    brief: str,
    candidates: list[dict],
    persona_records: dict,
    understanding: "BriefUnderstanding | None" = None,
) -> RerankedResult:
    system_prompt = (PROMPTS_DIR / "03_rerank_system.txt").read_text()

    publisher_lines = "\n".join(
        f"  {i+1}. {_format_publisher(pub)}"
        for i, pub in enumerate(candidates)
    )

    understanding_json = (
        json.dumps(
            {
                "hard_facets": understanding.hard_facets,
                "soft_facets": understanding.soft_facets,
                "age_range": understanding.age_range,
                "facet_confidence": understanding.facet_confidence,
            },
            indent=2,
        )
        if understanding is not None
        else "null"
    )

    user_prompt = (
        f"Advertiser brief: {brief}\n\n"
        f"Structured understanding of the brief (hard facets, soft facets, confidence scores):\n{understanding_json}\n\n"
        f"Shopper personas (full catalog):\n{json.dumps(list(persona_records.values()), indent=2)}\n\n"
        f"Candidate publishers ({len(candidates)} total):\n{publisher_lines}"
    )

    candidate_ids = [pub["id"] for pub in candidates]
    record_map = {pub["id"]: pub for pub in candidates}

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[_build_tool_schema(candidate_ids)],
        tool_choice={"type": "tool", "name": "rank_publishers"},
    )

    block = response.content[0]
    if block.type != "tool_use":
        raise ValueError(f"Expected tool_use block, got: {block.type}")
    tool_input: dict = block.input  # type: ignore[union-attr]

    recommended = [
        RankedPublisher(
            publisher_id=r["publisher_id"],
            name=record_map[r["publisher_id"]]["name"],
            category=record_map[r["publisher_id"]]["category"],
            fit_score=r["fit_score"],
            fit_reasoning=r["fit_reasoning"],
            record=record_map[r["publisher_id"]],
        )
        for r in tool_input.get("recommended", [])
    ]

    excluded = [
        ExcludedPublisher(
            publisher_id=e["publisher_id"],
            name=record_map[e["publisher_id"]]["name"],
            exclusion_reason=e["exclusion_reason"],
        )
        for e in tool_input.get("excluded", [])
    ]

    ranked_personas = [
        RankedPersona(
            id=p["id"],
            name=persona_records.get(p["id"], {}).get("name", p["id"]),
            reasoning=p["reasoning"],
        )
        for p in tool_input.get("ranked_personas", [])
    ]

    return RerankedResult(
        recommended=recommended,
        excluded=excluded,
        ranked_personas=ranked_personas,
    )
