import os
import re
from datetime import datetime
import uuid
import chainlit as cl
from chainlit.input_widget import Select
from dotenv import load_dotenv
from student_chain import build_student_chain
from evaluator_chain import build_evaluator_chain
from scorer_chain import build_scorer_chain, build_final_scorer_chain
from models import StudentResponse, TeacherResponse, EvaluatorResponse, ScorerResponse, FinalScorerResponse, get_llm
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
        save_scorer,
        fetch_session_interaction_ids,
        fetch_student_memory,
        fetch_session_scores
)
from qa_generator import generate_qa_for_subtopic, generate_subtopics, load_catalog
from translation import SUPPORTED_LANGUAGES, normalize_language, get_translation_service
from transcription import get_transcription_service


load_dotenv()
VS_DIR = VS_DIR = Path(os.getenv("VS_DIR", Path(__file__).resolve().parents[1] / "vectorstore"))
CATALOG_PATH = VS_DIR / "catalog.json"


def stop_input():
    try:
        cl.use_audio.endConversation()
    except Exception as e:
        print(e)


_EMOJI_PREFIX_RE = re.compile(r"^([^\w\s]+)\s+")


async def _localize(text: str, lang: str) -> str:
    """Translate a UI/chrome string once the participant's language is known.
    A no-op for English, same as the content translation calls elsewhere.

    A leading emoji (e.g. "👩‍🎓 ") is split off and re-attached after translating,
    rather than sent through Sarvam with the rest of the text: multi-codepoint
    ZWJ emoji sequences like the student avatar don't reliably survive the
    round trip (simple single-codepoint emoji like ⚠️/📚 do), so this keeps
    every message's prefix visually consistent regardless of that quirk.
    """
    prefix = ""
    match = _EMOJI_PREFIX_RE.match(text)
    if match:
        prefix, text = match.group(1), text[match.end():]
    if lang == "en":
        translated = text
    else:
        translated = await get_translation_service().from_english(text, lang)
    return f"{prefix} {translated}" if prefix else translated


def format_final_score(comments: dict) -> str:
    md = f"""
# 📝 Final Remarks
## 💡 Strengths
"""
    for s in comments.get("strengths", []):
        md += f"- {s}\n"

    md += "\n## 🔧 Improvements\n"
    for i in comments.get("improvements", []):
        md += f"- {i}\n"

    md += "\n## 🏁 Summary\n"
    for s in comments.get("summary", []):
        md += f"- {s}\n"

    return md.strip()


async def present_final_score(result: dict, lang: str = "en"):
    """Send the final evaluation in a nice markdown format to Chainlit UI, translated
    into the participant's teaching language. The scorer/evaluator agents themselves
    never see anything but English; only this presentation layer is translated."""
    comments = result.comments
    if lang != "en":
        translator = get_translation_service()
        comments = {
            "strengths": await translator.all_from_english(comments.get("strengths", []), lang),
            "improvements": await translator.all_from_english(comments.get("improvements", []), lang),
            "summary": await translator.all_from_english(comments.get("summary", []), lang),
        }
    md_output = format_final_score(comments)
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
    current_model = settings["Model"]
    print("Updated Model to: ", current_model)
    llm = get_llm(current_model)
    cl.user_session.set("llm", llm)
    user_topic = cl.user_session.get("topic")
    catalog = cl.user_session.get("catalog")
    student_chain, vs = build_student_chain(llm, user_topic, catalog)
    evaluator_chain = build_evaluator_chain(llm)
    scorer_chain = build_scorer_chain(llm)
    final_scorer_chain = build_final_scorer_chain(llm)
    cl.user_session.set("student_chain", student_chain)
    cl.user_session.set("evaluator_chain", evaluator_chain)
    cl.user_session.set("scorer_chain", scorer_chain)
    cl.user_session.set("final_scorer_chain", final_scorer_chain)


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
    await cl.Message(content=f"Welcome, {user.display_name or user.identifier}!").send()

    # Teaching language is picked once, up front, like subject/subtopic below —
    # unlike Model it is not reconfigurable mid-session via ChatSettings, since the
    # QA pool's ground-truth answers and every stored record are fixed to English.
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

    session_id = create_session(user.identifier, lang)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("session_memory", ConversationBufferMemory(return_messages=True))

    settings = await cl.ChatSettings(
        [
            Select(
                id="Model",
                label="Select Model",
                values=["openai/gpt-4o", "anthropic/claude-3.7-sonnet",
                        "google/gemini-2.5-pro"],
                initial_index=0
            )
        ]
    ).send()
    cl.user_session.set("llm", get_llm(settings["Model"]))

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

    # Step 1: Show main topics
    actions = [cl.Action(name=t, payload={"value": t}, label=t) for t in catalog.keys()]
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

    # Step 2: Build chains + vectorstore for chosen topic
    student_chain, vs = build_student_chain(llm, user_topic, catalog)
    evaluator_chain = build_evaluator_chain(llm)
    scorer_chain = build_scorer_chain(llm)
    final_scorer_chain = build_final_scorer_chain(llm)
    cl.user_session.set("student_chain", student_chain)
    cl.user_session.set("evaluator_chain", evaluator_chain)
    cl.user_session.set("scorer_chain", scorer_chain)
    cl.user_session.set("final_scorer_chain", final_scorer_chain)

    # Step 3: Generate subtopics (ONE API call)
    # subtopics = generate_subtopics(llm, vs)  # returns list of 10 standard subtopics
    subtopics = catalog[user_topic]["topics"]
    cl.user_session.set("subtopics", subtopics)

    # Step 4: Show subtopics to user and let them choose
    subtopic_actions = [cl.Action(name=s, payload={"value": s}, label=s) for s in subtopics]
    subtopic_res = await cl.AskActionMessage(
        content=await _localize(f"📖 Here are the topics for **{user_topic}**. Please choose one:", lang),
        actions=subtopic_actions
    ).send()

    chosen_subtopic = ""
    if subtopic_res and subtopic_res.get("payload").get("value"):
        chosen_subtopic = subtopic_res.get("payload").get("value")

    if chosen_subtopic not in subtopics:
        await cl.Message(content=await _localize(f"⚠️ '{chosen_subtopic}' is not a valid subtopic. Restart and try again.", lang)).send()
        return

    # Step 5: Generate student doubts/questions for the chosen subtopic (ONE API call)
    qa_pool = generate_qa_for_subtopic(llm, vs, chosen_subtopic)  # returns list of QAPair

    # Step 6: Store in session
    cl.user_session.set("qa_pool", qa_pool)
    cl.user_session.set("qa_index", 0)
    cl.user_session.set("topic", user_topic)
    cl.user_session.set("subtopic", chosen_subtopic)
    cl.user_session.set("followup_count", 0)
    session_memory = cl.user_session.get("session_memory")

    # Step 7: Kick off conversation
    if qa_pool:
        first_q = qa_pool[0].question
        content_en = (
            f"👩‍🎓 Student: Great! Let’s start with **{chosen_subtopic}**. "
            f"Here’s my first question:\n\n{first_q}"
        )
        message = cl.Message(content=await _localize(content_en, lang))
        await message.send()
        session_memory.chat_memory.add_ai_message(message.content)
    else:
        content_en = f"👩‍🎓 Student: I don’t have any questions for {chosen_subtopic} yet."
        message = cl.Message(content=await _localize(content_en, lang))
        await message.send()
        session_memory.chat_memory.add_ai_message(message.content)



# ------------------- MAIN LOOP ------------------- #
async def handle_teacher_turn(teacher_explanation: str):
    """Handle one teacher turn: student response, evaluation, and scoring.

    Shared by both typed messages (on_message) and dictated ones (on_audio_end) —
    a transcribed explanation goes through exactly the same pipeline as a typed one.
    """
    cl_user = cl.user_session.get("user")  # Chainlit User object
    session_id = cl.user_session.get("session_id")
    session_memory = cl.user_session.get("session_memory")
    lang = cl.user_session.get("lang", "en")
    if not cl_user:
        await cl.Message(content=await _localize("❌ User not authenticated.", lang)).send()
        return

    model_choice = cl.user_session.get("model", "gemini-1.5-flash")

    print(model_choice)

    # Extract normalized fields
    user_id = cl_user.identifier
    user_email = getattr(cl_user, "email", None)
    user_name = getattr(cl_user, "display_name", None)

    # Ensure user exists in DB
    create_user(user_id, user_email, user_name)

    # Load session state
    student_chain = cl.user_session.get("student_chain")
    evaluator_chain = cl.user_session.get("evaluator_chain")
    scorer_chain = cl.user_session.get("scorer_chain")
    qa_pool = cl.user_session.get("qa_pool", [])
    qa_index = cl.user_session.get("qa_index", 0)
    followup_count = cl.user_session.get("followup_count", 0)
    # Fetch all previous interactions of this session
    session_interaction_ids = fetch_session_interaction_ids(session_id)

    # Create new interaction entry
    interaction_id = create_interaction(session_id)

    # 1️⃣ Teacher provides explanation. The student/evaluator/scorer agents and every
    # stored record only ever see English; translate here, once, at the boundary.
    translator = get_translation_service()
    teacher_explanation_en = await translator.to_english(teacher_explanation, lang)
    teacher_model = TeacherResponse(message=teacher_explanation_en)
    save_teacher(interaction_id, teacher_model)
    session_memory.chat_memory.add_user_message(teacher_explanation_en)

    # Expected answer from QA pool
    expected_answer = qa_pool[qa_index].a if qa_index < len(qa_pool) else ""
    student_memory = fetch_student_memory(session_interaction_ids)
    # 2️⃣ Student generates response
    student_llm_response = student_chain.invoke({
        "teacher_explanation": teacher_explanation_en,
        "student_memory": student_memory
    })

    if isinstance(student_llm_response['text'], StudentResponse):
        student_model = student_llm_response['text']
    else:
        student_model = StudentResponse.parse_raw(student_llm_response['text'])

    save_student(interaction_id, student_model)

    # 3️⃣ Evaluator assesses
    evaluator_llm_response = evaluator_chain.invoke({
        "expected_explanation": expected_answer,
        "teacher_explanation": teacher_explanation_en,
        "student_question": qa_pool[qa_index].question,
        "student_followup_question": student_model.message,
        "student_response": student_model.json()
    })

    if isinstance(evaluator_llm_response['text'], EvaluatorResponse):
        evaluator_model = evaluator_llm_response['text']
    else:
        evaluator_model = EvaluatorResponse.parse_raw(
            evaluator_llm_response['text'])

    save_evaluator(interaction_id, evaluator_model)

    # 4️⃣ Scorer computes metrics
    scorer_llm_response = scorer_chain.invoke({
        "teacher_explanation": teacher_explanation_en,
        "student_question": qa_pool[qa_index].question,
        "student_followup_question": student_model.message,
        "student_response": student_model.json(),
        "evaluator_comments": evaluator_model.json()
    })

    if isinstance(scorer_llm_response['text'], ScorerResponse):
        scorer_model = scorer_llm_response['text']
    else:
        scorer_model = ScorerResponse.parse_raw(scorer_llm_response)

    save_scorer(interaction_id, scorer_model)

    # 5️⃣ Continue conversation
    if student_model.message and followup_count < 3:
        followup_count += 1
        student_message = await translator.from_english(student_model.message, lang) if lang != "en" else student_model.message
        message = cl.Message(content=f"👩‍🎓 Student: {student_message}")
        await message.send()
        session_memory.chat_memory.add_ai_message(message.content)
    else:
        if qa_index >= len(qa_pool)-1:
            message = cl.Message(content=await _localize("👩‍🎓 Student: Thank you for clarifying all my questions!", lang))
            stop_input()
            final_scorer_chain = cl.user_session.get("final_scorer_chain")
            interaction_scores = fetch_session_scores(session_id)
            print(interaction_scores)
            final_scorer_response = final_scorer_chain.invoke({
                "interaction_scores": interaction_scores
            })
            if isinstance(final_scorer_response['text'], FinalScorerResponse):
                final_scorer_model = final_scorer_response['text']
            else:
                final_scorer_model = FinalScorerResponse.parse_raw(final_scorer_response)
            await present_final_score(final_scorer_model, lang)
            stop_input()
        else:
            followup_count = 0
            message = cl.Message(content=await _localize("👩‍🎓 Student: I have another question!", lang))
            await message.send()
            session_memory.chat_memory.add_ai_message(message.content)
            qa_index += 1
            cl.user_session.set("qa_index", qa_index)
            if qa_index < len(qa_pool):
                next_q = qa_pool[qa_index].question
                if lang != "en":
                    next_q = await translator.from_english(next_q, lang)
                await cl.Message(content=f"👩‍🎓 Student: {next_q}").send()
    cl.user_session.set("followup_count", followup_count)


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
