# Fine-tuned Teach2Learn

## Run profile

| | |
|---|---|
| Lesson scripts | 24 (4 subjects × 3 topics × 2 subtopics) |
| Languages | 22 Indic + English |
| English runs / questions | 72 / 288 |
| Language-runs / judged turns | 175 of 176 / 525 |
| Boundary crossings | 1,575 |
| Model generations | 998 |
| Sarvam calls / judge calls | 1,787 / 1,056 |

---

## 1. Model performance

English only, no translation, no judge. Each model saw the identical 3-sentence
explanation for its paired subject, 6 lessons × 3 repeats.

| Model | Q | Unique openers | Repeated openings | Words/Q | Remember | Understand | Apply | Self-score | Rated Low | s/gen |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| Granite 3.3 8B | 72 | **33** | **6 · 8%** | 19.5 ± 5.4 | 17 | 29 | **8** | **0.11** | **89%** | 4.18 |
| Mistral 7B | 72 | 19 | 11 · 15% | 20.4 ± 5.4 | 14 | 40 | 0 | 0.74 | 26% | **3.53** |
| Gemma 2 9B | 72 | 15 | 24 · 33% | 20.8 ± 4.4 | 11 | 41 | 2 | 0.72 | 28% | 4.88 |
| Qwen3 8B | 72 | **7** | **61 · 85%** | 23.3 ± 3.9 | 8 | 46 | 0 | 0.83 | 17% | 4.70 |

- **Unique openers** — distinct first-six-word phrases across 72 questions. Whole-string
  uniqueness was 1.00 for every model, which hides this: Qwen3 wrote 72 different questions
  from 7 openings, Granite from 33.
- **Self-score** — the learner's own verdict on the teacher, 0 = Low, 1 = Medium, 2 = High.
- **Remember / Understand / Apply** — Bloom level reached, 54 evaluated turns per model.
  Nothing reached *Analyse* or above.
- Each model ran only its default subject (Granite→os, Mistral→oop_java, Gemma 2→dsa,
  Qwen3→cp), so a row difference is a model *and* a subject difference.


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

| Tier | Count | Prior report |
|---|---:|---:|
| Ready | **15** | 13 |
| Review | 6 | 7 |
| Blocked | 1 | 2 |

Each cell is now backed by 9–12 judged turns against 3 in the prior report.

---

## 5. Defects

| Defect | Scope | Evidence | Status |
|---|---|---|---|
| Sindhi returns Devanagari, not Perso-Arabic | All 4 models | Fidelity 1.0–1.5 in every column; `sarvam-translate:v1` rejects `output_script` | **Open — remove from picker** |
| Punjabi leaks Sarvam's OpenAPI schema | 1 sentence, `cp` | Failed 3/3 attempts, reproducing a finding from 2 months earlier | **Fixed** — rejected in the shipping translation module |
| Sarvam rate limiting returns text unchanged | 3 languages, mid-sweep | Harness aborted and labelled it rather than emitting clean rows | **Recovered** — 19 cells re-run |

### What is actually wrong with Sindhi

**Sindhi is written in two different alphabets.** Most Sindhi speakers read it in a
Perso-Arabic script — سنڌي. Some write it in Devanagari — सिन्धी, the same alphabet Hindi
uses. Sarvam always returns the Devanagari one.

So a participant picks Sindhi and gets back text in an alphabet many of them cannot read.
The *words* are often right; the *script* is wrong. It is like asking for Serbian and
receiving it in Latin letters when you only read Cyrillic — technically the language, but
not readable.

- **Not our bug.** The same failure appears in all four subject columns at 1.0–1.5 fidelity.
  A problem in one model would not show up identically in the other three.
- **Not fixable from our side.** The Sarvam API has no working setting for output script;
  `output_script` with `roman`, `fully-native` and `spoken-form-in-native` all return an
  HTTP 400 error. There is no request we can send that changes it.
- **What to do.** Remove Sindhi from the language picker until Sarvam supports the script.

### What is actually wrong with Punjabi

**The translation API returned a piece of its own documentation instead of a translation.**

Sarvam has a feature for gendered translations — it can give you a "female" version of a
sentence. For one particular sentence in the C-programming lesson, translated to Punjabi,
the API sent back the *description of that feature* rather than doing the translation:

```
{'description': 'The translation of the source sentence assuming the subject is female.',
 'title': 'Female', 'type': 'string'}
```

- **Why it got through.** Our code asked "is the reply a non-empty piece of text?" That blob
  is a non-empty piece of text, so it passed. It would then have been handed to the AI
  student as the participant's own explanation, written into the transcript, and shown back
  on screen in the middle of the lesson.
- **It is reproducible, and narrow.** Same sentence, same language, failed 3 of 3 attempts,
  and it failed the same way two months ago. The same sentence into Hindi, Gujarati and
  Bengali is fine, and a different sentence into Punjabi is fine. It is that one
  sentence-and-language pair.
- **Fixed.** The shipping translation module now checks whether a reply looks like
  documentation rather than a translation, and falls back to showing the original English —
  the same behaviour as when the network fails, and far better than a wall of JSON.
