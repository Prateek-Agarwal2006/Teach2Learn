"""Classify each student question by depth, with the judge blind to which system asked it.

    python scripts/judge_question_depth.py \
        --arm finetuned sweepA-cp.stdout.json sweepA-dsa.json sweepA-oop_java.json sweepA-os.json \
        --arm rag ".../sweepA-rag.json" \
        --arm rag_history ".../sweepA-rag-history.json" \
        --retest 60 --out question-depth.json

Learning by teaching works when the tutee's questions push the tutor to explain mechanisms and
causes rather than restate facts (Roscoe & Chi, 2007). Graesser & Person (1994) give the standard
18 question categories; this script asks the judge only for the category and maps categories to
depth itself, so the grouping cannot drift between calls.

Blinding: the judge receives the question sentence alone -- no system, subject, or teacher text --
and questions from every arm are shuffled together. A stock lead-in ("That makes sense, but ...")
is stripped first so phrasing habits cannot signal the source. Replies that contain no question
are skipped, as they are for lexical variety.

Identical question text is judged once and the label reused, so a repeated question costs nothing
extra and cannot be labelled two ways. Results are rewritten after every batch and reloaded on
restart. `--retest N` re-judges N random texts to report the instrument's own agreement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

JUDGE_MODEL = os.getenv("LANGCHECK_JUDGE_MODEL", "openai/gpt-5.6-luna")
CONCURRENCY = int(os.getenv("DEPTH_CONCURRENCY", "6"))
SEED = 20260915

DEPTH = {
    "verification": "shallow", "disjunctive": "shallow", "concept completion": "shallow",
    "feature specification": "shallow", "quantification": "shallow",
    "definition": "intermediate", "example": "intermediate", "comparison": "intermediate",
    "interpretation": "intermediate",
    "causal antecedent": "deep", "causal consequence": "deep", "goal orientation": "deep",
    "instrumental/procedural": "deep", "enablement": "deep", "expectational": "deep", "judgmental": "deep",
    "assertion": "not a question", "request/directive": "not a question",
}
ALIASES = {"instrumental": "instrumental/procedural", "procedural": "instrumental/procedural",
           "request": "request/directive", "directive": "request/directive",
           "feature": "feature specification", "concept": "concept completion"}

PROMPT = """You classify one question a student asked while learning a computer-science topic, using Graesser and Person's question categories.
Classify by the information the question seeks, not by its politeness form: "Could you explain how X works?" seeks a mechanism.

verification: whether something is true (yes/no)
disjunctive: which of the stated alternatives
concept completion: who, what, where or when, to fill in a missing detail
feature specification: the properties or attributes of something
quantification: how much or how many
definition: what a term or concept means
example: an example or instance of something
comparison: how two things are alike or differ
interpretation: what can be concluded from a pattern, data or situation
causal antecedent: what causes or caused something
causal consequence: what follows or would follow from something
goal orientation: why something is done, its purpose
instrumental/procedural: how something is done or works, its steps or mechanism
enablement: what makes something possible
expectational: why something expected does not happen
judgmental: an evaluation, opinion or recommendation
assertion: a statement of not knowing rather than a question
request/directive: asks the listener to do something unrelated to seeking information

Reply with exactly one line and nothing else:
Category: <one category name from the list>"""


def question_sentence(text: str) -> str | None:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if p]
    asked = [p for p in parts if p.endswith("?")]
    return asked[-1] if asked else None


def category_of(reply: str) -> str:
    match = re.search(r"Category:\s*([A-Za-z /-]+)", reply or "")
    if not match:
        return "unparsed"
    name = match.group(1).strip().lower().rstrip(".")
    if name in DEPTH:
        return name
    for alias, canonical in ALIASES.items():
        if name.startswith(alias):
            return canonical
    return "unparsed"


async def classify(client: httpx.AsyncClient, question: str) -> dict[str, Any]:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    try:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": JUDGE_MODEL, "max_tokens": int(os.getenv("LANGCHECK_JUDGE_MAX_TOKENS", "600")),
                  "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"Question: {question}"}]},
            timeout=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "90")),
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        # A reasoning model can return content null and put its text under reasoning.
        reply = message.get("content") or message.get("reasoning") or ""
    except Exception as exc:  # noqa: BLE001 - one failed call must not lose the batch
        return {"category": "unparsed", "depth": None, "raw": f"judge failed: {type(exc).__name__}"}
    category = category_of(reply if isinstance(reply, str) else str(reply))
    return {"category": category, "depth": DEPTH.get(category), "raw": str(reply).strip()[:160]}


def collect(arms: list[list[str]]) -> list[dict[str, Any]]:
    items = []
    for label, *paths in arms:
        for path in paths:
            try:
                runs = json.loads(Path(path).read_text()).get("runs", [])
            except (OSError, json.JSONDecodeError):
                continue  # empty interrupted captures
            for index, run in enumerate(runs):
                for turn, text in enumerate(run["baseline"]["questions"][1:], 1):
                    items.append({"arm": label, "lesson_id": run["lesson_id"], "subject": run["subject"],
                                  "run": f"{Path(path).name}#{index}", "turn": turn, "question": question_sentence(text)})
    return items


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", nargs="+", action="append", required=True, metavar=("LABEL", "FILE"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--retest", type=int, default=0)
    parser.add_argument("--limit", type=int, help="pilot: judge only this many distinct texts")
    args = parser.parse_args()
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise SystemExit("OPENROUTER_API_KEY is not set")

    rng = random.Random(SEED)
    items = collect(args.arm)
    out_path = Path(args.out)
    state = json.loads(out_path.read_text()) if out_path.exists() else {"labels": {}, "retest": {}}
    texts = sorted({i["question"] for i in items if i["question"]})
    rng.shuffle(texts)  # interleave the arms so the judge never sees one system's questions in a block
    pending = [t for t in texts if t not in state["labels"]]
    if args.limit:
        pending = pending[: args.limit]

    def save() -> None:
        state["model"], state["prompt"], state["depth_map"] = JUDGE_MODEL, PROMPT, DEPTH
        state["items"] = [{**i, **(state["labels"].get(i["question"]) or {"category": None, "depth": None})} for i in items]
        temporary = out_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=1, ensure_ascii=False))
        temporary.replace(out_path)

    semaphore = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        async def label(text: str, store: dict) -> None:
            async with semaphore:
                store[text] = await classify(client, text)

        for start in range(0, len(pending), 30):
            await asyncio.gather(*(label(t, state["labels"]) for t in pending[start:start + 30]))
            save()
            print(f"  judged {min(start + 30, len(pending))}/{len(pending)}", flush=True)

        # Re-judge texts that failed to parse once, then run the reliability sample.
        failed = [t for t, v in state["labels"].items() if v["category"] == "unparsed"]
        if failed:
            await asyncio.gather(*(label(t, state["labels"]) for t in failed))
        if args.retest and not state["retest"]:
            sample = rng.sample([t for t, v in state["labels"].items() if v["category"] != "unparsed"],
                                min(args.retest, len(state["labels"])))
            await asyncio.gather(*(label(t, state["retest"]) for t in sample))
        save()

    labels = state["labels"]
    for arm in dict.fromkeys(i["arm"] for i in items):
        asked = [i for i in items if i["arm"] == arm and i["question"] and i["question"] in labels]
        depths = Counter(labels[i["question"]]["depth"] for i in asked)
        rated = sum(depths[d] for d in ("shallow", "intermediate", "deep"))
        if rated:
            print(f"{arm:12} questions={len(asked):3}  " + "  ".join(f"{d} {depths[d] / rated:.0%}" for d in ("shallow", "intermediate", "deep"))
                  + f"  (not a question {depths['not a question']}, unparsed {depths[None]})")
    if state["retest"]:
        pairs = [(labels[t], v) for t, v in state["retest"].items() if v["category"] != "unparsed"]
        print(f"retest n={len(pairs)}  same depth {sum(a['depth'] == b['depth'] for a, b in pairs) / len(pairs):.0%}"
              f"  same category {sum(a['category'] == b['category'] for a, b in pairs) / len(pairs):.0%}")


if __name__ == "__main__":
    asyncio.run(main())
