import uuid
import json
from pathlib import Path
from pydantic import BaseModel
from datetime import datetime
from db import (
    users_collection,
    interaction_collection,
    teacher_collection,
    student_collection,
    evaluator_collection,
    final_feedback_collection,
    session_collection
)
from models import StudentResponse


def create_user(user_id, user_email, user_name):
    users_collection.update_one(
        {"_id": user_id},
        {"$setOnInsert": {
            "_id": user_id,
            "email": user_email,
            "name": user_name,
            "created_at": datetime.utcnow()
        }},
        upsert=True
    )


def create_session(user_id: str, lang: str = "en", teacher_gender: str | None = None):
    session_id = str(uuid.uuid4())
    session_collection.insert_one({
        "_id": session_id,
        "user_id": user_id,
        "lang": lang,
        "teacher_gender": teacher_gender,
        "timestamp": datetime.utcnow()
    })
    return session_id


def create_interaction(session_id: str) -> str:
    """Create a new interaction entry for a user."""
    interaction_id = str(uuid.uuid4())
    interaction_collection.insert_one({
        "_id": interaction_id,
        "session_id": session_id,
        "timestamp": datetime.utcnow()
    })
    return interaction_id


def save_teacher(interaction_id: str, model: BaseModel):
    teacher_collection.insert_one({
        "_id": interaction_id,
        **model.dict(),
        "timestamp": datetime.utcnow()
    })


def save_student(interaction_id: str, model: BaseModel):
    student_collection.insert_one({
        "_id": interaction_id,
        **model.dict(),
        "timestamp": datetime.utcnow()
    })


def save_evaluator(
    interaction_id: str,
    model: BaseModel,
    turn: int,
    ai_question_en: str,
    teacher_answer_en: str,
):
    # `turn` is stored explicitly (not just inferred from Mongo's natural order) because
    # decide_completion() is entirely recency-dependent (evaluations[-1], [-2:], [-3:]),
    # and neither $in-query order nor these random-UUID _ids give a reliable chronological
    # signal to sort by otherwise.
    #
    # ai_question_en/teacher_answer_en make this collection double as a proper per-turn
    # chat log with its score attached, rather than requiring a join against
    # teacher_collection every time a researcher (or build_deterministic_feedback) wants
    # both the conversation text and its evaluation together.
    evaluator_collection.insert_one({
        "_id": interaction_id,
        **model.dict(),
        "turn": turn,
        "ai_question_en": ai_question_en,
        "teacher_answer_en": teacher_answer_en,
        "timestamp": datetime.utcnow()
    })


def fetch_session_interaction_ids(session_id: str):
    session_interactions = interaction_collection.find(
        {"session_id": session_id},
        {"_id": 1}
    )
    interaction_ids = [i["_id"] for i in session_interactions]
    return interaction_ids


def fetch_student_memory(session_interaction_ids: list):
    student_memory_docs = student_collection.find(
        {"_id": {"$in": session_interaction_ids}}
    )
    student_memory = [StudentResponse(**doc) for doc in student_memory_docs]
    return student_memory


def fetch_session_evaluations(session_id: str):
    """All of this session's turn evaluations, ordered by turn -- decide_completion()'s
    recency-based logic depends on real chronological order, not Mongo's natural order."""
    session_interaction_ids = fetch_session_interaction_ids(session_id)
    docs = evaluator_collection.find(
        {"_id": {"$in": session_interaction_ids}}
    ).sort("turn", 1)
    return list(docs)


def fetch_session_turns(session_id: str):
    """Each turn's chat log reshaped for teaching_feedback.build_deterministic_feedback(),
    which needs teacher text alongside level/score/strength/improvement to compute its
    average-words/final-level summary. No join needed -- save_evaluator() already stores
    the turn's text alongside its score."""
    return [
        {
            "teacher_text": doc.get("teacher_answer_en", ""),
            "level": doc.get("level", ""),
            "score": doc.get("score", ""),
            "strength": doc.get("strength", ""),
            "improvement": doc.get("improvement", ""),
        }
        for doc in fetch_session_evaluations(session_id)
    ]


def save_final_feedback(session_id: str, data: dict):
    final_feedback_collection.replace_one(
        {"_id": session_id},
        {
            "_id": session_id,
            **data,
            "timestamp": datetime.utcnow()
        },
        upsert=True
    )
