import os
import json
from typing import List
from langchain.chains import LLMChain
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path


load_dotenv()
VS_DIR = os.getenv("VS_DIR")
CATALOG_PATH = Path(VS_DIR + "/catalog.json")


def load_catalog():
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


class SubtopicsModel(BaseModel):
    topics: List[str]

# -------------------- Generate Subtopics --------------------


def generate_subtopics(llm, vs, n: int = 10) -> List[str]:
    """
    Generate 10 standard subtopics for a given topic using the RAG context.
    Returns a list of subtopic strings.
    """
    docs = vs.similarity_search("learning by teaching", k=n)
    context = "\n\n".join(d.page_content for d in docs)

    parser = PydanticOutputParser(pydantic_object=SubtopicsModel)
    template = """
    Based on the following textbook context, generate a list of 10 standard, clearly separated subtopics
    that cover the main topic comprehensively.

    Requirements:
    - Each subtopic should represent a distinct area/concept within the main topic.
    - Focus on technical, academic, and conceptual areas.
    - Avoid soft skills, learning strategies, or meta concepts.

    Respond ONLY in valid JSON following this schema:
    {format_instructions}

    Context:
    {context}
    """
    prompt = ChatPromptTemplate.from_template(template).partial(
        format_instructions=parser.get_format_instructions()
    )
    chain = LLMChain(llm=llm, prompt=prompt)
    result = chain.run(context=context)

    try:
        parsed = parser.parse(result)
        return parsed.topics
    except Exception as e:
        print("Subtopic parsing failed:", e)
        return []
