from __future__ import annotations

import logging
import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import uvicorn
import httpx
from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth import GoogleAuthConfig, build_oauth
from app.config import Settings, configure_logging
from app.db import Database
from app.services.completion import MAX_TURNS, MIN_TURNS, completion_message, decide_completion
from app.services.inference import (
    InferenceBusyError,
    InferenceQueueTimeoutError,
    get_inference_service,
    parse_inline_evaluation,
)
from app.services.study_evaluator import evaluate_conversation
from app.services.teaching_feedback import build_teaching_feedback, parse_final_teaching_feedback
from app.services.transcription import TranscriptionUnavailableError, get_transcription_service
from app.services.transcripts import TranscriptStore
from app.services.translation import (
    SUPPORTED_LANGUAGES,
    get_translation_service,
    normalize_language,
)
from app.survey import (
    BACKGROUND_PROMPT,
    INSTRUMENT_ID,
    LIKERT_SCALE,
    QUALITATIVE_QUESTIONS,
    QUANTITATIVE_SECTIONS,
    parse_hci_student_survey,
)
from app.topics import MODELS, TOPICS, subjects, topic_selection


STUDENT_PROMPT = """You are a curious beginner learning from a human teacher. The human is the teacher and you are
the learner. Ask exactly one concise, natural question that exposes a gap, requests an example, or deepens the idea.
Stay within the selected topic, do not evaluate the teacher, and never reverse roles."""

FORK_SYSTEM_PROMPT = """You process one branch of a teaching interaction. The visible conversation contains an AI
learner's questions and a human teacher's answers. Follow only the final [Branch task]. Never include content from one
branch in another branch's output."""

QUESTION_BRANCH = """Act as the curious beginner learner. Ask exactly one concise, natural follow-up question about
the selected topic. Expose a gap, request an example, or deepen the idea. Do not evaluate the teacher or reverse roles."""

TURN_EVALUATOR_PROMPT = """You are an independent turn evaluator in a fresh chat. Evaluate only the supplied learner
question and teacher answer. Return exactly one <evaluation> block with four single-line fields: Level (Remember,
Understand, Apply, Analyze, Evaluate, or Create), Score (Low, Medium, or High), Strength, and Improvement. Be specific,
constructive, and grounded in the supplied answer. Do not ask a follow-up question."""

FINAL_EVALUATOR_PROMPT = """You are an independent final teaching evaluator in a fresh chat. Review only the supplied
visible conversation. Produce constructive participant-facing feedback grounded in what the teacher actually said.
Return exactly one <final_feedback> block containing two single-line Strength fields, two single-line Improvement
fields, and one single-line Summary field. Address the teacher as 'you'. Do not invent student reactions, grades,
personal details, or facts absent from the conversation."""

settings = Settings.from_env()
configure_logging(settings)
logger = logging.getLogger("teach2learn")
database = Database(settings.database_path)
transcripts = TranscriptStore(settings.transcript_dir, database)
google_auth = GoogleAuthConfig.from_env()
oauth = build_oauth(google_auth)
session_socket_locks: dict[str, asyncio.Lock] = {}
final_feedback_tasks: dict[str, asyncio.Task] = {}
IS_PRODUCTION = os.getenv("APP_ENV", "development") == "production"
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://learnbyteaching.sasanktumpati.com").rstrip("/")
# Lets one FastAPI process live at a URL subpath behind a shared reverse proxy
# (e.g. multiple independent deployments on one domain). Every route below is
# registered on `router` with this prefix rather than directly on `app`, so
# url_for()-generated links (static assets, the OAuth callback) get it automatically;
# literal RedirectResponse paths and template hrefs are prefixed by hand instead,
# since Starlette has no way to rewrite a string it didn't generate.
BASE_PATH = os.getenv("T2L_BASE_PATH", "").rstrip("/")
if BASE_PATH and not BASE_PATH.startswith("/"):
    BASE_PATH = f"/{BASE_PATH}"
MAX_REQUEST_BYTES = max(1024, int(os.getenv("MAX_REQUEST_BYTES", str(256 * 1024))))
# Voice recordings are audio, not JSON/form bodies, so they get their own much
# larger ceiling; ~2 minutes of compressed webm/opus comfortably fits in 15 MB.
MAX_AUDIO_BYTES = max(MAX_REQUEST_BYTES, int(os.getenv("MAX_AUDIO_BYTES", str(15 * 1024 * 1024))))
APP_NAME = os.getenv("APP_NAME", "EquitableT2L").strip() or "EquitableT2L"
ADMIN_EMAILS = tuple(
    item.strip().lower()
    for item in os.getenv(
        "ADMIN_EMAILS",
        "f20230309@pilani.bits-pilani.ac.in,f20230985@pilani.bits-pilani.ac.in",
    ).split(",")
    if item.strip()
)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
FINAL_FEEDBACK_MODEL = os.getenv("FINAL_FEEDBACK_MODEL", "openai/gpt-5.6-luna").strip()
FINAL_FEEDBACK_REASONING_EFFORT = os.getenv("FINAL_FEEDBACK_REASONING_EFFORT", "high").strip().lower()
OPENROUTER_TIMEOUT_SECONDS = max(10.0, float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "90")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    if IS_PRODUCTION:
        secret_key = os.getenv("SECRET_KEY", "local-development-change-me")
        if secret_key == "local-development-change-me" or len(secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be unique and at least 32 characters in production")
        if not google_auth.enabled or not google_auth.allowed_domains:
            raise RuntimeError("Google OAuth and GOOGLE_ALLOWED_DOMAINS are required in production")
    settings.ensure_directories()
    database.initialize()
    transcript_sync = transcripts.synchronize()
    storage_report = database.storage_report()
    mirror_report = transcripts.mirror_report()
    if storage_report["status"] != "ok" or mirror_report["status"] != "ok":
        raise RuntimeError(
            f"storage integrity check failed: database={storage_report} mirrors={mirror_report}"
        )
    logger.info(
        "storage_ready sessions=%s messages=%s imported_messages=%s",
        storage_report["counts"]["sessions"],
        storage_report["counts"]["messages"],
        transcript_sync["imported_messages"],
    )
    logger.info("portal_started backend=%s database=%s", os.getenv("INFERENCE_BACKEND", "fake"), settings.database_path)
    service = get_inference_service()
    await service.check_ready()
    preload_task = asyncio.create_task(service.preload_all()) if service.config.preload_models else None
    if preload_task:
        def log_preload_result(task: asyncio.Task) -> None:
            try:
                task.result()
                logger.info("model_preload_completed loaded_models=%s", service.status()["loaded_models"])
            except Exception:
                logger.exception("model_preload_failed")

        preload_task.add_done_callback(log_preload_result)
    yield
    if preload_task:
        try:
            await preload_task
        except Exception:
            logger.exception("model_preload_failed")
    if final_feedback_tasks:
        await asyncio.gather(*list(final_feedback_tasks.values()), return_exceptions=True)
    await service.unload_all()
    await get_translation_service().close()
    logger.info("portal_stopped")


app = FastAPI(
    title=APP_NAME,
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
trusted_hosts = [
    item.strip()
    for item in os.getenv(
        "TRUSTED_HOSTS",
        "learnbyteaching.sasanktumpati.com,localhost,127.0.0.1",
    ).split(",")
    if item.strip()
]
if not IS_PRODUCTION:
    trusted_hosts.append("testserver")
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=trusted_hosts,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "local-development-change-me"),
    session_cookie=os.getenv("SESSION_COOKIE_NAME", "__Host-t2l_session" if IS_PRODUCTION else "session"),
    same_site="lax",
    https_only=IS_PRODUCTION,
    max_age=max(900, int(os.getenv("SESSION_MAX_AGE_SECONDS", "43200"))),
)
app.mount(f"{BASE_PATH}/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix=BASE_PATH)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    content_length = request.headers.get("content-length")
    size_limit = MAX_AUDIO_BYTES if request.url.path == f"{BASE_PATH}/api/transcribe" else MAX_REQUEST_BYTES
    if content_length:
        try:
            too_large = int(content_length) > size_limit
        except ValueError:
            too_large = True
    else:
        too_large = False

    if too_large:
        response = JSONResponse({"detail": "Request body is too large."}, status_code=413)
    elif IS_PRODUCTION and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin", "").rstrip("/") != PUBLIC_ORIGIN:
            response = JSONResponse({"detail": "Cross-origin request rejected."}, status_code=403)
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'; object-src 'none'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self' wss:; "
        "img-src 'self' data:; font-src 'self'"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    return response


def eligible_participant(participant_id: str | None) -> dict | None:
    participant = database.get_participant(participant_id) if participant_id else None
    if not participant:
        return None
    metadata = participant["metadata"]
    if metadata.get("auth_provider") != "google" or not google_auth.allows_user(
        str(metadata.get("email", "")),
        str(metadata.get("hosted_domain", "")),
    ):
        return None
    return {**participant, "name": participant["metadata"].get("name", participant["external_id"])}


def participant_for(request: Request) -> dict | None:
    return eligible_participant(request.session.get("participant_id"))


def is_admin(participant: dict | None) -> bool:
    if not participant:
        return False
    email = str(participant.get("metadata", {}).get("email", "")).strip().lower()
    return any(secrets.compare_digest(email, allowed) for allowed in ADMIN_EMAILS)


def admin_for(request: Request) -> dict | None:
    participant = participant_for(request)
    return participant if is_admin(participant) else None


def language_for(session: dict) -> str:
    """Return the participant-chosen language code stored in session metadata."""
    return normalize_language(session.get("metadata", {}).get("lang"))


def teacher_gender_for(session: dict) -> str | None:
    """Return the participant-chosen gender stored in session metadata -- used to
    grammatically address the teacher correctly both in their final feedback and in
    the AI's own mid-conversation dialogue, which is almost always a question
    addressed to them ("Can *you* give me an example?")."""
    gender = session.get("metadata", {}).get("teacher_gender")
    return gender if gender in {"Male", "Female"} else None


async def localized_messages(
    messages: list[dict[str, Any]], lang: str, teacher_gender: str | None = None
) -> list[dict[str, Any]]:
    """Render stored English transcript text in the participant's language.

    Only the AI student's own turns get a speaker_gender hint -- the teacher's own
    turns are re-translated here too when history is redisplayed, and guessing a
    gender for the teacher's own words would be putting words in their mouth.

    That hint is the teacher's own stated gender, not a fixed persona gender: the
    AI's dialogue is almost always a question addressed to the teacher ("Can *you*
    give me an example?"), so the gender-sensitive clause in these sentences is
    usually about the teacher being addressed, not the AI itself.
    """
    if lang == "en":
        return messages
    translator = get_translation_service()
    contents = await asyncio.gather(
        *(
            translator.from_english(
                str(item.get("content", "")),
                lang,
                speaker_gender=teacher_gender if item.get("role") == "assistant" else None,
            )
            for item in messages
        )
    )
    return [{**item, "content": text} for item, text in zip(messages, contents)]


async def localized_feedback(
    feedback: dict[str, Any] | None, lang: str, teacher_gender: str | None = None
) -> dict[str, Any] | None:
    """Translate the participant-facing feedback fields only.

    This feedback addresses the teacher directly as "you", so -- unlike localized_messages,
    which deliberately never guesses the teacher's gender -- a real gender hint belongs
    here. It's the participant's own stated gender (collected at session start), not a
    guess, so it doesn't fall under that same restriction."""
    if lang == "en" or not feedback:
        return feedback
    translator = get_translation_service()
    strengths, improvements, summary = await asyncio.gather(
        translator.all_from_english([str(item) for item in feedback.get("strengths", [])], lang, speaker_gender=teacher_gender),
        translator.all_from_english([str(item) for item in feedback.get("improvements", [])], lang, speaker_gender=teacher_gender),
        translator.from_english(str(feedback.get("summary", "")), lang, speaker_gender=teacher_gender),
    )
    return {**feedback, "strengths": strengths, "improvements": improvements, "summary": summary}


def render(request: Request, template: str, **context):
    participant = participant_for(request)
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "participant": participant,
            "is_admin": is_admin(participant),
            "base_path": BASE_PATH,
            "min_turns": MIN_TURNS,
            "max_turns": MAX_TURNS,
            "google_oauth_enabled": google_auth.enabled,
            "app_name": APP_NAME,
            "student_questionnaire_enabled": settings.student_questionnaire_enabled,
            "supported_languages": SUPPORTED_LANGUAGES,
            "default_language": normalize_language(settings.default_language),
            **context,
        },
    )


def session_view(session: dict) -> dict:
    metadata = session.get("metadata", {})
    started_at = session.get("started_at", "")
    try:
        created_label = datetime.fromisoformat(started_at).strftime("%d %b %Y, %H:%M")
    except ValueError:
        created_label = started_at
    return {
        **session,
        **metadata,
        "created_at": started_at,
        "created_label": created_label,
        "turn": int(metadata.get("turn", 0)),
        "lang": normalize_language(metadata.get("lang")),
    }


def admin_turn_views(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair each teacher answer with the question it answered and its hidden evaluation."""
    turns: list[dict[str, Any]] = []
    previous_question: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    for message in messages:
        if message.get("role") == "user":
            current = {
                "number": int(message.get("turn", 0)),
                "question": previous_question,
                "answer": message,
                "response": None,
                "evaluation": None,
            }
            turns.append(current)
            continue
        if current and int(message.get("turn", 0)) == current["number"]:
            current["response"] = message
            current["evaluation"] = message.get("inline_evaluation")
        previous_question = message
    return turns


def owned_session(participant: dict | None, session_id: str) -> dict | None:
    session = database.get_session(session_id)
    if not participant or not session or session["participant_id"] != participant["id"]:
        return None
    return session


def teaching_feedback_for(session_id: str, result: dict | None = None) -> dict:
    if result and result.get("teaching_feedback"):
        return result["teaching_feedback"]
    return build_teaching_feedback(transcripts.read(session_id))


def visible_transcript_for_evaluator(transcript: list[dict[str, Any]]) -> str:
    lines = []
    for item in transcript:
        role = "Human teacher" if item.get("role") == "user" else "AI learner"
        content = " ".join(str(item.get("content", "")).split())
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)[:24000]


async def generate_openrouter_judgment(
    system_prompt: str,
    user_content: str,
    *,
    max_tokens: int,
) -> tuple[str, dict[str, Any]]:
    """Run an isolated judge through OpenRouter without retaining its reasoning trace."""
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT_SECONDS) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": PUBLIC_ORIGIN,
                "X-Title": APP_NAME,
            },
            json={
                "model": FINAL_FEEDBACK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "reasoning": {
                    "effort": FINAL_FEEDBACK_REASONING_EFFORT,
                    "exclude": True,
                },
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        payload = response.json()
    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        content = "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("text")
        )
    content = str(content).strip()
    if not content:
        raise ValueError("OpenRouter returned empty final feedback")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return content, {
        "provider": "openrouter",
        "model": FINAL_FEEDBACK_MODEL,
        "reasoning_effort": FINAL_FEEDBACK_REASONING_EFFORT,
        "generation_ms": round((time.perf_counter() - started) * 1000),
        "usage": {
            key: usage[key]
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if key in usage
        },
    }


async def generate_openrouter_feedback(transcript_text: str) -> tuple[str, dict[str, Any]]:
    return await generate_openrouter_judgment(
        FINAL_EVALUATOR_PROMPT,
        transcript_text,
        max_tokens=1600,
    )


async def generate_openrouter_turn_evaluation(
    topic: str,
    history: list[dict[str, str]],
) -> tuple[dict[str, str], dict[str, Any]]:
    teacher_answer = history[-1]["content"] if history and history[-1]["role"] == "user" else ""
    learner_question = next(
        (item["content"] for item in reversed(history[:-1]) if item["role"] == "assistant"),
        "",
    )
    user_content = (
        f"Selected topic: {topic}\n"
        f"AI learner question: {learner_question}\n"
        f"Human teacher answer: {teacher_answer}"
    )
    raw_evaluation, metadata = await generate_openrouter_judgment(
        TURN_EVALUATOR_PROMPT,
        user_content,
        max_tokens=1400,
    )
    evaluation = parse_inline_evaluation(raw_evaluation)
    if not evaluation:
        raise ValueError("OpenRouter returned an invalid turn evaluation")
    return evaluation, metadata


async def evaluate_turn(
    session: dict[str, Any],
    history: list[dict[str, str]],
) -> tuple[dict[str, str] | None, int, dict[str, Any]]:
    if OPENROUTER_API_KEY:
        try:
            evaluation, metadata = await generate_openrouter_turn_evaluation(
                session.get("subtopic") or session["subject"],
                history,
            )
            return evaluation, int(metadata["generation_ms"]), metadata
        except Exception as exc:
            logger.warning(
                "openrouter_turn_evaluation_failed session_id=%s error=%s",
                session["id"],
                type(exc).__name__,
            )
            fallback_reason = type(exc).__name__
    else:
        fallback_reason = "not_configured"
    generation = await get_inference_service().generate_detailed(
        session["subject"],
        session["subtopic"],
        messages=history,
        system_prompt=FORK_SYSTEM_PROMPT,
        model=session["metadata"]["model"],
        branch_instruction=TURN_EVALUATOR_PROMPT,
        stop_after_question=False,
        max_new_tokens=144,
    )
    return generation.evaluation, generation.generation_ms, {
        "provider": "local_fallback" if OPENROUTER_API_KEY else "local",
        "model": session["metadata"]["model"],
        "reason": fallback_reason,
    }


async def generate_final_feedback(session: dict, transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate one isolated, session-wide evaluation and persist it with a deterministic fallback."""
    fallback = build_teaching_feedback(transcript)
    baseline = evaluate_conversation(transcript)
    database.set_evaluation(session["id"], "running")
    try:
        transcript_text = visible_transcript_for_evaluator(transcript)
        evaluator: dict[str, Any]
        if OPENROUTER_API_KEY:
            try:
                raw_feedback, evaluator = await generate_openrouter_feedback(transcript_text)
            except Exception as exc:
                logger.warning(
                    "openrouter_final_feedback_failed session_id=%s error=%s",
                    session["id"],
                    type(exc).__name__,
                )
                generation = await get_inference_service().generate_detailed(
                    session["subject"],
                    session.get("subtopic") or session["subject"],
                    messages=[{"role": "user", "content": transcript_text}],
                    system_prompt=FINAL_EVALUATOR_PROMPT,
                    model=session["metadata"].get("model"),
                    transform_history=False,
                    stop_after_question=False,
                    max_new_tokens=320,
                )
                raw_feedback = generation.raw_content
                evaluator = {
                    "provider": "local_fallback",
                    "model": session["metadata"].get("model"),
                    "reason": type(exc).__name__,
                }
        else:
            generation = await get_inference_service().generate_detailed(
                session["subject"],
                session.get("subtopic") or session["subject"],
                messages=[{"role": "user", "content": transcript_text}],
                system_prompt=FINAL_EVALUATOR_PROMPT,
                model=session["metadata"].get("model"),
                transform_history=False,
                stop_after_question=False,
                max_new_tokens=320,
            )
            raw_feedback = generation.raw_content
            evaluator = {
                "provider": "local",
                "model": session["metadata"].get("model"),
            }
        feedback = parse_final_teaching_feedback(raw_feedback, fallback)
        result = {
            **baseline,
            "rubric_version": "independent-final-feedback-v2",
            "evaluator": evaluator,
            "teaching_feedback": feedback,
        }
        database.set_evaluation(session["id"], "completed", result=result)
        return result
    except Exception as exc:
        logger.exception("final_feedback_generation_failed session_id=%s", session["id"])
        result = {
            **baseline,
            "rubric_version": "deterministic-feedback-fallback-v1",
            "teaching_feedback": {**fallback, "generation": "deterministic_fallback"},
        }
        database.set_evaluation(session["id"], "completed", result=result, error=str(exc)[:500])
        return result


async def final_feedback_result(session: dict) -> dict[str, Any]:
    record = database.get_evaluation(session["id"])
    result = record.get("result") if record else None
    feedback = result.get("teaching_feedback") if result else None
    finalized_rubrics = {
        "independent-final-feedback-v1",
        "independent-final-feedback-v2",
        "deterministic-feedback-fallback-v1",
    }
    if feedback and (
        feedback.get("generation") in {"independent_final_evaluator", "hybrid_final_evaluator"}
        or result.get("rubric_version") in finalized_rubrics
    ):
        return result
    task = final_feedback_tasks.get(session["id"])
    if task:
        return await task
    return await generate_final_feedback(session, transcripts.read(session["id"]))


def schedule_final_feedback(session: dict, transcript: list[dict[str, Any]]) -> None:
    if session["id"] in final_feedback_tasks:
        return
    task = asyncio.create_task(generate_final_feedback(session, transcript))
    final_feedback_tasks[session["id"]] = task

    def finished(completed_task: asyncio.Task) -> None:
        if not completed_task.cancelled():
            completed_task.exception()
        final_feedback_tasks.pop(session["id"], None)

    task.add_done_callback(finished)


def complete_page_context(session: dict, result: dict | None = None, **context: Any) -> dict[str, Any]:
    return {
        "session": session_view(session),
        "teaching_feedback": teaching_feedback_for(session["id"], result),
        "likert_scale": LIKERT_SCALE,
        "quantitative_sections": QUANTITATIVE_SECTIONS,
        "background_prompt": BACKGROUND_PROMPT,
        "qualitative_questions": QUALITATIVE_QUESTIONS,
        **context,
    }


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(f"{BASE_PATH}/study" if participant_for(request) else f"{BASE_PATH}/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render(request, "login.html")


@router.get("/auth/google")
async def google_login(request: Request):
    if not google_auth.enabled:
        return render(request, "login.html", error="Google sign-in is not configured." )
    redirect_uri = google_auth.redirect_uri or str(request.url_for("google_auth_callback"))
    hosted_domain = google_auth.allowed_domains[0] if len(google_auth.allowed_domains) == 1 else None
    return await oauth.google.authorize_redirect(request, redirect_uri, hd=hosted_domain)


@router.get("/auth/callback", name="google_auth_callback")
async def google_auth_callback(request: Request):
    if not google_auth.enabled:
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    try:
        token = await oauth.google.authorize_access_token(request)
        user = token.get("userinfo") or await oauth.google.userinfo(token=token)
    except OAuthError:
        logger.exception("google_oauth_failed")
        return render(request, "login.html", error="Google sign-in could not be completed. Please try again.")

    subject = str(user.get("sub", "")).strip()
    email = str(user.get("email", "")).strip().lower()
    hosted_domain = str(user.get("hd", "")).strip().lower()
    name = " ".join(str(user.get("name", "")).strip().split())[:100]
    if not subject or not email or user.get("email_verified") is not True:
        return render(request, "login.html", error="Google did not provide a verified email address.")
    if not google_auth.allows_user(email, hosted_domain):
        logger.warning("google_login_rejected domain=%s hosted_domain=%s", email.rsplit("@", 1)[-1], hosted_domain)
        return render(request, "login.html", error="This Google account is not eligible for the study.")

    participant = database.get_or_create_participant(
        f"google_{subject}",
        name or email.split("@", 1)[0],
        {"email": email, "hosted_domain": hosted_domain, "auth_provider": "google"},
    )
    request.session["participant_id"] = participant["id"]
    logger.info("participant_google_login participant_id=%s", participant["id"])
    return RedirectResponse(f"{BASE_PATH}/study", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(f"{BASE_PATH}/login", status_code=303)


if not IS_PRODUCTION and os.getenv("T2L_DEV_LOGIN_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:

    @router.get("/dev/login")
    async def dev_login(request: Request):
        """Sign in a throwaway local participant so the portal can be exercised without Google."""
        participant = database.get_or_create_participant(
            "dev-local",
            "Local Developer",
            {"email": "dev@localhost", "hosted_domain": "", "auth_provider": "google"},
        )
        request.session["participant_id"] = participant["id"]
        logger.warning("dev_login_used participant_id=%s", participant["id"])
        return RedirectResponse(f"{BASE_PATH}/study", status_code=303)


@router.get("/study", response_class=HTMLResponse)
async def study(request: Request):
    if not participant_for(request):
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    return render(request, "select.html", models=MODELS, subjects=subjects(), taxonomy=TOPICS)


@router.post("/study/start")
async def start_study(
    request: Request,
    model: str = Form(...),
    subject: str = Form(...),
    topic: str = Form(...),
    subtopic: str = Form(...),
    lang: str = Form(default="en"),
    teacher_gender: str = Form(default=""),
):
    participant = participant_for(request)
    if not participant:
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    try:
        topic_name, subtopic_name = topic_selection(subject, topic, subtopic)
        model_name = next(item["name"] for item in MODELS if item["id"] == model)
    except (ValueError, StopIteration):
        return render(request, "select.html", models=MODELS, subjects=subjects(), taxonomy=TOPICS, error="Choose a valid model, subject, topic, and subtopic.")
    try:
        opening = await get_inference_service().generate(
            subject,
            subtopic_name,
            question="The lesson is starting. Introduce yourself briefly and ask your first question only.",
            system_prompt=STUDENT_PROMPT,
            model=model,
        )
    except Exception:
        logger.exception("opening_generation_failed model=%s subject=%s", model, subject)
        return render(
            request,
            "select.html",
            models=MODELS,
            subjects=subjects(),
            taxonomy=TOPICS,
            error="The selected AI learner is temporarily unavailable. Please try starting the session again.",
        )
    session_id = database.create_session(
        participant["id"],
        subject,
        subtopic_name,
        {
            "model": model,
            "model_name": model_name,
            "topic": topic_name,
            "topic_id": topic,
            "turn": 0,
            "study_variant": "hci",
            "lang": normalize_language(lang),
            "teacher_gender": teacher_gender if teacher_gender in {"Male", "Female"} else None,
            "survey_instrument": INSTRUMENT_ID if settings.student_questionnaire_enabled else None,
        },
        opening_message={"role": "assistant", "content": opening, "turn": 0},
    )
    transcripts.sync_session(session_id)
    logger.info("session_started session_id=%s model=%s subject=%s subtopic=%s", session_id, model, subject, subtopic_name)
    return RedirectResponse(f"{BASE_PATH}/sessions/{session_id}", status_code=303)


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_page(request: Request, session_id: str):
    participant = participant_for(request)
    session = owned_session(participant, session_id)
    if not session:
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    if session["status"] == "completed":
        return RedirectResponse(f"{BASE_PATH}/sessions/{session_id}/complete", status_code=303)
    view = session_view(session)
    return render(
        request,
        "chat.html",
        session=view,
        messages=await localized_messages(transcripts.read(session_id), view["lang"], teacher_gender_for(session)),
        turn=view["turn"],
        voice_input_enabled=get_transcription_service().is_enabled(),
    )


@router.post("/api/transcribe")
async def transcribe_audio(
    request: Request,
    session_id: str = Form(...),
    audio: UploadFile = File(...),
):
    session = owned_session(participant_for(request), session_id)
    if not session:
        return JSONResponse({"detail": "This session is unavailable."}, status_code=404)
    if session["status"] != "active":
        return JSONResponse({"detail": "This session is already complete."}, status_code=400)

    audio_bytes = await audio.read()
    if not audio_bytes:
        return JSONResponse({"detail": "No audio received."}, status_code=400)
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return JSONResponse({"detail": "That recording is too long."}, status_code=413)

    transcriber = get_transcription_service()
    try:
        text = await transcriber.transcribe(
            audio_bytes,
            audio.filename or "recording.webm",
            audio.content_type or "audio/webm",
            language_for(session),
        )
    except TranscriptionUnavailableError:
        return JSONResponse({"detail": "Voice input is not available right now."}, status_code=503)
    except Exception:
        logger.exception("transcription_failed session_id=%s", session_id)
        return JSONResponse({"detail": "Could not transcribe that recording. Try again."}, status_code=502)
    return JSONResponse({"text": text})


@router.websocket("/ws/chat/{session_id}")
async def chat_socket(websocket: WebSocket, session_id: str):
    if IS_PRODUCTION and websocket.headers.get("origin", "").rstrip("/") != PUBLIC_ORIGIN:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    participant_id = websocket.session.get("participant_id") if "session" in websocket.scope else None
    participant = eligible_participant(participant_id)
    session = database.get_session(session_id)
    if not participant or not session or session["participant_id"] != participant["id"]:
        await websocket.send_json({"error": "This session is unavailable."})
        await websocket.close(code=1008)
        return
    session_lock = session_socket_locks.setdefault(session_id, asyncio.Lock())
    if session_lock.locked():
        await websocket.send_json({"error": "This session is already open in another tab."})
        await websocket.close(code=1008)
        return
    await session_lock.acquire()
    try:
        while True:
            payload = await websocket.receive_json()
            session = database.get_session(session_id)
            if not session or session["status"] != "active":
                await websocket.send_json({"error": "This session is already complete."})
                continue
            content = str(payload.get("message", "")).strip()[:2000]
            user_lang = language_for(session)
            # The AI's own dialogue almost always takes the grammatical form of a
            # question addressed to the teacher ("Can *you* give me an example?"), so
            # the gender-sensitive clause in these sentences is usually about the
            # teacher, not the AI itself -- passing the AI's own fixed identity here
            # was misgendering the teacher on nearly every turn. Use the teacher's own
            # stated gender instead.
            ai_speaker_gender = teacher_gender_for(session)
            translator = get_translation_service()
            turn = int(session["metadata"].get("turn", 0)) + 1
            try:
                requested_turn = int(payload.get("turn", turn))
            except (TypeError, ValueError):
                requested_turn = -1
            if requested_turn != turn:
                await websocket.send_json({"error": "This turn was already handled. Refresh the session to continue."})
                continue
            if not content or turn > MAX_TURNS:
                await websocket.send_json({"error": "Enter a message for the current turn."})
                continue
            content_en = await translator.to_english(content, user_lang)
            history = [
                {
                    "role": item["role"],
                    "content": item["content"],
                }
                for item in transcripts.read(session_id)
            ]
            history.append({"role": "user", "content": content_en})
            try:
                started = time.perf_counter()
                inference_service = get_inference_service()
                queue = inference_service.queue_status(session["subject"], session["metadata"]["model"])
                if queue["busy"]:
                    await websocket.send_json(
                        {
                            "status": "queued",
                            "queue_position": queue["queue_position"],
                            "done": False,
                        }
                    )
                question_task = asyncio.create_task(
                    inference_service.generate_detailed(
                        session["subject"],
                        session["subtopic"],
                        messages=history,
                        system_prompt=FORK_SYSTEM_PROMPT,
                        model=session["metadata"]["model"],
                        branch_instruction=QUESTION_BRANCH,
                    )
                )
                evaluator_task = asyncio.create_task(
                    evaluate_turn(session, history)
                )
                try:
                    generation = await question_task
                except Exception:
                    evaluator_task.cancel()
                    await asyncio.gather(evaluator_task, return_exceptions=True)
                    raise
                preview_sent = turn < MIN_TURNS
                if preview_sent:
                    await websocket.send_json(
                        {
                            "status": "evaluating",
                            "content": await translator.from_english(
                                generation.content, user_lang, speaker_gender=ai_speaker_gender
                            ),
                            "turn": turn,
                            "done": False,
                        }
                    )
                try:
                    turn_evaluation, evaluation_generation_ms, turn_evaluator = await evaluator_task
                except Exception as evaluator_error:
                    logger.warning(
                        "turn_evaluation_failed session_id=%s turn=%s error=%s",
                        session_id,
                        turn,
                        type(evaluator_error).__name__,
                    )
                    turn_evaluation = generation.evaluation
                    evaluation_generation_ms = 0
                    turn_evaluator = {
                        "provider": "question_branch_fallback",
                        "model": session["metadata"]["model"],
                        "reason": type(evaluator_error).__name__,
                    }
                turn_evaluation = turn_evaluation or generation.evaluation
                latency_ms = round((time.perf_counter() - started) * 1000)
            except (InferenceBusyError, InferenceQueueTimeoutError):
                logger.warning("generation_capacity_rejected session_id=%s turn=%s", session_id, turn)
                await websocket.send_json(
                    {"error": "The inference service is at capacity. Please wait a moment and send your explanation again."}
                )
                continue
            except Exception:
                logger.exception("generation_failed session_id=%s turn=%s", session_id, turn)
                await websocket.send_json({"error": "The study partner could not respond. Please try again."})
                continue
            prior_evaluations = [
                item.get("inline_evaluation")
                for item in transcripts.read(session_id)
                if item.get("role") == "assistant" and item.get("inline_evaluation")
            ]
            decision = decide_completion([*prior_evaluations, turn_evaluation], turn)
            public_content = completion_message(session["subtopic"]) if decision.reason == "knowledge_threshold" else generation.content
            assistant_message = (
                {
                    "role": "assistant",
                    "content": public_content,
                    "generated_content": generation.content,
                    "raw_content": generation.raw_content,
                    "inline_evaluation": turn_evaluation,
                    "turn_evaluator": turn_evaluator,
                    "evaluation_generation_ms": evaluation_generation_ms,
                    "evaluation_context": (
                        "isolated_openrouter_v1"
                        if turn_evaluator.get("provider") == "openrouter"
                        else "isolated_fork_v1"
                    ),
                    "latency_ms": latency_ms,
                    "queue_wait_ms": generation.queue_wait_ms,
                    "generation_ms": generation.generation_ms,
                    "fallback_question": generation.fallback_used,
                    "turn": turn,
                }
            )
            metadata_updates = {"turn": turn}
            if decision.complete:
                metadata_updates.update({"completion_reason": decision.reason, "adaptive_completion": True})
            transcripts.record_turn(
                session_id,
                {"role": "user", "content": content_en, "turn": turn},
                assistant_message,
                metadata_updates,
                complete=decision.complete,
            )
            if decision.complete:
                schedule_final_feedback(session, transcripts.read(session_id))
                logger.info("session_completed session_id=%s turn=%s reason=%s", session_id, turn, decision.reason)
            await websocket.send_json(
                {
                    "content": None
                    if preview_sent
                    else await translator.from_english(public_content, user_lang, speaker_gender=ai_speaker_gender),
                    "turn": turn,
                    "done": True,
                    "complete": decision.complete,
                    "completion_reason": decision.reason,
                }
            )
    except WebSocketDisconnect:
        logger.info("websocket_disconnected session_id=%s", session_id)
    finally:
        session_lock.release()


@router.get("/sessions/{session_id}/complete", response_class=HTMLResponse)
async def complete(request: Request, session_id: str):
    session = owned_session(participant_for(request), session_id)
    if not session:
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    if session["status"] != "completed":
        return RedirectResponse(f"{BASE_PATH}/sessions/{session_id}", status_code=303)
    if settings.student_questionnaire_enabled and database.get_survey(session_id):
        return RedirectResponse(f"{BASE_PATH}/sessions/{session_id}/thanks", status_code=303)
    result = await final_feedback_result(session)
    context = complete_page_context(session, result)
    context["teaching_feedback"] = await localized_feedback(
        context["teaching_feedback"], language_for(session), teacher_gender_for(session)
    )
    return render(request, "complete.html", **context)


@router.post("/sessions/{session_id}/survey")
async def submit_survey(
    request: Request,
    session_id: str,
):
    session = owned_session(participant_for(request), session_id)
    if not session or session["status"] != "completed":
        return RedirectResponse(f"{BASE_PATH}/history", status_code=303)
    if not settings.student_questionnaire_enabled:
        return RedirectResponse(f"{BASE_PATH}/sessions/{session_id}/complete", status_code=303)
    form = await request.form()
    try:
        response_data = parse_hci_student_survey(form)
    except ValueError as exc:
        evaluation_record = database.get_evaluation(session_id)
        result = evaluation_record.get("result") if evaluation_record else None
        context = complete_page_context(
            session,
            result,
            survey_error=str(exc),
            form_values={key: str(value) for key, value in form.items()},
        )
        context["teaching_feedback"] = await localized_feedback(
            context["teaching_feedback"], language_for(session), teacher_gender_for(session)
        )
        response = render(request, "complete.html", **context)
        response.status_code = 422
        return response
    database.save_survey(session_id, response_data)
    logger.info("survey_saved session_id=%s instrument_id=%s", session_id, response_data["instrument_id"])
    return RedirectResponse(f"{BASE_PATH}/sessions/{session_id}/thanks", status_code=303)


@router.get("/sessions/{session_id}/thanks", response_class=HTMLResponse)
async def thanks(request: Request, session_id: str):
    if not owned_session(participant_for(request), session_id):
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    return render(request, "thanks.html", session_id=session_id)


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    participant = participant_for(request)
    if not participant:
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    session_rows = [session_view(item) for item in database.list_sessions(participant["id"])]
    return render(request, "history.html", sessions=session_rows)


@router.get("/history/{session_id}", response_class=HTMLResponse)
async def history_detail(request: Request, session_id: str):
    session = owned_session(participant_for(request), session_id)
    if not session:
        return RedirectResponse(f"{BASE_PATH}/history", status_code=303)
    result = await final_feedback_result(session) if session["status"] == "completed" else None
    lang = language_for(session)
    feedback = teaching_feedback_for(session_id, result) if session["status"] == "completed" else None
    return render(
        request,
        "history_detail.html",
        session=session_view(session),
        messages=await localized_messages(transcripts.read(session_id), lang, teacher_gender_for(session)),
        teaching_feedback=await localized_feedback(feedback, lang, teacher_gender_for(session)),
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    participant = participant_for(request)
    if not participant:
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    if not is_admin(participant):
        return HTMLResponse("Admin access is restricted.", status_code=403)
    all_users = database.list_participants_with_session_counts()
    query = str(request.query_params.get("q", "")).strip()[:100]
    query_folded = query.casefold()
    users = [
        user
        for user in all_users
        if not query_folded
        or query_folded in str(user.get("metadata", {}).get("name", "")).casefold()
        or query_folded in str(user.get("metadata", {}).get("email", "")).casefold()
    ]
    totals = {
        "users": len(all_users),
        "sessions": sum(int(item["session_count"] or 0) for item in all_users),
        "turns": sum(int(item["turn_count"] or 0) for item in all_users),
        "active": sum(int(item["active_count"] or 0) for item in all_users),
    }
    return render(request, "admin.html", users=users, totals=totals, query=query)


@router.get("/admin/users/{participant_id}", response_class=HTMLResponse)
async def admin_user_detail(request: Request, participant_id: str):
    if not participant_for(request):
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    if not admin_for(request):
        return HTMLResponse("Admin access is restricted.", status_code=403)
    user = database.get_participant(participant_id)
    if not user:
        return HTMLResponse("User not found.", status_code=404)
    sessions = [session_view(item) for item in database.list_sessions(participant_id)]
    summary = {
        "sessions": len(sessions),
        "completed": sum(item["status"] == "completed" for item in sessions),
        "turns": sum(int(item["turn"]) for item in sessions),
    }
    return render(request, "admin_user.html", user=user, sessions=sessions, summary=summary)


@router.get("/admin/sessions/{session_id}", response_class=HTMLResponse)
async def admin_session_detail(request: Request, session_id: str):
    if not participant_for(request):
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    if not admin_for(request):
        return HTMLResponse("Admin access is restricted.", status_code=403)
    session = database.get_session(session_id)
    if not session:
        return HTMLResponse("Session not found.", status_code=404)
    user = database.get_participant(session["participant_id"])
    if not user:
        return HTMLResponse("User not found.", status_code=404)
    messages = transcripts.read(session_id)
    return render(
        request,
        "admin_session.html",
        session=session_view(session),
        user=user,
        messages=messages,
        turns=admin_turn_views(messages),
        evaluation=database.get_evaluation(session_id),
        survey=database.get_survey(session_id),
    )


@router.get("/api/catalog")
async def catalog(request: Request):
    if not participant_for(request):
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    return {"models": MODELS, "subjects": TOPICS}


@router.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


app.include_router(router)


def run():
    uvicorn.run("app.main:app", host=os.getenv("APP_HOST", "127.0.0.1"), port=int(os.getenv("APP_PORT", "8000")))
