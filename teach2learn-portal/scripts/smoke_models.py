"""Run short, dynamic conversations through every configured fine-tuned model."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.inference import InferenceService


CASES = [
    (
        "qwen3",
        "os",
        "Semaphores and monitors",
        [
            "A semaphore uses atomic wait and signal operations to coordinate access to shared resources.",
            "A counting semaphore can represent several identical resources, while a binary semaphore has only zero and one.",
        ],
    ),
    (
        "gemma2",
        "dsa",
        "DFS and BFS",
        [
            "Breadth-first search explores a graph level by level using a queue.",
            "In an unweighted graph, the first time BFS reaches a vertex gives a shortest path by edge count.",
        ],
    ),
    (
        "mistral",
        "oop_java",
        "Polymorphism",
        [
            "Polymorphism lets code use an interface type while the runtime calls the concrete object's overridden method.",
            "For example, a List variable can refer to an ArrayList, so callers depend on the List contract rather than its storage.",
        ],
    ),
    (
        "granite",
        "cp",
        "Addresses and pointers",
        [
            "A pointer stores the address of another object, and dereferencing reads or changes the object at that address.",
            "The pointer's declared type controls how dereferencing interprets memory and how pointer arithmetic advances.",
        ],
    ),
    (
        "qwen2.5",
        "os",
        "Paging and segmentation",
        [
            "Paging divides virtual and physical memory into fixed-size blocks and maps pages to frames through page tables.",
            "Segmentation instead describes variable-size logical regions such as code, data, and stacks, each with bounds and permissions.",
        ],
    ),
]


async def main() -> None:
    service = InferenceService()
    try:
        for model, subject, topic, explanations in CASES:
            history: list[dict[str, str]] = []
            started = time.monotonic()
            opening = await service.generate(subject, topic, "The lesson is starting. Ask your first question.", model=model)
            if not opening.strip():
                raise RuntimeError(f"{model} returned an empty opening")
            history.append({"role": "assistant", "content": opening})
            print(f"\n[{model}] opening ({time.monotonic() - started:.2f}s): {opening}", flush=True)
            for turn, explanation in enumerate(explanations, 1):
                history.append({"role": "user", "content": explanation})
                started = time.monotonic()
                result = await service.generate_detailed(subject, topic, messages=history, model=model)
                reply = result.content
                if not reply.strip():
                    raise RuntimeError(f"{model} returned an empty reply on turn {turn}")
                if not result.evaluation:
                    raise RuntimeError(f"{model} omitted its private evaluation on turn {turn}")
                if "<evaluation>" in reply.lower():
                    raise RuntimeError(f"{model} leaked its private evaluation on turn {turn}")
                history.append({"role": "assistant", "content": result.raw_content})
                evaluation = result.evaluation
                print(
                    f"[{model}] turn {turn} ({time.monotonic() - started:.2f}s) "
                    f"eval={evaluation.get('level', '?')}/{evaluation.get('score', '?')}: {reply}",
                    flush=True,
                )
            print(f"[{model}] PASS: {len(history)} dynamic messages", flush=True)
    finally:
        await service.unload_all()


if __name__ == "__main__":
    asyncio.run(main())
