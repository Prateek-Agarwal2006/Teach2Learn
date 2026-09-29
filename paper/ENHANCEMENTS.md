# Planned enhancements to the paper

Recorded on 2026-09-19 from an internal review of `teach2learn-multilingual.tex`.

**Status (2026-09-19): the writing changes and the retrieval analysis are applied to the manuscript.**
- Main-text prose is 13.3% shorter, and main-text tables went from 14 to 11. That is a little short of the 15–20% target; Related Work and the Methods subsections are the next places to trim.
- Still open: the study-team items and the submission blockers listed at the end of this file.

## The review in brief

- The research is publishable, but this version is not ready for a journal.
- The strongest contribution is the translation boundary and the controlled comparison it makes possible. "We added 22 languages" is the weaker framing.
- The draft reads like two papers:
  - a systems and evaluation paper, which is largely done;
  - an educational user-study paper, which is still placeholders.

| Aspect | Reviewer's assessment |
|---|---|
| Research idea | Strong |
| Engineering contribution | Strong |
| Experimental discipline | Good to very good |
| Novelty | Potentially strong |
| Empirical evidence | Good, but incomplete |
| Educational significance | Not established yet |
| Writing | Good, but too defensive and over-engineered in places |
| Journal readiness | Not yet |

## Decisions already made (2026-09-19)

1. **Title:** "Teaching an AI Learner in Your Own Language: A Translation Boundary for Learning-by-Teaching Tutors in 22 Indian Languages and a Comparison of Two AI Learners".
2. **Composite 0–100 score:** move to an appendix. The main results report the six dimensions separately.
3. **Retrieval analysis:** done on 2026-09-19. The hypothesis failed, so repeated passages are not the cause. See `RETRIEVAL_OVERLAP_RESULTS.md` at the repo root; the paper still needs the new subsection.

## Writing changes (ours)

### Claims

- **Soften the causal claim.** Replace "multilingual quality is set by the translation layer rather than the learner" with "the strong agreement across systems suggests the translation layer is a dominant determinant of multilingual quality in this architecture". It appears in the abstract, §5, Discussion 8.1 and the Conclusion.
  - Support it with the correlation between the two systems' per-language means, computed 2026-09-19 from `PHASE1_COMPARISON.md`.
  - Fluency: Pearson 0.98 and Spearman 0.87, or 0.97 and 0.86 without Sindhi.
  - Fidelity: Pearson 0.98 and Spearman 0.84.
- **Soften novelty claims.** "To our knowledge, none…" and "We know of no study…" become "We found no … in the literature we reviewed", unless a systematic search is done.
- **Architectural comparison, not an ablation.** Name the learners "the retrieval-augmented GPT-4o learner" and "the subject-specific fine-tuned learners". State once, in Methods and Results: "This is an architectural comparison, not an ablation of retrieval versus fine-tuning."

### Structure

- **Split Results into two sections:**
  - "Results: The Multilingual Boundary" (RQ1, RQ2): reliability, fidelity, fluency, language effects.
  - "Results: Learner Behaviour" (RQ3): repetition first, then responsiveness, the failed teacher-history experiment, the retrieval analysis, lexical variety, question depth with its caveat, "recorded, not scored", and the five-model run.
- **Composite to an appendix.**
  - The Methods "Scorecard" subsection becomes "Behavioural and Translation Dimensions", with the definitions and the verdict rule.
  - Results open with a per-dimension table that has no composite rows.
  - The composite, both earlier versions and the weighting table go to a new appendix, with one sentence on why they are not an overall verdict ("its weighting is necessarily normative").
  - Remove composite mentions from the Discussion and Conclusion.
- **Make repetition a central finding.** Tell it as a sequence: the observation (0/72 vs 23/72; 5/175 vs 55/175), the hypothesis, the pre-registered intervention that failed, the next hypothesis (retrieval), and then its test.
- **Restructure the Introduction into six paragraphs:**
  1. The problem: why LbT works.
  2. The gap: existing systems are English-only.
  3. The solution: edge translation without retraining.
  4. The research challenge: translation can change meaning, fluency, evaluation and behaviour.
  5. The experiments.
  6. Three or four precise main findings.

  Then the contributions.
- **Narrative arc:** "Can an English-only LbT system be made multilingual without rebuilding it?" Then: it works technically; quality depends strongly on language; the two architectures fail in different ways, so neither "RAG is better" nor "fine-tuning is better" holds; and the user study shows whether it helps learning.

### Voice input

- Demote it from contribution #2. Fold it into the architecture contribution as "additionally supports speech input; recognition accuracy is outside the scope of this study".
- The other option is to evaluate it with word or character error rate per language.

### Trim engineering detail (target 15–20% shorter main text)

Move the following into a new appendix, "Implementation Details", and keep about one paragraph each in the main text:
- Chrome's WebM/Opus rejection and the WAV re-encode;
- the 15 MB cap and 24 kHz;
- 2,000 vs 1,000 character limits, chunking and the cache;
- the Odia `od-IN` code;
- the dictionary lock test;
- `cmp`;
- timeout values;
- schema-guard detail.

### Figures

- **Add a scatter plot:** each language's fine-tuned mean fluency (x) against its RAG mean fluency (y), with a y = x line, the correlations, and labels on the extreme languages. It goes in the main text of the boundary-results section.
- **Move the heatmap** (current Figure 3) to the appendix, next to the full results tables.

### Discussion

- **Name the design principle:** "A boundary that fails open must fail loudly." Silent passthrough keeps sessions alive but makes failure look like success.
- **Storage trade-off paragraph:**
  - English-only storage keeps research data language-independent, but it throws away the original wording, so translation errors cannot be audited later.
  - Recommend storing the original language, original text, English translation and translation metadata, with audio still discarded, subject to consent.
  - If there is a privacy reason not to, state it.
- **Keep reporting failures.** Sindhi, the Punjabi schema payload, rate limiting, non-determinism, grammatical gender and the English interface all add credibility.

## Retrieval-overlap analysis (ours, new data) — DONE 2026-09-19

**Result:** repeats were less common between turns that shared a passage (5.6%) than between turns that shared none (15.8%). No turn pair retrieved identical passages, and 54 of 59 repeats involved no shared passage. The hypothesis failed. Full results are in `RETRIEVAL_OVERLAP_RESULTS.md` and the RAG project's `retrieval-overlap.json`. The original plan follows.

1. **Pre-register it** in `PHASE1_PREREGISTRATION.md` with a UTC timestamp before running.
   - **Hypothesis:** a later follow-up repeats an earlier one more often when the two turns retrieved overlapping passages.
   - **Unit:** lesson × turn pair (24 × 3), pooling the committed RAG arm and the teacher-history arm.
   - **Overlap:** Jaccard overlap of the 4 retrieved passage IDs.
   - **Outcome:** share of repeats in which the later question sentence equals the earlier one, normalised as in `score_systems.py:repeats_itself`.
   - **Test:** overlap > 0 vs overlap = 0, with a lesson-level permutation test (seed 20260914) and the rank correlation.
   - **Failure criterion:** the hypothesis fails if the 95% interval includes zero.
   - Note that retrieval is deterministic per teacher sentence.
2. **Write a new script** at `scripts/retrieval_overlap.py` in the RAG project.
   - Reuse the lesson loading, the vectorstore from `student_chain.build_student_chain`, and the `--embeddings-via-openrouter` setup in `scripts/check_languages.py`.
   - Run `similarity_search(teacher_en, k=4)` for each sentence; a passage ID is (source, page) plus a content hash.
   - Read questions from the committed `sweepA-rag.json` and `sweepA-rag-history.json`.
   - Write `retrieval-overlap.json` with provenance.
   - Cost: about 72 embedding calls, cents. No generation, and no Mongo writes.
3. **Report whatever it shows** in a subsection "Does Repeated Retrieval Explain Repeated Questions?". A negative result is reported as plainly as a positive one.

## For the professor and PhD scholar (not ours)

The reviewer's recommendations for the human side of the paper:
- **User study:** make it a major part of the paper.
  - Participants type naturally, use their usual terms, code-switch, make mistakes, use speech, and interact over multiple turns.
  - This balances the benchmark's scripted, machine-translated input.
- **Student measures:** ease of explaining, cognitive load, perceived fluency, willingness to use, usefulness, learner responsiveness, trust, ability to express technical concepts, and language preference.
- **Educational outcome:** pre-test, LbT session, post-test.
- **Within-subject comparison:** English vs the participant's preferred Indian language, in counterbalanced order.
  - Measure explanation length, concepts explained, corrections, cognitive load, confidence, learning gain and satisfaction.
- **Native-speaker check of the LLM judge:** about 8–10 languages, 20–30 samples each, and 2 native speakers per language, rating fidelity and naturalness. Correlate their ratings with the judge's.
  - Prioritise Sanskrit, Santali, Bodo and Kashmiri, where LLM judges are least reliable.
- **Human rating of question depth:** rate a sample of questions with the lesson visible. This settles the "depth measures phrasing" caveat.
- **Store original-language text:** whether to store it during the study, with consent.

## Submission blockers still open

- Blue `[TRACK B]` placeholders:
  - the abstract's last sentence, contribution 5 and RQ4;
  - the user-study sections, the Discussion paragraph on participants, the user-study limitations, and the Conclusion sentence;
  - the ethics reference and Appendix F.
- The AI-use TODO (§4.9): confirm every statement is true before submission.
- References:
  - the RAG and fine-tuned Teach2Learn papers need venue, year and DOI;
  - the Granite citation needs confirming;
  - DOI check on all entries marked `[prior]` or `[std]`.
- Author names, acknowledgements, and the Declarations entries.
- The target journal: check its word and abstract limits once it is chosen.
