import os
import glob
import json
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma

# Paths
load_dotenv()
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
VS_DIR = VS_DIR = Path(os.getenv("VS_DIR", Path(__file__).resolve().parents[1] / "vectorstore"))
CATALOG_PATH = VS_DIR / "catalog.json"


def load_documents(topic_dir: Path):
    """Load PDFs, TXTs, and MDs from a topic folder with detailed logging."""
    docs = []

    pdf_paths = glob.glob(str(topic_dir / "*.pdf"))
    txt_paths = glob.glob(str(topic_dir / "*.txt"))
    md_paths = glob.glob(str(topic_dir / "*.md"))

    print(f"[ingest] Found {len(pdf_paths)} PDFs, {len(txt_paths)} TXTs, {len(md_paths)} MDs in {topic_dir}")

    for p in pdf_paths:
        try:
            print(f"[ingest] Loading PDF: {p}")
            pages = PyPDFLoader(p).load()
            print(f"[ingest]   -> Loaded {len(pages)} pages from {Path(p).name}")
            docs.extend(pages)
        except Exception as e:
            print(f"[ingest] Failed to load PDF {p}: {e}")

    for p in txt_paths + md_paths:
        try:
            print(f"[ingest] Loading text file: {p}")
            texts = TextLoader(p, encoding="utf-8").load()
            print(f"[ingest]   -> Loaded {len(texts)} document(s) from {Path(p).name}")
            docs.extend(texts)
        except Exception as e:
            print(f"[ingest] Failed to load text {p}: {e}")

    print(f"[ingest] Total loaded documents for {topic_dir.name}: {len(docs)}")
    return docs


def split_docs(docs, topic: str):
    """Split into manageable chunks for embeddings with logging."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        is_separator_regex=False,
    )
    splits = splitter.split_documents(docs)
    print(f"[ingest] Split {len(docs)} documents into {len(splits)} chunks for topic={topic}")
    return splits


def build_vectorstore(splits, topic: str, batch_size: int = 64):
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    topic_vs_dir = VS_DIR / topic

    print(f"[ingest] Building vectorstore for topic={topic} at {topic_vs_dir}")
    vs = Chroma(
        embedding_function=embeddings,
        persist_directory=str(topic_vs_dir),
    )

    # Insert in batches with progress bar
    for i in tqdm(range(0, len(splits), batch_size), desc=f"[{topic}] Embedding"):
        batch = splits[i: i + batch_size]
        vs.add_documents(batch)

    vs.persist()
    print(
        f"[ingest]   -> Vectorstore built with {len(splits)} chunks for {topic}")
    return vs


def update_catalog(topics):
    """Create or update catalog.json with topics and descriptions."""
    catalog = {}
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            catalog = json.load(f)

    for topic in topics:
        if topic not in catalog:
            catalog[topic] = {
                "description": f"This folder contains materials for {topic}.",
                "vectorstore_path": str(VS_DIR / topic),
            }

    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=4)
    print(f"[ingest] Catalog updated at {CATALOG_PATH}")


def main():
    load_dotenv()
    print(f"[ingest] DATA_DIR={DATA_DIR}")
    print(f"[ingest] VS_DIR={VS_DIR}")

    if not DATA_DIR.exists():
        print(f"[ingest] Data directory not found: {DATA_DIR}")
        return

    topic_dirs = [d for d in DATA_DIR.iterdir() if d.is_dir()]
    if not topic_dirs:
        print(f"[ingest] No topic folders found inside {DATA_DIR}")
        return

    processed_topics = []

    for topic_dir in topic_dirs:
        topic = topic_dir.name
        print(f"\n[ingest] === Processing topic: {topic} ===")
        docs = load_documents(topic_dir)
        if not docs:
            print(f"[ingest] No documents found in {topic_dir}, skipping...")
            continue

        splits = split_docs(docs, topic)
        _ = build_vectorstore(splits, topic)

        print(f"[ingest] Finished processing topic {topic}: {len(docs)} docs → {len(splits)} chunks")
        processed_topics.append(topic)

    if processed_topics:
        update_catalog(processed_topics)
        print(f"[ingest] All topics processed: {processed_topics}")


if __name__ == "__main__":
    main()
