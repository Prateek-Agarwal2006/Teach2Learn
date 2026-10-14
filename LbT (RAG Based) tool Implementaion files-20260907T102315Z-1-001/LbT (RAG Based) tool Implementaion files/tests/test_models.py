"""Round-trip the new judge-chain response models through PydanticOutputParser against
hand-written JSON, catching schema drift cheaply without an API call."""

import json

import pytest
from langchain.output_parsers import PydanticOutputParser

from models import FinalFeedbackResponse, StudentResponse, TurnEvaluationResponse


def test_turn_evaluation_response_parses_valid_json():
    parser = PydanticOutputParser(pydantic_object=TurnEvaluationResponse)
    payload = json.dumps({
        "level": "Understand",
        "score": "Medium",
        "strength": "Clear explanation of the core idea.",
        "improvement": "Add a concrete example.",
    })
    result = parser.parse(payload)
    assert result.level == "Understand"
    assert result.score == "Medium"
    assert result.strength
    assert result.improvement


def test_turn_evaluation_response_rejects_missing_fields():
    parser = PydanticOutputParser(pydantic_object=TurnEvaluationResponse)
    with pytest.raises(Exception):
        parser.parse(json.dumps({"level": "Understand", "score": "Medium"}))


def test_final_feedback_response_parses_valid_json():
    parser = PydanticOutputParser(pydantic_object=FinalFeedbackResponse)
    payload = json.dumps({
        "strengths": ["Explained clearly.", "Answered follow-ups well."],
        "improvements": ["Add an example.", "Check understanding before moving on."],
        "summary": "You built a solid explanation across the session.",
    })
    result = parser.parse(payload)
    assert len(result.strengths) == 2
    assert len(result.improvements) == 2
    assert result.summary


def test_final_feedback_response_rejects_missing_fields():
    parser = PydanticOutputParser(pydantic_object=FinalFeedbackResponse)
    with pytest.raises(Exception):
        parser.parse(json.dumps({"strengths": ["Explained clearly."]}))


def test_student_response_rating_is_tightened_to_two_values():
    # The student prompt only ever instructs "understood" or "confused" --
    # "needs work" is dead/unreachable and was removed from the schema.
    StudentResponse(message=None, rating="understood", reflection="Got it.", missing_points=[])
    StudentResponse(message="What about X?", rating="confused", reflection="Still unsure.", missing_points=[])
    with pytest.raises(Exception):
        StudentResponse(message=None, rating="needs work", reflection="Got it.", missing_points=[])


def test_student_samples_like_the_finetuned_portal_and_judge_does_not():
    from models import get_llm, get_student_llm

    student = get_student_llm("any/model")
    assert (student.temperature, student.top_p) == (0.2, 0.9)
    assert get_llm("any/model").top_p is None
