# System Prompt Improvements

Against the prompts in Appendix A of `Teach2Learn___ILE.pdf`. Ordered by impact.

---

## A.2.2 — Student Simulation Prompt

The highest-value fixes are all here. The prompt currently instructs the agent away
from the behaviour the paper claims for it.

- **Remove "Assume the explanation was helpful enough for now, even if not perfect."**
  It contradicts §1 and E.1.1, which claim the agent surfaces misconceptions and prompts
  metacognition. Keep the appreciation instruction; drop the satisfaction instruction.
- **Ask a question on every turn.** Today a question is conditional on being *"very
  confused"*, so a shallow-but-coherent explanation draws no follow-up — exactly the case
  where a novice would push.
- **Add the missing third rating.** The prompt offers only `understood | confused`; the
  schema in §3 defines three states. Add `needs work` — coherent but a step, condition or
  cause is missing — and route the most useful probe through it.
- **Pass Bloom level into this prompt.** The abstract claims the system "systematically
  increases question difficulty"; A.2.1 builds the ladder but A.2.2 never sees it, so
  escalation only exists inside the question pool. Add `{bloom_level}` and instruct the
  agent to probe at that level and advance when satisfied.
- **Give the agent retrieved context for private reasoning.** "You do not have any prior
  knowledge" and "list `missing_points`" cannot both hold — a zero-knowledge agent cannot
  identify an omission. Let it reason against `{context}` while still *speaking* as a novice.
- **Forbid reusing recent phrasings.** Pass the last few opening clauses and instruct the
  agent not to reuse them. Nothing currently asks for variety, and §5.3.8's report of
  agents "asking shallower or less targeted questions" is partly this.
- **Format `{student_memory}` as dialogue before substitution**, not as serialised
  response objects.

---

## A.2.1 — Question Pool Generation Prompt

- **Fix the schema conflict.** The one-shot example emits `"answer"`, while the model
  defined in §3 uses the field `a`. The example contradicts the `{format_instructions}`
  appended directly below it.
- **Replace the fixed TCP/UDP example.** It is used for every subject including C
  programming and Java; models imitate the example's domain. Use one example per subject,
  or a domain-neutral one.
- **Generate more than five questions, or regenerate mid-session.** Sessions run 10–15
  exchanges (§7.2) against a five-rung ladder, so the pool is exhausted well before the
  session ends.
- **Say what "concise" means.** The example's answers are two to three lines, which is
  what the model will copy regardless of the instruction.

---

## A.2.3 — Evaluator Simulation Prompt

- **Resolve who is being assessed.** The prompt opens "assess the *student's* answer",
  then instructs a rating for the *teacher's* explanation and feedback to help the
  *teacher* improve. Fix the opening line; the teacher is the participant and is the one
  who should be graded.
- **Stop calling `{expected_explanation}` "Pre-determined Ground Truth".** It is the QA
  pool's generated answer, not ground truth. The label invites the evaluator to mark a
  correct explanation wrong for disagreeing with a generated one. Relabel as "reference
  answer generated from course material; may be incomplete."
- **Define the five rating levels.** `excellent | good | partial | needs work | incorrect`
  are unanchored, so the boundary between adjacent levels drifts between sessions.
- **Instruct it to ignore length and fluency**, which LLM evaluators reward by default.

---

## A.2.4 — Scorer Simulation Prompt

- **Anchor the scale.** Five floats to two decimals with no rubric: nothing says what
  separates 0.7 from 0.8, so scores are not comparable across sessions or models. Define
  anchors at 0.2 / 0.5 / 0.8, or use a labelled 5-point scale.
- **Take `student_engagement` out of `overall_score`.** The student is the system's own
  agent, so the participant's headline number currently includes the AI grading its own
  liveliness. Report it separately as a system-health metric.
- **Name what each subscore measures.** `teacher_clarity` and `teacher_completeness` are
  given no definitions, so the two collapse toward each other.
- **State the tie-break with the evaluator.** The scorer receives `evaluator_comments` but
  is not told whether to defer to them or score independently.

---

## A.2.5 — Summarizer Simulation Prompt

- **Reconsider the mandatory positive.** "Always include at least one positive highlight",
  stacked on the student agent's instruction to assume the explanation was good enough,
  tunes the whole pipeline upward. Reasonable for a learning tool, not for scores reported
  as findings — state the intent, or remove it from the scored path.
- **Drop the trend instruction, or require more interactions.** "Consider trends, do not
  simply average" over the 4–6 interactions a session produces is asking the model to read
  a trend out of noise.
- **Define "actionable".** Without a required form — what to do differently on the next
  explanation — the summary reverts to restating the scores.

---

## Cross-cutting

- **Version the prompts.** §7.1 notes outputs are "sensitive to prompt wording"; without a
  version recorded alongside each session, results from different weeks are not comparable.
- **Separate the tutor voice from the measurement voice.** Encouragement belongs in what
  the participant reads; it should not reach the evaluator or scorer, whose outputs are
  reported as data.
- **State which prompt version produced the study data**, so Appendix A documents the
  prompts that actually ran.
