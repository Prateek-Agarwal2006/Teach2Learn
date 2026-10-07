"""Exercise the shared lesson bank against the real RAG pipeline.

This is the RAG-based tool's counterpart to teach2learn-portal/scripts/check_languages.py,
reading the same repo-root lessons.json bank that portal harness reads, so results from
the two systems describe the same teacher input (see RAG_TEST_PLAN.md's "one constraint
that decides everything"). Adapted for this project's architecture: there is no fine-tuned
adapter here, so the "model" step is student_chain.invoke() -- a general LLM now actually
grounded in the ingested vectorstore (see student_chain.py's {context} slot) via
similarity_search on the teacher's (translated-to-English) explanation each turn.

Nothing is written to Mongo: this calls student_chain.invoke() directly rather than going
through main.py's handle_teacher_turn(), so no create_session/save_student/etc. runs.

evaluator_chain.py's Level/Score schema now mirrors the finetuned portal's inline
<evaluation> block field-for-field (see completion.py), so the two systems' per-turn
evaluations ARE directly comparable where this harness does invoke the evaluator -- it
currently doesn't (this harness only exercises student_chain.invoke(), not
evaluator_chain.invoke(), so report_sweep.py's evaluation columns still correctly show
"-" for these runs; add an evaluator_chain.invoke() call here if that figure is wanted
from this harness too).

Usage (from this project's root, with the .env already sourced):

    # what's in the bank, and what's reviewed
    python scripts/check_languages.py --list-lessons

    # one subject, English only, three repeats (question variety + retrieval sanity)
    python scripts/check_languages.py --baseline --subject os --repeat 3 --out baseline-os.json

    # one lesson, two languages, one repeat -- a pilot before committing to the full sweep
    python scripts/check_languages.py --sweep --lesson os/threads-scheduling/cpu-scheduling \\
        --languages hi,ta --out pilot.json

    # the full grid, matching teach2learn-portal/TEST_BED.md's design
    python scripts/check_languages.py --sweep --repeat 3 --out sweep-all.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

import httpx
from langchain_openai import ChatOpenAI

log = partial(print, file=sys.stderr, flush=True)

_root = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(_root))

from models import StudentResponse  # noqa: E402
from qa_generator import load_catalog  # noqa: E402
from student_chain import (  # noqa: E402
    build_student_chain,
    generate_opening_question,
    outbound_text as _shared_outbound_text,
)
from translation import SUPPORTED_LANGUAGES, TranslationService  # noqa: E402

# Fixed decoding params from TEST_BED.md, applied here rather than in models.py's
# get_llm() so the live app's behaviour is untouched by this harness.
TEMPERATURE = float(os.getenv("LANGCHECK_TEMPERATURE", "0.25"))
TOP_P = float(os.getenv("LANGCHECK_TOP_P", "0.9"))

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

# Deliberately "piece of text"/"write", not "question"/"ask": the RAG student legitimately
# returns no question on rating="understood" and the harness falls back to the reflection
# text, which is not phrased as a question. RAG_TEST_PLAN.md asks the portal to adopt this
# wording rather than the reverse.
FLUENCY_PROMPT = """You judge one piece of text written in {language}, addressed by a student to their teacher.
Reply with exactly two lines and nothing else:
Score: <1-5>
Note: <one short clause>
5 means natural, fluent {language} in the correct script that a learner would actually write.
1 means unintelligible, wrong script, or untranslated English."""


class TranslationUnavailable(RuntimeError):
    """Sarvam returned the source text unchanged -- translation is not happening."""


def _looks_like_schema(text: str) -> bool:
    return bool(_SCHEMA_LEAK.search(text or ""))


def _has_non_latin(text: str) -> bool:
    return bool(_NON_LATIN.search(text or ""))


async def translate_or_fail(call: Any, text: str, code: str, label: str, attempts: int = 3) -> tuple[str, int]:
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


async def judge(client: httpx.AsyncClient | None, system: str, user: str) -> dict[str, Any]:
    """One isolated OpenRouter call. Never raises -- a dead judge must not kill the sweep."""
    if client is None:
        return {"score": None, "note": "judge disabled"}
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return {"score": None, "note": "no OPENROUTER_API_KEY"}
    try:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": JUDGE_MODEL,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
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
    return {"score": int(score.group(1)) if score else None, "note": note.group(1).strip() if note else text.strip()[:120]}


def _templated_openers(questions: list[str], words: int = 6) -> list[dict[str, Any]]:
    """Catch follow-ups that differ only after a shared stock opening.

    Ported verbatim from teach2learn-portal's harness: exact-string distinctness scores
    "I think I understand most of that. <X>" and "... <Y>" as two different questions,
    which is how formulaic phrasing slips through a perfect distinctness ratio.
    """
    counts: dict[str, int] = {}
    for question in questions:
        opener = " ".join(question.strip().lower().split()[:words])
        if opener:
            counts[opener] = counts.get(opener, 0) + 1
    return [{"opener": o, "count": c} for o, c in sorted(counts.items(), key=lambda kv: -kv[1]) if c > 1]


def _student_response(raw: Any) -> StudentResponse:
    return raw if isinstance(raw, StudentResponse) else StudentResponse.parse_raw(raw)


def _outbound_text(student_model: StudentResponse) -> tuple[str, str]:
    """Thin wrapper around student_chain.outbound_text() that also reports which field
    was used, for this harness's own turn-by-turn logging."""
    kind = "message" if student_model.message else "reflection"
    return _shared_outbound_text(student_model), kind


# --------------------------------------------------------------------------------
# Lesson bank
# --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Lesson:
    id: str
    subject: str
    topic_id: str
    subtopic: str
    script: tuple[str, ...]
    reviewed: bool
    carried_from: str | None


def _git_root(start: Path) -> Path | None:
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:  # noqa: BLE001 - fall through to the parents()-based guess
        pass
    return None


def resolve_lessons_path(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"--lessons path does not exist: {path}")
        return path
    # The true repo root, found via git rather than a fixed parents-count, since this
    # project's folder is nested a variable number of levels deep depending on how it
    # was extracted/merged (it moved once already, when phase1-test-bed merged in).
    candidates = []
    git_root = _git_root(_root)
    if git_root:
        candidates.append(git_root / "lessons.json")
    candidates.append(_root.parent / "lessons.json")
    candidates.append(_root.parent.parent / "lessons.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(
        "No lesson bank found. Tried: " + ", ".join(str(c) for c in candidates) +
        ". Pass --lessons explicitly. No fallback bank is used -- see RAG_TEST_PLAN.md."
    )


def load_lessons(path: Path) -> tuple[list[Lesson], int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    lessons = [
        Lesson(
            id=entry["id"],
            subject=entry["subject"],
            topic_id=entry["topic_id"],
            subtopic=entry["subtopic"],
            script=tuple(entry["script"]),
            reviewed=bool(entry.get("reviewed", False)),
            carried_from=entry.get("carried_from"),
        )
        for entry in payload["lessons"]
    ]
    return lessons, int(payload.get("version", 0))


def filter_lessons(
    lessons: list[Lesson], subject: str | None, lesson_ids: list[str] | None
) -> list[Lesson]:
    selected = lessons
    if subject:
        selected = [lesson for lesson in selected if lesson.subject == subject]
    if lesson_ids:
        wanted = set(lesson_ids)
        unknown = wanted - {lesson.id for lesson in lessons}
        if unknown:
            raise SystemExit(f"unknown lesson id(s): {', '.join(sorted(unknown))}")
        selected = [lesson for lesson in selected if lesson.id in wanted]
    return selected


# --------------------------------------------------------------------------------
# Running one lesson
# --------------------------------------------------------------------------------


async def run_baseline(
    student_chain: Any, vs: Any, lesson: Lesson, opening_en: str
) -> dict[str, Any]:
    """English only, real chain, real retrieval. Establishes whether the student
    varies its questions and whether retrieval is actually influencing it."""
    questions = [opening_en]
    student_memory: list[StudentResponse] = []
    for turn_index in range(len(lesson.script)):
        teacher_en = lesson.script[turn_index]
        context_docs = vs.similarity_search(teacher_en, k=4)
        context = "\n\n".join(doc.page_content for doc in context_docs)
        response = student_chain.invoke({
            "teacher_explanation": teacher_en,
            "student_memory": student_memory,
            "context": context,
        })
        student_model = _student_response(response["text"])
        student_memory.append(student_model)
        outbound_text, outbound_kind = _outbound_text(student_model)
        questions.append(outbound_text)
        log(f"    turn {turn_index + 1} ({outbound_kind}, rating={student_model.rating}): {outbound_text}")

    distinct = len({q.strip().lower() for q in questions})
    templated = _templated_openers(questions)
    return {"questions": questions, "distinct": distinct, "templated_openers": templated, "evaluations": []}


async def run_language(
    student_chain: Any,
    vs: Any,
    translator: TranslationService,
    client: httpx.AsyncClient | None,
    lesson: Lesson,
    opening_en: str,
    code: str,
) -> dict[str, Any]:
    name = SUPPORTED_LANGUAGES[code]
    record: dict[str, Any] = {"code": code, "language": name, "turns": []}

    opening_local, opening_retries = await translate_or_fail(translator.from_english, opening_en, code, "opening")
    record["opening_en"] = opening_en
    record["opening_local"] = opening_local
    record["opening_retries"] = opening_retries
    record["opening_untranslated"] = opening_local.strip() == opening_en.strip()

    student_memory: list[StudentResponse] = []
    for turn_index in range(len(lesson.script)):
        teacher_en = lesson.script[turn_index]
        teacher_local, seed_retries = await translate_or_fail(translator.from_english, teacher_en, code, "seed")
        teacher_back, inbound_retries = await translate_or_fail(translator.to_english, teacher_local, code, "inbound")

        context_docs = vs.similarity_search(teacher_back, k=4)
        context = "\n\n".join(doc.page_content for doc in context_docs)
        response = student_chain.invoke({
            "teacher_explanation": teacher_back,
            "student_memory": student_memory,
            "context": context,
        })
        student_model = _student_response(response["text"])
        student_memory.append(student_model)
        outbound_en, outbound_kind = _outbound_text(student_model)
        question_local, outbound_retries = await translate_or_fail(translator.from_english, outbound_en, code, "outbound")

        turn: dict[str, Any] = {
            "turn": turn_index + 1,
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
                client, FIDELITY_PROMPT.format(language=name),
                f"English source:\n{teacher_en}\n\n{name} translation:\n{teacher_local}",
            )
            turn["fluency"] = await judge(client, FLUENCY_PROMPT.format(language=name), f"{name} text:\n{question_local}")
        record["turns"].append(turn)

    return record


# --------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------


def _write_out(path: str | None, output: dict[str, Any]) -> None:
    payload = json.dumps(output, ensure_ascii=False, indent=2)
    if path:
        Path(path).write_text(payload, encoding="utf-8")
    print(payload)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", action="store_true", help="English-only variety check")
    parser.add_argument("--sweep", action="store_true", help="translation quality sweep")
    parser.add_argument("--list-lessons", action="store_true", help="print the bank and exit")
    parser.add_argument("--lessons", help="explicit path to lessons.json")
    parser.add_argument("--lesson", help="comma-separated lesson ids instead of all matching --subject")
    parser.add_argument("--subject", help="cp, dsa, oop_java, or os -- omit to run every subject in the bank")
    parser.add_argument("--languages", help="comma-separated codes for --sweep, default all 22")
    parser.add_argument("--model", default="openai/gpt-4o", help="LLM behind student_chain (via OpenRouter)")
    parser.add_argument("--repeat", type=int, default=1, help="times to repeat each lesson (captures sampling variance)")
    parser.add_argument("--allow-unreviewed", action="store_true")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--out", help="crash-safety copy, rewritten after every repeat")
    args = parser.parse_args()

    lessons_path = resolve_lessons_path(args.lessons)
    all_lessons, lessons_version = load_lessons(lessons_path)

    if args.list_lessons:
        for lesson in all_lessons:
            flag = "reviewed" if lesson.reviewed else "NOT REVIEWED"
            carried = f" (carried_from={lesson.carried_from})" if lesson.carried_from else ""
            print(f"{lesson.id}  [{flag}]{carried}")
        return

    if not args.baseline and not args.sweep:
        parser.error("pass --baseline, --sweep, --list-lessons, or a combination of the first two")

    lesson_ids = [x.strip() for x in args.lesson.split(",")] if args.lesson else None
    lessons = filter_lessons(all_lessons, args.subject, lesson_ids)
    if not lessons:
        parser.error("no lessons matched --subject/--lesson")

    unreviewed = [lesson.id for lesson in lessons if not lesson.reviewed]
    if unreviewed and not args.allow_unreviewed:
        parser.error(
            f"{len(unreviewed)} selected lesson(s) are not reviewed: {', '.join(unreviewed)}. "
            "Pass --allow-unreviewed to run anyway (the output is stamped as unreviewed)."
        )

    if args.languages:
        codes = [c.strip() for c in args.languages.split(",") if c.strip()]
        unknown_codes = [c for c in codes if c not in SUPPORTED_LANGUAGES]
        if unknown_codes:
            parser.error(f"unsupported language codes: {', '.join(unknown_codes)}")
    else:
        codes = [c for c in SUPPORTED_LANGUAGES if c != "en"]

    sarvam_key = os.getenv("SARVAM_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    log(f"lessons={lessons_path} v{lessons_version}  selected={len(lessons)}  repeats={args.repeat}  model={args.model}")
    log(f"sarvam_key={'set' if sarvam_key else 'MISSING'}  openrouter_key={'set' if openrouter_key else 'MISSING'}")

    llm = ChatOpenAI(
        base_url="https://openrouter.ai/api/v1", api_key=openrouter_key, model=args.model,
        temperature=TEMPERATURE, top_p=TOP_P,
    )
    catalog = load_catalog()

    subjects_needed = sorted({lesson.subject for lesson in lessons})
    missing_subjects = [subject for subject in subjects_needed if subject not in catalog]
    if missing_subjects:
        parser.error(f"subject(s) not in vectorstore/catalog.json -- run ingest.py first: {', '.join(missing_subjects)}")

    log(f"building chains for subjects: {', '.join(subjects_needed)}")
    chains: dict[str, tuple[Any, Any]] = {
        subject: build_student_chain(llm, subject, catalog) for subject in subjects_needed
    }

    translator = TranslationService()
    client = None if args.no_judge else httpx.AsyncClient()

    output: dict[str, Any] = {
        "test_bed": {
            "backend": "openrouter",
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "judge_model": JUDGE_MODEL if not args.no_judge else None,
            "lessons_source": str(lessons_path),
            "lessons_version": lessons_version,
            "languages": codes if args.sweep else None,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "results_are_unreviewed": bool(unreviewed),
        },
        "runs": [],
    }

    started_all = time.monotonic()
    opening_cache: dict[str, str] = {}
    try:
        for lesson in lessons:
            student_chain, vs = chains[lesson.subject]
            if lesson.id not in opening_cache:
                log(f"generating opening question for {lesson.id} ({lesson.subtopic!r})...")
                opening_student = generate_opening_question(student_chain, vs, lesson.subtopic)
                opening_cache[lesson.id] = _shared_outbound_text(opening_student)
            opening_en = opening_cache[lesson.id]

            for repeat_index in range(args.repeat):
                started = time.monotonic()
                run: dict[str, Any] = {
                    "lesson_id": lesson.id,
                    "subject": lesson.subject,
                    "profile": args.model,
                    "repeat": repeat_index,
                }
                try:
                    if args.baseline:
                        log(f"[{lesson.id}] baseline repeat {repeat_index + 1}/{args.repeat}")
                        run["baseline"] = await run_baseline(student_chain, vs, lesson, opening_en)
                    if args.sweep:
                        log(f"[{lesson.id}] sweep repeat {repeat_index + 1}/{args.repeat} ({len(codes)} languages)")
                        sweep_records = []
                        consecutive = 0
                        for position, code in enumerate(codes, 1):
                            try:
                                record = await run_language(student_chain, vs, translator, client, lesson, opening_en, code)
                            except TranslationUnavailable as exc:
                                consecutive += 1
                                record = {"code": code, "language": SUPPORTED_LANGUAGES[code], "turns": [], "error": str(exc)}
                                log(f"  [{position}/{len(codes)}] {record['language']:<12} FAILED: {exc}")
                                sweep_records.append(record)
                                if consecutive >= 3:
                                    log(f"  ABORTED after {consecutive} consecutive translation failures")
                                    break
                                continue
                            except Exception as exc:  # noqa: BLE001 - other good languages beat zero
                                consecutive += 1
                                record = {"code": code, "language": SUPPORTED_LANGUAGES[code], "turns": [], "error": f"{type(exc).__name__}: {exc}"}
                                log(f"  [{position}/{len(codes)}] {record['language']:<12} FAILED: {record['error']}")
                                sweep_records.append(record)
                                continue
                            else:
                                consecutive = 0
                                log(f"  [{position}/{len(codes)}] {record['language']:<12} ok")
                            sweep_records.append(record)
                        run["sweep"] = sweep_records
                except Exception as exc:  # noqa: BLE001 - one bad lesson/repeat should not kill the run
                    run["error"] = f"{type(exc).__name__}: {exc}"
                    log(f"[{lesson.id}] repeat {repeat_index + 1} FAILED: {run['error']}")

                run["elapsed_seconds"] = round(time.monotonic() - started, 1)
                output["runs"].append(run)
                _write_out(args.out, output)  # crash-safety: rewritten after every repeat
    finally:
        await translator.close()
        if client is not None:
            await client.aclose()

    output["test_bed"]["elapsed_seconds"] = round(time.monotonic() - started_all, 1)
    _write_out(args.out, output)
    if args.out:
        log(f"\nwrote {args.out} ({len(output['runs'])} runs)")


if __name__ == "__main__":
    asyncio.run(main())
