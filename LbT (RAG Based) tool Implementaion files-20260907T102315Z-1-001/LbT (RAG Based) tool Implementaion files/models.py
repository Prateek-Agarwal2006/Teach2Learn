import os
from typing import List, Optional, Literal
from pydantic import BaseModel
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
    rating: Literal["understood", "confused"]
    reflection: str  # Student’s meta-understanding: e.g. "I didn’t understand sorting properly."
    missing_points: List[str] = []  # Gaps in knowledge


# -------------------------------
# Turn evaluator -- mirrors teach2learn-portal's <evaluation> block field-for-field
# (Level/Score/Strength/Improvement), so app/services/completion.py's decide_completion
# can be ported verbatim and operate on these dicts with zero adaptation.
# -------------------------------
class TurnEvaluationResponse(BaseModel):
    level: str  # Remember | Understand | Apply | Analyze | Evaluate | Create
    score: str  # Low | Medium | High
    strength: str
    improvement: str


# -------------------------------
# Final feedback -- mirrors teach2learn-portal's <final_feedback> block
# -------------------------------
class FinalFeedbackResponse(BaseModel):
    strengths: List[str]
    improvements: List[str]
    summary: str
