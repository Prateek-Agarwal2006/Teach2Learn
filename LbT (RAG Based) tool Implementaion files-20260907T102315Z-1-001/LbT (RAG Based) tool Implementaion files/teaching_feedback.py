"""Deterministic final-feedback fallback.

Adapted from teach2learn-portal/app/services/teaching_feedback.py, not ported verbatim:
the portal's build_teaching_feedback(transcript) pulls both per-turn evaluations *and*
each turn's teacher text out of one transcript list where every assistant-turn dict has
an embedded "inline_evaluation" key. This app stores evaluations and teacher text in
separate Mongo collections, joined only by a shared interaction_id -- memory.py's
fetch_session_turns() does that join and hands build_deterministic_feedback() an
already-flat, already-ordered list instead.

_field/_score/_unique below are copied from that same portal file. They share names with
but are NOT the same functions as completion.py's own private _score/_level (those take a
raw string; these take a dict) -- don't conflate the two when touching either file later.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def build_deterministic_feedback(turns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build participant-facing feedback from each turn's already-produced evaluation."""
    teacher_turns = [str(item.get("teacher_text", "")).strip() for item in turns]

    strengths = _unique(
        _field(item, "strength") for item in reversed(turns)
    )
    improvements = _unique(
        _field(item, "improvement") for item in reversed(turns)
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

    levels = [_field(item, "level") for item in turns if _field(item, "level")]
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
        "assessment_count": len(turns),
        "generation": "deterministic_fallback",
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
