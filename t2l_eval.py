"""Phase 2: run both Teach2Learn systems through the same teaching loop, on every
learner model each side offers, and score them on Teach2Learn metrics.

Nothing in either system is modified. Each side's own code produces the learner turn:

  ft   the portal's InferenceService, called the way the live websocket handler calls it
       (FORK_SYSTEM_PROMPT + QUESTION_BRANCH, read out of app/main.py without importing it)
  rag  student_chain.py's chain and retrieval, as main.py's handle_teacher_turn does

Everything else is shared and lives here, so a difference between the two is a difference
between learners: one teacher, one judge (the portal's TURN_EVALUATOR_PROMPT, sent with the
portal's parameters -- the deployed RAG judge uses a different prompt and no reasoning
setting, which this harness deliberately does not reproduce), one completion rule
(completion.py, byte-identical on both sides).

By default a run covers the base models both sides offer (PAIRS; --models all for every
learner), every teaching language, and
a simulated teacher (TEACHER_MODEL) that answers the learner's actual question accurately
(--conditions good; also omit, error, vague). --conditions scripted replays the 3-sentence
script from the lesson bank (LESSONS) instead, which never answers the learner and so cannot complete.

    # RAG side, from a checkout, in the RAG tool's environment (OPENROUTER_API_KEY, SARVAM_API_KEY)
    python t2l_eval.py run --system rag --out rag.json
    # fine-tuned side: the adapters live on the GPU host, so pipe the program over ssh
    python t2l_eval.py pack | ssh HOST 'cd ~/scratch/teach2learn-portal && set -a && . ./.env && \\
        set +a && $APP_PYTHON - run --system ft' > ft.json
    python t2l_eval.py score ft.json rag.json
    python t2l_eval.py selfcheck

--teacher-model must be neither a learner nor the judge. --out is rewritten after every
session and an existing file is resumed, so a dropped connection loses one session.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PACKED_LESSONS = None
HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
LESSONS = "lessons_phase2.json"
NETWORK_ERROR = re.compile(r"Connect|ReadTimeout|RemoteProtocol|ReadError|NetworkError|Temporary failure in name resolution")
RAG_DIR = "LbT (RAG Based) tool Implementaion files-20260907T102315Z-1-001/LbT (RAG Based) tool Implementaion files"
JUDGE_MODEL = os.getenv("T2L_JUDGE_MODEL", "openai/gpt-5.6-luna")
# Adapters and the OpenRouter models built on the same base: the only pairs that speak to
# fine-tuning vs retrieval rather than to model size.
# No qwen3 pair: OpenRouter withdrew qwen/qwen3-8b on 9 Oct 2026, so the RAG side cannot run it.
PAIRS = {
    "qwen2.5": "qwen/qwen-2.5-7b-instruct",
    "llama31": "meta-llama/llama-3.1-8b-instruct",
    "granite42": "ibm-granite/granite-4.2-8b",
}
# The portal's DEFAULT_SUBJECT_MODELS: what a participant gets today, against RAG's default gpt-6.1-sol.
DEPLOYED = {"cp": "qwen3", "dsa": "gemma2", "oop_java": "mistral", "os": "granite"}
# Neither a learner on either side nor the judge.
TEACHER_MODEL = os.getenv("T2L_TEACHER_MODEL", "anthropic/claude-sonnet-5.5")
SIM_STYLES = {
    "good": "Answer accurately and completely.",
    "omit": "Answer accurately, but leave out one step or idea the learner needs.",
    "error": "Include exactly one plausible factual error.",
    "vague": "Answer vaguely: restate the idea without explaining how or why.",
}
SIM_PROMPT = """You are a university student teaching "{subtopic}" to a beginner AI learner. These are the points you know:
{script}

Answer the learner's latest question in 2-3 sentences, the way a student would type it. {style}
Reply with exactly two lines and nothing else:
Answer: <what you say to the learner>
Flaw: <the step you left out or the error you made, or none>"""
LABEL_PROMPT = """You label one reply from an AI learner in a learning-by-teaching session on "{subtopic}". The learner is meant to act as a beginner who asks the human teacher questions.
Reply with exactly six lines and nothing else:
Relevant: yes or no (the reply is about what the teacher just said)
Builds: yes or no (it connects the teacher's latest answer to something taught earlier in the conversation)
Repeat: yes or no (it asks again something the learner already asked)
Novice: yes or no (it stays in the beginner role: no teaching, and no facts the teacher has not given)
Depth: shallow, intermediate or deep (shallow = yes/no or recall; intermediate = define, compare, example; deep = why, how, what if)
Challenges: yes or no (it doubts, questions the correctness of, or corrects something the teacher said)"""
CHECK_PROMPT = """A teacher's answer had this flaw: {flaw}
Reply with exactly one line, "Verdict: yes" or "Verdict: no": does the text below ask about, challenge, or point out that flaw?"""


def log(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)


def portal_prompts(main_py: Path) -> dict[str, str]:
    """The live portal's prompts, read from source: importing app.main would open the
    production database and build the OAuth client."""
    source = main_py.read_text()
    prompts = {
        node.targets[0].id: node.value.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }
    prompts["OPENING"] = re.search(r'question="(The lesson is starting[^"]*)"', source).group(1)
    return prompts


async def openrouter(client: Any, model: str, system: str, user: str, **extra: Any) -> str:
    response = await client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY'].strip()}"},
        json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], **extra},
        timeout=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "90")),
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or ""
    if isinstance(content, list):
        content = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content).strip()


def source_hash(*paths: Path) -> str:
    """Which code actually ran: the GPU host's copy is not a checkout, so there is no SHA."""
    return hashlib.sha1(b"".join(path.read_bytes() for path in paths)).hexdigest()[:12]


def fields(text: str, *keys: str) -> dict[str, list[str]]:
    return {k: [m.strip() for m in re.findall(rf"^\s*{k}(?:\s*\d+)?\s*:\s*(.+)$", text, re.M | re.I)] for k in keys}


async def judge_turn(ctx: dict, topic: str, question: str, answer: str) -> tuple[dict[str, str] | None, str]:
    """Same request the portal's generate_openrouter_turn_evaluation sends, parsed by the
    portal's own parser. Returns (evaluation, raw reply or error): an unparseable reply and
    a dead judge both leave the turn unscored, and only the raw text tells them apart."""
    if ctx["no_judge"]:
        return None, "judge disabled"
    try:
        text = await openrouter(
            ctx["client"], JUDGE_MODEL, ctx["prompts"]["TURN_EVALUATOR_PROMPT"],
            f"Selected topic: {topic}\nAI learner question: {question}\nHuman teacher answer: {answer}",
            reasoning={"effort": "high", "exclude": True}, max_tokens=1400,
        )
    except Exception as exc:  # noqa: BLE001 - a dead judge must not end the sweep
        return None, f"judge failed: {type(exc).__name__}"
    return ctx["parse_evaluation"](text), text


async def label_reply(ctx: dict, subtopic: str, history: list[dict], teacher: str, reply: str) -> dict[str, str] | None:
    """The judge's reading of one learner reply. None when it could not be labelled."""
    if ctx["no_judge"]:
        return None
    shown = "\n".join(f"{'Learner' if m['role'] == 'assistant' else 'Teacher'}: {m['content']}" for m in history)
    try:
        text = await openrouter(
            ctx["client"], JUDGE_MODEL, LABEL_PROMPT.format(subtopic=subtopic),
            f"Conversation so far:\n{shown}\n\nTeacher's latest answer: {teacher}\nLearner's reply: {reply}", max_tokens=600, temperature=0,
        )
    except Exception:  # noqa: BLE001
        return None
    got = fields(text, "relevant", "builds", "repeat", "novice", "depth", "challenges")
    return {k: v[0].lower().split()[0].strip(".,") for k, v in got.items()} if all(got.values()) else None


async def verdict(ctx: dict, flaw: str, text: str) -> bool | None:
    try:
        reply = await openrouter(ctx["client"], ctx["teacher_model"], CHECK_PROMPT.format(flaw=flaw), text, temperature=0)
    except Exception:  # noqa: BLE001
        return None
    found = re.search(r"verdict:\s*(yes|no)", reply, re.I)
    return found.group(1).lower() == "yes" if found else None


# ------------------------------------------------------------------ the two learners


class FineTuned:
    name = "ft"

    def __init__(self, root: Path, args: argparse.Namespace):
        sys.path.insert(0, str(root))
        from app.services.completion import decide_completion
        from app.services.inference import InferenceService, parse_inline_evaluation
        from app.topics import MODELS

        self.decide, self.root, self.parse_evaluation = decide_completion, root, parse_inline_evaluation
        self.source = source_hash(root / "app" / "main.py", root / "app" / "services" / "inference.py")
        self.service = InferenceService()
        config = self.service.config
        if config.backend == "fake" and not args.allow_fake:
            sys.exit("INFERENCE_BACKEND=fake returns a canned string, not a model. Pass --allow-fake to test plumbing.")
        self.models = [m["id"] for m in MODELS]
        self.prompts = portal_prompts(root / "app" / "main.py")
        self.decoding = {"backend": config.backend, "temperature": config.temperature, "top_p": config.top_p}

    def translator(self) -> Any:
        from app.services.translation import TranslationService
        return TranslationService()

    def unavailable(self, model: str, subject: str) -> str | None:
        _, profile = self.service._profile_for(subject, model)
        if self.decoding["backend"] == "transformers" and profile.adapter and not Path(profile.adapter).exists():
            return f"no adapter at {profile.adapter}"
        if self.decoding["backend"] == "vllm" and not profile.endpoint:
            return "no vLLM endpoint configured"
        return None

    def start(self, model: str, lesson: dict) -> None:
        pass

    async def opening(self, model: str, lesson: dict) -> dict:
        # generate() is what the portal calls, but it hides fallback_used.
        result = await self.service.generate_detailed(
            lesson["subject"], lesson["subtopic"], question=self.prompts["OPENING"],
            system_prompt=self.prompts["STUDENT_PROMPT"], model=model,
        )
        return {"text": result.content, "raw": result.raw_content, "kind": "fallback" if result.fallback_used else "question"}

    async def reply(self, model: str, lesson: dict, history: list[dict], teacher_en: str) -> dict:
        result = await self.service.generate_detailed(
            lesson["subject"], lesson["subtopic"], messages=history,
            system_prompt=self.prompts["FORK_SYSTEM_PROMPT"], model=model,
            branch_instruction=self.prompts["QUESTION_BRANCH"],
        )
        # fallback_used means the adapter produced no question and the portal substituted
        # its stock one, so the participant saw a question the learner never asked.
        return {"text": result.content, "raw": result.raw_content, "kind": "fallback" if result.fallback_used else "question"}


class Rag:
    name = "rag"

    def __init__(self, root: Path, args: argparse.Namespace):
        sys.path[:0] = [str(root), str(Path(args.portal_main).resolve().parents[1])]
        from app.services.inference import parse_inline_evaluation
        from completion import decide_completion

        self.decide, self.root, self.args, self.parse_evaluation = decide_completion, root, args, parse_inline_evaluation
        self.source = source_hash(root / "student_chain.py", root / "main.py")
        # The tool's README: retrieval embeds through the same OpenRouter key.
        os.environ.setdefault("OPENAI_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
        os.environ.setdefault("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        self.models = [m for m in re.findall(r'"([\w.-]+/[\w.:-]+)"', (root / "main.py").read_text().split("values=[")[1].split("]")[0])]
        self.prompts = portal_prompts(Path(args.portal_main))
        self.decoding = {"backend": "openrouter", "temperature": args.temperature, "top_p": args.top_p, "extra_body": args.rag_extra_body}
        # Opened from a throwaway copy: Chroma rewrites its files on open, and the
        # vectorstore is committed.
        self.catalog = json.loads((root / "vectorstore" / "catalog.json").read_text())
        self.tmp = Path(tempfile.mkdtemp(prefix="t2l-vs-"))
        self.chains: dict[tuple[str, str], tuple[Any, Any]] = {}

    def translator(self) -> Any:
        from translation import TranslationService
        return TranslationService()

    def unavailable(self, model: str, subject: str) -> str | None:
        return None if subject in self.catalog else "subject not in vectorstore/catalog.json"

    def start(self, model: str, lesson: dict) -> None:
        from langchain_openai import ChatOpenAI
        from student_chain import build_student_chain_only, build_vectorstore

        key = (model, lesson["subject"])
        if key not in self.chains:
            copy = self.tmp / lesson["subject"]
            if not copy.exists():
                shutil.copytree(self.root / self.catalog[lesson["subject"]]["vectorstore_path"], copy)
            from models import STUDENT_TEMPERATURE, STUDENT_TOP_P

            # As deployed (models.get_student_llm) unless a flag overrides it.
            over = {"temperature": STUDENT_TEMPERATURE if self.args.temperature is None else self.args.temperature,
                    "top_p": STUDENT_TOP_P if self.args.top_p is None else self.args.top_p}
            if self.args.rag_extra_body:
                over["extra_body"] = json.loads(self.args.rag_extra_body)
            llm = ChatOpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"].strip(), model=model, **over)
            # What the run actually used, library defaults included (meta holds this same dict).
            self.decoding.update(temperature=llm.temperature, top_p=llm.top_p)
            vs = build_vectorstore(lesson["subject"], {lesson["subject"]: {"vectorstore_path": str(copy)}})
            self.chains[key] = (build_student_chain_only(llm), vs)
        self.chain, self.vs = self.chains[key]
        self.memory: list[Any] = []

    def _shape(self, student: Any) -> dict:
        from student_chain import outbound_text
        return {
            "text": outbound_text(student), "kind": "question" if student.message else "reflection",
            "rating": student.rating, "raw": student.json(),
        }

    async def opening(self, model: str, lesson: dict) -> dict:
        from student_chain import generate_opening_question
        return self._shape(await asyncio.to_thread(generate_opening_question, self.chain, self.vs, lesson["subtopic"]))

    async def reply(self, model: str, lesson: dict, history: list[dict], teacher_en: str) -> dict:
        from models import StudentResponse

        docs = await asyncio.to_thread(self.vs.similarity_search, teacher_en, 4)
        response = await asyncio.to_thread(self.chain.invoke, {
            "teacher_explanation": teacher_en, "student_memory": self.memory,
            "context": "\n\n".join(doc.page_content for doc in docs),
        })
        student = response["text"]
        if not isinstance(student, StudentResponse):
            student = StudentResponse.parse_raw(student)
        self.memory.append(student)
        return {**self._shape(student), "retrieved": [hashlib.sha1(d.page_content.encode()).hexdigest()[:10] for d in docs]}


# ------------------------------------------------------------------ one session


async def timed(work: Any) -> dict:
    """The learner's reply with the seconds it alone took (the judge runs alongside it)."""
    started = time.monotonic()
    out = await work
    return {**out, "seconds": round(time.monotonic() - started, 2)}


async def teach(ctx: dict, lesson: dict, condition: str, turn: int, history: list[dict]) -> tuple[str, str | None]:
    if condition == "scripted":
        return lesson["script"][turn - 1], None
    shown = "\n".join(f"{'Learner' if m['role'] == 'assistant' else 'You'}: {m['content']}" for m in history)
    text = await openrouter(
        ctx["client"], ctx["teacher_model"],
        SIM_PROMPT.format(subtopic=lesson["subtopic"], script="\n".join(f"- {s}" for s in lesson["script"]), style=SIM_STYLES[condition]),
        # Room for hidden reasoning, which some models cannot switch off and which
        # otherwise eats the answer.
        shown, temperature=0, max_tokens=2000,
    )
    got = fields(text, "answer", "flaw")
    if not got["answer"] or not got["flaw"]:
        raise ValueError("simulated teacher reply was cut short or off format")
    flaw = got["flaw"][0]
    return got["answer"][0], None if flaw.lower().strip(". ") == "none" else flaw


async def run_session(learner: Any, ctx: dict, key: dict, lesson: dict) -> dict:
    model, condition, lang = key["model"], key["condition"], key["lang"]
    record: dict[str, Any] = {**key, "system": learner.name, "subject": lesson["subject"], "lesson_script": lesson["script"], "turns": [], "completion": None, "error": None}
    try:
        learner.start(model, lesson)
        record["opening"] = await learner.opening(model, lesson)
        history = [{"role": "assistant", "content": record["opening"]["text"]}]
        evaluations: list[dict | None] = []
        flaws: list[str] = []
        limit = len(lesson["script"]) if condition == "scripted" else ctx["max_turns"]
        for turn in range(1, limit + 1):
            teacher, flaw = await teach(ctx, lesson, condition, turn, history)
            seen = teacher
            if lang != "en":
                # What the learner receives when the teacher types in this language.
                local = await ctx["translator"].from_english(teacher, lang)
                if local == teacher:
                    # The service swallows a failed call and hands back the English.
                    raise RuntimeError(f"translation to {lang} failed")
                seen = await ctx["translator"].to_english(local, lang)
            started = time.monotonic()
            reply, (evaluation, judge_raw) = await asyncio.gather(
                timed(learner.reply(model, lesson, [*history, {"role": "user", "content": seen}], seen)),
                judge_turn(ctx, lesson["subtopic"], history[-1]["content"], seen),
                return_exceptions=True,
            )
            if isinstance(reply, BaseException):
                # Unusable output is a result for this turn, not a reason to drop the
                # turns before it: dropping them would keep only the well-behaved sessions.
                reply = {"text": "", "kind": "invalid", "error": f"{type(reply).__name__}: {reply}"[:300]}
            # Both live paths pass only the scored earlier turns plus the current one.
            decision = learner.decide([*[e for e in evaluations if e], evaluation], turn)
            evaluations.append(evaluation)
            entry = {
                "turn": turn, "teacher": teacher, "seen": seen, "flaw": flaw, "learner": reply, "evaluation": evaluation,
                "judge_raw": judge_raw, "seconds": round(time.monotonic() - started, 1),
            }
            if reply["kind"] != "invalid":
                entry["labels"] = await label_reply(ctx, lesson["subtopic"], history, seen, reply["text"])
            if flaw and reply["kind"] != "invalid":
                flaws.append(flaw)
                entry["flaw_targeted"] = await verdict(ctx, flaw, reply["text"])
            record["turns"].append(entry)
            history += [{"role": "user", "content": seen}, {"role": "assistant", "content": reply["text"]}]
            if reply["kind"] == "invalid":
                break
            if decision.complete:
                record["completion"] = {"turn": turn, "reason": decision.reason}
                break
        if condition != "scripted" and not ctx["no_judge"]:
            transcript = "\n".join(f"{'Human teacher' if m['role'] == 'user' else 'AI learner'}: {m['content']}" for m in history)
            record["feedback"] = await openrouter(
                ctx["client"], JUDGE_MODEL, ctx["prompts"]["FINAL_EVALUATOR_PROMPT"], transcript,
                reasoning={"effort": "high", "exclude": True}, max_tokens=1600,
            )
            if flaws:
                record["feedback_names_flaw"] = await verdict(ctx, "; ".join(flaws), record["feedback"])
    except Exception as exc:  # noqa: BLE001 - a failed session is a result, not a crash
        record["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return record


async def run(args: argparse.Namespace) -> None:
    import httpx

    default_root = HERE / ("teach2learn-portal" if args.system == "ft" else RAG_DIR)
    root = Path(args.root) if args.root else default_root if default_root.exists() else Path.cwd()
    learner = (FineTuned if args.system == "ft" else Rag)(root, args)
    bank = PACKED_LESSONS or json.loads(Path(args.lessons or HERE / LESSONS).read_text())
    lessons = [
        lesson for lesson in bank["lessons"]
        if (not args.subject or lesson["subject"] in args.subject.split(","))
        and (not args.lesson or lesson["id"] in args.lesson.split(","))
    ]
    common = list(PAIRS) if args.system == "ft" else list(PAIRS.values())
    models = {"all": learner.models, "common": common}.get(args.models) or args.models.split(",")
    conditions = args.conditions.split(",")
    unknown = [c for c in conditions if c != "scripted" and c not in SIM_STYLES]
    if unknown or not lessons:
        sys.exit(f"unknown conditions {unknown}" if unknown else "no lessons matched")
    unreviewed = [lesson["id"] for lesson in lessons if not lesson.get("reviewed")]
    if unreviewed and not args.allow_unreviewed:
        sys.exit(f"{len(unreviewed)} lessons are not reviewed yet (first: {unreviewed[0]}). Pass --allow-unreviewed for a trial run.")
    if conditions != ["scripted"] and (not args.teacher_model or args.teacher_model in {JUDGE_MODEL, *models}):
        sys.exit("--teacher-model is required for a simulated teacher and must be neither a learner nor the judge")
    translator = learner.translator()
    languages = list(sys.modules[type(translator).__module__].SUPPORTED_LANGUAGES) if args.languages == "all" else args.languages.split(",")
    if languages != ["en"] and (not translator.is_enabled() or translator.backend == "echo") and not args.allow_fake:
        sys.exit("non-English sessions need SARVAM_API_KEY and T2L_TRANSLATION_BACKEND=sarvam; pass --languages en to run without")
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001 - the GPU host's copy is not a checkout
        sha = None
    output: dict[str, Any] = {
        "meta": {
            "system": learner.name, "decoding": learner.decoding, "judge_model": None if args.no_judge else JUDGE_MODEL,
            "teacher_model": args.teacher_model, "lessons_version": bank.get("version"), "unreviewed_lessons": unreviewed, "git_sha": sha, "source_sha1": learner.source,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results_are_fake": learner.decoding["backend"] == "fake",
        },
        "sessions": [],
    }
    if args.out and Path(args.out).exists():
        # Sessions that errored are run again: most are a rate limit or a timeout.
        output["sessions"] = [s for s in json.loads(Path(args.out).read_text())["sessions"] if not s["error"] or s["error"].startswith("unavailable")]
    done = {session_key(s) for s in output["sessions"]}
    for model in models:
        missing = sorted({lesson["subject"] for lesson in lessons if learner.unavailable(model, lesson["subject"])})
        log(f"  {model}: {'ok' if not missing else 'UNAVAILABLE for ' + ', '.join(missing)}")
    async with httpx.AsyncClient() as client:
        ctx = {
            "client": client, "prompts": learner.prompts, "teacher_model": args.teacher_model, "no_judge": args.no_judge,
            "parse_evaluation": learner.parse_evaluation,
            "max_turns": args.max_turns, "translator": translator,
        }
        # Model outermost: the portal keeps one model loaded at a time.
        for model in models:
            for lesson in lessons:
                why = learner.unavailable(model, lesson["subject"])
                for condition in conditions:
                    for lang in languages:
                        for repeat in range(args.repeat):
                            key = {"model": model, "lesson_id": lesson["id"], "condition": condition, "lang": lang, "repeat": repeat}
                            if session_key({**key, "system": learner.name}) in done:
                                continue
                            if why:
                                session = {**key, "system": learner.name, "subject": lesson["subject"], "turns": [], "completion": None, "error": f"unavailable: {why}"}
                            else:
                                session = await run_session(learner, ctx, key, lesson)
                                # A dropped network fails every session in seconds; wait for it
                                # instead of burning through the rest of the run as errors.
                                for wait in (60, 120, 300, 600, 900):
                                    if not NETWORK_ERROR.search(session["error"] or ""):
                                        break
                                    log(f"network error, retrying in {wait}s: {session['error'][:80]}")
                                    await asyncio.sleep(wait)
                                    session = await run_session(learner, ctx, key, lesson)
                            output["sessions"].append(session)
                            log(f"{model} {lesson['id']} {condition} {lang} #{repeat}: "
                                f"{len(session['turns'])} turns, {session['completion'] or session['error'] or 'open'}")
                            if args.out:
                                # Write then rename, so a kill mid-write cannot corrupt the results.
                                Path(args.out + ".tmp").write_text(json.dumps(output, ensure_ascii=False, indent=1))
                                os.replace(args.out + ".tmp", args.out)
    if not args.out:
        print(json.dumps(output, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ scoring (stdlib only)

SCORE = {"low": 0, "medium": 1, "moderate": 1, "high": 2}
LEVELS = ("remember", "understand", "apply", "analy", "evaluat", "create")


def session_key(s: dict) -> tuple:
    return (s["system"], s["model"], s["lesson_id"], s["condition"], s["lang"], s["repeat"])


STOP = set("the and that this with from have what does when then than into they them their there which while would could should about your also just like only some more most very will been were because since make makes made".split())
WHY_HOW = re.compile(r"\b(why|how|what if|what happens|what would)\b", re.I)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", text.lower()) if len(w) > 3 and w not in STOP}


def overlap(part: set[str], whole: set[str]) -> float:
    return len(part & whole) / len(part) if part else 0.0


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def measure(session: dict) -> dict[str, float]:
    """Per-session values; every metric is then a mean over sessions."""
    if session["error"] or not session["turns"]:
        return {"valid": 0.0}
    turns = session["turns"]
    kinds = [t["learner"]["kind"] for t in turns]
    out = {
        "valid": 1.0,
        "opening_is_question": float(session["opening"]["kind"] == "question"),
        "invalid_turns": kinds.count("invalid") / len(turns),
        "no_question": sum(k not in ("question", "invalid") for k in kinds) / len(turns),
    }
    # Everything about what the learner asked comes from the judge's labels.
    judged = [(t["learner"]["kind"] == "question", t["labels"]) for t in turns if t.get("labels")]
    if judged:
        share = lambda test: sum(bool(test(asks, lab)) for asks, lab in judged) / len(judged)  # noqa: E731
        out["productive"] = share(lambda asks, lab: asks and lab["relevant"] == "yes" and lab["repeat"] == "no")
        out["repeats"] = share(lambda asks, lab: lab["repeat"] == "yes")
        out["builds_on_earlier"] = share(lambda asks, lab: lab["builds"] == "yes")
        out["stays_novice"] = share(lambda asks, lab: lab["novice"] == "yes")
        out["deep_question"] = share(lambda asks, lab: asks and lab["depth"] == "deep")
    scores = [SCORE[e["score"].lower().split()[0]] for t in turns if (e := t["evaluation"]) and e["score"].lower().split()[0] in SCORE]
    levels = [next((i for i, name in reversed(list(enumerate(LEVELS))) if name in t["evaluation"]["level"].lower()), 0) for t in turns if t["evaluation"]]
    if scores:
        out["elicited_score"] = statistics.mean(scores)
        out["elicited_level"] = statistics.mean(levels)
    if len(scores) > 1:
        out["grade_trend"] = scores[-1] - scores[0]
    # Counted from the text alone, no judge. Denominators: replies = every usable learner
    # turn; questions = the replies that ask something (plus the opening, as an earlier question).
    replies = [(t, t["learner"]) for t in turns if t["learner"]["kind"] != "invalid"]
    if replies:
        out["learner_words"] = statistics.mean(len(r["text"].split()) for _, r in replies)
        out["length_ratio"] = statistics.mean(len(r["text"].split()) / max(1, len(t["seen"].split())) for t, r in replies)
        out["echo"] = statistics.mean(overlap(words(r["text"]), words(t["seen"])) for t, r in replies)
        pairs = [b for text in (r["text"] for _, r in replies) for b in zip(text.lower().split(), text.lower().split()[1:])]
        if pairs:
            out["distinct_2"] = len(set(pairs)) / len(pairs)
        if any("seconds" in r for _, r in replies):
            out["learner_seconds"] = statistics.mean(r["seconds"] for _, r in replies if "seconds" in r)
    questions = [r["text"] for _, r in replies if r["kind"] == "question"]
    if questions:
        out["why_how"] = sum(bool(WHY_HOW.search(q)) for q in questions) / len(questions)
        earlier = [session["opening"]["text"]] if session["opening"]["kind"] == "question" else []
        repeats = []
        for q in questions:
            if earlier:
                repeats.append(max(jaccard(words(q), words(e)) for e in earlier))
            earlier.append(q)
        if repeats:
            out["self_repeat"] = statistics.mean(repeats)
    if session["condition"] != "scripted" and session.get("lesson_script"):
        taught = words(" ".join(t["teacher"] for t in turns))
        out["key_points_covered"] = statistics.mean(overlap(words(point), taught) >= 0.5 for point in session["lesson_script"])
    # Flawed turns are keyed on the turn's own flaw, not the condition: the accurate
    # teacher sometimes owns up to a slip of its own.
    labelled = [(bool(t["flaw"]), t["labels"].get("challenges") == "yes") for t in turns if t.get("labels") and "challenges" in t["labels"]]
    if any(f for f, _ in labelled):
        out["challenge_when_flawed"] = statistics.mean(c for f, c in labelled if f)
    if any(not f for f, _ in labelled):
        out["challenge_when_clean"] = statistics.mean(c for f, c in labelled if not f)
    if session["condition"] != "scripted":
        # A session cut short by an unusable reply made no completion decision; reliability
        # already charges for it.
        if kinds[-1] != "invalid":
            out["turns"] = float(len(turns))
            out["completed"] = float(bool(session["completion"]) and session["completion"]["reason"] == "knowledge_threshold")
        out["teacher_words"] = statistics.mean(len(t["teacher"].split()) for t in turns)
    targeted = [t["flaw_targeted"] for t in turns if t.get("flaw_targeted") is not None]
    if targeted:
        out["flaw_targeted"] = statistics.mean(targeted)
        out["flaw_caught"] = float(any(targeted))
        if any(targeted):
            out["detection_delay"] = float(targeted.index(True))
    if session.get("feedback_names_flaw") is not None:
        out["feedback_names_flaw"] = float(session["feedback_names_flaw"])
    return out


def table(title: str, rows: dict[str, list[dict]], metrics: list[str]) -> None:
    print(f"\n### {title}\n\n| | n | " + " | ".join(metrics) + " |\n|---|---:|" + "---:|" * len(metrics))
    for name, values in rows.items():
        cells = [f"{statistics.mean(v[m] for v in values if m in v):.2f}" if any(m in v for v in values) else "-" for m in metrics]
        print(f"| {name} | {len(values)} | " + " | ".join(cells) + " |")


def wilcoxon_p(diffs: list[float]) -> float:
    """Two-sided Wilcoxon signed-rank test, normal approximation with tie correction."""
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks, ties, i = [0.0] * n, 0.0, 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        ties += (j - i + 1) ** 3 - (j - i + 1)
        i = j + 1
    w = sum(r for r, x in zip(ranks, d) if x > 0)
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24 - ties / 48)
    return 1.0 if sigma == 0 else math.erfc(abs(w - n * (n + 1) / 4) / sigma / math.sqrt(2))


def by_lesson(items: list[tuple[str, dict]], metric: str) -> dict[str, float]:
    grouped = defaultdict(list)
    for lesson, values in items:
        if metric in values:
            grouped[lesson].append(values[metric])
    return {lesson: statistics.mean(v) for lesson, v in grouped.items()}


def paired_gap(a: list[tuple[str, dict]], b: list[tuple[str, dict]], metric: str, draws: int = 2000) -> dict | None:
    """RAG minus fine-tuned per lesson: mean, 95% bootstrap over lessons (both sides share
    each draw), Wilcoxon p, and the paired effect size dz = mean / sd of the differences."""
    left, right = by_lesson(a, metric), by_lesson(b, metric)
    diffs = [right[i] - left[i] for i in sorted(set(left) & set(right))]
    if len(diffs) < 2:
        return None
    rng = random.Random(0)
    boot = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(draws))
    sd = statistics.stdev(diffs)
    return {"gap": statistics.mean(diffs), "lo": boot[int(draws * 0.025)], "hi": boot[int(draws * 0.975)],
            "p": wilcoxon_p(diffs), "dz": statistics.mean(diffs) / sd if sd else 0.0, "n": len(diffs)}


def holm(ps: dict[str, float]) -> dict[str, float]:
    adjusted, running = {}, 0.0
    for rank, (key, p) in enumerate(sorted(ps.items(), key=lambda kv: kv[1])):
        running = max(running, min(1.0, p * (len(ps) - rank)))
        adjusted[key] = running
    return adjusted


def gap_table(title: str, comparisons: list[tuple[str, list, list]], metrics: list[str]) -> None:
    """One row per metric, one column per comparison. p is Holm-adjusted within each column."""
    cols = {name: {m: paired_gap(ft, rag, m) for m in metrics} for name, ft, rag in comparisons if ft and rag}
    if not cols:
        return
    adjusted = {name: holm({m: g["p"] for m, g in col.items() if g}) for name, col in cols.items()}
    print(f"\n### {title}\n\nRAG minus fine-tuned per lesson: gap [95% CI] · Holm-adjusted Wilcoxon p · effect size dz\n")
    print("| metric | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols))
    for m in metrics:
        cells = [f"{g['gap']:+.2f} [{g['lo']:+.2f}, {g['hi']:+.2f}] p={adjusted[name][m]:.3f} dz={g['dz']:+.2f}" if (g := cols[name][m]) else "-" for name in cols]
        print(f"| {m} | " + " | ".join(cells) + " |")


def phrasing(sessions: list[dict]) -> None:
    """Per model, across all its sessions: how formulaic its wording is."""
    print("\n### Phrasing, per model across all sessions\n\n| | replies | template_rate | top opening | distinct_2 |\n|---|---:|---:|---|---:|")
    by_model = defaultdict(list)
    for s in sessions:
        by_model[f"{s['system']} · {s['model']}"] += [t["learner"]["text"] for t in s["turns"] if t["learner"]["kind"] != "invalid"]
    for name, texts in sorted(by_model.items()):
        if not texts:
            continue
        top, count = Counter(" ".join(t.lower().split()[:3]) for t in texts).most_common(1)[0]
        pairs = [b for t in texts for b in zip(t.lower().split(), t.lower().split()[1:])]
        print(f"| {name} | {len(texts)} | {count / len(texts):.2f} | {top} | {len(set(pairs)) / max(1, len(pairs)):.2f} |")


def contrasts(measured: list[tuple[dict, dict]]) -> list[tuple[dict, dict]]:
    """Per system, model and lesson: how the sessions change when the teaching gets worse
    (flawed minus accurate teacher), and net flaw detection (challenges on flawed turns minus
    challenges on clean ones). These are the T2L contrasts, one value per lesson."""
    cells = defaultdict(lambda: defaultdict(list))
    for s, v in measured:
        cells[(s["system"], s["model"], s["lesson_id"])][s["condition"]].append(v)
    out = []
    for (system, model, lesson), by_condition in cells.items():
        def mean(cond: str, m: str) -> float | None:
            got = [x[m] for x in by_condition.get(cond, []) if m in x]
            return statistics.mean(got) if got else None
        values = {}
        for cond in ("vague", "omit", "error"):
            for m in ("turns", "completed", "elicited_score"):
                bad, good = mean(cond, m), mean("good", m)
                if bad is not None and good is not None:
                    values[f"{cond}_minus_good_{m}"] = bad - good
        pooled = [x for vs in by_condition.values() for x in vs]
        flawed = [x["challenge_when_flawed"] for x in pooled if "challenge_when_flawed" in x]
        clean = [x["challenge_when_clean"] for x in pooled if "challenge_when_clean" in x]
        if flawed and clean:
            values["net_flaw_detection"] = statistics.mean(flawed) - statistics.mean(clean)
        out.append(({"system": system, "model": model, "lesson_id": lesson, "subject": lesson.split("/")[0]}, values))
    return out


# The final score. Each dimension's weight, then its metrics, which count equally within it.
# Every metric goes onto a fixed 0..1 scale, never rescaled to the learners in the run:
# "up" is a rate where higher is better, "down" is 1 - rate, "fewer" is (1 - x) / 2 for a
# contrast in -1..1 that should be negative. Agreed 2026-10-14, before any fine-tuned results were scored.
WEIGHTS = {
    "reliability": (0.10, {"valid": "up", "invalid_turns": "down", "opening_is_question": "up"}),
    "questioning": (0.25, {"productive": "up", "deep_question": "up", "why_how": "up", "builds_on_earlier": "up",
                           "no_question": "down", "repeats": "down", "self_repeat": "down"}),
    "novice_role": (0.15, {"stays_novice": "up", "echo": "down", "distinct_2": "up"}),
    # False alarms weigh on their own: inside flaw catching, a learner that challenges
    # every turn would score well.
    "flaw_catching": (0.20, {"challenge_when_flawed": "up", "flaw_targeted": "up", "flaw_caught": "up", "detection_speed": "up"}),
    "no_false_alarms": (0.15, {"challenge_when_clean": "down"}),
    "responds_to_teaching": (0.15, {"good_completed": "up", "vague_minus_good_completed": "fewer",
                                    "omit_minus_good_completed": "fewer", "error_minus_good_completed": "fewer"}),
}
UNSCORED = {
    "learner_words, length_ratio, turns": "no direction is better",
    "teacher_words, key_points_covered": "measure the simulated teacher",
    "learner_seconds": "measures hardware: an API from a laptop against a local GPU",
    "elicited_score, elicited_level, grade_trend, *_minus_good_elicited_score": "grade the teacher's answers",
    "*_minus_good_turns": "the same reaction as the completion contrasts",
    "net_flaw_detection": "both of its parts are scored",
    "detection_delay": "scored as detection_speed, which also counts flaws never caught",
    "feedback_names_flaw": "written by the one shared judge, not by either system",
}
SCALE = {"up": lambda x: x, "down": lambda x: 1 - x, "fewer": lambda x: (1 - x) / 2}


def learner_cells(measured: list[tuple[dict, dict]], derived: list[tuple[dict, dict]], max_turns: int = 6) -> dict:
    """learner -> lesson -> metric: session values pooled over teacher types, completion
    under the accurate teacher only, plus that lesson's teaching contrasts."""
    pooled = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for s, v in measured:
        cell = pooled[f"{s['system']} · {s['model']}"][s["lesson_id"]]
        for m, x in v.items():
            cell[m].append(x)
        if "flaw_caught" in v:
            # A flaw never caught counts as the slowest catch, not as a missing value.
            cell["detection_speed"].append(1 - v["detection_delay"] / (max_turns - 1) if v["flaw_caught"] else 0.0)
        if s["condition"] == "good" and "completed" in v:
            cell["good_completed"].append(v["completed"])
    cells = {who: {lesson: {m: statistics.mean(x) for m, x in ms.items()} for lesson, ms in lessons.items()} for who, lessons in pooled.items()}
    for s, v in derived:
        cells.setdefault(f"{s['system']} · {s['model']}", {}).setdefault(s["lesson_id"], {}).update(v)
    return cells


def final_score(lessons: dict, sample: list[str], weights: dict) -> tuple[float, dict[str, float]]:
    """0-100 for one learner over the sampled lessons. A metric is averaged over the lessons
    that have it; a dimension or metric with no values drops out and the rest are reweighted."""
    dims = {}
    for dim, (_, metrics) in weights.items():
        got = []
        for m, kind in metrics.items():
            xs = [lessons[i][m] for i in sample if m in lessons.get(i, {})]
            if xs:
                got.append(min(1.0, max(0.0, SCALE[kind](statistics.mean(xs)))))
        if got:
            dims[dim] = 100 * statistics.mean(got)
    total = sum(weights[d][0] for d in dims)
    return (sum(weights[d][0] * x for d, x in dims.items()) / total if total else float("nan")), dims


def composite(cells: dict, draws: int = 1000) -> None:
    print("\n### Final score: weights\n\n| dimension | weight | metrics (scale) |\n|---|---:|---|")
    for dim, (w, metrics) in WEIGHTS.items():
        print(f"| {dim} | {w:.0%} | " + ", ".join(f"{m} ({k})" for m, k in metrics.items()) + " |")
    print("\nNot scored, reported only: " + "; ".join(f"{m} ({why})" for m, why in UNSCORED.items()))
    learners = sorted(cells)
    lessons = sorted({i for c in cells.values() for i in c})
    scored = {m for _, ms in WEIGHTS.values() for m in ms}
    have = {who: {m for c in cells[who].values() for m in c} & scored for who in learners}
    for who in learners:
        if missing := set.union(*have.values()) - have[who]:
            print(f"\n**Warning:** {who} has no {', '.join(sorted(missing))}; its score reweights the rest.")
    equal = {d: (1 / len(WEIGHTS), ms) for d, (_, ms) in WEIGHTS.items()}
    drop = {d: {k: v for k, v in WEIGHTS.items() if k != d} for d in WEIGHTS}
    # The same lesson draws for every learner, so the comparisons stay paired.
    rng = random.Random(0)
    boot = defaultdict(list)
    for _ in range(draws):
        sample = rng.choices(lessons, k=len(lessons))
        got = {who: final_score(cells[who], sample, WEIGHTS)[0] for who in learners}
        best = max(got, key=got.get)
        for who, x in got.items():
            boot[who].append(x)
            boot[who + " first"].append(float(who == best))
    def ci(xs: list[float]) -> tuple[float, float]:
        # A draw holding none of a learner's lessons has no score.
        xs = sorted(x for x in xs if x == x)
        return (xs[int(len(xs) * 0.025)], xs[int(len(xs) * 0.975)]) if xs else (float("nan"), float("nan"))
    rank = lambda weights: {who: r for r, who in enumerate(sorted(learners, key=lambda w: -final_score(cells[w], lessons, weights)[0]), 1)}  # noqa: E731
    main, flat, without = rank(WEIGHTS), rank(equal), {d: rank(w) for d, w in drop.items()}
    print("\n### Final score, 0-100, by learner\n\n95% CI from resampling the lessons; rank under equal dimension weights; "
          "rank with each dimension left out\n")
    print("| learner | score [95% CI] | P(first) | " + " | ".join(WEIGHTS) + " | rank | equal-weight rank | ranks leaving one out |")
    print("|---|---|---:|" + "---:|" * len(WEIGHTS) + "---:|---:|---|")
    for who in sorted(learners, key=main.get):
        total, dims = final_score(cells[who], lessons, WEIGHTS)
        lo, hi = ci(boot[who])
        print(f"| {who} | {total:.1f} [{lo:.1f}, {hi:.1f}] | {statistics.mean(boot[who + ' first']):.2f} | "
              + " | ".join(f"{dims[d]:.1f}" if d in dims else "-" for d in WEIGHTS)
              + f" | {main[who]} | {flat[who]} | " + " ".join(str(without[d][who]) for d in WEIGHTS) + " |")
    gaps = [(f"{a} vs {b}", f"ft · {a}", f"rag · {b}") for a, b in PAIRS.items() if f"ft · {a}" in cells and f"rag · {b}" in cells]
    if gaps:
        print("\n### Final score: RAG minus fine-tuned, same base model\n\n| pair | gap [95% CI] |\n|---|---|")
        for name, ft, rag in gaps:
            diffs = [r - f for r, f in zip(boot[rag], boot[ft])]
            lo, hi = ci(diffs)
            print(f"| {name} | {final_score(cells[rag], lessons, WEIGHTS)[0] - final_score(cells[ft], lessons, WEIGHTS)[0]:+.1f} [{lo:+.1f}, {hi:+.1f}] |")
        diffs = [statistics.mean(boot[r][k] - boot[f][k] for _, f, r in gaps) for k in range(draws)]
        lo, hi = ci(diffs)
        point = statistics.mean(final_score(cells[r], lessons, WEIGHTS)[0] - final_score(cells[f], lessons, WEIGHTS)[0] for _, f, r in gaps)
        print(f"| mean of the {len(gaps)} pairs | {point:+.1f} [{lo:+.1f}, {hi:+.1f}] |")


def comparisons_for(rows: list[tuple[dict, dict]]) -> list[tuple[str, list, list]]:
    side = lambda system, model=None: [(s["lesson_id"], v) for s, v in rows if s["system"] == system and model in (None, s["model"])]  # noqa: E731
    deployed = [(s["lesson_id"], v) for s, v in rows if s["system"] == "ft" and DEPLOYED.get(s["subject"]) == s["model"]]
    return [("every model", side("ft"), side("rag")), ("as deployed", deployed, side("rag", "openai/gpt-6.1-sol")),
            *[(f"{a} vs {b}", side("ft", a), side("rag", b)) for a, b in PAIRS.items()]]


def score(paths: list[str], force: bool = False) -> None:
    files = [json.loads(Path(path).read_text()) for path in paths]
    for field in ("teacher_model", "judge_model", "lessons_version", "results_are_fake"):
        seen = {str(f["meta"][field]) for f in files}
        if (len(seen) > 1 or (field == "results_are_fake" and "True" in seen)) and not force:
            sys.exit(f"these runs are not comparable: {field} = {sorted(seen)}. Pass --force to score them anyway.")
    for f in files:
        if f["meta"].get("unreviewed_lessons"):
            print(f"**Warning:** {f['meta']['system']} ran {len(f['meta']['unreviewed_lessons'])} unreviewed lessons.")
    sessions = [s for f in files for s in f["sessions"]]
    measured = [(s, measure(s)) for s in sessions]
    metrics = sorted({m for _, v in measured for m in v}, key=lambda m: (m != "valid", m))
    for condition in sorted({s["condition"] for s in sessions}):
        chosen = [(s, v) for s, v in measured if s["condition"] == condition]
        group = lambda keyfn: {k: [v for s, v in chosen if keyfn(s) == k] for k in sorted({keyfn(s) for s, _ in chosen})}  # noqa: E731
        # Not like for like: each side's mix holds models the other has no counterpart for.
        table(f"{condition}: every model in the run, pooled", group(lambda s: s["system"]), metrics)
        table(f"{condition}: by model", group(lambda s: f"{s['system']} · {s['model']}"), metrics)
        if len({s["lang"] for s, _ in chosen}) > 1:
            table(f"{condition}: by language", group(lambda s: f"{s['system']} · {s['lang']}"), metrics)
        gap_table(f"{condition}: RAG minus fine-tuned", comparisons_for(chosen), metrics)
    derived = contrasts([(s, v) for s, v in measured if v.get("valid")])
    names = sorted({m for _, v in derived for m in v})
    if names:
        models = sorted({f"{s['system']} · {s['model']}" for s, _ in derived})
        table("Teaching contrasts, by model", {k: [v for s, v in derived if f"{s['system']} · {s['model']}" == k] for k in models}, names)
        gap_table("Teaching contrasts: RAG minus fine-tuned", comparisons_for(derived), names)
    composite(learner_cells(measured, derived))
    phrasing(sessions)
    by_cell = defaultdict(list)
    for s in sessions:
        # Scripted only: a simulated teacher answers each learner differently, so across
        # languages it is no longer the same teaching.
        if not s["error"] and s["condition"] == "scripted":
            by_cell[(s["system"], s["model"], s["lesson_id"], s["condition"], s["repeat"])].append(str(s["completion"]))
    spread = defaultdict(list)
    for (system, *_), outcomes in by_cell.items():
        if len(outcomes) > 1:
            spread[system].append(Counter(outcomes).most_common(1)[0][1] / len(outcomes))
    for system, values in spread.items():
        print(f"\n{system}: the same teaching gets the modal completion decision in {statistics.mean(values):.0%} of languages ({len(values)} cells)")


# ------------------------------------------------------------------ self-check


def selfcheck() -> None:
    """Runs the whole loop against a stub learner and a stub OpenRouter, so it costs nothing."""
    global openrouter
    sys.path.insert(0, str(HERE / "teach2learn-portal"))
    from app.services.completion import decide_completion
    from app.services.inference import parse_inline_evaluation

    prompts = portal_prompts(HERE / "teach2learn-portal" / "app" / "main.py")
    assert {"STUDENT_PROMPT", "FORK_SYSTEM_PROMPT", "QUESTION_BRANCH", "TURN_EVALUATOR_PROMPT", "FINAL_EVALUATOR_PROMPT", "OPENING"} <= set(prompts)

    class Stub:
        name, decide = "ft", staticmethod(decide_completion)
        replies = ["How does the heap stay ordered after a removal?", "How does the heap stay ordered after a removal?", "I think I got it."]
        def start(self, model, lesson): self.n = 0
        async def opening(self, model, lesson): return {"text": "Hi! What is a heap?", "kind": "question"}
        async def reply(self, model, lesson, history, teacher):
            if self.n == getattr(self, "break_at", None):
                raise ValueError("not JSON")
            text = self.replies[self.n % 3]; self.n += 1
            return {"text": text, "kind": "question" if "?" in text else "reflection"}

    async def fake_openrouter(client, model, system, user, **extra):
        if "turn evaluator" in system:
            return "<evaluation>\nLevel: Apply\nScore: High\nStrength: clear\nImprovement: add an example\n</evaluation>"
        if "label one reply" in system:
            return f"Relevant: yes\nBuilds: no\nRepeat: {'yes' if user.count(user.rsplit(': ', 1)[1]) > 1 else 'no'}\nNovice: yes\nDepth: deep\nChallenges: no"
        if "Verdict" in system:
            return "Verdict: yes"
        if "final teaching evaluator" in system:
            return "<final_feedback>Strength: a\nStrength: b\nImprovement: c\nImprovement: d\nSummary: e</final_feedback>"
        return "Answer: A heap keeps the smallest item at the root after every removal.\nFlaw: said nothing about sifting down"

    real, openrouter = openrouter, fake_openrouter
    try:
        lesson = {"id": "dsa/x", "subject": "dsa", "subtopic": "Heaps", "script": ["A heap is a tree.", "The root is the smallest item.", "Removal sifts down."]}
        ctx = {"client": None, "prompts": prompts, "teacher_model": "t", "no_judge": False, "max_turns": 6, "translator": None,
               "parse_evaluation": parse_inline_evaluation}
        key = {"model": "m", "lesson_id": "dsa/x", "lang": "en", "repeat": 0}
        sim = asyncio.run(run_session(Stub(), ctx, {**key, "condition": "error"}, lesson))
        scripted = asyncio.run(run_session(Stub(), ctx, {**key, "condition": "scripted"}, lesson))
        Stub.break_at = 1
        broken = asyncio.run(run_session(Stub(), ctx, {**key, "condition": "scripted"}, lesson))
    finally:
        openrouter = real
    assert sim["error"] is None and scripted["error"] is None, (sim["error"], scripted["error"])
    # Two High/Apply turns satisfy the rule at the minimum of three turns, on either teacher.
    assert sim["completion"] == {"turn": 3, "reason": "knowledge_threshold"}, sim["completion"]
    assert sim["feedback_names_flaw"] is True and sim["turns"][0]["flaw_targeted"] is True
    assert len(scripted["turns"]) == 3 and scripted["turns"][0]["teacher"] == "A heap is a tree."
    assert [t["labels"]["repeat"] for t in scripted["turns"]] == ["no", "yes", "no"]
    got = measure(sim)
    assert got["completed"] == 1.0 and got["elicited_score"] == 2.0, got
    # Turn 1 is a fresh question, turn 2 repeats it, turn 3 is a reflection.
    assert abs(got["productive"] - 1 / 3) < 1e-9 and abs(got["repeats"] - 1 / 3) < 1e-9 and abs(got["no_question"] - 1 / 3) < 1e-9, got
    assert measure({**sim, "error": "x"}) == {"valid": 0.0}
    # Text metrics: the second question copies the first; the teacher's answer covers two of three points.
    assert abs(got["self_repeat"] - 0.6) < 1e-9 and abs(got["key_points_covered"] - 2 / 3) < 1e-9, got
    assert got["challenge_when_flawed"] == 0.0 and "challenge_when_clean" not in got and got["detection_delay"] == 0.0, got
    assert "learner_seconds" in got and 0 < got["echo"] <= 1 and 0 < got["distinct_2"] <= 1, got
    derived = contrasts([(sim, got), ({**sim, "condition": "good"}, got)])
    assert derived[0][1]["error_minus_good_turns"] == 0.0, derived
    # Final score: a learner perfect on every scored metric gets 100, its opposite 0, and
    # a flaw caught at the first chance counts as the fastest catch.
    best = {m: 1.0 if k == "up" else 0.0 for _, ms in WEIGHTS.values() for m, k in ms.items()}
    best.update({m: -1.0 for m, k in best.items() if WEIGHTS["responds_to_teaching"][1].get(m) == "fewer"})
    worst = {m: (1.0 if x == 0.0 else 0.0) if x >= 0 else 1.0 for m, x in best.items()}
    assert final_score({"l": best}, ["l"], WEIGHTS)[0] == 100 and final_score({"l": worst}, ["l"], WEIGHTS)[0] == 0
    assert "completed" not in measure({**broken, "condition": "error"}) and "turns" not in measure({**broken, "condition": "error"})
    cells = learner_cells([(sim, got), ({**sim, "condition": "good"}, got)], derived)
    assert cells["ft · m"]["dsa/x"]["detection_speed"] == 1.0 and cells["ft · m"]["dsa/x"]["good_completed"] == 1.0, cells
    assert wilcoxon_p(list(range(1, 11))) < 0.01 and wilcoxon_p([-1, 1] * 5) == 1.0
    assert holm({"a": 0.01, "b": 0.04}) == {"a": 0.02, "b": 0.04}
    # A learner that breaks at turn 2 keeps turn 1 and is charged one invalid turn.
    assert broken["error"] is None and [t["learner"]["kind"] for t in broken["turns"]] == ["question", "invalid"]
    assert measure(broken)["valid"] == 1.0 and measure(broken)["invalid_turns"] == 0.5
    assert sim["turns"][0]["judge_raw"].startswith("<evaluation>")
    assert fields("Level: Apply\nscore: High", "level", "score") == {"level": ["Apply"], "score": ["High"]}
    print("selfcheck ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--system", choices=["ft", "rag"], required=True)
    r.add_argument("--models", default="common", help="comma-separated; 'common' for the base models both sides offer; 'all' for every learner this side offers")
    r.add_argument("--conditions", default="good", help="any of: " + ",".join(SIM_STYLES) + "; or scripted (fixed lesson lines, no teacher model)")
    r.add_argument("--teacher-model", default=TEACHER_MODEL, help="OpenRouter id of the simulated teacher")
    r.add_argument("--subject")
    r.add_argument("--lesson")
    r.add_argument("--languages", default="en", help="comma-separated codes, or 'all' for every language the system offers")
    r.add_argument("--repeat", type=int, default=1)
    r.add_argument("--max-turns", type=int, default=6)
    r.add_argument("--temperature", type=float, help="RAG learner only, default as deployed (models.STUDENT_TEMPERATURE); the portal reads INFERENCE_TEMPERATURE")
    r.add_argument("--top-p", type=float, help="RAG learner only, default as deployed (models.STUDENT_TOP_P)")
    r.add_argument("--rag-extra-body", help="JSON merged into every RAG learner request, e.g. to pin a provider or switch off thinking")
    r.add_argument("--root", help="the system's own directory, if not the checkout's")
    r.add_argument("--portal-main", default=str(HERE / "teach2learn-portal" / "app" / "main.py"))
    r.add_argument("--lessons")
    r.add_argument("--out")
    r.add_argument("--no-judge", action="store_true")
    r.add_argument("--allow-fake", action="store_true")
    r.add_argument("--allow-unreviewed", action="store_true", help="run lessons nobody has accepted yet; the run file lists them")
    s = sub.add_parser("score")
    s.add_argument("files", nargs="+")
    s.add_argument("--force", action="store_true", help="score runs whose teacher, judge or lesson bank differ, or fake runs")
    p = sub.add_parser("pack", help="print this program with lessons.json embedded, for piping to the GPU host")
    p.add_argument("--lessons", default=str(HERE / LESSONS))
    sub.add_parser("selfcheck")
    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(run(args))
    elif args.command == "score":
        score(args.files, args.force)
    elif args.command == "pack":
        bank = json.loads(Path(args.lessons).read_text())
        print(Path(__file__).read_text().replace("PACKED_LESSONS = None", f"PACKED_LESSONS = {bank!r}", 1))
    else:
        selfcheck()


if __name__ == "__main__":
    main()
