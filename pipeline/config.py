"""
Phase 5a — Campaign Config

Sonnet call for bid strategy, budget allocation, flight duration, and brand safety.
Runs in parallel with creative generation after reranking completes.
"""

import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
PROMPTS_DIR = ROOT / "prompts"
sys.path.insert(0, str(ROOT))

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _normalize_allocations(allocations_raw: list[dict]) -> dict[str, float]:
    """Floor each publisher's budget_pct at 5, then renormalize to sum to 100."""
    floored = {a["publisher_id"]: max(a.get("budget_pct", 5), 5) for a in allocations_raw}
    total = sum(floored.values()) or 1.0
    return {pid: round(w / total * 100, 1) for pid, w in floored.items()}


def _build_targeting(understanding) -> dict:
    return {
        "categories": understanding.hard_facets.get("categories", []),
        "income_tiers": understanding.hard_facets.get("income_tiers", []),
        "age_range": understanding.age_range,
        "geos": understanding.hard_facets.get("geos") or ["nationwide"],
        "gender_skew": understanding.soft_facets.get("gender_skew"),
    }


def _build_tool_schema(publisher_ids: list[str]) -> dict:
    return {
        "name": "build_campaign_config",
        "description": (
            "Build campaign configuration for this advertiser. "
            "Use this tool to output all fields — do not respond in plain text."
        ),
        "input_schema": {
            "type": "object",
            "required": [
                "bid_strategy", "bid_strategy_reasoning",
                "publisher_allocations", "flight_duration_days", "brand_safety_flags",
            ],
            "properties": {
                "bid_strategy": {
                    "type": "string",
                    "enum": ["CPM", "CPC", "CPA"],
                    "description": "Recommended bid strategy for this campaign.",
                },
                "bid_strategy_reasoning": {
                    "type": "string",
                    "description": "One sentence explaining the bid strategy choice.",
                },
                "publisher_allocations": {
                    "type": "array",
                    "description": "Budget allocation across recommended publishers.",
                    "items": {
                        "type": "object",
                        "required": ["publisher_id", "budget_pct", "allocation_reasoning"],
                        "properties": {
                            "publisher_id": {
                                "type": "string",
                                "enum": publisher_ids,
                            },
                            "budget_pct": {
                                "type": "number",
                                "description": (
                                    "Raw budget weight for this publisher. "
                                    "Will be floored at 5 and renormalized to sum to 100 — "
                                    "do not try to make values sum to 100 yourself."
                                ),
                            },
                            "allocation_reasoning": {
                                "type": "string",
                                "description": (
                                    "One sentence explaining why this publisher received "
                                    "its relative budget share — reference fit score, AOV "
                                    "alignment, reach, or income tier as appropriate for "
                                    "the chosen bid strategy."
                                ),
                            },
                        },
                    },
                },
                "flight_duration_days": {
                    "type": "integer",
                    "description": "Suggested campaign flight duration in days.",
                },
                "brand_safety_flags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Content categories this advertiser should avoid appearing next to.",
                },
            },
        },
    }


def build_campaign_config(
    brief: str,
    understanding,
    reranked,
) -> dict:
    system_prompt = (PROMPTS_DIR / "04_campaign_config_system.txt").read_text()

    publisher_lines = "\n".join(
        f"  {pub.publisher_id} | {pub.name} | fit_score: {pub.fit_score} | "
        f"AOV: ${pub.record['aov_usd']} | "
        f"impressions: {pub.record['monthly_impressions']:,} | "
        f"income: {pub.record['income_tier']} | "
        f"notes: {pub.record['notes']}"
        for pub in reranked.recommended
    )

    understanding_json = json.dumps(
        {
            "hard_facets": understanding.hard_facets,
            "soft_facets": understanding.soft_facets,
            "age_range": understanding.age_range,
            "facet_confidence": understanding.facet_confidence,
        },
        indent=2,
    )

    user_prompt = (
        f"Advertiser brief: {brief}\n\n"
        f"Structured understanding of the brief:\n{understanding_json}\n\n"
        f"Recommended publishers (fit_score | AOV | impressions | income | notes):\n{publisher_lines}"
    )

    publisher_ids = [pub.publisher_id for pub in reranked.recommended]

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[_build_tool_schema(publisher_ids)],
        tool_choice={"type": "tool", "name": "build_campaign_config"},
    )

    block = response.content[0]
    if block.type != "tool_use":
        raise ValueError(f"Expected tool_use block, got: {block.type}")
    tool_input: dict = block.input  # type: ignore[union-attr]

    normalized_budgets = _normalize_allocations(tool_input["publisher_allocations"])
    allocation_map = {
        a["publisher_id"]: a.get("allocation_reasoning", "")
        for a in tool_input["publisher_allocations"]
    }

    return {
        "targeting": _build_targeting(understanding),
        "publisher_allocations": [
            {
                "publisher_id": pub.publisher_id,
                "publisher_name": pub.name,
                "budget_pct": normalized_budgets.get(pub.publisher_id, 0.0),
                "monthly_impressions": pub.record["monthly_impressions"],
                "fit_score": pub.fit_score,
                "allocation_reasoning": allocation_map.get(pub.publisher_id, ""),
            }
            for pub in reranked.recommended
        ],
        "bid_strategy": tool_input["bid_strategy"],
        "bid_strategy_reasoning": tool_input["bid_strategy_reasoning"],
        "flight_duration_days": tool_input["flight_duration_days"],
        "brand_safety_flags": tool_input["brand_safety_flags"],
    }
