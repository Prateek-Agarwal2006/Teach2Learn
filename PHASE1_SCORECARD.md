# Teach2Learn Phase 1: fine-tuned vs RAG student

*Updated 2026-09-15 · Interactive version: https://claude.ai/code/artifact/0aa4deea-3606-4ac2-a532-58122ea17e49*

## RAG leads once question depth counts

A blind judge rated **90% of RAG's questions deep**, against 60% for the fine-tuned student, and that moves the composite from a tie to a RAG lead. Hold that loosely: **every RAG question is a request to explain or clarify**, usually “Could you explain how…”, which the taxonomy counts as deep almost by default. The fine-tuned student still **never repeats a question**, and giving RAG the teacher's earlier sentences did not change that.

| | Fine-tuned | RAG |
|---|---:|---:|
| Composite, 0–100 (six dimensions) | **75.0** [72.6–77.3] | **81.4** [78.8–83.9] |
| Gap, RAG − fine-tuned | | +6.5 [+3.6, +9.6] → **RAG** |
| Without question depth (five dimensions) | 78.6 | 79.3 · gap +0.7 [−2.2, +3.3] → **Tie** |

Three dimensions go to RAG, one to fine-tuned, two tied. **Depth alone moves the verdict**; read its caveat below before quoting the lead.

**Key findings**

- **Questions rated deep:** RAG 90% vs fine-tuned 60%. Same depth on a re-judge 97% of the time, but 82% of RAG's questions fall in one category.
- **Repeats a question word for word:** fine-tuned 0 vs RAG 23 of 72 English conversations. The language sweep agrees: 5 vs 55 of 175.
- **Fluency after translation:** RAG +0.14 on 1–5, 95% CI +0.08 to +0.21 over 524 paired turns. Holds on identical Sarvam input and on length-matched pairs.
- **RAG given the teacher's history:** 24 of 72 still repeat. The pre-registered prediction (toward 0) failed. Cost $0.89.

## Scorecard

Only signals both harnesses recorded, and only ones the student produces itself. A dimension goes to a system only when the 95% interval of the difference excludes zero; otherwise it is a tie.

| Dimension | Weight | Fine-tuned | RAG | Difference, 95% CI | Goes to |
|---|---:|---:|---:|---|---|
| **Fluency**<br><sub>Judge fluency of the translated message</sub> | 36 | 78.9 | 82.5 | +0.14 on 1–5 [+0.08, +0.21] | RAG |
| **Question depth †**<br><sub>Share of questions a blind judge rates deep</sub> | 20 | 60.2 | 89.9 | +30 pts deep [+18, +41] | RAG |
| **Lexical variety**<br><sub>Opening-word entropy over questions, equal n</sub> | 12 | 52.9 | 78.5 | +0.26 entropy [+0.14, +0.37] | RAG |
| **Non-repetition**<br><sub>Conversations with no question asked twice</sub> | 12 | 100.0 | 68.1 | 23 vs 0 of 72 repeat [+19, +44 pts] | Fine-tuned |
| **Robustness**<br><sub>Languages in the Ready tier</sub> | 12 | 68.2 | 68.2 | 15 vs 15 of 22 | Tie |
| **Reliability**<br><sub>Crossings with no retry, passthrough or leak</sub> | 8 | 99.7 | 100.0 | 0 vs 4 of 1,575, p = 0.12 | Tie |

### † Read with the depth row

**The judge labels questions consistently. Whether it measures depth or phrasing is not settled.**

| | Fine-tuned | RAG |
|---|---:|---:|
| Questions phrased as a request to explain (“Could you explain / clarify…”) | 20% | 100% |
| Share in the single most common category (instrumental/procedural) | 29% | 82% |
| Question categories used, of Graesser & Person's 18 | 13 | 7 |

Graesser and Person file *“how does X work?”* under instrumental/procedural, a deep category. RAG asks nearly everything that way, so it scores deep almost by construction. The judge sees only the question sentence. It never sees the lesson, and it can't tell whether the teacher had already answered the question.

**Two checks cut the other way.** Re-judging 60 questions gave the same depth 97% of the time. Among the fine-tuned student's own questions, the ones phrased as a request to explain were only a little more often deep (66%) than the rest (59%). **Neither check can settle RAG's case**, because RAG never phrases a question any other way. Counting a repeated question only once per conversation leaves RAG's figure unchanged, at 90%.

### Does the verdict survive a different view of what matters?

RAG leads under every weighting that includes depth, except one that prizes conversation over translation. Take depth out and the two tie.

| Weighting | Fluency | Depth | Lexical | Repeats | Robust. | Reliab. | Fine-tuned | RAG | RAG − FT, 95% CI | Leader |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| This scorecard | 36 | 20 | 12 | 12 | 12 | 8 | 75.0 | 81.4 | +6.5 [+3.6, +9.6] | RAG |
| Equal weights | 16 | 20 | 16 | 16 | 16 | 16 | 76.0 | 81.5 | +5.5 [+2.1, +9.1] | RAG |
| Multilingual first | 48 | 20 | 8 | 8 | 12 | 4 | 74.3 | 81.5 | +7.2 [+4.6, +10.0] | RAG |
| Conversation first | 20 | 20 | 8 | 32 | 12 | 8 | 80.2 | 78.7 | −1.5 [−6.6, +3.4] | Tie |
| Without question depth (previous scorecard) | 45 | — | 15 | 15 | 15 | 10 | 78.6 | 79.3 | +0.7 [−2.2, +3.3] | Tie |
| Pre-declared, before transcripts (superseded) | 45 | — | 30 | — | 15 | 10 | 71.6 | 80.9 | +9.3 [+5.9, +12.7] | RAG |

**The scorecard has changed twice, and both changes are shown.** First, a single variety dimension worth 30 rewarded RAG for varying the first six words of questions it then repeated, so it was split evenly into lexical variety and non-repetition. Second, question depth was added at weight 20, with the other five scaled by 0.8. That was written down on 14 September at 18:35 UTC, before any question had been judged, with a rule to report depth unscored if re-judge agreement fell below 70%. Agreement came in at 97% on depth and 93% on the exact category.

## Where RAG leads

### Question depth

Each question sentence was classified alone, with system names removed and all three arms shuffled together.

| Arm | Questions | Deep | Intermediate | Shallow |
|---|---:|---:|---:|---:|
| Fine-tuned | 216 | 60% | 34% | 6% |
| RAG | 169 | 90% | 7% | 3% |
| RAG + teacher history (experiment) | 177 | 92% | 5% | 3% |

Deep = why, how, what if · Intermediate = define, compare, example · Shallow = yes/no, fill a blank.

Examples, as judged:

| Fine-tuned (13 categories in use) | RAG (7 categories in use) |
|---|---|
| How does Big-O actually work? — *deep, instrumental/procedural* | Could you explain how associativity affects the evaluation order? — *deep, instrumental/procedural* |
| What happens if I use floating-point numbers instead of integers in this division? — *deep, causal consequence* | Could you clarify how multiple statements are handled within a switch case? — *deep, instrumental/procedural* |
| Can you give me an example of how inheritance works with fields and methods? — *intermediate, example* | Could you explain how atomic operations specifically prevent lost updates? — *asked at turns 2 and 3 of the same lesson* |
| Can you clarify the difference? — *intermediate, comparison* | Could you clarify what distinguishes an internal node from an external node? — *intermediate, comparison* |

<details><summary>Depth sensitivity checks, per arm and subject</summary>

| Measure | Fine-tuned | RAG | RAG + history |
|---|---:|---:|---:|
| Questions judged | 216 | 169 | 177 |
| Rated deep | 60% | 90% | 92% |
| Rated deep, each distinct question once per conversation | 60% of 216 | 90% of 143 | 91% of 150 |
| Phrased as a request to explain | 20% | 100% | 100% |
| Deep among those / among other phrasings | 66% / 59% | 90% / none | 92% / none |
| Share in the most common category | 29% (instrumental/procedural) | 82% (instrumental/procedural) | 79% (instrumental/procedural) |
| Categories used, of 18 | 13 | 7 | 7 |
| Rated deep · Computer programming | 72% | 98% | 100% |
| Rated deep · Data structures | 46% | 76% | 87% |
| Rated deep · OOP with Java | 54% | 78% | 81% |
| Rated deep · Operating systems | 69% | 100% | 96% |

</details>

### Fluency: a small gap that holds under every cut of the data

RAG minus fine-tuned, on the judge's 1–5 scale, with 95% cluster-bootstrap intervals over (lesson, language).

| Cut | Paired turns | Fine-tuned | RAG | Difference | 95% CI |
|---|---:|---:|---:|---:|---|
| All paired turns | 524 | 4.16 | 4.30 | +0.14 | [+0.08, +0.21] |
| Questions only | 503 | 4.15 | 4.32 | +0.17 | [+0.11, +0.24] |
| Identical Sarvam input | 409 | 4.20 | 4.34 | +0.15 | [+0.08, +0.22] |
| Length-matched pairs | 164 | 4.05 | 4.20 | +0.15 | [+0.02, +0.27] |
| Computer programming | 129 | 4.31 | 4.31 | ±0.00 | [−0.13, +0.13] |
| Data structures | 131 | 4.15 | 4.31 | +0.16 | [+0.02, +0.30] |
| OOP with Java | 132 | 4.04 | 4.23 | +0.19 | [+0.06, +0.33] |
| Operating systems | 132 | 4.13 | 4.35 | +0.22 | [+0.11, +0.33] |

**The gap is smaller than one judge disagreeing with itself, and still real.** Given the same translated sentence twice, the judge's fidelity scores differ by 0.18 on average. It holds because every turn is paired and the effect is consistent: RAG scores higher on 147 turns, the fine-tuned student on 82, with 295 level, and in 19 of 22 languages. **Computer programming is the exception**, dead level, where the fine-tuned side runs Qwen3.

### Lexical variety: the fine-tuned students lean on stock lead-ins

How often the single most common six-word opening begins a question, per subject. Lower is more varied.

| Subject | Fine-tuned model | Fine-tuned | Most common opening | RAG |
|---|---|---:|---|---:|
| Computer programming | Qwen3 8B | 83% | “that makes sense but i'm still…” | 16% |
| Data structures | Gemma 2 9B | 37% | “that makes sense but i'm still…” | 24% |
| OOP with Java | Mistral 7B | 26% | “that makes sense but i'm still…” | 15% |
| Operating systems | Granite 3.3 8B | 9% | “i'm still really confused can you…” | 19% |

Rarefied to 169 questions each, opener entropy is 0.53 for the fine-tuned students and 0.78 for RAG, a gap of +0.26 (95% CI +0.14 to +0.37). The measure reads six words and RAG's shared “Could you explain how” is only four, so RAG counts as varied here even though its questions all open alike.

## Where fine-tuned leads: it follows the lesson; RAG asks the same question again

A learner who repeats a question after the teacher has moved on gives the teacher nothing new to explain, which is the whole mechanism Teach2Learn relies on.

| Measure | Fine-tuned | RAG | RAG − FT, 95% CI |
|---|---:|---:|---|
| Repeats a question, English | 0/72 | 23/72 | +19 to +44 pts |
| Repeats a question, 22 languages | 5/175 | 55/175 | +22 to +35 pts |
| Answers the current sentence | 61% | 44% | −27 to −7 pts |
| Looks backward to an earlier one | 14% | 30% | +6 to +28 pts |

Conversations with a question asked twice, by subject (of 18 each):

| Subject | Fine-tuned | RAG | RAG + teacher history |
|---|---:|---:|---:|
| Computer programming | 0 | 8 | 12 |
| Data structures | 0 | 4 | 4 |
| OOP with Java | 0 | 6 | 4 |
| Operating systems | 0 | 5 | 4 |

“Answers the current sentence” means a question shares the most content words with the teacher's latest sentence; “looks backward” means it shares more with an earlier one. Word overlap is a crude proxy; the repeat count needs no proxy at all.

### Two lessons, as each student actually asked them

The same teacher sentences went to all three. The third column is the memory experiment below. **Bold** marks a question asked word for word earlier in the same conversation. The fine-tuned student's stock lead-in is in italics.

**Synchronization and locks** · `oop_java/concurrency/synchronization-and-locks`

| Turn | Teacher | Fine-tuned · Mistral 7B | RAG · gpt-4o | RAG + teacher history |
|---|---|---|---|---|
| 1 | When two threads update the same field at once one update can be lost, because reading, changing, and writing back is not a single indivisible step. | *Okay, I'm following you.* Okay, so how does a lock actually prevent those updates from being lost? | Could you explain how atomic operations help prevent lost updates in multithreading? | Could you explain how atomic operations help prevent lost updates? |
| 2 | A synchronized block lets only one thread hold the object's monitor at a time, so every other thread waits until that block finishes. | *That makes sense, but I'm still slightly unsure about one thing.* And how does the thread know when it can get the lock back? | Could you explain how atomic operations specifically prevent lost updates? | Could you explain what makes an operation atomic? |
| 3 | Acquiring two locks in different orders in different threads can deadlock, so the usual rule is to always take locks in one fixed global order. | *I think I understand most of that.* Why is it so important to always acquire locks in the same order? | **Could you explain how atomic operations specifically prevent lost updates?** (same as turn 2) | Could you explain how atomic operations specifically prevent lost updates? |

**CPU scheduling** · `os/threads-scheduling/cpu-scheduling`

| Turn | Teacher | Fine-tuned · Granite 3.3 8B | RAG · gpt-4o | RAG + teacher history |
|---|---|---|---|---|
| 1 | The scheduler decides which ready process runs next on the CPU, because there are usually more runnable processes than cores. | *That makes sense, but I'm still slightly unsure about one thing.* Why is it important for the scheduler to decide which process runs next? | Could you explain how the scheduler decides which process to run if multiple processes are ready at the same time? | Could you explain how the scheduler decides which process to run when there are multiple ready processes? |
| 2 | Round-robin gives each process a fixed time quantum in turn, so no single process can starve the others while it holds the CPU. | *I think I understand most of that.* How does round-robin scheduling affect system efficiency compared to other methods? | **Could you explain how the scheduler decides which process to run if multiple processes are ready at the same time?** (same as turn 1) | Could you explain what happens if a process needs more time than its time quantum? |
| 3 | A very small quantum wastes time on context switches, while a very large one makes the scheduler behave like plain first-come first-served. | *Okay, I'm following you.* Can you give an example of when round-robin might not be the best choice? | Could you explain how the scheduler chooses between multiple ready processes? | **Could you explain how the scheduler decides which process to run when there are multiple ready processes?** (same as turn 1) |

## Experiment (pre-registered): giving RAG the teacher's earlier sentences did not stop the repeats

The live RAG app stores the teacher's messages but passes the student only its own earlier replies. That looked like the reason it repeated itself. We wrote down a prediction, ran all 72 English conversations again with the teacher's history added, and the prediction failed.

**Pre-registration, written 2026-09-14 18:31 UTC, before the run** (full text: `PHASE1_PREREGISTRATION.md`)

| | |
|---|---|
| Change | Add the teacher's earlier sentences in the lesson to the RAG student's prompt. Nothing else changes. |
| Primary metric | English conversations with a question asked twice, word for word. Baseline 23 of 72. |
| Prediction | Falls from 23 toward 0, the fine-tuned level. |
| Fails if | The 95% interval for the change includes zero. |
| **Result** | **Prediction failed: 23/72 → 24/72**, change +1.4 pts, 95% CI −10.8 to +14.2 |

Nothing moved, including the measures reported whatever they showed (committed RAG run vs the new arm, paired by lesson):

| Measure | RAG | RAG + history | Change | 95% CI | Reads as |
|---|---:|---:|---:|---|---|
| **Conversations repeating a question** (primary) | 23/72 | 24/72 | +1.4 pts | −10.8 to +14.2 | No detectable change |
| Looks backward to an earlier sentence | 30% | 31% | +1.3 pts | −9.7 to +12.7 | No detectable change |
| Answers the current sentence | 44% | 41% | −3.4 pts | −12.2 to +4.4 | No detectable change |
| Follow-ups that are questions | 78% | 82% | +3.7 pts | −2.7 to +11.2 | No detectable change |
| Questions rated deep | 90% | 92% | +1.6 pts | −2.0 to +5.5 | No detectable change |
| Lexical variety (opener entropy, rarefied to 169) | 0.78 | 0.80 | +0.011 | −0.028 to +0.056 | No detectable change |

- **What was held fixed:** gpt-4o at temperature 0.25, k = 4 retrieval, the 24 lessons three times each. Opening questions were reused from the committed run so they could not differ. At turn 1, with no earlier sentence to show, the prompt was byte-identical to the committed one.
- **Subject by subject, noise:** computer programming rose from 8 to 12 repeating conversations; OOP with Java fell from 6 to 4, operating systems from 5 to 4, and data structures stayed at 4. The total went from 23 to 24.
- **The composite doesn't move either:** no language sweep was run, so this arm's fluency is unmeasured. Assuming RAG's, the projected composite gap over fine-tuned is RAG +6.8 [+4.1, +9.4], against +6.5 [+3.6, +9.6] for committed RAG.
- **What's left to test: retrieval (untested).** RAG's prompt tells it to ask about any gap between the teacher and the retrieved passages. If the same four passages come back on every turn of a lesson, the same gap question comes back too. Logging the retrieved passage IDs per turn would test this without generating any new questions.

## Tied: where the two cannot be separated

- **Robustness, languages Ready:** 15 vs 15. Same tier for all 22 languages. Sindhi Blocked on both, Sanskrit the weakest Review on both, both upstream in Sarvam.
- **Reliability, failed crossings:** 4 vs 0 out of 1,575 each. Fisher's exact p = 0.12, so a tie. The four were Sarvam rate-limit retries during the fine-tuned run, not anything the student did.
- **Control, translation fidelity:** fidelity grades Sarvam's translation of the teacher's sentence, the same input for both, so it isn't scored. On 409 identical strings the judge gave identical scores 84% of the time, with a net gap of −0.02. That is the noise floor.

**Sarvam is not deterministic.** 116 of 525 teacher sentences came back translated differently for the two runs, concentrated in low-resource languages (Santali 14 of 24, Kashmiri 12 of 24). RAG's fluency lead is the same on the 409 turns where Sarvam returned identical text (+0.15, 95% CI +0.08 to +0.22).

## Recorded, not scored

These follow from how each system was built or prompted, so scoring them would compare design choices rather than students.

| Observation | Fine-tuned | RAG | Why it isn't scored |
|---|---:|---:|---|
| Follow-ups that are questions | 100% | 78% | RAG is told it may reply with a reflection; the adapter is trained to always ask. |
| Language turns answered with a reflection | 0 of 525 | 21 of 525 | Same prompt difference, in the language sweep. |
| Words per follow-up | 20.3 | 16.9 | Set by each system's instructions rather than by what the student understood. |
| Distinct follow-up strings | 99% | 78% | Misleads both ways: a fixed lead-in with a different ending counts as distinct. |
| Runs flagged by the in-run opener check | 36 of 72 | 53 of 72 | RAG's reflections all start alike, so this count points the wrong way. |

## Fluency and fidelity, language by language

| Language | Code | FT fidelity | RAG fidelity | Δ | FT fluency | RAG fluency | Δ | FT tier | RAG tier |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| Punjabi | pa | 4.67 | 4.57 | −0.10 | 4.76 | 4.95 | +0.19 | Ready | Ready |
| Malayalam | ml | 4.75 | 4.83 | +0.08 | 4.58 | 4.92 | +0.33 | Ready | Ready |
| Telugu | te | 4.50 | 4.33 | −0.17 | 4.79 | 4.83 | +0.04 | Ready | Ready |
| Urdu | ur | 4.67 | 4.67 | ±0.00 | 4.54 | 4.83 | +0.29 | Ready | Ready |
| Gujarati | gu | 4.71 | 4.71 | ±0.00 | 4.75 | 4.79 | +0.04 | Ready | Ready |
| Hindi | hi | 4.58 | 4.62 | +0.04 | 4.62 | 4.79 | +0.17 | Ready | Ready |
| Bengali | bn | 4.38 | 4.38 | ±0.00 | 4.79 | 4.71 | −0.08 | Ready | Ready |
| Odia | or | 4.75 | 4.54 | −0.21 | 4.33 | 4.71 | +0.38 | Ready | Ready |
| Nepali | ne | 4.42 | 4.42 | ±0.00 | 4.58 | 4.71 | +0.12 | Ready | Ready |
| Kannada | kn | 4.50 | 4.54 | +0.04 | 4.50 | 4.67 | +0.17 | Ready | Ready |
| Marathi | mr | 4.46 | 4.38 | −0.08 | 4.54 | 4.67 | +0.12 | Ready | Ready |
| Assamese | as | 4.21 | 4.54 | +0.33 | 4.58 | 4.62 | +0.04 | Ready | Ready |
| Tamil | ta | 4.50 | 4.38 | −0.12 | 4.58 | 4.58 | ±0.00 | Ready | Ready |
| Maithili | mai | 4.62 | 4.58 | −0.04 | 4.33 | 4.38 | +0.04 | Ready | Ready |
| Dogri | doi | 4.38 | 4.42 | +0.04 | 4.00 | 4.25 | +0.25 | Ready | Ready |
| Kashmiri | ks | 4.12 | 4.50 | +0.38 | 3.79 | 3.96 | +0.17 | Review | Review |
| Bodo | brx | 4.75 | 4.75 | ±0.00 | 3.79 | 3.96 | +0.17 | Review | Review |
| Konkani | kok | 4.58 | 4.58 | ±0.00 | 3.38 | 3.83 | +0.46 | Review | Review |
| Manipuri | mni | 4.79 | 4.88 | +0.08 | 3.67 | 3.79 | +0.12 | Review | Review |
| Santali | sat | 4.75 | 4.88 | +0.12 | 3.42 | 3.57 | +0.15 | Review | Review |
| Sanskrit | sa | 3.17 | 3.25 | +0.08 | 3.00 | 3.25 | +0.25 | Review | Review |
| Sindhi | sd | 1.33 | 1.00 | −0.33 | 2.12 | 1.88 | −0.25 | Blocked | Blocked |

## The two systems

| | Fine-tuned Teach2Learn | RAG Teach2Learn |
|---|---|---|
| Model | 4 LoRA adapters: Qwen3 (cp) · Gemma 2 (dsa) · Mistral (oop_java) · Granite (os) | gpt-4o via OpenRouter, one model for every subject |
| Context | Full dialogue history | Four textbook passages retrieved per teacher sentence (Chroma, k = 4) plus its own earlier replies |
| Decoding | Temperature 0.2 · top-p 0.9 | Temperature 0.25 · top-p 0.9 |
| English runs | 72 (24 lessons × 3) | 72 (24 lessons × 3) |
| Language turns | 525 (175 of 176 runs) | 525 (175 of 176 runs) |
| Shared | Translation `sarvam-translate:v1` · judge `openai/gpt-5.6-luna` · lesson bank v1 | same |

## Method and limits: read before quoting a number

- **This compares two systems, not two techniques.** RAG runs gpt-4o, a far larger model than the 7–9B adapters. A RAG lead cannot be credited to retrieval, and a fine-tuned lead cannot be credited to fine-tuning.
- **Depth measures phrasing as well as content.** It carries weight 20 and is the only dimension that changes the verdict. A human rating a sample with the lesson in view would separate RAG's template from what its questions ask.
- **One decoding setting differs** (0.2 vs 0.25). Lower temperature would, if anything, favour repetition on the fine-tuned side, which makes its repeat result conservative.
- **Pre-registered, twice.** The memory experiment's prediction and failure rule, and the depth instrument's grouping, weight and reliability floor, were each written down before the data they judge existed (`PHASE1_PREREGISTRATION.md`).
- **Intervals.** Fluency uses a 5,000-draw cluster bootstrap over (lesson, language). The English measures, depth included, resample half the lessons without replacement. Draws are paired across systems throughout.
- **Judged scores are directional.** Fluency and depth are one model's labels. No native reader has confirmed any language's scores and no person has checked the depth labels.

## Reproduce

From `teach2learn-portal/` on branch `phase1-test-bed`:

```bash
R="../LbT (RAG Based) tool Implementaion files-20260907T102315Z-1-001/LbT (RAG Based) tool Implementaion files"
.venv/bin/python scripts/score_systems.py \
  --finetuned-english sweepA-cp.stdout.json sweepA-dsa.json sweepA-oop_java.json sweepA-os.json \
  --finetuned-languages sweepB-cp.json sweepB-dsa.json sweepB-oop_java.json sweepB-os.json fix-cp.json fix-oop.json fix-os.json \
  --rag-english "$R/sweepA-rag.json" --rag-languages "$R/sweepB-rag.json" \
  --rag-history-english "$R/sweepA-rag-history.json" --depth question-depth.json
```

## References

1. Efron, B. & Tibshirani, R. (1993). *An Introduction to the Bootstrap*. Chapman & Hall.
2. Graesser, A. C. & Person, N. K. (1994). Question asking during tutoring. *American Educational Research Journal*, 31(1).
3. Nosek, B. A., Ebersole, C. R., DeHaven, A. C. & Mellor, D. T. (2018). The preregistration revolution. *PNAS*, 115(11).
4. Roscoe, R. D. & Chi, M. T. H. (2007). Understanding tutor learning: knowledge-building and knowledge-telling in peer tutors' explanations and questions. *Review of Educational Research*, 77(4).
