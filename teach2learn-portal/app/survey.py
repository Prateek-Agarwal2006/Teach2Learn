from __future__ import annotations

from typing import Any, Mapping


INSTRUMENT_ID = "equitablet2l-hci-student-v1"
LIKERT_SCALE = {
    1: "Strongly Disagree",
    2: "Disagree",
    3: "Neutral",
    4: "Agree",
    5: "Strongly Agree",
}

QUANTITATIVE_SECTIONS = (
    (
        "Evaluation of EquitableT2L",
        (
            ("q01", "EquitableT2L consistently behaved like a beginner throughout the interaction."),
            ("q02", "EquitableT2L avoided giving expert-level explanations before teaching the concept."),
            ("q03", "EquitableT2L asked questions that encouraged me to explain concepts in detail."),
            ("q04", "EquitableT2L recalled concepts I had explained earlier and applied them to later questions."),
            ("q05", "The questions asked by EquitableT2L became progressively more advanced as the interaction continued."),
            ("q06", "EquitableT2L remained in the learner role throughout the session, without switching to the expert role."),
            ("q07", "The follow-up questions asked by EquitableT2L felt relevant and natural."),
            ("q08", "The final feedback from EquitableT2L accurately reflected how well I taught the topic."),
            ("q09", "Overall, the behavior of EquitableT2L supported the Learning-by-Teaching process."),
        ),
    ),
    (
        "Effectiveness for Learning",
        (
            ("q10", "Teaching EquitableT2L helped me identify gaps in my understanding."),
            ("q11", "Teaching EquitableT2L improved my understanding of the topic."),
            ("q12", "I would use EquitableT2L again for future learning."),
        ),
    ),
)

BACKGROUND_PROMPT = (
    "Can you tell us a little about yourself, such as your academic background and experience with the topic?"
)

QUALITATIVE_QUESTIONS = (
    ("q01", "How believable was EquitableT2L as a beginner learner? What made it feel realistic or unrealistic?"),
    ("q02", "Were there any moments when EquitableT2L behaved more like an expert than a learner? Please describe them."),
    ("q03", "How effectively did EquitableT2L build on your previous explanations during the interaction?"),
    ("q04", "How did the questions asked by EquitableT2L influence the way you explained the topic?"),
    ("q05", "What did you think about the feedback provided by EquitableT2L? How could it be improved?"),
    ("q06", "What changes would make EquitableT2L a more effective Learning-by-Teaching partner?"),
)


def _quantitative_items() -> tuple[tuple[str, str], ...]:
    return tuple(item for _, section in QUANTITATIVE_SECTIONS for item in section)


def parse_hci_student_survey(form: Mapping[str, Any]) -> dict[str, Any]:
    quantitative: dict[str, dict[str, Any]] = {}
    for key, statement in _quantitative_items():
        value = str(form.get(f"quant_{key}", "")).strip()
        if value not in {"1", "2", "3", "4", "5"}:
            raise ValueError("Please answer every agreement-scale question.")
        rating = int(value)
        quantitative[key] = {
            "statement": statement,
            "rating": rating,
            "label": LIKERT_SCALE[rating],
        }

    qualitative: dict[str, dict[str, str]] = {}
    for key, question in QUALITATIVE_QUESTIONS:
        response = str(form.get(f"qual_{key}", "")).strip()
        if not response:
            raise ValueError("Please answer every written reflection question.")
        if len(response) > 2000:
            raise ValueError("Each written response must be 2,000 characters or fewer.")
        qualitative[key] = {"question": question, "response": response}

    background = str(form.get("background", "")).strip()
    if len(background) > 2000:
        raise ValueError("The background response must be 2,000 characters or fewer.")

    return {
        "instrument_id": INSTRUMENT_ID,
        "respondent_role": "student",
        "scale": {str(key): value for key, value in LIKERT_SCALE.items()},
        "quantitative": quantitative,
        "qualitative": {
            "background": {
                "question": BACKGROUND_PROMPT,
                "response": background,
                "optional": True,
            },
            "responses": qualitative,
        },
    }
