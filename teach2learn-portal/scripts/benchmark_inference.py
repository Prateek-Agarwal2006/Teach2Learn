from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.inference import InferenceService


SYSTEM = (
    "You are a curious student learning from a human teacher. Assess the explanation inside <evaluation> tags "
    "using Level, Score, Strength, and Improvement fields, then ask exactly one concise follow-up question."
)
SUBJECTS = ("cp", "dsa", "oop_java", "os")
MODELS = ("qwen3", "gemma2", "mistral", "granite", "qwen2.5")


async def one(service: InferenceService, model: str, subject: str, index: int) -> dict[str, object]:
    started = time.perf_counter()
    result = await service.generate_detailed(
        subject,
        "Mutexes and critical sections",
        question=(
            "A mutex protects a shared critical section by allowing one thread at a time. "
            f"For example, it prevents two threads from losing a shared-counter update. Case {index}."
        ),
        system_prompt=SYSTEM,
        model=model,
    )
    return {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "generation_ms": result.generation_ms,
        "evaluation": result.evaluation is not None,
        "question": "?" in result.content,
        "fallback_used": result.fallback_used,
        "raw_characters": len(result.raw_content),
    }


async def scenario(name: str, jobs: list[tuple[str, str, int]]) -> dict[str, object]:
    service = InferenceService()
    started = time.perf_counter()
    outcomes = await asyncio.gather(
        *(one(service, *job) for job in jobs),
        return_exceptions=True,
    )
    results = [item for item in outcomes if isinstance(item, dict)]
    errors = [f"{type(item).__name__}: {item}" for item in outcomes if isinstance(item, Exception)]
    latencies = sorted(int(item["latency_ms"]) for item in results)
    per_model = {
        model: {
            "requests": len(values),
            "mean_ms": round(statistics.mean(int(item["latency_ms"]) for item in values)),
            "max_ms": max(int(item["latency_ms"]) for item in values),
        }
        for model in MODELS
        if (values := [item for item in results if item["model"] == model])
    }
    await service.unload_all()
    return {
        "scenario": name,
        "requests": len(jobs),
        "completed": len(results),
        "errors": errors,
        "wall_ms": round((time.perf_counter() - started) * 1000),
        "p50_ms": round(statistics.median(latencies)) if latencies else None,
        "p95_ms": latencies[max(0, round(0.95 * len(latencies)) - 1)] if latencies else None,
        "evaluations_parsed": sum(bool(item["evaluation"]) for item in results),
        "questions_present": sum(bool(item["question"]) for item in results),
        "fallbacks_used": sum(bool(item["fallback_used"]) for item in results),
        "per_model": per_model,
    }


async def main() -> None:
    mixed = [(model, SUBJECTS[index % len(SUBJECTS)], index) for index, model in enumerate(MODELS * 2)]
    qwen = [("qwen3", SUBJECTS[index % len(SUBJECTS)], index) for index in range(10)]
    print(json.dumps(await scenario("ten_mixed_models", mixed), sort_keys=True))
    print(json.dumps(await scenario("ten_qwen3", qwen), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
