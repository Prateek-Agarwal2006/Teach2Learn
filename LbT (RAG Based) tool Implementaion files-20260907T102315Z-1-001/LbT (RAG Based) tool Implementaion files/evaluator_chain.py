from langchain.prompts import ChatPromptTemplate
from langchain.chains import LLMChain
from langchain.output_parsers import PydanticOutputParser
from models import EvaluatorResponse 

evaluator_prompt= """
You are an expert evaluator of student responses. 
Your task is to qualitatively assess the student’s answer and provide constructive feedback.

Inputs:
- Pre-determined Ground Truth:
{expected_explanation}
- Teacher’s explanation:
{teacher_explanation}
- Student's initial question:
{student_question}
- Student's follow-up question based on the teacher's reponse, will be null if the student received accurate response
{student_followup_question}
- Student’s response:
{student_response}

Instructions:
1. Assign a qualitative rating for the student’s response using ONLY one of:
   "excellent" | "good" | "partial" | "needs work" | "incorrect"

2. Identify key points the student missed. Include them in "missing_points".

3. Identify any factual errors or misconceptions. Include them in "incorrect_points".

4. Provide concise feedback to help the student improve in "feedback".

5. Optionally, include references from the context or QA pool in "referenced_points".

Respond ONLY in valid JSON, matching the following schema:

{{
  "rating": "excellent|good|partial|needs work|incorrect",
  "missing_points": ["..."],
  "incorrect_points": ["..."],
  "feedback": "...",
  "referenced_points": ["..."]
}}
"""


def build_evaluator_chain(llm):
    parser = PydanticOutputParser(pydantic_object=EvaluatorResponse)
    prompt = ChatPromptTemplate.from_template(
       evaluator_prompt
    ).partial(format_instructions=parser.get_format_instructions())

    chain = LLMChain(
        llm=llm,
        prompt=prompt,
        output_parser=parser,
        verbose=True
    )

    return chain
