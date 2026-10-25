import asyncio
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import uuid
import chainlit as cl
from chainlit.input_widget import Select
from dotenv import load_dotenv
from student_chain import (
    build_vectorstore,
    build_student_chain_only,
    generate_opening_question,
    outbound_text,
)
from evaluator_chain import build_evaluator_chain, build_final_feedback_chain
from completion import decide_completion, completion_message
from teaching_feedback import build_deterministic_feedback
from models import StudentResponse, TeacherResponse, TurnEvaluationResponse, FinalFeedbackResponse, get_llm, get_student_llm
from langchain.memory import ConversationBufferMemory
from typing import Optional
from pathlib import Path
import json
from memory import (
        create_user,
        create_session,
        create_interaction,
        save_student,
        save_teacher,
        save_evaluator,
        fetch_session_interaction_ids,
        fetch_student_memory,
        fetch_session_evaluations,
        fetch_session_turns,
        save_final_feedback,
        update_session_topic,
        update_session_model,
        get_session,
        list_user_sessions,
        get_final_feedback,
)
from translation import SUPPORTED_LANGUAGES, normalize_language, get_translation_service
from transcription import get_transcription_service
from topics import TOPICS

from chainlit.server import app as _fastapi_app
from chainlit.auth import get_current_user
from chainlit.user import User, PersistedUser
from chainlit.config import config as cl_config
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

GENDERS = ["Male", "Female"]
FINAL_FEEDBACK_MODEL = os.getenv("FINAL_FEEDBACK_MODEL", "openai/gpt-5.6-luna")

# -------------------------------
# History -- plain authenticated routes on Chainlit's own FastAPI app, not
# Chainlit's native data layer/thread-resume (that would need a schema adapter
# from this project's session/interaction/teacher/student/evaluator Mongo
# collections onto Chainlit's ThreadDict/StepDict shape). get_current_user
# reads the same access_token cookie/JWT the existing Google OAuth login
# already sets -- no separate auth mechanism needed. Routes must carry
# config.run.root_path themselves (only set when started with --root-path,
# e.g. production's /rag_multilingual) since they bypass Chainlit's own
# APIRouter(prefix=root_path) entirely.
# -------------------------------
_templates = Jinja2Templates(directory="templates")
_ROOT = cl_config.run.root_path
_history_router = APIRouter()
_IST = ZoneInfo("Asia/Kolkata")


def _as_ist(ts):
    """memory.py stores datetime.utcnow() -- naive, and pymongo reads it back naive
    too -- so a bare strftime in the template would silently display UTC labeled as
    if it were the viewer's own clock, off by 5:30 for every participant (this whole
    app is BITS-Pilani-only, so IST is the one real timezone that matters here)."""
    if ts is None:
        return None
    return ts.replace(tzinfo=timezone.utc).astimezone(_IST)


@_history_router.get(f"{_ROOT}/history", response_class=HTMLResponse)
async def history_page(request: Request, current_user: Optional[User | PersistedUser] = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(401, "Unauthorized")
    sessions = list_user_sessions(current_user.identifier)
    for s in sessions:
        s["completed"] = get_final_feedback(s["_id"]) is not None
        s["timestamp"] = _as_ist(s.get("timestamp"))
    return _templates.TemplateResponse(request, "history.html", {"sessions": sessions, "root": _ROOT})


@_history_router.get(f"{_ROOT}/history/{{session_id}}", response_class=HTMLResponse)
async def history_detail_page(
    request: Request,
    session_id: str,
    current_user: Optional[User | PersistedUser] = Depends(get_current_user),
):
    session = get_session(session_id)
    if not current_user or not session or session.get("user_id") != current_user.identifier:
        raise HTTPException(404, "Not found")
    session["timestamp"] = _as_ist(session.get("timestamp"))
    turns = fetch_session_evaluations(session_id)
    feedback = get_final_feedback(session_id)

    # Every field stored here is English (ai_question_en/teacher_answer_en, judge-written
    # strength/improvement/summary) -- the live chat translates on the way out instead of
    # storing pre-translated text, so history has to translate on the way back in too, same
    # as _localize/present_final_score do for the live session. teacher_answer_en gets no
    # speaker_gender hint: it's the teacher's own words, not a line addressed to them.
    lang = normalize_language(session.get("lang", "en"))
    teacher_gender = session.get("teacher_gender")
    if lang != "en":
        translator = get_translation_service()

        async def _translate_turn(t):
            ai_q, teacher_a, strength, improvement = await asyncio.gather(
                translator.from_english(t.get("ai_question_en", ""), lang, speaker_gender=teacher_gender),
                translator.from_english(t.get("teacher_answer_en", ""), lang),
                translator.from_english(t.get("strength", ""), lang, speaker_gender=teacher_gender),
                translator.from_english(t.get("improvement", ""), lang, speaker_gender=teacher_gender),
            )
            return {**t, "ai_question_en": ai_q, "teacher_answer_en": teacher_a, "strength": strength, "improvement": improvement}

        turns = list(await asyncio.gather(*(_translate_turn(t) for t in turns)))
        if feedback:
            strengths, improvements, summary = await asyncio.gather(
                translator.all_from_english(feedback.get("strengths", []), lang, speaker_gender=teacher_gender),
                translator.all_from_english(feedback.get("improvements", []), lang, speaker_gender=teacher_gender),
                translator.from_english(feedback.get("summary", ""), lang, speaker_gender=teacher_gender),
            )
            feedback = {**feedback, "strengths": strengths, "improvements": improvements, "summary": summary}

    return _templates.TemplateResponse(
        request, "history_detail.html", {"session": session, "turns": turns, "feedback": feedback, "root": _ROOT}
    )


# Chainlit's own routes (health, auth, the SPA catch-all, ...) don't live as flat
# entries on app.router.routes -- app.include_router(router) (chainlit/server.py)
# wraps them in a private fastapi.routing._IncludedRouter, whose real route list is
# nested at .include_context.included_router.routes, ending with the SPA catch-all
# (`GET {root_path}/{full_path:path}`, chainlit/server.py). A plain @app.get(...)
# registers as a sibling top-level entry and is never reached -- empirically verified
# live: the catch-all served its SPA shell for every request before this splice was
# added. Inserting directly into that same nested list, just before the catch-all,
# is what actually makes these routes reachable; this reaches into a private
# (underscore-prefixed) FastAPI/Chainlit internal, so a Chainlit/FastAPI upgrade could
# require re-verifying this still finds the catch-all at the same place.
_included = next(r for r in reversed(_fastapi_app.router.routes) if type(r).__name__ == "_IncludedRouter")
_chainlit_routes = _included.include_context.included_router.routes
_catch_all_idx = next(i for i, r in enumerate(_chainlit_routes) if getattr(r, "path", None) == f"{_ROOT}/{{full_path:path}}")
for _offset, _route in enumerate(_history_router.routes):
    _chainlit_routes.insert(_catch_all_idx + _offset, _route)


load_dotenv()
VS_DIR = VS_DIR = Path(os.getenv("VS_DIR", Path(__file__).resolve().parents[1] / "vectorstore"))
CATALOG_PATH = VS_DIR / "catalog.json"


def stop_input():
    try:
        cl.use_audio.endConversation()
    except Exception as e:
        print(e)


_EMOJI_PREFIX_RE = re.compile(r"^([^\w\s]+)\s+")


async def _localize(text: str, lang: str, speaker_gender: str | None = None) -> str:
    """Translate a UI/chrome string once the participant's language is known.
    A no-op for English, same as the content translation calls elsewhere.

    A leading emoji (e.g. "👩‍🎓 ") is split off and re-attached after translating,
    rather than sent through Sarvam with the rest of the text: multi-codepoint
    ZWJ emoji sequences like the student avatar don't reliably survive the
    round trip (simple single-codepoint emoji like ⚠️/📚 do), so this keeps
    every message's prefix visually consistent regardless of that quirk.

    speaker_gender is only meaningful for the AI student's own lines, and should be
    the *teacher's* stated gender, not a fixed persona gender: the AI's dialogue is
    almost always a question addressed to the teacher ("Can *you* give me an
    example?"), so the gender-sensitive clause in these sentences is usually about
    the teacher being addressed. Never pass it for text addressed to the teacher in
    a context where it would represent a guess rather than their own stated value.
    """
    prefix = ""
    match = _EMOJI_PREFIX_RE.match(text)
    if match:
        prefix, text = match.group(1), text[match.end():]
    if lang == "en":
        translated = text
    else:
        translated = await get_translation_service().from_english(
            text, lang, speaker_gender=speaker_gender
        )
    return f"{prefix} {translated}" if prefix else translated


def format_final_score(result: dict) -> str:
    md = f"""
# 📝 Final Remarks
## 💡 Strengths
"""
    for s in result.get("strengths", []):
        md += f"- {s}\n"

    md += "\n## 🔧 Improvements\n"
    for i in result.get("improvements", []):
        md += f"- {i}\n"

    md += "\n## 🏁 Summary\n"
    md += f"- {result.get('summary', '')}\n"

    return md.strip()


async def present_final_score(result: dict, lang: str, teacher_gender: str | None):
    """Send the final evaluation in a nice markdown format to Chainlit UI, translated
    into the participant's teaching language. The judge chains themselves never see
    anything but English; only this presentation layer is translated.

    This feedback addresses the teacher directly as "you", so the correct grammatical
    gender here is the teacher's own, which is why it's asked up front at start()
    rather than assumed -- same reasoning as the AI's own mid-conversation dialogue,
    which also addresses the teacher far more often than it speaks about itself."""
    if lang != "en":
        translator = get_translation_service()
        result = {
            **result,
            "strengths": await translator.all_from_english(result.get("strengths", []), lang, speaker_gender=teacher_gender),
            "improvements": await translator.all_from_english(result.get("improvements", []), lang, speaker_gender=teacher_gender),
            "summary": await translator.from_english(result.get("summary", ""), lang, speaker_gender=teacher_gender),
        }
    md_output = format_final_score(result)
    await cl.Message(content=md_output).send()


# ------------------- AUTH ------------------- #


@cl.oauth_callback
def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: dict,
    default_user: cl.User,
) -> Optional[cl.User]:
    print("Provider: ", provider_id)
    print("Raw user data: ", raw_user_data)
    if provider_id == "google":
        email = raw_user_data.get("email", "")
        if email.endswith("@pilani.bits-pilani.ac.in"):
            return default_user
    return None

# ------------------- ON SETTINGS UPDATE ------------------- #


@cl.on_settings_update
async def setup_agent(settings):
    # Only the student-facing teaching model is reconfigurable mid-session. `vs`
    # depends only on catalog/topic (never the LLM) so it's left alone rather than
    # reopening the same Chroma persist_directory on every model switch; the judge
    # chains (evaluator_chain/final_feedback_chain) are intentionally never rebuilt
    # here either -- they must stay on the fixed judge model regardless of which
    # model the participant is being taught by, or the judge itself becomes a
    # confound in the model comparison.
    current_model = settings["Model"]
    print("Updated Model to: ", current_model)
    llm = get_student_llm(current_model)
    cl.user_session.set("llm", llm)
    cl.user_session.set("student_chain", build_student_chain_only(llm))
    # Tracked separately from the ChatSettings object itself: cl.ChatSettings.send()
    # (chainlit/chat_settings.py) returns each widget's *initial* value immediately --
    # it does not wait for the user to touch the panel -- so the `settings` variable
    # captured right after start()'s .send() call is always the hardcoded default,
    # never whatever the user actually picks. This is the one place that record is
    # updated to the real selection, for update_session_topic() to read from.
    cl.user_session.set("model", current_model)
    # The settings panel is disabled for the entire language/gender/subject/topic/
    # subtopic picker flow (confirmed live), so update_session_topic() always sees the
    # untouched default by the time it runs -- the only way a teacher ever reaches
    # this handler with a different model is by changing it afterward, which this app
    # already treats as a legitimate mid-session switch. Mongo needs to reflect that
    # live, not just cl.user_session, or History keeps showing the stale default no
    # matter what model teaching actually happens with.
    if session_id := cl.user_session.get("session_id"):
        update_session_model(session_id, current_model)


# ------------------- ON CHAT RESUME --------------- #
@cl.on_chat_resume
async def on_chat_resume(thread):
    session_memory = ConversationBufferMemory(return_messages=True)
    root_messages = [m for m in thread["steps"] if m["parentId"] == None]
    for message in root_messages:
        if message["type"] == "user_message":
            session_memory.chat_memory.add_user_message(message["output"])
        else:
            session_memory.chat_memory.add_ai_message(message["output"])

    cl.user_session.set("session_memory", session_memory)


# ------------------- CHAT START ------------------- #

@cl.on_chat_start
async def start():
    """Initialize session, show topics, generate subtopics, and prepare Q&A."""
    user = cl.user_session.get("user")
    # cl.Action has no URL/link variant (dataclass fields: name/payload/label/tooltip/
    # icon, action.py -- purely a Python-callback button), and there's no persistent
    # header/toolbar extension point without a custom frontend build, so a markdown
    # link in the welcome message is the lowest-friction way to surface History from
    # the main chat UI itself rather than only a typed-in URL.
    await cl.Message(
        content=f"Welcome, {user.display_name or user.identifier}! [View your past sessions]({_ROOT}/history)"
    ).send()

    # Teaching language is picked once, up front, like subject/subtopic below —
    # unlike Model it is not reconfigurable mid-session via ChatSettings, since every
    # stored record is fixed to English.
    lang_actions = [
        cl.Action(name=code, payload={"value": code}, label=name)
        for code, name in SUPPORTED_LANGUAGES.items()
    ]
    lang_res = await cl.AskActionMessage(
        content="🌐 Choose your teaching language:",
        actions=lang_actions
    ).send()
    lang = normalize_language(lang_res.get("payload", {}).get("value") if lang_res else None)
    cl.user_session.set("lang", lang)

    # Asked explicitly rather than assumed: the final feedback and the AI's own
    # dialogue both need this. The AI's lines are almost always a question addressed
    # to the teacher ("Can *you* give me an example?"), so the gender-sensitive
    # clause in those sentences is usually about the teacher being addressed, not a
    # fixed "AI persona gender" -- a hardcoded "Female" here was misgendering the
    # teacher on nearly every turn regardless of what they'd select, confirmed via
    # direct Sarvam translation checks (e.g. "aap...sakti hain" vs "sakte hain").
    gender_actions = [
        cl.Action(name=gender, payload={"value": gender}, label=gender)
        for gender in GENDERS
    ]
    gender_res = await cl.AskActionMessage(
        content="🧑 For correct grammar in your feedback, how should we address you?",
        actions=gender_actions
    ).send()
    teacher_gender = gender_res.get("payload", {}).get("value") if gender_res else None
    cl.user_session.set("teacher_gender", teacher_gender)

    session_id = create_session(user.identifier, lang, teacher_gender)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("session_memory", ConversationBufferMemory(return_messages=True))

    # Judge chains (per-turn evaluator + session-final feedback) are built once from a
    # fixed model, independent of whichever model the participant ends up being taught
    # by below -- see setup_agent's docstring for why they're never rebuilt afterward.
    judge_llm = get_llm(FINAL_FEEDBACK_MODEL)
    cl.user_session.set("evaluator_chain", build_evaluator_chain(judge_llm))
    cl.user_session.set("final_feedback_chain", build_final_feedback_chain(judge_llm))

    settings = await cl.ChatSettings(
        [
            Select(
                id="Model",
                label="Select Model",
                values=[
                    # Frontier options. OpenRouter has withdrawn claude-3.7-sonnet and qwen3-8b.
                    # claude-sonnet-5 is the direct same-tier successor (confirmed live).
                    "openai/gpt-6.1-sol", "google/gemini-4-argon", "anthropic/claude-sonnet-5",
                    # Same base models as the finetuned side's adapters (exact OpenRouter
                    # matches only, verified live) -- lets a session be run ungrounded on
                    # the identical base model a finetuned adapter was built on, for a
                    # direct RAG-vs-finetuned comparison.
                    # qwen3-8b (the original match) was withdrawn by OpenRouter 9 Oct 2026 with
                    # no same-generation 8B-class text-only successor available, so the finetuned
                    # "qwen3" adapter was retrained from scratch on Qwen3-14B instead -- this is
                    # that adapter's actual base model now, confirmed via the from-scratch LoRA
                    # run, not an approximation.
                    "qwen/qwen3-14b",             # base of the finetuned "qwen3" adapter
                    "qwen/qwen-2.5-7b-instruct",  # base of the finetuned "qwen2.5" adapter
                    "meta-llama/llama-3.1-8b-instruct",  # base of the finetuned "llama31" adapter
                    "ibm-granite/granite-4.2-8b",        # base of the finetuned "granite42" adapter
                ],
                initial_index=0
            )
        ]
    ).send()
    cl.user_session.set("llm", get_student_llm(settings["Model"]))
    # Fallback for update_session_topic() below, in case the user never opens the
    # settings panel at all before teaching starts -- setup_agent() overwrites this
    # with the real selection the moment they do.
    cl.user_session.set("model", settings["Model"])

    # Load catalog
    if not CATALOG_PATH.exists():
        await cl.Message(content=await _localize("⚠️ No catalog found. Please run ingestion first.", lang)).send()
        return

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    if not catalog:
        await cl.Message(content=await _localize("⚠️ Catalog is empty. Add some topics first.", lang)).send()
        return

    cl.user_session.set("catalog", catalog)

    # Step 1: Show main subjects. Labeled with TOPICS's friendly name (e.g. "Computer
    # Programming") rather than the raw catalog key -- matches the finetuned portal's
    # subject picker, which never showed the bare "cp"/"dsa"/etc. key to begin with.
    actions = [
        cl.Action(name=t, payload={"value": t}, label=TOPICS.get(t, {}).get("name", t))
        for t in catalog.keys()
    ]
    actions_res = await cl.AskActionMessage(
        content=await _localize("📚 Here are the available subjects. Please choose one:", lang),
        actions=actions
    ).send()

    user_topic = ""
    if actions_res and actions_res.get("payload").get("value"):
        user_topic = actions_res.get("payload").get("value")

    if user_topic not in catalog:
        await cl.Message(content=await _localize(f"⚠️ '{user_topic}' is not a valid topic. Restart and try again.", lang)).send()
        return

    llm = cl.user_session.get("llm")

    # Step 2: Build the student chain + vectorstore for the chosen topic
    vs = build_vectorstore(user_topic, catalog)
    student_chain = build_student_chain_only(llm)
    cl.user_session.set("student_chain", student_chain)
    cl.user_session.set("vs", vs)

    # Step 3: Show topics within the chosen subject (mirrors the finetuned portal's
    # 2-level subject -> topic -> subtopic hierarchy exactly, sourced from the same
    # TOPICS data -- see topics.py's module docstring).
    subject_topics = TOPICS[user_topic]["topics"]
    topic_actions = [
        cl.Action(name=tid, payload={"value": tid}, label=t["name"])
        for tid, t in subject_topics.items()
    ]
    topic_res = await cl.AskActionMessage(
        content=await _localize(f"📂 Here are the topics for **{TOPICS[user_topic]['name']}**. Please choose one:", lang),
        actions=topic_actions
    ).send()

    chosen_topic_id = ""
    if topic_res and topic_res.get("payload").get("value"):
        chosen_topic_id = topic_res.get("payload").get("value")

    if chosen_topic_id not in subject_topics:
        await cl.Message(content=await _localize(f"⚠️ '{chosen_topic_id}' is not a valid topic. Restart and try again.", lang)).send()
        return

    # Step 4: Show the subtopics within the chosen topic and let them choose
    subtopics = subject_topics[chosen_topic_id]["subtopics"]
    subtopic_actions = [cl.Action(name=s, payload={"value": s}, label=s) for s in subtopics]
    subtopic_res = await cl.AskActionMessage(
        content=await _localize(f"📖 Here are the subtopics for **{subject_topics[chosen_topic_id]['name']}**. Please choose one:", lang),
        actions=subtopic_actions
    ).send()

    chosen_subtopic = ""
    if subtopic_res and subtopic_res.get("payload").get("value"):
        chosen_subtopic = subtopic_res.get("payload").get("value")

    if chosen_subtopic not in subtopics:
        await cl.Message(content=await _localize(f"⚠️ '{chosen_subtopic}' is not a valid subtopic. Restart and try again.", lang)).send()
        return

    # Step 5: Session state. turn/visible_transcript_en are new -- turn drives
    # decide_completion(), visible_transcript_en is an English-only record (separate
    # from Chainlit's own session_memory, which stores translated display text for
    # on_chat_resume only) that feeds the judge chains.
    cl.user_session.set("topic", user_topic)
    cl.user_session.set("subtopic", chosen_subtopic)
    update_session_topic(
        session_id, user_topic, chosen_topic_id,
        subject_topics[chosen_topic_id]["name"],
        chosen_subtopic, cl.user_session.get("model", settings["Model"]),
    )
    cl.user_session.set("turn", 0)
    cl.user_session.set("visible_transcript_en", [])
    session_memory = cl.user_session.get("session_memory")

    # Step 6: Kick off conversation with a dynamically generated opening question --
    # replaces the old pre-baked qa_pool entirely. Mirrors the finetuned side: this
    # bootstrap is never persisted as a turn (no save_teacher/save_student/save_evaluator
    # call, no "user" line in visible_transcript_en), and `turn` stays at 0 until the
    # first real teacher answer.
    opening_student = generate_opening_question(student_chain, vs, chosen_subtopic)
    opening_en = outbound_text(opening_student)
    content_en = (
        f"👩‍🎓 Student: Great! Let’s start with **{chosen_subtopic}**. "
        f"Here’s my first question:\n\n{opening_en}"
    )
    message = cl.Message(content=await _localize(content_en, lang, speaker_gender=teacher_gender))
    await message.send()
    session_memory.chat_memory.add_ai_message(message.content)
    cl.user_session.set("visible_transcript_en", [{"role": "assistant", "content": opening_en}])



# ------------------- MAIN LOOP ------------------- #
async def handle_teacher_turn(teacher_explanation: str):
    """Handle one teacher turn: grounded student response, ungrounded judge evaluation,
    adaptive completion -- mirrors teach2learn-portal's mechanics exactly except for the
    one deliberate difference (the student stays retrieval-grounded via `vs`; the judges
    never are).

    Shared by both typed messages (on_message) and dictated ones (on_audio_end) —
    a transcribed explanation goes through exactly the same pipeline as a typed one.
    """
    cl_user = cl.user_session.get("user")  # Chainlit User object
    session_id = cl.user_session.get("session_id")
    session_memory = cl.user_session.get("session_memory")
    lang = cl.user_session.get("lang", "en")
    teacher_gender = cl.user_session.get("teacher_gender")
    if not cl_user:
        await cl.Message(content=await _localize("❌ User not authenticated.", lang)).send()
        return

    # Extract normalized fields
    user_id = cl_user.identifier
    user_email = getattr(cl_user, "email", None)
    user_name = getattr(cl_user, "display_name", None)

    # Ensure user exists in DB
    create_user(user_id, user_email, user_name)

    # Load session state
    student_chain = cl.user_session.get("student_chain")
    vs = cl.user_session.get("vs")
    evaluator_chain = cl.user_session.get("evaluator_chain")
    subtopic = cl.user_session.get("subtopic")
    turn = cl.user_session.get("turn", 0)
    visible_transcript_en = cl.user_session.get("visible_transcript_en", [])
    session_interaction_ids = fetch_session_interaction_ids(session_id)

    # Create new interaction entry
    interaction_id = create_interaction(session_id)

    # 1️⃣ Teacher provides explanation. The student/judge chains and every stored record
    # only ever see English; translate here, once, at the boundary.
    translator = get_translation_service()
    teacher_explanation_en = await translator.to_english(teacher_explanation, lang)
    teacher_model = TeacherResponse(message=teacher_explanation_en)
    save_teacher(interaction_id, teacher_model)
    session_memory.chat_memory.add_user_message(teacher_explanation_en)

    last_ai_en = next(
        (item["content"] for item in reversed(visible_transcript_en) if item["role"] == "assistant"),
        "",
    )
    visible_transcript_en = [*visible_transcript_en, {"role": "user", "content": teacher_explanation_en}]

    student_memory = fetch_student_memory(session_interaction_ids)

    # 2️⃣ Student (grounded) and judge (ungrounded) run concurrently -- mirrors the
    # finetuned side's concurrent question/evaluator tasks. Neither chain offers an
    # async .invoke, so each runs in its own thread rather than blocking the other.
    context_docs = vs.similarity_search(teacher_explanation_en, k=4)
    context = "\n\n".join(doc.page_content for doc in context_docs)

    student_llm_response, evaluator_result = await asyncio.gather(
        asyncio.to_thread(
            student_chain.invoke,
            {
                "teacher_explanation": teacher_explanation_en,
                "student_memory": student_memory,
                "context": context,
            },
        ),
        asyncio.to_thread(
            evaluator_chain.invoke,
            {
                "subtopic": subtopic,
                "last_ai_en": last_ai_en,
                "teacher_explanation_en": teacher_explanation_en,
            },
        ),
        return_exceptions=True,
    )

    if isinstance(student_llm_response, BaseException):
        raise student_llm_response

    student_text = student_llm_response["text"]
    student_model = student_text if isinstance(student_text, StudentResponse) else StudentResponse.parse_raw(student_text)
    save_student(interaction_id, student_model)

    # 3️⃣ Evaluator. No local-model fallback exists on this side (a single LLM access
    # point via OpenRouter, unlike the finetuned side's fork-branch fallback) -- on
    # failure, degrade to turn_evaluation=None and keep the session going.
    turn_evaluation = None
    if not isinstance(evaluator_result, BaseException):
        evaluator_text = evaluator_result["text"]
        turn_evaluation = evaluator_text if isinstance(evaluator_text, TurnEvaluationResponse) else TurnEvaluationResponse.parse_raw(evaluator_text)
        turn += 1
        save_evaluator(interaction_id, turn_evaluation, turn, last_ai_en, teacher_explanation_en)
    else:
        turn += 1

    outbound = outbound_text(student_model)
    visible_transcript_en = [*visible_transcript_en, {"role": "assistant", "content": outbound}]
    cl.user_session.set("visible_transcript_en", visible_transcript_en)
    cl.user_session.set("turn", turn)

    # 4️⃣ Adaptive completion -- same decide_completion() as the finetuned side.
    # fetch_session_evaluations() naturally omits this turn entirely when the evaluator
    # failed (nothing was saved for it), which would otherwise leave evaluations[-1]
    # silently pointing at a STALE prior turn instead of signaling "this turn is
    # unscored". Append an explicit None so decide_completion sees exactly what the
    # finetuned side's decide_completion([*prior_evaluations, turn_evaluation], turn)
    # sees -- a real gap, never mistaken for an old good score.
    evaluations = fetch_session_evaluations(session_id)
    if turn_evaluation is None:
        evaluations = [*evaluations, None]
    decision = decide_completion(evaluations, turn)

    if not decision.complete:
        outbound_localized = await _localize(f"👩‍🎓 Student: {outbound}", lang, speaker_gender=teacher_gender)
        message = cl.Message(content=outbound_localized)
        await message.send()
        session_memory.chat_memory.add_ai_message(message.content)
        return

    # 5️⃣ Session complete.
    message = cl.Message(content=await _localize(completion_message(subtopic), lang, speaker_gender=teacher_gender))
    await message.send()
    session_memory.chat_memory.add_ai_message(message.content)
    stop_input()

    fallback = build_deterministic_feedback(fetch_session_turns(session_id))
    final_feedback_chain = cl.user_session.get("final_feedback_chain")
    transcript_text = "\n".join(
        f"{'Human teacher' if item['role'] == 'user' else 'AI learner'}: {item['content']}"
        for item in visible_transcript_en
    )
    try:
        final_response = final_feedback_chain.invoke({"transcript": transcript_text})
        final_text = final_response["text"]
        final_model = final_text if isinstance(final_text, FinalFeedbackResponse) else FinalFeedbackResponse.parse_raw(final_text)
        result = {
            "strengths": final_model.strengths[:2] or fallback["strengths"],
            "improvements": final_model.improvements[:2] or fallback["improvements"],
            "summary": final_model.summary or fallback["summary"],
            "final_level": fallback["final_level"],
            "assessment_count": fallback["assessment_count"],
            "generation": "independent_final_evaluator",
        }
    except Exception as exc:
        print(f"final_feedback_failed: {exc}")
        result = fallback

    save_final_feedback(session_id, result)
    await present_final_score(result, lang, teacher_gender)
    stop_input()


@cl.on_message
async def main(message: cl.Message):
    await handle_teacher_turn(message.content)


# ------------------- VOICE INPUT ------------------- #
# Chainlit's own mic control (enabled via .chainlit/config.toml's [features.audio])
# streams raw PCM16 chunks through these three hooks — there is no custom button or
# browser JS to write, unlike the FastAPI app's hand-rolled MediaRecorder/WAV pipeline.
@cl.on_audio_start
async def on_audio_start():
    cl.user_session.set("audio_chunks", [])
    return True


@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    chunks = cl.user_session.get("audio_chunks")
    if chunks is not None:
        chunks.append(chunk.data)


@cl.on_audio_end
async def on_audio_end():
    import io
    import wave

    chunks = cl.user_session.get("audio_chunks") or []
    cl.user_session.set("audio_chunks", [])
    if not chunks:
        return

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit PCM
        w.setframerate(24000)  # matches .chainlit/config.toml's [features.audio].sample_rate
        w.writeframes(b"".join(chunks))

    transcriber = get_transcription_service()
    lang = cl.user_session.get("lang", "en")
    try:
        text = await transcriber.transcribe(buf.getvalue(), "recording.wav", "audio/wav", lang)
    except Exception as exc:
        print(f"transcription_failed: {exc}")
        await cl.Message(content=await _localize("Could not transcribe that recording. Try again.", lang)).send()
        return

    # Audio bypasses the normal message-submit path, so nothing echoes what was heard
    # unless we send it explicitly — without this the teacher's own turn is invisible,
    # even though it was transcribed and processed correctly.
    await cl.Message(author="You", type="user_message", content=text).send()
    await handle_teacher_turn(text)
