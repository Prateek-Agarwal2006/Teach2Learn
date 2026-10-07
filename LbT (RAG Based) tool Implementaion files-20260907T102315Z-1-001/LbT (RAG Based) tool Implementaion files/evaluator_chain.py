from langchain.prompts import ChatPromptTemplate
from langchain.chains import LLMChain
from langchain.output_parsers import PydanticOutputParser
from models import TurnEvaluationResponse, FinalFeedbackResponse

# Independent, ungrounded per-turn judge -- mirrors teach2learn-portal's
# TURN_EVALUATOR_PROMPT exactly in intent: judges only the supplied AI question and
# teacher answer, no retrieval, no ground-truth answer key. Never sees {context}.
evaluator_prompt = """
You are an independent turn evaluator in a fresh chat. Evaluate only the supplied
learner question and teacher answer -- you have no other context.

Selected subtopic:
{subtopic}

AI learner's previous question (or reflection, if it had no question):
{last_ai_en}

Human teacher's answer:
{teacher_explanation_en}

Instructions:
1. Assign a Level using ONLY one of: Remember, Understand, Apply, Analyze, Evaluate, Create.
2. Assign a Score using ONLY one of: Low, Medium, High.
3. Give one specific, constructive Strength.
4. Give one specific, constructive Improvement.
Do not ask a follow-up question. Be grounded only in the supplied answer.

Respond ONLY in valid JSON, matching the following schema:

{{
  "level": "Remember|Understand|Apply|Analyze|Evaluate|Create",
  "score": "Low|Medium|High",
  "strength": "...",
  "improvement": "..."
}}
"""


def build_evaluator_chain(llm):
    parser = PydanticOutputParser(pydantic_object=TurnEvaluationResponse)
    prompt = ChatPromptTemplate.from_template(
        evaluator_prompt
    ).partial(format_instructions=parser.get_format_instructions())

    return LLMChain(llm=llm, prompt=prompt, output_parser=parser)


# Independent, ungrounded session-final judge -- mirrors FINAL_EVALUATOR_PROMPT. Reviews
# only the visible English conversation, never retrieval context, and addresses the
# teacher as "you". Built from the same fixed judge model as build_evaluator_chain, kept
# independent of whichever model the participant is being taught by.
final_feedback_prompt = """
You are an independent final teaching evaluator in a fresh chat. Review only the
supplied visible conversation. Produce constructive participant-facing feedback
grounded in what the teacher actually said. Address the teacher as "you". Do not invent
student reactions, grades, personal details, or facts absent from the conversation.

Visible conversation:
{transcript}

Respond ONLY in valid JSON, matching the following schema:

{{
  "strengths": ["...", "..."],
  "improvements": ["...", "..."],
  "summary": "..."
}}
"""


def build_final_feedback_chain(llm):
    parser = PydanticOutputParser(pydantic_object=FinalFeedbackResponse)
    prompt = ChatPromptTemplate.from_template(
        final_feedback_prompt
    ).partial(format_instructions=parser.get_format_instructions())

    return LLMChain(llm=llm, prompt=prompt, output_parser=parser)
