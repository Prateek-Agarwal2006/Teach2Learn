"""Exercise every supported teaching language against a real fine-tuned adapter.

This runs the same chain a live session runs -- Sarvam inbound, the subject LoRA,
Sarvam outbound -- without needing a participant session or the WebSocket, so it
works on the GPU host under APP_ENV=production.

It answers two separate questions, and they are worth keeping separate:

  --baseline   Does the adapter itself ask varied, on-topic questions in English?
               Translation cannot fix a repetitive learner, so a poor baseline
               makes the language sweep meaningless. Run this first.

  --sweep      For each language: seed a teacher answer, push it through the
               boundary, and record what the adapter saw and what the participant
               would read back.

On the seeding circularity
--------------------------
The sweep seeds each language by translating an English teacher answer with
Sarvam, then measures Sarvam translating it back. That is Sarvam composed with
itself: a language it renders consistently wrong in both directions still round
-trips cleanly. The round-trip number is therefore reported as *self-consistency*,
not quality. The independent OpenRouter judge on the seeded text is what actually
breaks the loop, so prefer its fidelity score when the two disagree.

Nothing is written to the server
--------------------------------
No file is created, no config is edited, and the portal's database and transcripts
are never touched -- this calls InferenceService and TranslationService directly.
It is designed to be piped in over ssh and to emit its results on stdout, so the
GPU host keeps no trace of the run:

    ssh HOST 'cd ~/scratch/teach2learn-portal && set -a && . ./.env && set +a && \
      python - --sweep' < scripts/check_languages.py > languages.json

Progress goes to stderr, the JSON result to stdout, so redirecting stdout locally
captures everything while you still watch it run.

The deployed .env decides the backend; this deliberately does not override it.
Under INFERENCE_BACKEND=vllm the run reuses the already-serving engines and adds no
GPU memory, which is the cheapest way to do this on a busy host. Under
INFERENCE_BACKEND=transformers it loads its own copy of the base model and can
contend with production, so prefer a quiet moment. Note DEFAULT_PROFILES carries no
endpoint or adapter_name, so a vllm run needs INFERENCE_PROFILES set in the
environment; the preflight below checks for that and stops before the sweep.

What this does cost, even though it writes nothing: GPU time for roughly
1 + turns generations per language, and two OpenRouter judge calls per turn unless
--no-judge is passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from functools import partial
from collections.abc import Sequence
from typing import Any

import httpx

# Progress goes to stderr so stdout carries only the JSON result, which lets an
# ssh redirect capture the run without writing anything on the host.
log = partial(print, file=sys.stderr, flush=True)

# Piped in over ssh there is no __file__, so fall back to the working directory,
# which the ssh command sets to the portal root.
_root = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(_root))

from app.services.inference import InferenceService  # noqa: E402
from app.topics import normalize_subject, topic_selection  # noqa: E402
from app.services.translation import (  # noqa: E402
    SUPPORTED_LANGUAGES,
    TranslationService,
)

# One fixed lesson per subject, reused for every language so differences within a
# subject are attributable to the language rather than to what the teacher said.
#
# Subject is not just a prompt change: DEFAULT_SUBJECT_MODELS routes each subject to
# a different base model and a different LoRA (cp->qwen3, dsa->gemma2,
# oop_java->mistral, os->granite), so sweeping subjects also sweeps adapters. Keep
# each script at three entries and run --turns 3, so TEACHER_SCRIPT[index % len] is
# exactly one pass and the cycling that muddied the first baseline cannot return.
LESSONS: dict[str, dict[str, Any]] = {
    "os": {
        "topic_id": "threads-scheduling",
        "subtopic": "CPU scheduling",
        "script": (
            "The scheduler decides which ready process runs next on the CPU, because there are "
            "usually more runnable processes than cores.",
            "Round-robin gives each process a fixed time quantum in turn, so no single process "
            "can starve the others while it holds the CPU.",
            "A very small quantum wastes time on context switches, while a very large one makes "
            "the scheduler behave like plain first-come first-served.",
        ),
    },
    "cp": {
        "topic_id": "pointers",
        "subtopic": "Dynamic memory allocation",
        "script": (
            "malloc reserves a block of memory on the heap while the program is running and "
            "returns a pointer to its first byte, because the size is not known at compile time.",
            "Every successful malloc must be matched by exactly one free, otherwise the block "
            "stays reserved for the whole life of the program and the process leaks memory.",
            "Using a pointer after its block has been freed is undefined behaviour, so it is "
            "good practice to set the pointer to NULL immediately after freeing it.",
        ),
    },
    "dsa": {
        "topic_id": "trees-heaps",
        "subtopic": "Heaps",
        "script": (
            "A binary heap is a complete binary tree where every parent is ordered against its "
            "children, so the smallest element is always sitting at the root.",
            "Because the tree is complete, the heap can be stored in a plain array, where the "
            "children of index i live at 2i+1 and 2i+2 and no pointers are needed.",
            "Inserting or removing an element only walks one path between a leaf and the root, "
            "so both operations cost logarithmic time in the number of elements.",
        ),
    },
    "oop_java": {
        "topic_id": "concurrency",
        "subtopic": "Synchronization and locks",
        "script": (
            "When two threads update the same field at once one update can be lost, because "
            "reading, changing, and writing back is not a single indivisible step.",
            "A synchronized block lets only one thread hold the object's monitor at a time, so "
            "every other thread waits until that block finishes.",
            "Acquiring two locks in different orders in different threads can deadlock, so the "
            "usual rule is to always take locks in one fixed global order.",
        ),
    },
}

# Indic + Perso-Arabic ranges. Any hit inside text that is supposed to be English
# means untranslated participant text reached the English zone.
# Every script Sarvam actually returns across the 22 languages: Devanagari,
# Bengali/Assamese, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam,
# Perso-Arabic (Urdu/Kashmiri), Ol Chiki (Santali), and Meetei Mayek (Manipuri).
# Meetei Mayek was missing here, so a Manipuri leak would have scored as clean --
# an absent alarm reads exactly like a passing test.
_NON_LATIN = re.compile(
    r"[ऀ-ॿঀ-৿਀-੿઀-૿଀-୿"
    r"஀-௿ఀ-౿ಀ-೿ഀ-ൿ؀-ۿ᱐-᱿"
    r"ꯀ-\uabff]"
)

JUDGE_MODEL = os.getenv("LANGCHECK_JUDGE_MODEL", "openai/gpt-5.6-luna")

FIDELITY_PROMPT = """You compare a source English sentence with its translation into {language}.
Reply with exactly two lines and nothing else:
Score: <1-5>
Note: <one short clause>
5 means the translation preserves the full technical meaning in correct {language} script.
1 means the meaning is lost, the script is wrong, or the text is still English."""

FLUENCY_PROMPT = """You judge one question written in {language}, addressed by a student to their teacher.
Reply with exactly two lines and nothing else:
Score: <1-5>
Note: <one short clause>
5 means natural, fluent {language} in the correct script that a learner would actually ask.
1 means unintelligible, wrong script, or untranslated English."""


class TranslationUnavailable(RuntimeError):
    """Sarvam returned the source text unchanged, so translation is not happening.

    translation.py returns the input on any failure, which is right for a live
    session -- a participant keeps going in English rather than seeing an error.
    It is wrong for a sweep: a dead key produced six languages whose rows looked
    structurally fine. Raising here turns that into an abort with the results so
    far intact, instead of unlabelled bad cells nobody can audit later.
    """


@dataclass(frozen=True)
class Lesson:
    subject: str
    topic: str
    subtopic: str
    script: tuple[str, ...]


def resolve_lesson(subject: str) -> Lesson:
    """Normalise the subject and validate the topic pair against the real catalogue.

    topic_selection raises if the pair is not one a participant could have picked,
    which keeps the report from claiming a topic the portal does not actually offer.
    """
    key = normalize_subject(subject)
    if key not in LESSONS:
        raise SystemExit(f"no lesson defined for subject {key!r}; have {sorted(LESSONS)}")
    lesson = LESSONS[key]
    topic_name, subtopic = topic_selection(key, lesson["topic_id"], lesson["subtopic"])
    return Lesson(key, topic_name, subtopic, lesson["script"])


# Sarvam has returned fragments of its own OpenAPI schema in translated_text --
# reproducibly, for particular (sentence, language) pairs. That payload would be
# handed to the adapter as the participant's answer and shown back to them, so it
# has to be caught as a failed crossing rather than accepted as text.
_SCHEMA_LEAK = re.compile(
    r"^\s*[\{\[]|['\"](?:type|title|description|properties|\$ref)['\"]\s*:", re.I
)


def _looks_like_schema(text: str) -> bool:
    return bool(_SCHEMA_LEAK.search(text or ""))


async def translate_or_fail(
    call: Any, text: str, code: str, label: str, attempts: int = 3
) -> tuple[str, int]:
    """One boundary crossing, retried, returning the text and the retries it cost.

    translation.py returns its input on any failure, so an unchanged result is the
    only failure signal there is -- but it cannot tell a transient ConnectTimeout
    (Sarvam's client timeout defaults to 5s, which is tight) from a dead key. The
    first version of this treated both as fatal and threw away eighteen healthy
    languages over one dropped connection. Retry first; abort only once a crossing
    has failed every attempt.
    """
    for attempt in range(1, attempts + 1):
        result = await call(text, code)
        leaked = _looks_like_schema(result)
        if result.strip() != text.strip() and not leaked:
            return result, attempt - 1
        why = "leaked a schema fragment" if leaked else "came back unchanged"
        if attempt < attempts:
            log(f"    retry {attempt}/{attempts - 1}: {label} for {code} {why}")
            await asyncio.sleep(1.5 * attempt)
    raise TranslationUnavailable(f"{label} for {code} {why} on {attempts} attempts")


def _has_non_latin(text: str) -> bool:
    return bool(_NON_LATIN.search(text or ""))


async def judge(client: httpx.AsyncClient, system: str, user: str) -> dict[str, Any]:
    """One isolated OpenRouter call. Never raises -- a dead judge must not kill the sweep."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return {"score": None, "note": "no OPENROUTER_API_KEY"}
    try:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": JUDGE_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": int(os.getenv("LANGCHECK_JUDGE_MAX_TOKENS", "600")),
            },
            timeout=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "90")),
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        # A reasoning model returns content: null and puts its text elsewhere, and
        # a short max_tokens can leave even that empty. Passing None to re.search
        # raises TypeError, which escaped this try and killed a whole 22-language
        # sweep after the first judged turn.
        text = message.get("content") or message.get("reasoning") or ""
        if not isinstance(text, str):
            text = str(text)
    except Exception as exc:  # noqa: BLE001 - the sweep continues without this score
        return {"score": None, "note": f"judge failed: {type(exc).__name__}"}
    if not text.strip():
        return {"score": None, "note": "judge returned empty content"}
    score = re.search(r"Score:\s*([1-5])", text)
    note = re.search(r"Note:\s*(.+)", text)
    return {
        "score": int(score.group(1)) if score else None,
        "note": note.group(1).strip() if note else text.strip()[:120],
    }



def _templated_openers(questions: Sequence[str], words: int = 6) -> list[tuple[str, int]]:
    """Catch follow-ups that differ only after a shared stock opening.

    Exact-string distinctness scores "I think I understand most of that. <X>" and
    "... <Y>" as two different questions, which is how formulaic phrasing -- the
    complaint that started this -- slips through a 6/6 result. Comparing the first
    few words instead surfaces it.
    """
    counts: dict[str, int] = {}
    for question in questions:
        opener = " ".join(question.strip().lower().split()[:words])
        if opener:
            counts[opener] = counts.get(opener, 0) + 1
    return sorted(((o, c) for o, c in counts.items() if c > 1), key=lambda pair: -pair[1])


async def run_baseline(
    service: InferenceService, lesson: Lesson, model: str, turns: int
) -> dict[str, Any]:
    """English only, real adapter. Establishes whether the learner varies its questions."""
    log(f"\n=== BASELINE (English, subject={lesson.subject}, model={model}) ===")
    history: list[dict[str, str]] = []
    opening = await service.generate(
        lesson.subject, lesson.subtopic, "The lesson is starting. Ask your first question.", model=model
    )
    history.append({"role": "assistant", "content": opening})
    log(f"  opening: {opening}")

    questions = [opening]
    evaluations: list[dict[str, str] | None] = []
    for index in range(turns):
        answer = lesson.script[index % len(lesson.script)]
        history.append({"role": "user", "content": answer})
        started = time.monotonic()
        result = await service.generate_detailed(
            lesson.subject, lesson.subtopic, messages=history, model=model
        )
        history.append({"role": "assistant", "content": result.raw_content})
        questions.append(result.content)
        evaluations.append(result.evaluation)
        log(
            f"  turn {index + 1} ({time.monotonic() - started:.1f}s) "
            f"eval={(result.evaluation or {}).get('level', '?')}/"
            f"{(result.evaluation or {}).get('score', '?')}: {result.content}",
        )

    distinct = len({q.strip().lower() for q in questions})
    templated = _templated_openers(questions)
    log(f"\n  distinct questions: {distinct}/{len(questions)}")
    if templated:
        log("  WARNING: repeated openers (formulaic follow-ups):")
        for opener, count in templated:
            log(f"    {count}x  {opener!r}")
    return {
        "questions": questions,
        "evaluations": evaluations,
        "distinct": distinct,
        "templated_openers": [{"opener": o, "count": c} for o, c in templated],
    }


async def run_language(
    service: InferenceService,
    translator: TranslationService,
    client: httpx.AsyncClient | None,
    lesson: Lesson,
    code: str,
    model: str,
    turns: int,
) -> dict[str, Any]:
    name = SUPPORTED_LANGUAGES[code]
    record: dict[str, Any] = {"code": code, "language": name, "turns": []}

    history: list[dict[str, str]] = []
    opening_en = await service.generate(
        lesson.subject, lesson.subtopic, "The lesson is starting. Ask your first question.", model=model
    )
    history.append({"role": "assistant", "content": opening_en})
    record["opening_en"] = opening_en
    opening_local, opening_retries = await translate_or_fail(
        translator.from_english, opening_en, code, "opening"
    )
    record["opening_local"] = opening_local
    record["opening_retries"] = opening_retries
    # The opening crosses the boundary too, but it sits outside the turn loop, so
    # nothing checked it. A Sindhi run had its opening silently left in English by
    # a Sarvam ConnectTimeout and still summarised as clean.
    record["opening_untranslated"] = opening_local.strip() == opening_en.strip()

    for index in range(turns):
        teacher_en = lesson.script[index % len(lesson.script)]
        # Seed: what the participant would have typed in their language.
        teacher_local, seed_retries = await translate_or_fail(
            translator.from_english, teacher_en, code, "seed"
        )
        # Inbound crossing: what the adapter actually receives.
        teacher_back, inbound_retries = await translate_or_fail(
            translator.to_english, teacher_local, code, "inbound"
        )

        history.append({"role": "user", "content": teacher_back})
        result = await service.generate_detailed(
            lesson.subject, lesson.subtopic, messages=history, model=model
        )
        history.append({"role": "assistant", "content": result.raw_content})
        # Outbound crossing: what the participant reads.
        question_local, outbound_retries = await translate_or_fail(
            translator.from_english, result.content, code, "outbound"
        )

        turn: dict[str, Any] = {
            "turn": index + 1,
            "teacher_en": teacher_en,
            "teacher_local": teacher_local,
            "teacher_back_en": teacher_back,
            "question_en": result.content,
            "question_local": question_local,
            # The adapter's own evaluation, kept raw. On the GPU host the OpenRouter
            # turn judge normally supplies the score a live session uses, so this is
            # the only place the adapter's native Score format is visible.
            "adapter_evaluation": result.evaluation,
            # Failure signals that need no judge.
            # Retries are the transient-failure rate; a crossing that needed one
            # would have silently passed English through before this was added.
            "retries": seed_retries + inbound_retries + outbound_retries,
            "seed_untranslated": teacher_local.strip() == teacher_en.strip(),
            "outbound_untranslated": question_local.strip() == result.content.strip(),
            "english_zone_leak": _has_non_latin(teacher_back) or _has_non_latin(result.content),
        }
        if client is not None and code != "en":
            turn["fidelity"] = await judge(
                client,
                FIDELITY_PROMPT.format(language=name),
                f"English source:\n{teacher_en}\n\n{name} translation:\n{teacher_local}",
            )
            turn["fluency"] = await judge(
                client,
                FLUENCY_PROMPT.format(language=name),
                f"{name} question:\n{question_local}",
            )
        record["turns"].append(turn)

    return record


def summarise(records: list[dict[str, Any]]) -> None:
    log("\n" + "=" * 78)
    log(f"{'lang':<12}{'seed':<7}{'out':<7}{'leak':<7}{'fidel':<8}{'fluent':<8}{'verdict'}")
    log("=" * 78)
    for record in records:
        # A failed language has no turns, so every count below would be 0 and the
        # verdict would read "ok" -- the worst possible way to report a failure.
        if record.get("error"):
            log(f"{record['language']:<12}{'-':<7}{'-':<7}{'-':<7}{'-':<8}{'-':<8}FAILED: {record['error'][:44]}")
            continue
        turns = record["turns"]
        seed_bad = sum(1 for t in turns if t["seed_untranslated"])
        out_bad = sum(1 for t in turns if t["outbound_untranslated"])
        leaks = sum(1 for t in turns if t["english_zone_leak"])
        fidel = [t["fidelity"]["score"] for t in turns if t.get("fidelity", {}).get("score")]
        fluent = [t["fluency"]["score"] for t in turns if t.get("fluency", {}).get("score")]
        fidel_avg = sum(fidel) / len(fidel) if fidel else None
        fluent_avg = sum(fluent) / len(fluent) if fluent else None

        problems = []
        if seed_bad or out_bad or record.get("opening_untranslated"):
            problems.append("PASSTHROUGH")
        if leaks:
            problems.append("LEAK")
        if fidel_avg is not None and fidel_avg < 3.5:
            problems.append("LOW-FIDELITY")
        if fluent_avg is not None and fluent_avg < 3.5:
            problems.append("LOW-FLUENCY")
        verdict = ", ".join(problems) if problems else "ok"

        log(
            f"{record['language']:<12}{seed_bad:<7}{out_bad:<7}{leaks:<7}"
            f"{(f'{fidel_avg:.1f}' if fidel_avg else '-'):<8}"
            f"{(f'{fluent_avg:.1f}' if fluent_avg else '-'):<8}{verdict}"
        )

    # The adapter's native Score format decides whether knowledge_threshold
    # completion can ever fire when the OpenRouter turn judge is unavailable.
    scores = [
        t["adapter_evaluation"].get("score")
        for r in records
        for t in r["turns"]
        if t.get("adapter_evaluation")
    ]
    worded = sum(1 for s in scores if s and re.search(r"high|medium|low", str(s), re.I))
    log("=" * 78)
    log(f"adapter Score fields: {len(scores)} seen, {worded} word-form, {len(scores) - worded} other")
    if scores and worded == 0:
        log("  -> completion.py::_score() reads none of these. With the OpenRouter turn")
        log("     judge unavailable, knowledge_threshold completion cannot fire.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="English-only adapter variety check")
    parser.add_argument("--sweep", action="store_true", help="run every supported language")
    parser.add_argument("--languages", help="comma-separated codes instead of all")
    parser.add_argument(
        "--subject",
        default="os",
        help="cp, dsa, oop_java, or os. Each routes to a different base model and LoRA, "
             "so this also selects which adapter is exercised.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="inference profile; default routes by subject exactly as a live session does",
    )
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--no-judge", action="store_true", help="skip OpenRouter scoring")
    parser.add_argument("--out", help="write full JSON results here")
    args = parser.parse_args()

    if not args.baseline and not args.sweep:
        parser.error("pass --baseline, --sweep, or both")

    service = InferenceService()
    translator = TranslationService()

    # Fail loudly here rather than 22 languages deep. DEFAULT_PROFILES carries no
    # endpoint or adapter_name, so a vllm run needs INFERENCE_PROFILES in the
    # environment; without it every generation would error identically.
    lesson = resolve_lesson(args.subject)
    config = service.config
    # subject_models is keyed by the normalised slug, so resolve before looking up.
    profile_name = args.model or config.subject_models.get(lesson.subject, "?")
    profile = config.profiles.get(profile_name)
    log(f"backend={config.backend}  subject={lesson.subject}  profile={profile_name}")
    log(f"  topic={lesson.topic!r}  subtopic={lesson.subtopic!r}")
    log(f"  base_model={getattr(profile, 'base_model', '?')}")
    log(f"  endpoint={getattr(profile, 'endpoint', None)}  adapter_name={getattr(profile, 'adapter_name', None)}")
    log(f"  adapter_root={config.adapter_root}  adapter={getattr(profile, 'adapter', None)}")
    # A profile pinning `device` is resolved after CUDA_VISIBLE_DEVICES remaps the
    # indices, so a run pinned to one GPU can still land somewhere unintended.
    log(f"  device={getattr(profile, 'device', None)}  device_map={config.device_map}"
        f"  CUDA_VISIBLE_DEVICES={os.getenv('CUDA_VISIBLE_DEVICES', 'unset')}")
    log(f"  translation={translator.backend}  sarvam_key={'set' if translator.api_key else 'MISSING'}")
    if config.backend == "vllm" and not getattr(profile, "endpoint", None):
        parser.error(
            f"backend is vllm but profile '{profile_name}' has no endpoint. "
            "Set INFERENCE_PROFILES, or drop the INFERENCE_BACKEND override to use .env as deployed."
        )
    client = None if args.no_judge else httpx.AsyncClient()
    output: dict[str, Any] = {
        "model": args.model,
        "profile": profile_name,
        "subject": lesson.subject,
        "topic": lesson.topic,
        "subtopic": lesson.subtopic,
        "turns": args.turns,
    }

    try:
        if args.baseline:
            output["baseline"] = await run_baseline(service, lesson, args.model, args.turns)

        if args.sweep:
            if args.languages:
                codes = [c.strip() for c in args.languages.split(",") if c.strip()]
                unknown = [c for c in codes if c not in SUPPORTED_LANGUAGES]
                if unknown:
                    parser.error(f"unsupported language codes: {', '.join(unknown)}")
            else:
                codes = [c for c in SUPPORTED_LANGUAGES if c != "en"]

            log(f"\n=== SWEEP ({len(codes)} languages, subject={lesson.subject}, model={args.model}) ===")
            records = []
            consecutive = 0
            for position, code in enumerate(codes, 1):
                started = time.monotonic()
                try:
                    record = await run_language(
                        service, translator, client, lesson, code, args.model, args.turns
                    )
                except TranslationUnavailable as exc:
                    # A single poisoned (sentence, language) pair is a finding about that
                    # language, not a reason to discard the other 21. Only a run of
                    # consecutive failures means Sarvam itself is down.
                    consecutive += 1
                    record = {
                        "code": code,
                        "language": SUPPORTED_LANGUAGES[code],
                        "turns": [],
                        "error": f"TranslationUnavailable: {exc}",
                    }
                    log(f"  [{position}/{len(codes)}] {record['language']:<12} FAILED: {exc}")
                    if consecutive >= 3:
                        log(f"\n  ABORTED: {consecutive} languages in a row failed to translate")
                        output["aborted"] = {
                            "at": code,
                            "reason": str(exc),
                            "not_run": codes[position:],
                        }
                        records.append(record)
                        break
                    records.append(record)
                    continue
                except Exception as exc:  # noqa: BLE001 - 21 good languages beat 0
                    record = {
                        "code": code,
                        "language": SUPPORTED_LANGUAGES[code],
                        "turns": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    log(f"  [{position}/{len(codes)}] {record['language']:<12} FAILED: {record['error']}")
                    consecutive += 1
                else:
                    consecutive = 0
                    log(
                        f"  [{position}/{len(codes)}] {record['language']:<12} "
                        f"{time.monotonic() - started:.1f}s",
                    )
                records.append(record)
            output["sweep"] = records
            summarise(records)
    finally:
        await service.unload_all()
        await translator.close()
        if client is not None:
            await client.aclose()

    payload = json.dumps(output, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload)
        log(f"\nwrote {args.out}")
    else:
        # Default target is stdout: piped in over ssh, this is the only way results
        # leave the host, and it keeps the server free of new files.
        print(payload)


if __name__ == "__main__":
    asyncio.run(main())
