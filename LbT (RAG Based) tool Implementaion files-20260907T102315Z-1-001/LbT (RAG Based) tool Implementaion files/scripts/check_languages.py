"""Exercise every supported teaching language against the real RAG pipeline.

This is the RAG-based tool's equivalent of teach2learn-portal/scripts/check_languages.py,
adapted for this project's architecture: there is no fine-tuned adapter here, so the
"model" step is student_chain.invoke() (a general LLM grounded by a real ingested
vectorstore, via qa_generator's QA pool), not a LoRA-tuned generation call. Everything
else -- the translation boundary, the passthrough/leak checks, the independent
OpenRouter fidelity/fluency judge -- is the same methodology, reusing this project's own
(verbatim-ported) translation.py unchanged.

Nothing is written to Mongo: this calls student_chain.invoke() directly rather than going
through main.py's handle_teacher_turn(), so no create_session/save_student/etc. runs.

Usage (from this project's root, with SARVAM_API_KEY / OPENROUTER_API_KEY / MONGO_URI
etc. already in the environment -- source .env first):

    python scripts/check_languages.py --sweep --subject os --turns 3
    python scripts/check_languages.py --sweep --languages hi,ta,te --turns 3 --out results.json
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
from functools import partial
from pathlib import Path
from typing import Any

import httpx

log = partial(print, file=sys.stderr, flush=True)

_root = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(_root))

from models import get_llm  # noqa: E402
from qa_generator import generate_qa_for_subtopic, load_catalog  # noqa: E402
from student_chain import build_student_chain  # noqa: E402
from models import StudentResponse  # noqa: E402
from translation import SUPPORTED_LANGUAGES, TranslationService  # noqa: E402

# One fixed 3-line lesson, reused for every language so differences within the subject
# are attributable to the language rather than to what the teacher said. Matches
# teach2learn-portal's "os" script verbatim -- both tools teach the same topic, so the
# results are meaningfully comparable across the two implementations.
LESSONS: dict[str, dict[str, Any]] = {
    "os": {
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
}

# Indic + Perso-Arabic ranges -- identical to teach2learn-portal's check, since both
# projects route through the same Sarvam script set across the same 22 languages.
_NON_LATIN = re.compile(
    r"[ऀ-ॿঀ-৿਀-੿઀-૿଀-୿"
    r"஀-௿ఀ-౿ಀ-೿ഀ-ൿ؀-ۿ᱐-᱿"
    r"ꯀ-꯿]"
)

_SCHEMA_LEAK = re.compile(
    r"^\s*[\{\[]|['\"](?:type|title|description|properties|\$ref)['\"]\s*:", re.I
)

JUDGE_MODEL = os.getenv("LANGCHECK_JUDGE_MODEL", "openai/gpt-5.6-luna")

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
    """Sarvam returned the source text unchanged -- translation is not happening.

    translation.py returns the input on any failure, which is right for a live session
    (the participant keeps going in English) but wrong for a sweep, where an unlabelled
    passthrough looks identical to a language that was never actually exercised.
    """


def _looks_like_schema(text: str) -> bool:
    return bool(_SCHEMA_LEAK.search(text or ""))


def _has_non_latin(text: str) -> bool:
    return bool(_NON_LATIN.search(text or ""))


async def translate_or_fail(
    call: Any, text: str, code: str, label: str, attempts: int = 3
) -> tuple[str, int]:
    """One boundary crossing, retried, returning the text and the retries it cost."""
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


@dataclass(frozen=True)
class Lesson:
    subject: str
    subtopic: str
    script: tuple[str, ...]


def resolve_lesson(subject: str) -> Lesson:
    if subject not in LESSONS:
        raise SystemExit(f"no lesson defined for subject {subject!r}; have {sorted(LESSONS)}")
    lesson = LESSONS[subject]
    return Lesson(subject, lesson["subtopic"], lesson["script"])


async def run_language(
    student_chain: Any,
    translator: TranslationService,
    client: httpx.AsyncClient | None,
    lesson: Lesson,
    opening_en: str,
    code: str,
    turns: int,
) -> dict[str, Any]:
    name = SUPPORTED_LANGUAGES[code]
    record: dict[str, Any] = {"code": code, "language": name, "turns": []}

    opening_local, opening_retries = await translate_or_fail(
        translator.from_english, opening_en, code, "opening"
    )
    record["opening_en"] = opening_en
    record["opening_local"] = opening_local
    record["opening_retries"] = opening_retries
    # The opening crosses the boundary too, but it sits outside the turn loop below, so
    # nothing else would ever check it -- mirrors the same fix made in the finetuned
    # version's harness after a silently-English opening was scored as clean there.
    record["opening_untranslated"] = opening_local.strip() == opening_en.strip()

    student_memory: list[StudentResponse] = []
    for index in range(turns):
        teacher_en = lesson.script[index % len(lesson.script)]
        # Seed: what the participant would have typed in their language.
        teacher_local, seed_retries = await translate_or_fail(
            translator.from_english, teacher_en, code, "seed"
        )
        # Inbound crossing: what student_chain actually receives.
        teacher_back, inbound_retries = await translate_or_fail(
            translator.to_english, teacher_local, code, "inbound"
        )

        student_llm_response = student_chain.invoke({
            "teacher_explanation": teacher_back,
            "student_memory": student_memory,
        })
        raw = student_llm_response["text"]
        student_model = raw if isinstance(raw, StudentResponse) else StudentResponse.parse_raw(raw)
        student_memory.append(student_model)

        # Outbound crossing: what the participant reads back. The student sometimes has
        # no follow-up question (rating="understood", message=None) -- unlike the
        # finetuned adapter, which always asks something -- so fall back to the
        # reflection text, which is always populated, to keep every turn judgeable.
        outbound_kind = "message" if student_model.message else "reflection"
        outbound_en = student_model.message or student_model.reflection
        question_local, outbound_retries = await translate_or_fail(
            translator.from_english, outbound_en, code, "outbound"
        )

        turn: dict[str, Any] = {
            "turn": index + 1,
            "teacher_en": teacher_en,
            "teacher_local": teacher_local,
            "teacher_back_en": teacher_back,
            "outbound_kind": outbound_kind,
            "question_en": outbound_en,
            "question_local": question_local,
            "student_rating": student_model.rating,
            "retries": seed_retries + inbound_retries + outbound_retries,
            "seed_untranslated": teacher_local.strip() == teacher_en.strip(),
            "outbound_untranslated": question_local.strip() == outbound_en.strip(),
            "english_zone_leak": _has_non_latin(teacher_back) or _has_non_latin(outbound_en),
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
    log("=" * 78)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", action="store_true", help="run every supported language")
    parser.add_argument("--languages", help="comma-separated codes instead of all")
    parser.add_argument("--subject", default="os", help="only 'os' has ingested content right now")
    parser.add_argument("--model", default="openai/gpt-4o", help="LLM behind student_chain (via OpenRouter)")
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--no-judge", action="store_true", help="skip OpenRouter scoring")
    parser.add_argument("--out", help="write full JSON results here")
    args = parser.parse_args()

    if not args.sweep:
        parser.error("pass --sweep")

    lesson = resolve_lesson(args.subject)
    sarvam_key = os.getenv("SARVAM_API_KEY", "").strip()
    log(f"subject={lesson.subject}  subtopic={lesson.subtopic!r}  model={args.model}")
    log(f"sarvam_key={'set' if sarvam_key else 'MISSING'}  openrouter_key={'set' if os.getenv('OPENROUTER_API_KEY') else 'MISSING'}")

    llm = get_llm(args.model)
    catalog = load_catalog()
    if lesson.subject not in catalog:
        parser.error(f"'{lesson.subject}' not in catalog -- run ingest.py first")
    student_chain, vs = build_student_chain(llm, lesson.subject, catalog)
    translator = TranslationService()

    log("generating QA pool (one call, reused for every language)...")
    qa_pool = generate_qa_for_subtopic(llm, vs, lesson.subtopic)
    if not qa_pool:
        parser.error("QA pool generation returned nothing -- check the model/vectorstore")
    opening_en = qa_pool[0].question
    log(f"  opening: {opening_en}")

    client = None if args.no_judge else httpx.AsyncClient()
    output: dict[str, Any] = {
        "model": args.model,
        "subject": lesson.subject,
        "subtopic": lesson.subtopic,
        "turns": args.turns,
        "opening_en": opening_en,
    }

    try:
        if args.languages:
            codes = [c.strip() for c in args.languages.split(",") if c.strip()]
            unknown = [c for c in codes if c not in SUPPORTED_LANGUAGES]
            if unknown:
                parser.error(f"unsupported language codes: {', '.join(unknown)}")
        else:
            codes = [c for c in SUPPORTED_LANGUAGES if c != "en"]

        log(f"\n=== SWEEP ({len(codes)} languages, subject={lesson.subject}) ===")
        records = []
        consecutive = 0
        for position, code in enumerate(codes, 1):
            started = time.monotonic()
            try:
                record = await run_language(student_chain, translator, client, lesson, opening_en, code, args.turns)
            except TranslationUnavailable as exc:
                consecutive += 1
                record = {"code": code, "language": SUPPORTED_LANGUAGES[code], "turns": [], "error": f"TranslationUnavailable: {exc}"}
                log(f"  [{position}/{len(codes)}] {record['language']:<12} FAILED: {exc}")
                if consecutive >= 3:
                    log(f"\n  ABORTED: {consecutive} languages in a row failed to translate")
                    output["aborted"] = {"at": code, "reason": str(exc), "not_run": codes[position:]}
                    records.append(record)
                    break
                records.append(record)
                continue
            except Exception as exc:  # noqa: BLE001 - other good languages beat zero
                record = {"code": code, "language": SUPPORTED_LANGUAGES[code], "turns": [], "error": f"{type(exc).__name__}: {exc}"}
                log(f"  [{position}/{len(codes)}] {record['language']:<12} FAILED: {record['error']}")
                consecutive += 1
            else:
                consecutive = 0
                log(f"  [{position}/{len(codes)}] {record['language']:<12} {time.monotonic() - started:.1f}s")
            records.append(record)
        output["sweep"] = records
        summarise(records)
    finally:
        await translator.close()
        if client is not None:
            await client.aclose()

    payload = json.dumps(output, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload)
        log(f"\nwrote {args.out}")
    else:
        print(payload)


if __name__ == "__main__":
    asyncio.run(main())
