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
    scorer_collection,
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


def create_session(user_id: str, lang: str = "en"):
    session_id = str(uuid.uuid4())
    session_collection.insert_one({
        "_id": session_id,
        "user_id": user_id,
        "lang": lang,
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


def save_evaluator(interaction_id: str, model: BaseModel):
    evaluator_collection.insert_one({
        "_id": interaction_id,
        **model.dict(),
        "timestamp": datetime.utcnow()
    })


def save_scorer(interaction_id: str, model: BaseModel):
    scorer_collection.insert_one({
        "_id": interaction_id,
        **model.dict(),
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


def fetch_session_scores(session_id: str):
    session_interaction_ids = fetch_session_interaction_ids(session_id)
    session_scores = scorer_collection.find(
            {"_id": {"$in": session_interaction_ids}}
    )
    return list(session_scores)
