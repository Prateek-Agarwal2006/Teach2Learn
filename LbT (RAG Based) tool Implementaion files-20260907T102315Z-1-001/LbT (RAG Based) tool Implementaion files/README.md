# Teach2Learn (RAG-based implementation)

A Learning-by-Teaching tutoring tool: the participant teaches a topic to an AI "student"
persona, which asks Bloom's-taxonomy-ordered follow-up questions grounded in real course
material via Retrieval-Augmented Generation. Built with Chainlit (UI), LangChain
(agent chains), MongoDB (session/interaction storage), and Chroma (vector store).

See `CHANGELOG.md` for what's changed over time, and the accompanying paper
(`Teach2Learn___ILE.pdf`, one directory up) for the system design and user study this
implementation is based on.

## Setup

```bash
python3 -m venv .venv  # or: uv venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # or: uv pip install -r requirements.txt
cp .env.example .env              # fill in OPENROUTER_API_KEY, SARVAM_API_KEY, MONGO_URI
```

You need a MongoDB instance reachable at `MONGO_URI` (a local `mongod`, or Atlas). The
LLM behind every agent (student/evaluator/scorer/summarizer) and the embeddings both run
through OpenRouter (`OPENROUTER_API_KEY`) — `models.py`'s `get_llm` points at OpenRouter's
`base_url`, and `ingest.py`/`qa_generator.py`/`student_chain.py`'s `OpenAIEmbeddings` need
`OPENAI_API_KEY`/`OPENAI_BASE_URL` set to the same OpenRouter key/endpoint (see
`.env.example`) since there's no dedicated OpenRouter override for embeddings.

```bash
chainlit run main.py
```

Google OAuth (`@cl.oauth_callback` in `main.py`) restricts sign-in to
`@pilani.bits-pilani.ac.in`. There's no local password-auth fallback in this codebase —
if you need one for local testing without real OAuth credentials, that's a temporary,
non-committed swap, not something this repo ships.

## Vector database

`vectorstore/` is committed to this repo, pre-built, so you don't need to re-run
embeddings (which costs real OpenRouter API calls) just to try the app. It covers all
four subjects, grounded in the actual BITS Pilani course textbooks:

| Subject | Source | Pages | Chunks |
|---|---|---|---|
| `cp` | Hanly & Koffman + 3 reference books (CS F111) | 2,289 | 7,530 |
| `dsa` | CLRS + Goodrich/Tamassia/Mount (CS F211) | 2,033 | 5,605 |
| `oop_java` | Schildt + Horstmann (CS F213) | 1,788 | 5,148 |
| `os` | Silberschatz & Galvin (CS F372) | 983 | 3,281 |

`vectorstore/catalog.json`'s topic lists per subject come from the real course handout
module breakdowns, not an invented taxonomy.

The raw source PDFs (`data/`, ~150MB of copyrighted textbooks) are **not** committed —
only the derived vector store is. To re-ingest (e.g. after adding a subject, or fixing a
PDF that failed to parse), drop source files under `data/<subject>/` and run:

```bash
python ingest.py
```

This appends to any existing vectorstore for a subject rather than replacing it, so
delete `vectorstore/<subject>/` first if you want a clean re-ingest for that subject.

**Known gap:** `CP_r2.pdf` (Forouzan & Gilberg) failed to parse ("EI stream not found" —
a malformed PDF stream) and was skipped; `cp` is grounded in the other 4 of 5 CP sources.

## Multilingual sessions and voice input

Both features are ported from the sibling FastAPI implementation
(`teach2learn-portal`) and documented in detail in `CHANGELOG.md`. In short: a language
picker at session start translates the AI's questions and the final summary into the
participant's language (Sarvam AI), and Chainlit's native microphone control lets
participants dictate instead of type (Sarvam Saaras or Whisper via OpenRouter). Stored
Mongo records and the evaluator/scorer chains always stay English.

## Tests

```bash
pytest tests/
```

Covers `translation.py` and `transcription.py` directly (mocked HTTP, no real API calls
needed). There's no Chainlit equivalent of FastAPI's `TestClient`, so the
endpoint/session-level tests that exist for the sibling FastAPI app don't have a
counterpart here — see `CHANGELOG.md` for what that means in practice.

## Language-quality verification

`scripts/check_languages.py` sweeps every supported teaching language through the real
translation boundary (seed → inbound → `student_chain` → outbound), checking for
untranslated passthrough and script leaks, plus an independent OpenRouter judge scoring
fidelity and fluency. See `CHANGELOG.md` for the last run's results.
