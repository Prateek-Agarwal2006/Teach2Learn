from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.completion import MIN_TURNS
from app.services.teaching_feedback import build_teaching_feedback


def evaluate_conversation(transcript: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Transparent conversation-only baseline; replaceable by the research judge."""
    teacher = [str(item.get("content", "")).strip() for item in transcript if item.get("role") == "user"]
    student = [str(item.get("content", "")).strip() for item in transcript if item.get("role") == "assistant"]
    question_rate = sum("?" in item for item in student) / len(student) if student else 0.0
    average_teacher_words = sum(len(item.split()) for item in teacher) / len(teacher) if teacher else 0.0
    completed = len(teacher) >= MIN_TURNS
    score = round(min(1.0, 0.45 * question_rate + 0.35 * min(1.0, average_teacher_words / 40) + 0.20 * completed), 4)
    return {
        "rubric_version": "conversation-baseline-v2",
        "conversation_only": True,
        "teacher_turns": len(teacher),
        "student_turns": len(student),
        "student_question_rate": round(question_rate, 4),
        "average_teacher_answer_words": round(average_teacher_words, 2),
        "completed": completed,
        "overall_score": score,
        "teaching_feedback": build_teaching_feedback(transcript),
        "note": "Operational baseline only; replace with the calibrated human-study evaluator before reporting research results.",
    }
