from app.services.study_evaluator import evaluate_conversation
from app.services.teaching_feedback import build_teaching_feedback, parse_final_teaching_feedback


def test_structured_assessments_become_visible_feedback():
    transcript = [
        {"role": "assistant", "content": "What is it?"},
        {"role": "user", "content": "A mutex protects a shared critical section."},
        {
            "role": "assistant",
            "content": "Can you give an example?",
            "inline_evaluation": {
                "level": "Understand",
                "score": "High",
                "strength": "You clearly connected the mutex to shared state.",
                "improvement": "Add a concrete two-thread example.",
            },
        },
    ]

    feedback = build_teaching_feedback(transcript)
    assert feedback["final_level"] == "Understand"
    assert feedback["strengths"] == ["You clearly connected the mutex to shared state."]
    assert feedback["improvements"] == ["Add a concrete two-thread example."]
    assert "1 explanation" in feedback["summary"]


def test_legacy_feedback_and_fallbacks_are_supported():
    transcript = [
        {"role": "user", "content": "It synchronizes access."},
        {
            "role": "assistant",
            "content": "Why?",
            "inline_evaluation": {
                "level": "Remember",
                "score": "Low",
                "feedback": "Explain what can go wrong without the mutex.",
            },
        },
    ]
    feedback = build_teaching_feedback(transcript)
    assert feedback["strengths"]
    assert feedback["improvements"] == ["Explain what can go wrong without the mutex."]


def test_study_evaluation_persists_teaching_feedback():
    result = evaluate_conversation(
        [
            {"role": "user", "content": "A detailed explanation with an example."},
            {"role": "assistant", "content": "Why does that work?"},
        ]
    )
    assert result["rubric_version"] == "conversation-baseline-v2"
    assert result["teaching_feedback"]["summary"]


def test_final_evaluator_output_is_parsed_and_bounded():
    fallback = {
        "summary": "Fallback summary.",
        "strengths": ["Fallback strength."],
        "improvements": ["Fallback improvement."],
    }
    result = parse_final_teaching_feedback(
        """<final_feedback>
Strength: Clear explanation of the core mechanism.
Strength: Useful connection to the example.
Improvement: Explain the tradeoff explicitly.
Improvement: Check understanding before moving on.
Summary: You built the explanation progressively and used relevant details.
</final_feedback>""",
        fallback,
    )
    assert result["generation"] == "independent_final_evaluator"
    assert len(result["strengths"]) == 2
    assert result["summary"].startswith("You built")


def test_incomplete_final_evaluator_output_uses_fallbacks():
    fallback = {
        "summary": "Fallback summary.",
        "strengths": ["Fallback strength."],
        "improvements": ["Fallback improvement."],
    }
    result = parse_final_teaching_feedback("Strength: Only one field.", fallback)
    assert result["generation"] == "deterministic_fallback"
    assert result["improvements"] == fallback["improvements"]
    assert result["summary"] == fallback["summary"]


def test_xml_final_evaluator_and_hybrid_completion_are_supported():
    fallback = {
        "summary": "Fallback summary.",
        "strengths": ["Evidence-backed fallback strength."],
        "improvements": ["Fallback improvement."],
    }
    result = parse_final_teaching_feedback(
        """<final_feedback>
<strength>Clear explanation of the central idea.</strength>
<improvement>Add a worked example.</improvement>
<improvement>Explain the tradeoff.</improvement>
<summary>You explained the concept clearly but could add more practical detail.</summary>
</final_feedback>""",
        fallback,
    )
    assert result["generation"] == "hybrid_final_evaluator"
    assert result["strengths"] == [
        "Clear explanation of the central idea.",
        "Evidence-backed fallback strength.",
    ]
    assert len(result["improvements"]) == 2
