from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def build_teaching_feedback(transcript: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build participant-facing feedback from assessments already produced per turn."""
    teacher_turns = [str(item.get("content", "")).strip() for item in transcript if item.get("role") == "user"]
    assessments = [
        item["inline_evaluation"]
        for item in transcript
        if item.get("role") == "assistant" and isinstance(item.get("inline_evaluation"), Mapping)
    ]

    strengths = _unique(
        _field(item, "strength") or (_field(item, "feedback") if _score(item) >= 1 else "")
        for item in reversed(assessments)
    )
    improvements = _unique(
        _field(item, "improvement") or (_field(item, "feedback") if _score(item) == 0 else "")
        for item in reversed(assessments)
    )

    average_words = round(sum(len(item.split()) for item in teacher_turns) / len(teacher_turns)) if teacher_turns else 0
    if not strengths:
        strengths = [
            "You stayed engaged with the learner's follow-up questions and completed the teaching sequence."
        ]
    if not improvements:
        improvements = [
            "Add one concrete example and explain why it works, so the learner can connect the idea to its use."
        ]

    levels = [_field(item, "level") for item in assessments if _field(item, "level")]
    final_level = levels[-1] if levels else "not recorded"
    summary = (
        f"You taught the learner across {len(teacher_turns)} explanation"
        f"{'s' if len(teacher_turns) != 1 else ''}, averaging {average_words} words each. "
        f"The final explanation was assessed at the {final_level} level."
    )
    return {
        "summary": summary,
        "strengths": strengths[:2],
        "improvements": improvements[:2],
        "final_level": final_level,
        "assessment_count": len(assessments),
    }


def parse_final_teaching_feedback(text: str, fallback: Mapping[str, Any]) -> dict[str, Any]:
    """Parse a bounded final-evaluator response, retaining safe deterministic fallbacks."""
    body_match = re.search(r"<final_feedback>(.*?)</final_feedback>", text, flags=re.DOTALL | re.IGNORECASE)
    body = body_match.group(1) if body_match else text
    strengths = _unique(
        [
            *re.findall(r"^\s*strength(?:\s+\d+)?\s*:\s*(.+)$", body, flags=re.MULTILINE | re.IGNORECASE),
            *re.findall(r"<strength>\s*(.*?)\s*</strength>", body, flags=re.DOTALL | re.IGNORECASE),
        ]
    )
    improvements = _unique(
        [
            *re.findall(r"^\s*improvement(?:\s+\d+)?\s*:\s*(.+)$", body, flags=re.MULTILINE | re.IGNORECASE),
            *re.findall(r"<improvement>\s*(.*?)\s*</improvement>", body, flags=re.DOTALL | re.IGNORECASE),
        ]
    )
    summary_match = re.search(r"^\s*summary\s*:\s*(.+)$", body, flags=re.MULTILINE | re.IGNORECASE)
    tagged_summary = re.search(r"<summary>\s*(.*?)\s*</summary>", body, flags=re.DOTALL | re.IGNORECASE)
    summary_value = summary_match.group(1) if summary_match else tagged_summary.group(1) if tagged_summary else ""
    summary = " ".join(summary_value.split())
    valid = bool(strengths and improvements and summary)
    filled_strengths = _unique([*strengths, *fallback["strengths"]])[:2]
    filled_improvements = _unique([*improvements, *fallback["improvements"]])[:2]
    complete = len(strengths) >= 2 and len(improvements) >= 2
    return {
        **dict(fallback),
        "strengths": [item[:600] for item in filled_strengths] if valid else list(fallback["strengths"]),
        "improvements": [item[:600] for item in filled_improvements] if valid else list(fallback["improvements"]),
        "summary": summary[:1200] if valid else str(fallback["summary"]),
        "generation": "independent_final_evaluator" if valid and complete else "hybrid_final_evaluator" if valid else "deterministic_fallback",
    }


def _field(item: Mapping[str, Any], name: str) -> str:
    value = " ".join(str(item.get(name, "")).split())
    return re.sub(rf"^(?:{name}|feedback)\s*:\s*", "", value, flags=re.IGNORECASE).strip()


def _score(item: Mapping[str, Any]) -> int:
    value = _field(item, "score").lower()
    if "high" in value:
        return 2
    if "medium" in value or "moderate" in value:
        return 1
    return 0


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
