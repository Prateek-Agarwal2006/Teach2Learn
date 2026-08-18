from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import (
    FINAL_EVALUATOR_PROMPT,
    FORK_SYSTEM_PROMPT,
    QUESTION_BRANCH,
    TURN_EVALUATOR_PROMPT,
)
from app.services.inference import get_inference_service
from app.services.teaching_feedback import parse_final_teaching_feedback


PROFILES = {
    "qwen3": "cp",
    "gemma2": "dsa",
    "mistral": "oop_java",
    "granite": "os",
    "qwen2.5": "cp",
}


async def main() -> None:
    service = get_inference_service()
    await service.check_ready()
    results: dict[str, dict[str, object]] = {}
    history = [
        {"role": "assistant", "content": "What is mutual exclusion?"},
        {
            "role": "user",
            "content": "Mutual exclusion ensures only one thread enters a critical section at a time, preventing races on shared state.",
        },
    ]
    fallback = {
        "summary": "Fallback summary.",
        "strengths": ["Fallback strength."],
        "improvements": ["Fallback improvement."],
    }
    try:
        for model, subject in PROFILES.items():
            question, evaluation = await asyncio.gather(
                service.generate_detailed(
                    subject,
                    "Mutual exclusion",
                    messages=history,
                    system_prompt=FORK_SYSTEM_PROMPT,
                    model=model,
                    branch_instruction=QUESTION_BRANCH,
                ),
                service.generate_detailed(
                    subject,
                    "Mutual exclusion",
                    messages=history,
                    system_prompt=FORK_SYSTEM_PROMPT,
                    model=model,
                    branch_instruction=TURN_EVALUATOR_PROMPT,
                    stop_after_question=False,
                    max_new_tokens=144,
                ),
            )
            final = await service.generate_detailed(
                subject,
                "Mutual exclusion",
                messages=[
                    {
                        "role": "user",
                        "content": "AI learner: What is mutual exclusion?\nHuman teacher: " + history[-1]["content"],
                    }
                ],
                system_prompt=FINAL_EVALUATOR_PROMPT,
                model=model,
                transform_history=False,
                stop_after_question=False,
                max_new_tokens=320,
            )
            parsed_final = parse_final_teaching_feedback(final.raw_content, fallback)
            results[model] = {
                "question_present": "?" in question.content,
                "turn_evaluation_present": evaluation.evaluation is not None,
                "turn_level": (evaluation.evaluation or {}).get("level"),
                "final_generation": parsed_final["generation"],
                "question_ms": question.generation_ms,
                "evaluation_ms": evaluation.generation_ms,
                "final_ms": final.generation_ms,
            }
            if parsed_final["generation"] == "deterministic_fallback":
                results[model]["final_preview"] = final.raw_content[:1200]
    finally:
        await service.unload_all()
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
