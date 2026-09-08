import os
from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, confloat
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")


def get_llm(model_name: str):
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=API_KEY,
        model=f"{model_name}"
    )

# -------------------------------
# Teacher
# -------------------------------


class TeacherResponse(BaseModel):
    message: str  # Explanation of the concept


# -------------------------------
# Student
# -------------------------------
class StudentResponse(BaseModel):
    # Follow-up question, can be null if fully understood
    message: Optional[str]
    rating: Literal["understood", "needs work", "confused"]
    reflection: str  # Student’s meta-understanding: e.g. "I didn’t understand sorting properly."
    missing_points: List[str] = []  # Gaps in knowledge


# -------------------------------
# Evaluator
# -------------------------------
class EvaluatorResponse(BaseModel):
    rating: str  # "excellent" | "good" | "partial" | "needs work" | "incorrect"
    missing_points: Optional[List[str]] = []
    incorrect_points: Optional[List[str]] = []
    feedback: Optional[str] = None
    referenced_points: Optional[List[str]] = []


# -------------------------------
# Scorer
# -------------------------------
class ScorerResponse(BaseModel):
    overall_score: confloat(ge=0.0, le=1.0)
    # Subscores (0.0 to 1.0)
    teacher_clarity: confloat(ge=0.0, le=1.0)
    teacher_completeness: confloat(ge=0.0, le=1.0)
    student_understanding: confloat(ge=0.0, le=1.0)
    student_engagement: confloat(ge=0.0, le=1.0)
    # Comments are required, even if empty
    comments: List[str]


# -------------------------------
# Final Score
# -------------------------------
class FinalScorerResponse(BaseModel):
    overall_score: confloat(ge=0.0, le=1.0)
    # Aggregated subscores (session-wide, 0.0–1.0)
    teacher_clarity: confloat(ge=0.0, le=1.0)
    teacher_completeness: confloat(ge=0.0, le=1.0)
    student_understanding: confloat(ge=0.0, le=1.0)
    student_engagement: confloat(ge=0.0, le=1.0)
    # Structured feedback
    comments: Dict[str, List[str]]
