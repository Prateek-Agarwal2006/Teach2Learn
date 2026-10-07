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
You are a curious student learning from the teacher. You do not have any prior knowledge of the topic other than the Student Context and Course Material provided below.

Course Material (retrieved from the textbook, for your reference only — never tell the
teacher you have a textbook; you are learning only from what they explain):
{context}

Student Context:
{student_memory}

Teacher explanation:
"{teacher_explanation}"

Your task:
- Decide how well you understood the explanation.
  * If it made sense overall, even if it wasn’t detailed, → rating = "understood", message = null
  * If you’re still very confused → rating = "confused", but ask ONE short and polite clarifying question
  * If the Course Material above contradicts or is clearly more complete than what the teacher said, treat that as still-confused and gently ask about the specific gap, without ever citing or naming the material itself.
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


def build_vectorstore(topic: str, catalog: dict):
    """Return the Chroma vectorstore for a given topic -- split out from chain-building
    since retrieval depends only on catalog/topic, never on the teaching LLM, so callers
    can cache this across a teaching-model switch instead of reopening the same Chroma
    persist_directory on every settings update."""
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    topic_info = catalog.get(topic)
    if not topic_info:
        raise ValueError(f"Topic '{topic}' not found in catalog")
    vs_path = topic_info["vectorstore_path"]
    return Chroma(persist_directory=vs_path, embedding_function=embeddings)


def build_student_chain_only(llm):
    """The LLM chain half of build_student_chain, decoupled from vectorstore setup."""
    parser = PydanticOutputParser(pydantic_object=StudentResponse)
    prompt = ChatPromptTemplate.from_template(student_prompt).partial(
        format_instructions=parser.get_format_instructions()
    )
    return LLMChain(llm=llm, prompt=prompt, output_parser=parser)


def build_student_chain(llm, topic: str, catalog: dict):
    """Return (LLM chain, vectorstore) for a given topic using catalog path."""
    vs = build_vectorstore(topic, catalog)
    chain = build_student_chain_only(llm)
    return chain, vs


_OPENING_SENTINEL = (
    "[SYSTEM TRIGGER]: The lesson is starting. The teacher has not said anything yet "
    "-- introduce yourself briefly and ask your first question about the subtopic."
)


def generate_opening_question(chain, vs, subtopic: str) -> StudentResponse:
    """Dynamically generate the session's opening question, grounded on the subtopic
    itself (there's no teacher explanation yet to search retrieval on). Replaces the old
    pre-baked qa_pool[0] -- every outbound student turn, opening included, now comes from
    one live call to the same chain instead of a fixed Bloom's-taxonomy pool."""
    context_docs = vs.similarity_search(subtopic, k=4)
    context = "\n\n".join(doc.page_content for doc in context_docs)
    response = chain.invoke({
        "teacher_explanation": _OPENING_SENTINEL,
        "student_memory": [],
        "context": context,
    })
    result = response["text"]
    return result if isinstance(result, StudentResponse) else StudentResponse.parse_raw(result)


def outbound_text(student_model: StudentResponse) -> str:
    """What the participant reads back. The student sometimes has no follow-up
    (rating="understood", message=None) -- unlike a fine-tuned adapter that always
    asks something -- so fall back to the always-populated reflection text."""
    return student_model.message or student_model.reflection
