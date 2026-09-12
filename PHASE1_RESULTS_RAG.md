# RAG-based Teach2Learn

Companion to `PHASE1_RESULTS.md` (the fine-tuned portal's results), run against the same
`lessons.json` bank, the same 22 languages, the same judge model and judge prompts (aligned
2026-09-12; the finetuned side's fluency was re-scored to match), and the byte-identical
(now schema-leak-fixed) `translation.py`. Where the finetuned side routes each subject to
a different fine-tuned local model, this system has one general LLM (`openai/gpt-4o`, via
OpenRouter) playing the student, grounded per turn by a `similarity_search` against the
real ingested textbooks — see `RAG_TEST_PLAN.md` for why the two systems' native
evaluations (this tool's `evaluator_chain`/`scorer_chain` vs. the portal's inline
`Level`/`Score`) are excluded from this comparison rather than placed beside each other.

## Run profile

| | |
|---|---|
| Lesson scripts | 24 (same bank; question-variety run) / 8 (same bank; language sweep — the confirmed comparison subset) |
| Languages | 22 Indic + English |
| Student model | `openai/gpt-4o`, pinned (via OpenRouter), temperature 0.25, top-p 0.9 |
| Decoding difference | The finetuned side ran at temperature **0.2**, not the 0.25 `TEST_BED.md` specifies. Recorded, not corrected — re-running that side needs the GPU host. |
| English runs / questions | 72 / 288 |
| Language-runs / judged turns | 175 of 176 / 525 |
| Boundary crossings | 1,575 |
| Sarvam calls / judge calls | 1,750 / 1,050 |
| Measured cost | $3.44 OpenRouter + ₹430.67 (~$5.15) Sarvam ≈ **$8.59 total**, read from OpenRouter's `/credits` endpoint before/after, not estimated |

---

## 1. Question variety

English only, no translation, no judge, run against **all 24 lessons, 3 repeats each** —
same lesson bank and repeat count as the portal's Sweep A. Unlike the portal, there is only
one student here (no per-subject fine-tuned model to compare against itself), so this
section reports variety directly rather than as a five-way comparison.

Variety is measured over **follow-up questions only** — the opening question is retrieval-
generated once per lesson and would otherwise flatter every run identically.

| Subject | Model | Lessons | Runs | Distinct question ratio | Runs with repeated openers | Most repeated opening |
|---|---|---:|---:|---|---:|---|
| Computer Programming | gpt-4o | 6 | 18 | 0.86 (0.50–1.00) | 14/18 | 8× "could you explain how associativity affects…" |
| Data Structures and Algorithms | gpt-4o | 6 | 18 | 0.92 (0.50–1.00) | 16/18 | 27× "i think i got the main…" |
| OOP with Java | gpt-4o | 6 | 18 | 0.90 (0.75–1.00) | 10/18 | 7× "could you explain how thread priorities…" |
| Operating Systems | gpt-4o | 6 | 18 | 0.93 (0.75–1.00) | 13/18 | 9× "could you explain how the scheduler…" |

**No Bloom-level or adapter-score column** — this student has no fine-tuned inline
evaluation to report, and fabricating one against the portal's `Level`/`Score` vocabulary
would be exactly the confound `RAG_TEST_PLAN.md` warns against. `student_rating`
("understood"/"confused") is recorded per turn in the raw JSON but isn't a Bloom measure.

**Repeated openers are common here too** — 53 of 72 runs (74%) had at least one recurring
opening phrase, comparable to the portal's finding that formulaic follow-ups are a real,
widespread pattern rather than an artifact of one model or one architecture.

---

## 2. Translation boundary

Identical `translation.py` to the portal (now including the schema-leak fix), run over the
8-lesson comparison subset.

| Check | Count | Over |
|---|---:|---:|
| Untranslated participant text | **0** | 525 turns |
| Untranslated text shown back | **0** | 525 turns |
| Native script reaching the English zone | **0** | 525 turns |
| Crossings needing a retry | 0 | 1,575 crossings |
| Schema payloads rejected | 1 | 1,575 crossings |

The one rejected schema payload is the same known Punjabi/`cp` defect the portal found —
see Defects below.

---

## 3. Subject performance

| Subject | Model | Turns | Fidelity | Fluency | ≥4.0 fluency | Retries | Leaks | Unrecovered |
|---|---|---:|---|---|---:|---:|---:|---|
| Computer Programming | gpt-4o | 129 | 4.35 ± 1.06 | 4.31 ± 0.86 | 17/22 | 0/387 | 0 | Punjabi |
| Data Structures & Algorithms | gpt-4o | 132 | 4.36 ± 0.96 | 4.31 ± 0.87 | 17/22 | 0/396 | 0 | — |
| OOP with Java | gpt-4o | 132 | 4.39 ± 1.13 | 4.23 ± 0.89 | 16/22 | 0/396 | 0 | — |
| Operating Systems | gpt-4o | 132 | 4.30 ± 1.01 | 4.35 ± 0.81 | 18/22 | 0/396 | 0 | — |

| Source of variance | Range on a 1–5 scale |
|---|---:|
| Between subjects (fidelity) | 0.09 |
| Between subjects (fluency) | 0.12 |
| **Between languages (fluency)** | **~3.1** (Sindhi 1.9 to Malayalam 4.9) |

Same finding as the portal: **language accounts for far more spread than subject does.**
The four subject rows are within a few hundredths of each other; the language column below
spans the full range.

---

## 4. Language performance

Each cell is fidelity / fluency for that language in that subject's column. Status from
scores alone: **Blocked** < 2.0 fidelity · **Review** < 3.5 fidelity or < 4.0 fluency ·
else **Ready**. † = one lesson never produced data (Punjabi, the schema-leak cell).

| Language | Script | Code | cp | dsa | oop_java | os | Mean | Status |
|---|---|---|---|---|---|---|---|---|
| Malayalam | Malayalam | `ml` | 5.0/4.8 | 4.8/4.8 | 4.5/5.0 | 5.0/5.0 | 4.8/4.9 | Ready |
| Punjabi † | Gurmukhi | `pa` | 4.3/5.0 | 4.8/5.0 | 4.7/4.8 | 4.3/5.0 | 4.6/5.0 | Ready |
| Gujarati | Gujarati | `gu` | 4.8/4.8 | 4.7/4.8 | 4.5/4.7 | 4.8/4.8 | 4.7/4.8 | Ready |
| Urdu | Perso-Arabic | `ur` | 4.8/5.0 | 4.7/4.8 | 4.7/4.8 | 4.5/4.7 | 4.7/4.8 | Ready |
| Hindi | Devanagari | `hi` | 5.0/5.0 | 4.3/4.7 | 4.7/4.5 | 4.5/5.0 | 4.6/4.8 | Ready |
| Telugu | Telugu | `te` | 4.2/4.8 | 4.0/4.7 | 4.7/4.8 | 4.5/5.0 | 4.3/4.8 | Ready |
| Odia | Odia | `or` | 4.5/4.7 | 4.5/4.7 | 4.7/4.5 | 4.5/5.0 | 4.5/4.7 | Ready |
| Nepali | Devanagari | `ne` | 4.0/5.0 | 4.7/4.7 | 4.7/4.5 | 4.3/4.7 | 4.4/4.7 | Ready |
| Kannada | Kannada | `kn` | 4.7/4.5 | 4.3/4.7 | 4.7/4.8 | 4.5/4.7 | 4.5/4.7 | Ready |
| Bengali | Bengali | `bn` | 4.3/4.5 | 4.3/4.8 | 4.7/4.8 | 4.2/4.7 | 4.4/4.7 | Ready |
| Marathi | Devanagari | `mr` | 4.3/4.7 | 4.3/4.7 | 4.5/4.7 | 4.3/4.7 | 4.4/4.7 | Ready |
| Assamese | Bengali | `as` | 4.7/4.5 | 4.7/4.5 | 4.5/4.8 | 4.3/4.7 | 4.5/4.6 | Ready |
| Tamil | Tamil | `ta` | 4.0/5.0 | 4.5/4.7 | 4.7/4.5 | 4.3/4.2 | 4.4/4.6 | Ready |
| Maithili | Devanagari | `mai` | 4.7/4.5 | 4.7/4.5 | 4.8/4.2 | 4.2/4.3 | 4.6/4.4 | Ready |
| Dogri | Devanagari | `doi` | 4.2/4.2 | 4.7/4.5 | 4.5/4.2 | 4.3/4.2 | 4.4/4.2 | Ready |
| Bodo | Devanagari | `brx` | 4.8/4.0 | 4.8/4.0 | 4.3/3.8 | 5.0/4.0 | 4.8/4.0 | Review |
| Kashmiri | Perso-Arabic | `ks` | 4.7/4.0 | 4.7/4.2 | 4.3/3.5 | 4.3/4.2 | 4.5/4.0 | Review |
| Konkani | Devanagari | `kok` | 4.3/3.7 | 4.8/3.8 | 4.7/3.8 | 4.5/4.0 | 4.6/3.8 | Review |
| Manipuri | Meetei Mayek | `mni` | 5.0/4.0 | 4.5/3.7 | 5.0/3.7 | 5.0/3.8 | 4.9/3.8 | Review |
| Santali | Ol Chiki | `sat` | 4.8/3.3 | 4.8/3.6 | 4.8/3.3 | 5.0/4.0 | 4.9/3.6 | Review |
| Sanskrit | Devanagari | `sa` | 3.5/3.2 | 3.3/3.2 | 3.2/3.5 | 3.0/3.2 | 3.2/3.2 | Review |
| Sindhi | Devanagari* | `sd` | 1.0/2.0 | 1.0/1.8 | 1.0/1.7 | 1.0/2.0 | **1.0/1.9** | **Blocked** |

\* Sarvam returns Devanagari; Perso-Arabic is the dominant script for Sindhi — identical
defect to the portal, confirming it's upstream in Sarvam, not either application.

| Tier | Count |
|---|---:|
| Ready | **15** |
| Review | 6 |
| Blocked | 1 |

**Identical tier counts to the portal's 15/6/1**, and the same two languages (Sanskrit,
Sindhi) are the weakest on both systems. Given the two "student" architectures share
nothing except the translation layer, this is strong evidence that language quality here is
governed almost entirely by Sarvam, not by which system is teaching.

---

## 5. Defects

| Defect | Scope | Evidence | Status |
|---|---|---|---|
| Sindhi returns Devanagari, not Perso-Arabic | All subjects | Fidelity 1.0 in every column, identical to the portal | **Open — same upstream Sarvam limitation, not fixable here** |
| Punjabi leaks Sarvam's OpenAPI schema | 1 sentence, `cp/pointers/dynamic-memory-allocation` | Same sentence and subject as the portal's finding; 3/3 attempts | **Fixed** — schema-leak guard ported into this project's `translation.py` before this run |
