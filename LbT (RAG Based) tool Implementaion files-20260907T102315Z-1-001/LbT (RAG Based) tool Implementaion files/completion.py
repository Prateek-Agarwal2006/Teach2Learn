from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


MIN_TURNS = 3
MAX_TURNS = 6


@dataclass(frozen=True)
class CompletionDecision:
    complete: bool
    reason: str | None = None


def decide_completion(
    evaluations: Sequence[Mapping[str, Any] | None],
    turn: int,
    *,
    min_turns: int = MIN_TURNS,
    max_turns: int = MAX_TURNS,
) -> CompletionDecision:
    """End early only when recent private evaluations consistently show knowledge."""
    if turn >= max_turns:
        return CompletionDecision(True, "max_turns")
    if turn < min_turns:
        return CompletionDecision(False)
    if not evaluations or not evaluations[-1] or _score(evaluations[-1].get("score")) is None:
        return CompletionDecision(False)

    scored = [item for item in evaluations if item and _score(item.get("score")) is not None]
    if len(scored) < 2:
        return CompletionDecision(False)

    recent_two = scored[-2:]
    recent_scores = [_score(item.get("score")) or 0 for item in recent_two]
    demonstrates_understanding = any(_level(item.get("level")) >= 1 for item in recent_two)

    # At turn three, require at least one High plus one Medium-or-better result.
    if sum(recent_scores) >= 3 and demonstrates_understanding:
        return CompletionDecision(True, "knowledge_threshold")

    # Consistent Medium-or-better performance is enough after one extra probe.
    if turn >= min_turns + 1 and len(scored) >= 3:
        recent_three = scored[-3:]
        if all((_score(item.get("score")) or 0) >= 1 for item in recent_three) and any(
            _level(item.get("level")) >= 1 for item in recent_three
        ):
            return CompletionDecision(True, "knowledge_threshold")

    return CompletionDecision(False)


def completion_message(topic: str) -> str:
    return f"Thanks—that explanation gives me a solid understanding of {topic}. I think we can finish the lesson here."


def _score(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if "high" in text:
        return 2
    if "medium" in text or "moderate" in text:
        return 1
    if "low" in text:
        return 0
    return None


def _level(value: Any) -> int:
    text = str(value or "").strip().lower()
    levels = ("remember", "understand", "apply", "analy", "evaluat", "create")
    return next((index for index, name in reversed(tuple(enumerate(levels))) if name in text), 0)
