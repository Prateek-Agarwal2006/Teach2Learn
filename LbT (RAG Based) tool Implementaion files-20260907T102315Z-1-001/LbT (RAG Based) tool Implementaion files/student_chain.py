import os
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.prompts import ChatPromptTemplate
from langchain.chains import LLMChain
from langchain.output_parsers import PydanticOutputParser
from models import StudentResponse
from dotenv import load_dotenv 

load_dotenv()

student_prompt = """
You are a curious student learning from the teacher. You do not have any prior knowledge of the topic other than the Student Context provided below.

Student Context:
{student_memory}

Teacher explanation:
"{teacher_explanation}"

Your task:
- Decide how well you understood the explanation.
  * If it made sense overall, even if it wasn’t detailed, → rating = "understood", message = null
  * If you’re still very confused → rating = "confused", but ask ONE short and polite clarifying question
- Write a short reflection about your understanding in natural language, e.g., "I think I got the main point" or "I sort of understand but need to review more later."
- If you noticed anything missing, keep it very light and optional (e.g., "maybe more detail later could help"), but only if really needed.

**Always show appreciation for the teacher’s effort. Assume the explanation was helpful enough for now, even if not perfect.**

Respond ONLY in valid JSON that matches this schema:
{{
  "message": "Your follow-up question or null",
  "rating": "understood|confused",
  "reflection": "How you understood the concept",
  "missing_points": ["point1", "point2"]
}}
"""


def build_student_chain(llm, topic: str, catalog: dict):
    """Return (LLM chain, vectorstore) for a given topic using catalog path."""
    # Embeddings
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    # Get vectorstore path from catalog
    topic_info = catalog.get(topic)
    if not topic_info:
        raise ValueError(f"Topic '{topic}' not found in catalog")

    vs_path = topic_info["vectorstore_path"]

    # Load Chroma for this topic
    vs = Chroma(
        persist_directory=vs_path,
        embedding_function=embeddings
    )

    # Parser
    parser = PydanticOutputParser(pydantic_object=StudentResponse)

    # Prompt with parser format instructions
    prompt = ChatPromptTemplate.from_template(student_prompt).partial(
        format_instructions=parser.get_format_instructions()
    )

    # Chain
    chain = LLMChain(llm=llm, prompt=prompt, output_parser=parser)

    return chain, vs
