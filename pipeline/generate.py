"""
Phase 5b — Creative Generation

Single Sonnet call with all ranked personas (3–5). Generates one differentiated
creative variant per persona in a single pass so the model can ensure variety
across headlines, angles, and tones.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
PROMPTS_DIR = ROOT / "prompts"

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

_CREATIVE_TOOL = {
    "name": "generate_creatives",
    "description": (
        "Generate one ad creative variant per persona. "
        "Use this tool to output all fields — do not respond in plain text."
    ),
    "input_schema": {
        "type": "object",
        "required": ["variants"],
        "properties": {
            "variants": {
                "type": "array",
                "description": "One creative variant per persona, in the same order as the input personas.",
                "items": {
                    "type": "object",
                    "required": ["persona_id", "persona_reasoning", "headline", "body_copy"],
                    "properties": {
                        "persona_id": {
                            "type": "string",
                            "description": "ID of the persona this variant targets.",
                        },
                        "persona_reasoning": {
                            "type": "string",
                            "description": (
                                "One sentence: distill the rerank reasoning into why this "
                                "persona responds to this advertiser and what creative angle follows."
                            ),
                        },
                        "headline": {
                            "type": "string",
                            "description": "6–10 words. Direct, specific, benefit-led.",
                        },
                        "body_copy": {
                            "type": "string",
                            "description": (
                                "2–3 sentences tuned to this persona's messaging_preferences. "
                                "Avoid anything in their disinterested_in list."
                            ),
                        },
                    },
                },
            },
        },
    },
}


@dataclass
class CreativeVariant:
    persona_id: str
    persona_name: str
    persona_reasoning: str
    headline: str
    body_copy: str


def _format_personas(ranked_personas, persona_records: dict) -> str:
    lines = []
    for i, rp in enumerate(ranked_personas, 1):
        p = persona_records.get(rp.id, {})
        lines.append(
            f"Persona {i}:\n"
            f"Rerank reasoning: {rp.reasoning or 'Not provided.'}\n"
            f"Profile: {json.dumps(p, indent=2)}"
        )
    return "\n\n".join(lines)


def _format_publisher_context(recommended_publishers) -> str:
    lines = []
    for pub in recommended_publishers:
        lines.append(f"- {pub.record['name']}: {pub.record['notes']}")
    return "\n".join(lines)


def generate_creatives(
    brief: str,
    ranked_personas,
    persona_records: dict,
    recommended_publishers=None,
) -> list[CreativeVariant]:
    system_prompt = (PROMPTS_DIR / "05_creative_system.txt").read_text()

    publisher_context = (
        f"Publisher editorial context (the placements where these ads will run):\n"
        f"{_format_publisher_context(recommended_publishers)}\n\n"
        if recommended_publishers
        else ""
    )

    user_prompt = (
        f"Advertiser brief: {brief}\n\n"
        f"{publisher_context}"
        f"Personas (generate one variant per persona, in order):\n{_format_personas(ranked_personas, persona_records)}"
    )

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        temperature=1.0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[_CREATIVE_TOOL],
        tool_choice={"type": "tool", "name": "generate_creatives"},
    )

    block = response.content[0]
    if block.type != "tool_use":
        raise ValueError(f"Expected tool_use block, got: {block.type}")
    tool_input: dict = block.input  # type: ignore[union-attr]

    persona_name_map = {rp.id: persona_records.get(rp.id, {}).get("name", rp.id) for rp in ranked_personas}

    return [
        CreativeVariant(
            persona_id=v["persona_id"],
            persona_name=persona_name_map.get(v["persona_id"], v["persona_id"]),
            persona_reasoning=v["persona_reasoning"],
            headline=v["headline"],
            body_copy=v["body_copy"],
        )
        for v in tool_input.get("variants", [])
    ]


