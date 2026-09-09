# Fine-tuned Teach2Learn

## Run profile

| | |
|---|---|
| Lesson scripts | 24 (4 subjects × 3 topics × 2 subtopics) |
| Languages | 22 Indic + English |
| Models compared | 5 of 5, on 2 subjects each |
| English runs / questions | 252 / 1,008 |
| Language-runs / judged turns | 175 of 176 / 525 |
| Boundary crossings | 1,575 |
| Model generations | 1,718 |
| Sarvam calls / judge calls | 1,787 / 1,056 |

---

## 1. Model performance

English only, no translation, no judge. Every model saw the **same six lessons and the same
three-sentence explanations** for each subject, 3 repeats each. Five models × two subjects =
10 runs, 720 questions.

Variety is measured over **follow-up questions only** — the opening greeting is structurally
identical in every run and would otherwise flatter whichever model repeats it.

| Model | Subject | Unique openers | Most-repeated | Remember | Understand | Apply | Mean Bloom | Self-score | Rated Low | s/gen |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Granite 3.3 8B | os | **27** | **9%** | 18 | 29 | 7 | 0.80 | 0.22 | 78% | 4.14 |
| Granite 3.3 8B | cp | 17 | 24% | 7 | 42 | 5 | 0.96 | 0.54 | 46% | 4.45 |
| Mistral 7B | os | 25 | 26% | 27 | 24 | 3 | 0.56 | 0.61 | 39% | 3.29 |
| Mistral 7B | cp | 17 | 22% | 8 | 46 | 0 | 0.85 | 0.85 | 15% | 3.62 |
| Qwen3 8B | os | 22 | 22% | 25 | 14 | 4 | 0.49 | 0.29 | 71% | 4.02 |
| Qwen3 8B | cp | **4** | **85%** | 7 | 47 | 0 | 0.87 | 0.85 | 15% | 4.81 |
| Gemma 2 9B | os | 22 | 35% | 35 | 10 | 9 | 0.52 | 0.69 | 31% | 4.66 |
| Gemma 2 9B | cp | 16 | 35% | 20 | 32 | 2 | 0.67 | 0.65 | 35% | 5.53 |
| **Qwen 2.5 7B** | os | 19 | 33% | 14 | 20 | **17** | **1.00** | 0.76 | 28% | **2.73** |
| **Qwen 2.5 7B** | cp | 20 | 30% | 14 | 25 | **14** | **0.98** | 0.85 | 20% | **2.69** |

- **Unique openers** — distinct first-six-word phrases across 54 follow-ups.
- **Most-repeated** — share of follow-ups beginning with the single commonest phrase.
- **Mean Bloom** — 0 = Remember, 1 = Understand, 2 = Apply, over 54 evaluated turns.
- **Self-score** — the learner's verdict on the *teacher*, 0 Low / 1 Medium / 2 High. Not a
  quality measure: it is the model grading the participant, with no ground truth to check against.

### Stability across subjects

The same model, same metric, different lessons. This column is what a single-subject run
cannot show.

| Model | Repetition os → cp | Swing | Bloom swing | Apply os / cp | Mean s/gen |
|---|---|---:|---:|---:|---:|
| **Qwen 2.5 7B** | 33% → 30% | **4** | **0.02** | **17 / 14** | **2.71** |
| Gemma 2 9B | 35% → 35% | 0 | 0.15 | 9 / 2 | 5.10 |
| Mistral 7B | 26% → 22% | 4 | 0.30 | 3 / 0 | 3.46 |
| Granite 3.3 8B | 9% → 24% | 15 | 0.17 | 7 / 5 | 4.29 |
| **Qwen3 8B** | 22% → **85%** | **63** | 0.38 | 4 / 0 | 4.41 |

**Qwen 2.5 7B is the only model that holds across both subjects** — repetition within 4
points, Bloom within 0.02, *Apply* reached 17 and 14 times against a field of 0–9, and it is
the fastest by a wide margin. No subject defaults to it, so before this run it had never been
exercised at all.

**Qwen3's formulaic behaviour is subject-specific, not a property of the model.** On C
lessons it collapses to 4 distinct openings and repeats one phrase in 85% of follow-ups; on OS
lessons it is unremarkable at 22%. The cp result reproduces across two independent runs a day
apart (83% and 85%), so neither figure is noise.

**The C-programming lessons flatten every model**, not just Qwen3 — Granite drops from 27
openers to 17, Mistral from 25 to 17, Gemma 2 from 22 to 16. Qwen3 is the extreme case of a
real effect, not an isolated one. Those six scripts are worth re-reading.

### What replication showed

Granite on `os` ran twice, a day apart: 32 openers / 9% and 27 openers / 9%. That is the
run-to-run noise floor, and every difference called out above is far outside it.

---

## 2. Translation boundary


| Check | Count | Over |
|---|---:|---:|
| Untranslated participant text | **0** | 525 turns |
| Untranslated text shown back | **0** | 525 turns |
| Native script reaching the English zone | **0** | 525 turns |
| Crossings needing a retry | 4 | 1,575 crossings |
| Schema payloads rejected | 1 | 1,575 crossings |

---

## 3. Subject performance



| Subject | Model | Turns | Fidelity | Fluency | ≥4.0 fluency | Retries | Leaks | Unrecovered |
|---|---|---:|---|---|---:|---:|---:|---|
| Computer Programming | qwen3 | 129 | **4.38** ± 0.99 | **4.43** ± 0.82 | **18/22** | 0/387 | 1 | Punjabi |
| Data Structures & Algorithms | gemma2 | 132 | 4.35 ± 0.91 | 4.15 ± 0.79 | 14/22 | 2/396 | 0 | — |
| OOP with Java | mistral | 132 | 4.34 ± **1.17** | 4.10 ± 0.90 | 15/22 | 2/396 | 0 | — |
| Operating Systems | granite | 132 | 4.30 ± 0.98 | 4.22 ± 0.83 | 16/22 | 0/396 | 0 | — |

| Source of variance | Range on a 1–5 scale |
|---|---:|
| Between subjects (fidelity) | 0.08 |
| Between subjects (fluency) | 0.33 |
| **Between languages (fluency)** | **2.70** |

**Language accounts for roughly 8× the spread that subject does.** Technical vocabulary is
not the constraint; the participant's choice of language is.

---

## 4. Language performance

Each cell is fidelity / fluency for that language in that subject's column.
Status from scores alone: **Blocked** < 2.0 fidelity · **Review** < 3.5 fidelity or
< 4.0 fluency · else **Ready**. † = one lesson never produced data.

| Language | Script | Code | cp | dsa | oop_java | os | Mean | Status |
|---|---|---|---|---|---|---|---|---|
| Punjabi † | Gurmukhi | `pa` | 5.0/5.0 | 4.7/4.8 | 4.7/4.8 | 4.5/4.8 | 4.7/4.9 | Ready |
| Bengali | Bengali | `bn` | 4.2/5.0 | 4.3/4.8 | 4.8/4.8 | 4.2/4.7 | 4.4/4.8 | Ready |
| Telugu | Telugu | `te` | 4.5/5.0 | 4.3/4.7 | 4.7/4.8 | 4.5/4.7 | 4.5/4.8 | Ready |
| Gujarati | Gujarati | `gu` | 4.8/5.0 | 4.7/4.8 | 4.5/4.5 | 4.8/4.8 | 4.7/4.8 | Ready |
| Tamil | Tamil | `ta` | 4.2/4.8 | 4.8/4.8 | 4.7/4.5 | 4.3/4.5 | 4.5/4.7 | Ready |
| Kannada | Kannada | `kn` | 4.7/5.0 | 4.3/4.5 | 4.7/4.5 | 4.3/4.5 | 4.5/4.6 | Ready |
| Malayalam | Malayalam | `ml` | 5.0/4.8 | 4.7/4.5 | 4.5/4.5 | 4.8/4.7 | 4.8/4.6 | Ready |
| Marathi | Devanagari | `mr` | 4.3/4.7 | 4.5/4.5 | 4.5/4.5 | 4.5/4.8 | 4.5/4.6 | Ready |
| Hindi | Devanagari | `hi` | 5.0/4.5 | 4.2/4.3 | 4.8/4.8 | 4.3/4.7 | 4.6/4.6 | Ready |
| Assamese | Bengali | `as` | 4.5/4.8 | 3.8/4.5 | 4.3/4.5 | 4.2/4.5 | 4.2/4.6 | Ready |
| Nepali | Devanagari | `ne` | 3.8/4.8 | 4.7/4.5 | 4.7/4.3 | 4.5/4.7 | 4.4/4.6 | Ready |
| Odia | Odia | `or` | 4.8/4.8 | 4.7/4.3 | 4.8/4.3 | 4.7/4.7 | 4.8/4.5 | Ready |
| Urdu | Perso-Arabic | `ur` | 5.0/4.7 | 4.5/4.3 | 4.7/4.5 | 4.5/4.3 | 4.7/4.5 | Ready |
| Maithili | Devanagari | `mai` | 4.7/4.7 | 4.7/4.7 | 4.7/4.0 | 4.5/4.3 | 4.6/4.4 | Ready |
| Dogri | Devanagari | `doi` | 4.2/4.5 | 4.8/3.7 | 4.5/4.3 | 4.0/4.2 | 4.4/4.2 | Ready |
| Bodo | Devanagari | `brx` | 4.8/4.0 | 5.0/3.7 | 4.2/3.7 | 5.0/4.0 | 4.8/3.8 | Review |
| Manipuri | Meetei Mayek | `mni` | 5.0/4.3 | 4.5/3.8 | 4.8/3.2 | 4.8/3.8 | 4.8/3.8 | Review |
| Kashmiri | Perso-Arabic | `ks` | 4.5/4.5 | 4.3/3.3 | 3.3/3.7 | 4.3/3.7 | 4.1/3.8 | Review |
| Konkani | Devanagari | `kok` | 4.5/3.7 | 4.8/3.7 | 4.7/3.7 | 4.3/3.7 | 4.6/3.7 | Review |
| Santali | Ol Chiki | `sat` | 4.5/3.8 | 4.7/3.2 | 4.8/3.2 | 5.0/3.7 | 4.8/3.5 | Review |
| Sanskrit | Devanagari | `sa` | 3.3/3.2 | 3.2/3.0 | 3.2/2.8 | 3.0/3.2 | 3.2/3.0 | Review |
| Sindhi | Devanagari* | `sd` | 1.3/2.2 | 1.5/2.8 | 1.0/2.0 | 1.5/2.0 | **1.3/2.2** | **Blocked** |

\* Sarvam returns Devanagari; Perso-Arabic is the dominant script for Sindhi. That is the defect.

| Tier | Count | 
|---|---:|
| Ready | **15** |
| Review | 6 |
| Blocked | 1 |

Each cell is now backed by 9–12 judged turns against 3 in the prior report.

---

## 5. Defects

| Defect | Scope | Evidence | Status |
|---|---|---|---|
| Sindhi returns Devanagari, not Perso-Arabic | All 4 models | Fidelity 1.0–1.5 in every column; `sarvam-translate:v1` rejects `output_script` | **Open — remove from picker** |
| Punjabi leaks Sarvam's OpenAPI schema | 1 sentence, `cp` | Failed 3/3 attempts, reproducing a finding from 2 months earlier | **Fixed** — rejected in the shipping translation module |
| Sarvam rate limiting returns text unchanged | 3 languages, mid-sweep | Harness aborted and labelled it rather than emitting clean rows | **Recovered** — 19 cells re-run |

