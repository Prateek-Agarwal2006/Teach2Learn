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

Teacher scripts come from lessons.json at the repo root, shared with the RAG tool's
harness so both systems receive identical teacher input. Without --lesson or
--subject every lesson in the bank runs; --repeat runs each one several times, and
the spread across repeats is what separates a real difference from run-to-run noise.

Two guards, because both failures produce a results file that looks complete:
INFERENCE_BACKEND=fake needs --allow-fake, since FakeBackend returns a canned string
rather than calling a model; and lessons nobody has marked reviewed need
--allow-unreviewed. Either way the output is stamped, so a bad run cannot be
mistaken for a reportable one later.

On the seeding circularity
--------------------------
The sweep seeds each language by translating an English teacher answer with
Sarvam, then measures Sarvam translating it back. That is Sarvam composed with
itself: a language it renders consistently wrong in both directions still round
-trips cleanly. The round-trip number is therefore reported as *self-consistency*,
not quality. The independent OpenRouter judge on the seeded text is what actually
breaks the loop, so prefer its fidelity score when the two disagree.

Nothing is written to the server, unless you ask for it
------------------------------------------------------
No config is edited and the portal's database and transcripts are never touched --
this calls InferenceService and TranslationService directly. Results always go to
stdout, which over a pipe is the only way they leave the host.

--out is the one exception: it writes a file wherever the program is running, which
over a pipe means on the server. That is deliberate for a run measured in hours,
because it is rewritten after every repeat and so survives a dropped connection,
but it does leave a file behind. Delete it once the run is collected.
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
from datetime import datetime, timezone
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
    looks_like_schema,
)

# The teacher scripts live in lessons.json at the repo root rather than here, shared
# byte-for-byte with the RAG tool's harness so the same lesson run against both
# systems receives identical teacher input. That is the whole basis for comparing
# them; a second hardcoded copy would drift within a week.
#
# Subject is not just a prompt change: DEFAULT_SUBJECT_MODELS routes each subject to
# a different base model and a different LoRA (cp->qwen3, dsa->gemma2,
# oop_java->mistral, os->granite), so sweeping subjects also sweeps adapters. Every
# script in the bank is exactly three sentences and runs under --turns 3, so
# script[index % len] is exactly one pass and the cycling that muddied the first
# baseline cannot return.
#
# scripts/pack_for_server.py assigns the decoded bank to PACKED_LESSONS before this
# module's code runs, because the packed program reaches the GPU host over stdin and
# no lessons.json exists there to open. The name is deliberately not _pack_-prefixed:
# the prelude deletes every _pack_* global once it has finished.
PACKED_LESSONS: dict[str, Any] | None = None


def load_lessons(path: str | None) -> dict[str, Any]:
    """Return the lesson bank, or exit naming every place that was tried.

    There is deliberately no built-in fallback bank. Falling back would emit a results
    file that looks like a 24-lesson run and is not -- the same failure shape as the
    dead Sarvam key that once produced six clean-looking rows, where the absence of an
    error is indistinguishable from a pass.
    """
    if PACKED_LESSONS is not None:
        bank = dict(PACKED_LESSONS)
        source = "packed by pack_for_server.py"
    else:
        # Piped in over ssh _root is the working directory, so the repo root is worth
        # trying as well as the portal root.
        candidates = [Path(path)] if path else [_root / "lessons.json", _root.parent / "lessons.json"]
        found = next((candidate for candidate in candidates if candidate.exists()), None)
        if found is None:
            raise SystemExit(
                "no lesson bank found. Looked in: "
                + ", ".join(str(candidate) for candidate in candidates)
                + "\nPass --lessons PATH, or pipe scripts/pack_for_server.py, which embeds it."
            )
        bank = json.loads(found.read_text())
        source = str(found)

    if not bank.get("lessons"):
        raise SystemExit(f"lesson bank at {source} contains no lessons")
    bank["source"] = source
    return bank

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

# What a pilot exists to measure. The three costs are paid to different places -- GPU
# time on a shared host, Sarvam quota, OpenRouter spend -- so a single wall-clock
# number cannot be extrapolated into any of them. Accumulated globally because the
# sweep runs one language at a time; concurrency would need this per task.
COST: dict[str, float] = {
    "generation_seconds": 0.0,
    "generation_calls": 0,
    "translation_seconds": 0.0,
    "translation_calls": 0,
    "judge_seconds": 0.0,
    "judge_calls": 0,
}

# The two sweeps TEST_BED.md plans, as turn counts, so a pilot extrapolates directly
# into the decision it exists to inform: 24 lessons x 3 repeats x 3 turns, English
# only for the first and every non-English language for the second.
PLANNED_TURNS = {
    "Sweep A (English, 24 lessons x3)": 24 * 3 * 3,
    "Sweep B (22 languages, 24 lessons x3)": 24 * 3 * 22 * 3,
}


# A generation slower than this means something is wrong with the configuration
# rather than with the model. On the vLLM path a turn is seconds; the one run that
# took 794s per language was loading its own copy of the base model onto a GPU that
# was already full, and silently offloading half of it to the CPU. Nothing in the
# output said so -- the numbers came out correct, just a hundred times too slowly.
SLOW_GENERATION_SECONDS = float(os.getenv("LANGCHECK_SLOW_GENERATION_SECONDS", "30"))
_warned_slow = False


async def timed(bucket: str, awaitable: Any) -> Any:
    """Charge one awaited call to a cost bucket, whether it succeeds or raises."""
    global _warned_slow
    started = time.monotonic()
    try:
        return await awaitable
    finally:
        elapsed = time.monotonic() - started
        COST[f"{bucket}_seconds"] += elapsed
        COST[f"{bucket}_calls"] += 1
        if bucket == "generation" and elapsed > SLOW_GENERATION_SECONDS and not _warned_slow:
            _warned_slow = True
            log(
                f"\n  WARNING: first generation took {elapsed:.0f}s, over the {SLOW_GENERATION_SECONDS:.0f}s\n"
                "  threshold. At this rate a full sweep runs for days. Usual causes, in order:\n"
                "    - INFERENCE_BACKEND=transformers while the host serves vLLM. run.sh sources\n"
                "      .env AND deploy/oauth.env; sourcing only .env leaves the backend on\n"
                "      transformers, which loads a second copy of the base model.\n"
                "    - CUDA_VISIBLE_DEVICES pinning the model to a GPU that is already full,\n"
                "      which offloads layers to the CPU ('parameters are on the meta device').\n"
                "  Stop now rather than at the end -- the results will be correct and worthless."
            )

FIDELITY_PROMPT = """You compare a source English sentence with its translation into {language}.
Reply with exactly two lines and nothing else:
Score: <1-5>
Note: <one short clause>
5 means the translation preserves the full technical meaning in correct {language} script.
1 means the meaning is lost, the script is wrong, or the text is still English."""

FLUENCY_PROMPT = """You judge one piece of text written in {language}, addressed by a student to their teacher.
Reply with exactly two lines and nothing else:
Score: <1-5>
Note: <one short clause>
5 means natural, fluent {language} in the correct script that a learner would actually write.
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
    lesson_id: str
    subject: str
    topic: str
    subtopic: str
    script: tuple[str, ...]
    reviewed: bool
    carried_from: str | None


def resolve_lessons(bank: dict[str, Any], subject: str | None, lesson_id: str | None) -> list[Lesson]:
    """Select lessons from the bank and validate each against the real catalogue.

    topic_selection raises if the pair is not one a participant could have picked,
    which keeps the report from claiming a topic the portal does not actually offer.
    Validating every selected lesson up front means a typo in the bank fails before
    the first generation rather than an hour into a sweep.
    """
    entries = bank["lessons"]
    if lesson_id:
        # Comma-separated, so a run sized to a time budget can name the exact cells it
        # wants -- two lessons per subject, say -- instead of one invocation each.
        wanted = [item.strip() for item in lesson_id.split(",") if item.strip()]
        known = {entry["id"] for entry in entries}
        missing = [item for item in wanted if item not in known]
        if missing:
            raise SystemExit(
                f"no lesson with id {', '.join(missing)} in {bank['source']}; "
                "run --list-lessons to see them"
            )
        order = {item: position for position, item in enumerate(wanted)}
        entries = sorted((e for e in entries if e["id"] in order), key=lambda e: order[e["id"]])
    elif subject:
        key = normalize_subject(subject)
        entries = [entry for entry in entries if normalize_subject(entry["subject"]) == key]
        if not entries:
            raise SystemExit(f"no lessons for subject {key!r} in {bank['source']}")

    resolved: list[Lesson] = []
    for entry in entries:
        key = normalize_subject(entry["subject"])
        topic_name, subtopic = topic_selection(key, entry["topic_id"], entry["subtopic"])
        resolved.append(
            Lesson(
                entry["id"],
                key,
                topic_name,
                subtopic,
                tuple(entry["script"]),
                bool(entry.get("reviewed", False)),
                entry.get("carried_from"),
            )
        )
    return resolved


# The schema-leak detector now lives in translation.py, so the live path rejects these
# payloads too rather than only the sweep noticing them. Imported above.


def _looks_like_schema(text: str) -> bool:
    # Kept as a name the rest of this file and its tests already use.
    return looks_like_schema(text)


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
        result = await timed("translation", call(text, code))
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
        response = await timed("judge", client.post(
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
        ))
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
    opening = await timed("generation", service.generate(
        lesson.subject, lesson.subtopic, "The lesson is starting. Ask your first question.", model=model
    ))
    history.append({"role": "assistant", "content": opening})
    log(f"  opening: {opening}")

    questions = [opening]
    evaluations: list[dict[str, str] | None] = []
    for index in range(turns):
        answer = lesson.script[index % len(lesson.script)]
        history.append({"role": "user", "content": answer})
        started = time.monotonic()
        result = await timed("generation", service.generate_detailed(
            lesson.subject, lesson.subtopic, messages=history, model=model
        ))
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
    opening_en = await timed("generation", service.generate(
        lesson.subject, lesson.subtopic, "The lesson is starting. Ask your first question.", model=model
    ))
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
        result = await timed("generation", service.generate_detailed(
            lesson.subject, lesson.subtopic, messages=history, model=model
        ))
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
                f"{name} text:\n{question_local}",
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


async def run_sweep(
    service: InferenceService,
    translator: TranslationService,
    client: httpx.AsyncClient | None,
    lesson: Lesson,
    codes: Sequence[str],
    model: str | None,
    turns: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Every language for one lesson, returning the records and an abort note if any."""
    log(f"\n=== SWEEP ({len(codes)} languages, lesson={lesson.lesson_id}, model={model}) ===")
    records: list[dict[str, Any]] = []
    aborted: dict[str, Any] | None = None
    consecutive = 0
    for position, code in enumerate(codes, 1):
        started = time.monotonic()
        try:
            record = await run_language(service, translator, client, lesson, code, model, turns)
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
            records.append(record)
            if consecutive >= 3:
                log(f"\n  ABORTED: {consecutive} languages in a row failed to translate")
                aborted = {"at": code, "reason": str(exc), "not_run": list(codes[position:])}
                break
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
            record["elapsed_seconds"] = round(time.monotonic() - started, 1)
            log(
                f"  [{position}/{len(codes)}] {record['language']:<12} "
                f"{record['elapsed_seconds']:.1f}s",
            )
        records.append(record)
    return records, aborted


def _cell_means(record: dict[str, Any]) -> tuple[float | None, float | None]:
    """Mean fidelity and fluency over the judged turns of one language record."""
    turns = record.get("turns") or []
    fidelity = [t["fidelity"]["score"] for t in turns if t.get("fidelity", {}).get("score")]
    fluency = [t["fluency"]["score"] for t in turns if t.get("fluency", {}).get("score")]
    return (
        sum(fidelity) / len(fidelity) if fidelity else None,
        sum(fluency) / len(fluency) if fluency else None,
    )


def summarise_runs(runs: Sequence[dict[str, Any]]) -> None:
    """Per lesson, aggregate across repeats.

    A single run gives one number per cell and no way to tell a real difference from
    run-to-run noise, which is the whole reason --repeat exists. So report the spread
    next to the mean; where they overlap between two lessons, the difference is not a
    finding.
    """
    by_lesson: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_lesson.setdefault(run["lesson_id"], []).append(run)

    log("\n" + "=" * 96)
    log(f"{'lesson':<50}{'n':<4}{'distinct':<11}{'fidelity':<20}{'fluency':<20}")
    log("ranges pool every language and repeat, so on a full sweep they are dominated by")
    log("differences between languages; the JSON keeps each cell for the real breakdown.")
    log("=" * 96)
    for lesson_id, lesson_runs in by_lesson.items():
        distinct = [
            run["baseline"]["distinct"] / max(len(run["baseline"]["questions"]), 1)
            for run in lesson_runs
            if run.get("baseline")
        ]
        fidelities: list[float] = []
        fluencies: list[float] = []
        for run in lesson_runs:
            for record in run.get("sweep") or []:
                fidelity, fluency = _cell_means(record)
                if fidelity is not None:
                    fidelities.append(fidelity)
                if fluency is not None:
                    fluencies.append(fluency)

        def spread(values: list[float]) -> str:
            if not values:
                return "-"
            mean = sum(values) / len(values)
            if len(values) == 1:
                return f"{mean:.2f}"
            return f"{mean:.2f} ({min(values):.2f}-{max(values):.2f})"

        log(
            f"{lesson_id:<50}{len(lesson_runs):<4}"
            f"{(f'{sum(distinct) / len(distinct):.2f}' if distinct else '-'):<11}"
            f"{spread(fidelities):<20}{spread(fluencies):<20}"
        )
    log("=" * 96)


def summarise_cost(wall_clock: float, turns_run: int) -> dict[str, Any]:
    """Print and return what the run cost, and what that implies for the full sweeps."""
    basis: dict[str, Any] = {"wall_clock_seconds": round(wall_clock, 1), "turns": turns_run}
    log("\n" + "=" * 78)
    log(f"cost basis over {turns_run} turns, {wall_clock:.0f}s wall clock")
    log("=" * 78)
    for bucket in ("generation", "translation", "judge"):
        calls = int(COST[f"{bucket}_calls"])
        seconds = COST[f"{bucket}_seconds"]
        basis[bucket] = {
            "calls": calls,
            "seconds": round(seconds, 1),
            "seconds_per_call": round(seconds / calls, 2) if calls else None,
            "calls_per_turn": round(calls / turns_run, 2) if turns_run else None,
        }
        log(
            f"  {bucket:<12}{calls:>6} calls{seconds:>9.1f}s"
            f"{(seconds / calls if calls else 0):>8.2f}s/call"
            f"{(calls / turns_run if turns_run else 0):>8.2f}/turn"
        )

    if not turns_run:
        log("=" * 78)
        return basis

    # Projections assume the pilot's per-turn rates hold, which is the assumption the
    # pilot is there to test. A larger sweep contends for the same GPU, so treat these
    # as a floor rather than an estimate.
    per_turn = wall_clock / turns_run
    judge_per_turn = COST["judge_calls"] / turns_run
    basis["projected"] = {}
    log("-" * 78)
    log("  projected at these rates (a floor: a longer run contends for the same GPU)")
    for label, turns in PLANNED_TURNS.items():
        hours = turns * per_turn / 3600
        judged = int(turns * judge_per_turn)
        basis["projected"][label] = {
            "turns": turns,
            "hours": round(hours, 1),
            "judge_calls": judged,
        }
        log(f"  {label:<40}{turns:>6} turns{hours:>7.1f}h{judged:>8} judge calls")
    log("=" * 78)
    return basis


def describe_profile(service: InferenceService, lesson: Lesson, model: str | None) -> str:
    """Log exactly which model and adapter this lesson will exercise, and return its name.

    Printed per lesson rather than once, because subject routes to a different base
    model and LoRA, so a multi-subject run touches several.
    """
    config = service.config
    # subject_models is keyed by the normalised slug, so resolve before looking up.
    profile_name = model or config.subject_models.get(lesson.subject, "?")
    profile = config.profiles.get(profile_name)
    log(f"\nlesson={lesson.lesson_id}  subject={lesson.subject}  profile={profile_name}")
    log(f"  topic={lesson.topic!r}  subtopic={lesson.subtopic!r}  reviewed={lesson.reviewed}")
    log(f"  base_model={getattr(profile, 'base_model', '?')}")
    log(f"  endpoint={getattr(profile, 'endpoint', None)}  adapter_name={getattr(profile, 'adapter_name', None)}")
    log(f"  adapter_root={config.adapter_root}  adapter={getattr(profile, 'adapter', None)}")
    # A profile pinning `device` is resolved after CUDA_VISIBLE_DEVICES remaps the
    # indices, so a run pinned to one GPU can still land somewhere unintended.
    log(f"  device={getattr(profile, 'device', None)}  device_map={config.device_map}"
        f"  CUDA_VISIBLE_DEVICES={os.getenv('CUDA_VISIBLE_DEVICES', 'unset')}")
    # Fail loudly here rather than 22 languages deep. DEFAULT_PROFILES carries no
    # endpoint or adapter_name, so a vllm run needs INFERENCE_PROFILES in the
    # environment; without it every generation would error identically.
    if config.backend == "vllm" and not getattr(profile, "endpoint", None):
        raise SystemExit(
            f"backend is vllm but profile '{profile_name}' has no endpoint. "
            "Set INFERENCE_PROFILES, or drop the INFERENCE_BACKEND override to use .env as deployed."
        )
    return profile_name


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="English-only adapter variety check")
    parser.add_argument("--sweep", action="store_true", help="run every supported language")
    parser.add_argument("--languages", help="comma-separated codes instead of all")
    parser.add_argument(
        "--lessons",
        help="path to the shared lesson bank; default is lessons.json at the repo root",
    )
    parser.add_argument(
        "--lesson",
        help="run these lessons by id, comma-separated, e.g. "
             "os/threads-scheduling/cpu-scheduling,dsa/trees-heaps/heaps. "
             "Without this and without --subject, every lesson in the bank runs.",
    )
    parser.add_argument("--list-lessons", action="store_true", help="print the selected lessons and exit")
    parser.add_argument(
        "--subject",
        default=None,
        help="cp, dsa, oop_java, or os: run every lesson for that subject. Each subject "
             "routes to a different base model and LoRA, so this also selects the adapter.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="inference profile; default routes by subject exactly as a live session does",
    )
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run each lesson this many times. One run gives a number with no spread, "
             "which cannot distinguish a real difference from run-to-run noise.",
    )
    parser.add_argument("--no-judge", action="store_true", help="skip OpenRouter scoring")
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="permit INFERENCE_BACKEND=fake; results are stamped fake and must not be reported",
    )
    parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="permit lessons no human has accepted yet; results are stamped unreviewed",
    )
    parser.add_argument("--out", help="write full JSON results here")
    args = parser.parse_args()

    bank = load_lessons(args.lessons)
    lessons = resolve_lessons(bank, args.subject, args.lesson)

    if args.list_lessons:
        log(f"{len(lessons)} lessons from {bank['source']} (version {bank.get('version')})")
        for lesson in lessons:
            notes = [] if lesson.reviewed else ["UNREVIEWED"]
            if lesson.carried_from:
                notes.append(f"carried from {lesson.carried_from}")
            log(f"  {lesson.lesson_id:<50}{'  '.join(notes)}")
        return

    if not args.baseline and not args.sweep:
        parser.error("pass --baseline, --sweep, or both")
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    # Step 3 of the plan is a human reading each script. Without this guard that step
    # is advisory, and the first run under time pressure quietly skips it while the
    # write-up still says the scripts were accepted by a reader.
    unreviewed = [lesson.lesson_id for lesson in lessons if not lesson.reviewed]
    if unreviewed and not args.allow_unreviewed:
        parser.error(
            f"{len(unreviewed)} of {len(lessons)} selected lessons are not marked reviewed in "
            f"{bank['source']}:\n  " + "\n  ".join(unreviewed[:5])
            + (f"\n  ... and {len(unreviewed) - 5} more" if len(unreviewed) > 5 else "")
            + "\nHave someone who knows the material accept each script and set "
              '"reviewed": true, or pass --allow-unreviewed for a dry run.'
        )

    service = InferenceService()
    translator = TranslationService()
    config = service.config

    # FakeBackend returns a canned string rather than calling a model, so every
    # question, evaluation, and fluency score below would be about that string. The
    # results file would still look complete, which is the failure this catches.
    if config.backend == "fake" and not args.allow_fake:
        parser.error(
            "INFERENCE_BACKEND=fake returns a scripted string, not a model, so nothing "
            "model-dependent in the output would mean anything -- and the results file "
            "would look exactly like a real run. Set INFERENCE_BACKEND=vllm or "
            "transformers, or pass --allow-fake to check the plumbing."
        )

    log(f"backend={config.backend}  lessons={len(lessons)}  repeats={args.repeat}  from={bank['source']}")
    # The deployed portal reads .env and deploy/oauth.env, and only the second sets
    # vllm. A run that sourced just .env looks identical here apart from this line.
    if config.backend == "transformers":
        log("  NOTE: backend is transformers, so this loads its own copy of the base model.")
        log("  If the host serves vLLM, source deploy/oauth.env as scripts/run.sh does.")
    log(f"  translation={translator.backend}  sarvam_key={'set' if translator.api_key else 'MISSING'}")
    log(f"  judge={'off' if args.no_judge else JUDGE_MODEL}")

    if args.languages:
        codes = [code.strip() for code in args.languages.split(",") if code.strip()]
        unknown = [code for code in codes if code not in SUPPORTED_LANGUAGES]
        if unknown:
            parser.error(f"unsupported language codes: {', '.join(unknown)}")
    else:
        codes = [code for code in SUPPORTED_LANGUAGES if code != "en"]

    client = None if args.no_judge else httpx.AsyncClient()
    # Everything the write-up's test bed table needs, recorded by the run itself
    # rather than remembered afterwards.
    output: dict[str, Any] = {
        "test_bed": {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "backend": config.backend,
            "results_are_fake": config.backend == "fake",
            "results_are_unreviewed": bool(unreviewed),
            "lessons_source": bank["source"],
            "lessons_version": bank.get("version"),
            "lesson_ids": [lesson.lesson_id for lesson in lessons],
            "unreviewed_lesson_ids": unreviewed,
            "model_override": args.model,
            "turns": args.turns,
            "repeats": args.repeat,
            "languages": codes if args.sweep else [],
            # The judge only runs inside a sweep, so a baseline-only run records none.
            "judge_model": JUDGE_MODEL if (args.sweep and not args.no_judge) else None,
            "translation_backend": translator.backend,
            # --repeat only produces a spread because decoding samples; at
            # temperature 0 the repeats would be identical by construction and the
            # printed range would be zero while looking like measured variance.
            "temperature": config.temperature,
            "top_p": config.top_p,
            "adapter_root": str(config.adapter_root),
            "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES"),
        },
        "runs": [],
    }

    run_started = time.monotonic()
    turns_run = 0
    try:
        for lesson in lessons:
            profile_name = describe_profile(service, lesson, args.model)
            for repeat in range(1, args.repeat + 1):
                run: dict[str, Any] = {
                    "lesson_id": lesson.lesson_id,
                    "subject": lesson.subject,
                    "topic": lesson.topic,
                    "subtopic": lesson.subtopic,
                    "carried_from": lesson.carried_from,
                    "reviewed": lesson.reviewed,
                    "profile": profile_name,
                    "repeat": repeat,
                    "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                started = time.monotonic()
                if args.baseline:
                    run["baseline"] = await run_baseline(service, lesson, args.model, args.turns)
                    turns_run += args.turns
                if args.sweep:
                    records, aborted = await run_sweep(
                        service, translator, client, lesson, codes, args.model, args.turns
                    )
                    run["sweep"] = records
                    if aborted:
                        run["aborted"] = aborted
                    turns_run += sum(len(record["turns"]) for record in records)
                    summarise(records)
                run["elapsed_seconds"] = round(time.monotonic() - started, 1)
                output["runs"].append(run)
                # Written after every repeat, not once at the end. A run measured in
                # hours will eventually meet a dropped ssh or a killed engine, and
                # losing every completed lesson to that is not worth the tidiness of a
                # single final write. Without --out the JSON still goes to stdout at
                # the end, which is the only way results leave the host over a pipe.
                if args.out:
                    Path(args.out).write_text(
                        json.dumps(output, ensure_ascii=False, indent=2)
                    )
    finally:
        await service.unload_all()
        await translator.close()
        if client is not None:
            await client.aclose()

    summarise_runs(output["runs"])
    output["cost_basis"] = summarise_cost(time.monotonic() - run_started, turns_run)
    if config.backend == "fake":
        log("\n  WARNING: INFERENCE_BACKEND=fake -- these numbers describe a canned string.")
    if unreviewed:
        log(f"\n  WARNING: {len(unreviewed)} lesson(s) had no human review.")

    payload = json.dumps(output, ensure_ascii=False, indent=2)
    # stdout always, --out as well. Piped in over ssh, stdout is the only way results
    # leave the host, so writing only to --out strands them there -- which is exactly
    # what happened on the first multi-subject run, where every local file was empty
    # and the results sat on the server needing an scp nobody had planned.
    print(payload)
    if args.out:
        Path(args.out).write_text(payload)
        log(f"\nalso wrote {args.out} on this machine (delete it once the run is collected)")


if __name__ == "__main__":
    asyncio.run(main())
