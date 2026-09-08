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


class QAPair(BaseModel):
    question: str
    a: str


class QAList(BaseModel):
    questions: List[QAPair]

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

# -------------------- Generate Student Doubts for Subtopic --------------------


def generate_qa_for_subtopic(llm, vs, subtopic: str, n: int = 5) -> List[QAPair]:
    """
    Generate a list of 1-2 genuine student doubts/questions for a given subtopic.
    Returns a list of QAPair objects.
    """
    docs = vs.similarity_search(subtopic, k=n)
    context = "\n\n".join(d.page_content for d in docs)

    parser = PydanticOutputParser(pydantic_object=QAList)
    template = """
    Based on the following subtopic: "{subtopic}", generate 5 questions that reflect genuine
    doubts a student might have while learning this topic.

    Requirements:
    - Difficulty must progress from easy to hard, following Bloom’s Taxonomy:  
      - Q1: Remember (definitions, facts)  
      - Q2: Understand (explanations, distinctions)  
      - Q3: Apply (examples, real-world usage)  
      - Q4: Analyze (comparisons, mechanisms, cause-effect)  
      - Q5: Evaluate/Create (critiques, design, hypothetical scenarios)  
    - Provide concise and correct answers for each question.  
    - Avoid exam-style phrasing (no “explain in detail” or “discuss”).  
    - Questions should reflect genuine student doubts that could arise when learning.  
    - Output must be valid JSON in the following schema:

    One-shot Example:  
    Subtopic: "TCP vs UDP"  
    Output:
    [
      {{
        "question": "Why do we need both TCP and UDP if they are both transport layer protocols?",
        "answer": "TCP provides reliable, connection-oriented communication, while UDP offers faster, connectionless communication without reliability guarantees."
      }},
      {{
        "question": "How does TCP ensure reliability while UDP does not?",
        "answer": "TCP uses acknowledgments, retransmissions, and sequence numbers, whereas UDP simply sends datagrams without error recovery."
      }},
      {{
        "question": "In what situations would using UDP be preferred over TCP?",
        "answer": "UDP is preferred for real-time applications like video streaming, gaming, or VoIP, where low latency is more important than reliability."
      }},
      {{
        "question": "How does TCP handle congestion control differently from flow control?",
        "answer": "Flow control prevents overwhelming the receiver using a sliding window, while congestion control prevents overloading the network using algorithms like AIMD and slow start."
      }},
      {{
        "question": "Why does TCP require a 3-way handshake, and what would go wrong with only 2 steps?",
        "answer": "The 3-way handshake ensures both sides can send and receive, preventing half-open connections. A 2-step process could leave one side believing a connection exists when the other does not."
      }}
    ]


    Respond ONLY in valid JSON following this schema:
    {format_instructions}

    Context:
    {context}
    """
    prompt = ChatPromptTemplate.from_template(template).partial(
        subtopic=subtopic,
        format_instructions=parser.get_format_instructions()
    )
    chain = LLMChain(llm=llm, prompt=prompt)
    result = chain.run(context=context)

    try:
        parsed = parser.parse(result)
        print(parsed)
        return parsed.questions
    except Exception as e:
        print(f"QA parsing failed for subtopic '{subtopic}':", e)
        return []
