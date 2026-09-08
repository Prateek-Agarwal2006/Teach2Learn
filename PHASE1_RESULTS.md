# Phase 1 Results

The expanded test bed, run against the real fine-tuned adapters on the GPU host,
8 September 2026. Setup is described in `TEST_BED.md`; this is what came out of it.

**Both parts complete.** `RAG_TEST_PLAN.md` describes how to reproduce this on the RAG
implementation so the two can be compared.

---

## Part 1 — English: does the learner behave like a learner?

**24 lessons · 4 subjects · 3 topics per subject · 3 repeats · 72 runs · 288 questions**

This is the run the expanded test bed was built for. Each subject routes to a different
fine-tuned model, so four subjects means four models receiving byte-identical teacher
input from the shared lesson bank. No translation and no judge are involved: this asks
only whether the learner varies, probes, and assesses sensibly in English.

Every figure below rests on six lessons per subject run three times each, rather than
one script run once as in `LANGUAGE_TEST_RESULTS.md`.

### The four models behave measurably differently

| Subject | Model | Repeated openings (of 72 questions) | Mean self-score (of 2) | Rated Low | Reached Apply |
|---|---|---:|---:|---:|---:|
| Operating Systems | Granite 3.3 8B | **6 (8%)** | **0.11** | **89%** | **8** |
| OOP with Java | Mistral 7B | 11 (15%) | 0.74 | 26% | 0 |
| Data Structures | Gemma 2 9B | 24 (33%) | 0.72 | 28% | 2 |
| Computer Programming | Qwen3 8B | **61 (85%)** | **0.83** | 17% | 0 |

Read across a row and each model has a consistent character. **Granite behaves like a
demanding learner**: it almost never reuses a phrasing, it rates the same three-sentence
explanation Low nine times out of ten, and it is the only model that reaches Bloom's
*Apply* with any regularity. **Qwen3 is its opposite**: it opens 85% of its questions the
same way, accepts the explanation as adequate, and never gets past *Understand*.

Since all four received the identical teacher text, this is a property of the fine-tuning,
not of the lesson.

### Textual distinctness hides all of this

The distinct-question ratio is **1.00 for every subject, every lesson, every repeat**. No
model ever asked the literally same question twice.

That number is nearly worthless on its own. Qwen3's questions are all distinct *and* 85%
of them begin `"That makes sense, but I'm still..."`. Whole-string comparison scores four
questions that share an opening clause and diverge afterwards as four different questions.
The harness's opener check was written for exactly this, and the two measures have to be
reported together or the formulaic case reads as a perfect score.

### Why this matters for the language results

The harness argues that translation cannot rescue a repetitive learner, so a poor English
baseline would make the whole language sweep meaningless. That has been an assumption
until now. It is now measured: no model is repetitive by the strict measure, and the
weakest — Qwen3 — is formulaic in its openings but still on-topic and varied in substance.

The language results therefore rest on a learner that genuinely varies. That is a claim
the paper can now support with evidence rather than assert.

### Where the learner stayed shallow

Bloom level reached, pooled across all 216 evaluated turns: *Understand* dominates with
156, *Remember* accounts for 50, and *Apply* for just 10 — eight of those from Granite.
Nothing reached *Analyse* or above.

This is expected and is a property of the test bed rather than of the models: the scripted
teacher says three sentences and never responds to what the learner asks. A real
participant answers the follow-up, which is what would push the exchange higher. It is a
limitation to state, not a result to report.

### Reliability

- 72 of 72 runs completed. No aborts, no failed generations, no unparsed evaluations.
- Every lesson was human-reviewed before the run; no result carries the unreviewed stamp.
- Four of the 24 lessons are carried verbatim from `LANGUAGE_TEST_RESULTS.md`, so those
  cells remain directly comparable to the earlier report.

---

## Part 2 — Languages: does the boundary hold, and for whom?

**8 lessons · 22 languages · 175 language-runs · 525 judged turns**

Two lessons per subject, one of each pair carried over from `LANGUAGE_TEST_RESULTS.md`,
pushed through every language the translation layer supports. Full tables in
`teach2learn-portal/results-languages.md`.

### The mechanical checks are clean

| | Count | Over |
|---|---|---|
| Untranslated participant text | 0 | 525 turns |
| Untranslated text shown back | 0 | 525 turns |
| Native script reaching the English zone | 0 | 525 turns |
| Crossings needing a retry | 4 | 1,575 crossings |

These carry no opinion and are the figures to quote. The model never saw a non-Latin
character; the participant never saw an English one.

### Fifteen ready, six for review, one blocked

Judged fidelity and fluency, 1–5, from an independent model. Status comes from scores
alone: Blocked under 2.0 fidelity, Review under 3.5 fidelity or 4.0 fluency, else Ready.

- **Ready (15)** — Punjabi, Bengali, Telugu, Gujarati, Tamil, Kannada, Malayalam, Marathi,
  Hindi, Assamese, Nepali, Odia, Urdu, Maithili, Dogri
- **Review (6)** — Bodo, Manipuri, Kashmiri, Konkani, Santali, Sanskrit. All show the same
  pattern: fidelity intact, phrasing stilted. Usable, not broken; they need a native reader.
- **Blocked (1)** — Sindhi, at 1.3 fidelity across all four columns.

Against the earlier report this is 15/6/1 versus 13/7/2, with each cell now backed by
9–12 judged turns instead of 3.

### Language explains roughly eight times the spread that subject does

| Subject | Judged turns | Fidelity | Fluency | ≥4.0 fluency |
|---|---|---|---|---|
| Computer Programming | 129 | 4.38 ± 0.99 | 4.43 ± 0.82 | 18 / 22 |
| Data Structures and Algorithms | 132 | 4.35 ± 0.91 | 4.15 ± 0.79 | 14 / 22 |
| OOP with Java | 132 | 4.34 ± 1.17 | 4.10 ± 0.90 | 15 / 22 |
| Operating Systems | 132 | 4.30 ± 0.98 | 4.22 ± 0.83 | 16 / 22 |

Mean fidelity spans 4.30–4.38 across subjects, a range of 0.08 on a five-point scale.
Across languages, fluency spans 2.2–4.9, a range of 2.7. **Technical vocabulary is not the
constraint — the choice of language is.** Pointers and `malloc` translate as well as heaps
and recurrences.

### Two failures, both understood

- **Sindhi returns the wrong script.** Sarvam renders Devanagari (सिन्धी) where
  Perso-Arabic (سنڌي) is dominant. Identical across all four models, which places the fault
  upstream rather than in any adapter, and `sarvam-translate:v1` rejects `output_script`.
  Remove Sindhi from the picker.
- **Punjabi leaks Sarvam's OpenAPI schema** on one C-programming sentence, on all three
  attempts, reproducing the finding from two months earlier. Now rejected in the shipping
  translation module rather than only in the test harness — the participant reads their own
  sentence in English instead of raw JSON.

### Reliability

175 of 176 language-runs produced data. Nineteen cells lost to a Sarvam rate-limit abort
were recovered on a re-run; the harness aborted and labelled the failure rather than
emitting clean-looking rows. The single unrecovered cell is Punjabi on
`cp/pointers/dynamic-memory-allocation`, which is the schema leak above.

---

## Caveats to carry into the presentation

**Subject and model are confounded by design.** Each subject routes to its own fine-tuned
model, so a difference between two subjects is also a difference between two models and
the design cannot separate them. Every comparison above is stated as "this model, on this
subject" for that reason.

**The self-score is each model grading itself.** Granite's 89% Low and Qwen3's 17% Low are
not a measurement of teaching quality — they are two models disagreeing about identical
text. Which is closer to a human judgement is unknown and would need an external grader.

**Three repeats is enough for a range, not for significance.** Where two ranges overlap,
treat the difference as noise. The gaps reported above — 6 versus 61 repeated openings,
0.11 versus 0.83 mean score — are far larger than the spread within any subject, which is
why they are stated as findings.
