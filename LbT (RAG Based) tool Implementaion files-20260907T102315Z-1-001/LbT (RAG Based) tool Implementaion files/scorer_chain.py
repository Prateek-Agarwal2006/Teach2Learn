from langchain.prompts import ChatPromptTemplate
from langchain.chains import LLMChain
from langchain.output_parsers import PydanticOutputParser
from models import ScorerResponse, FinalScorerResponse
from dotenv import load_dotenv 

load_dotenv()

scorer_prompt = """
You are an automated scorer for a teaching-learning interaction.
You are given the following details of a single interaction:

- teacher_explanation: What the teacher explained.
- student_question: The initial question asked by the student.
- student_followup_question: Any follow-up question from the student.
- student_response: The response of the student (message, rating, reflection, missing_points).
- evaluator_comments: Qualitative feedback from the evaluator.

Your task is to produce a **quantitative evaluation** of the interaction as a JSON object
matching the following Pydantic model `ScorerResponse`:

{{
  "overall_score": "float between 0.0 and 1.0",
  "teacher_clarity": "float between 0.0 and 1.0",
  "teacher_completeness": "float between 0.0 and 1.0",
  "student_understanding": "float between 0.0 and 1.0",
  "student_engagement": "float between 0.0 and 1.0",
  "comments": ["string"]
}}

Rules:

1. All scores must be **between 0.0 and 1.0** inclusive.
2. Provide all scores; do not leave any field blank.
3. Comments should summarize any important qualitative insights.
4. Respond **ONLY** in valid JSON corresponding to the `ScorerResponse` model.

Interaction details:

teacher_explanation: {teacher_explanation}
student_question: {student_question}
student_followup_question: {student_followup_question}
student_response: {student_response}
evaluator_comments: {evaluator_comments}
"""


def build_scorer_chain(llm):
    """Build the LLM chain for scoring interactions."""
    parser = PydanticOutputParser(pydantic_object=ScorerResponse)

    prompt = ChatPromptTemplate.from_template(scorer_prompt).partial(
        format_instructions=parser.get_format_instructions()
    )

    chain = LLMChain(llm=llm, prompt=prompt, output_parser=parser)
    return chain


final_score_prompt = """
You are a professional evaluator, think clearly and perform the following actions.
The session consists of multiple teacher-student interactions.
Each interaction has already been evaluated with subscores in the following categories:
- teacher_clarity (0.0–1.0)
- teacher_completeness (0.0–1.0)
- student_understanding (0.0–1.0)
- student_engagement (0.0–1.0)

You will now provide a final, session-level evaluation by:
1. Reviewing the trend of scores across all interactions.
2. Highlighting strengths (where performance was consistently good).
3. Highlighting weaknesses (where performance dipped or was inconsistent).
4. Providing a concise but actionable summary of how the teacher and student performed overall.

### Instructions:
- Do not simply average the numbers — also consider trends (improvement, decline, or stability).
- Use the numerical scores to support your reasoning.
- Always include at least one **positive highlight** and one **improvement suggestion**.
- Write all the comments in a teacher oriented way. In the sense that you are evaluating the teachers responses and explaination.
- Do not be overly critical while giving remarks, be genuinley helpful and polite while giving feedback.

### LIST OF INTERACTION SCORES ###
{interaction_scores}
### END OF LIST ###

Return your result in the exact JSON format described below.
{{
  "overall_score": float,  // 0.0 to 1.0
  "teacher_clarity": float,  // 0.0 to 1.0
  "teacher_completeness": float,  // 0.0 to 1.0
  "student_understanding": float,  // 0.0 to 1.0
  "student_engagement": float,  // 0.0 to 1.0
  "comments": {{
    "strengths": [string],
    "improvements": [string],
    "summary": [string]
  }}
}}
"""


def build_final_scorer_chain(llm):
    parser = PydanticOutputParser(pydantic_object=FinalScorerResponse)

    prompt = ChatPromptTemplate.from_template(final_score_prompt).partial(
            format_instructions=parser.get_format_instructions()
    )

    chain = LLMChain(llm=llm, prompt=prompt, output_parser=parser)
    return chain
