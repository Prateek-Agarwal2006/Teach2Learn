"""Re-score fluency on existing results with the current fluency prompt.

RAG_TEST_PLAN.md blocker 4: the portal asked the judge about "one question ... a learner
would actually ask" while the RAG harness asked about "one piece of text ... would
actually write". The RAG wording is the careful one -- its student legitimately returns a
reflection rather than a question -- so the portal adopted it. Every fluency score already
on disk was produced by the old wording, and a cross-system fluency comparison needs both
sides judged by the same prompt.

Only the judge runs again. Nothing is regenerated: no model, no GPU, no translation call.
The old score is kept as `fluency_prompt_v1` on each turn so the change stays auditable,
and `fluency_prompt_version` on the test bed makes a re-run of this script a no-op.

    python scripts/rejudge_fluency.py sweepB-*.json fix-*.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_languages import (  # noqa: E402
    COST,
    FLUENCY_PROMPT,
    JUDGE_MODEL,
    SUPPORTED_LANGUAGES,
    judge,
)

PROMPT_VERSION = 2
CONCURRENCY = int(os.getenv("REJUDGE_CONCURRENCY", "6"))


async def credits(client: httpx.AsyncClient) -> float | None:
    """OpenRouter's remaining-credit reading, so cost is measured rather than estimated."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None
    try:
        response = await client.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()["data"]
        return float(data["total_credits"]) - float(data["total_usage"])
    except Exception:  # noqa: BLE001 - a missing reading must not stop the re-scoring
        return None


def targets(document: dict) -> list[dict]:
    """Turns carrying a fluency score, which is exactly what this re-scores."""
    return [
        turn
        for run in document.get("runs", [])
        for language in run.get("sweep", [])
        if language.get("code") != "en"
        for turn in language.get("turns", [])
        if "fluency" in turn
    ]


def language_of(document: dict, turn: dict) -> str:
    for run in document.get("runs", []):
        for language in run.get("sweep", []):
            if turn in language.get("turns", []):
                return SUPPORTED_LANGUAGES.get(language["code"], language["code"])
    return "the target language"


async def rescore(path: Path, client: httpx.AsyncClient) -> tuple[int, int]:
    document = json.loads(path.read_text())
    bed = document.setdefault("test_bed", {})
    if bed.get("fluency_prompt_version") == PROMPT_VERSION:
        print(f"  {path.name}: already at prompt version {PROMPT_VERSION}, skipped")
        return 0, 0

    turns = targets(document)
    if not turns:
        print(f"  {path.name}: no fluency scores to re-run")
        return 0, 0

    # Resolve the language name once per turn before going concurrent: language_of walks
    # the document, and doing that inside the gather would be quadratic for no reason.
    named = [(turn, language_of(document, turn)) for turn in turns]
    semaphore = asyncio.Semaphore(CONCURRENCY)
    changed = 0

    async def one(turn: dict, name: str) -> None:
        nonlocal changed
        async with semaphore:
            result = await judge(
                client,
                FLUENCY_PROMPT.format(language=name),
                f"{name} text:\n{turn.get('question_local', '')}",
            )
        if result.get("score") is None:
            # Keep the old score rather than writing a null over a real reading.
            print(f"    warning: {name} turn kept its old score ({result.get('note')})")
            return
        previous = turn["fluency"]
        turn["fluency_prompt_v1"] = previous
        turn["fluency"] = result
        if previous.get("score") != result["score"]:
            changed += 1

    await asyncio.gather(*(one(turn, name) for turn, name in named))

    bed["fluency_prompt_version"] = PROMPT_VERSION
    bed["fluency_prompt_note"] = (
        "Fluency re-scored with the RAG-aligned prompt (RAG_TEST_PLAN.md blocker 4). "
        "Original scores kept per turn as fluency_prompt_v1. Fidelity is untouched."
    )
    # Write through a temporary file: a crash mid-write would otherwise destroy results
    # that cost a GPU sweep to produce.
    temporary = path.with_suffix(".rejudge.tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False))
    temporary.replace(path)
    print(f"  {path.name}: {len(turns)} re-scored, {changed} changed")
    return len(turns), changed


async def main() -> None:
    paths = [Path(argument) for argument in sys.argv[1:]]
    if not paths:
        raise SystemExit(__doc__)
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise SystemExit("OPENROUTER_API_KEY is not set; nothing would be re-scored.")

    print(f"Judge: {JUDGE_MODEL}\nPrompt: {FLUENCY_PROMPT.splitlines()[0]}\n")
    async with httpx.AsyncClient() as client:
        before = await credits(client)
        total = 0
        changed = 0
        for path in paths:
            scored, moved = await rescore(path, client)
            total += scored
            changed += moved
        after = await credits(client)

    print(f"\n{total} turns re-scored, {changed} scores changed.")
    print(f"Judge calls: {COST.get('judge_calls', 0)}  seconds: {COST.get('judge_seconds', 0):.0f}")
    if before is not None and after is not None:
        print(f"Measured cost: ${before - after:.4f} (credits {before:.4f} -> {after:.4f})")


if __name__ == "__main__":
    asyncio.run(main())
