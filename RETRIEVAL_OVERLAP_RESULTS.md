# Does repeated retrieval explain RAG's repeated questions?

Run on 2026-09-19 (05:34–05:35 UTC). Pre-registered before the run in `PHASE1_PREREGISTRATION.md`, entry "Retrieval overlap and repeated questions", written 2026-09-19T05:32:53Z.

- **Raw output:** `LbT (RAG Based) tool Implementaion files-…/retrieval-overlap.json`
- **Script:** `…/scripts/retrieval_overlap.py`

## Result: the hypothesis failed

The pre-registered prediction was that pairs of turns sharing retrieved passages would repeat a question more often. They repeated it **less** often.

| | Pairs of turns | Repeat rate |
|---|---:|---:|
| Share at least one retrieved passage | 15 | 5.6% |
| Share no retrieved passage | 57 | 15.8% |
| **Difference** | | **−10.2 points, 95% CI [−18.3, −0.8]** |

- The rank correlation between passage overlap and repeat rate is −0.25, 95% CI [−0.47, −0.00].
- Under the pre-registered rule the hypothesis fails. The interval excludes zero, but on the wrong side.
- The upper bound, −0.8 points, is close to zero, so read the negative direction as "no support", not as evidence that shared passages *prevent* repeats.

## Repeats happen without shared passages

- **No passage sets were identical:** in all 72 pairs of turns, no two turns of a lesson retrieved the same four passages. 57 pairs shared none, 14 shared one, and 1 shared two.
- **Most repeats had no shared passage:** 54 of the 59 repeated questions happened between turns that retrieved completely different passages.
- **Most repeating pairs had no overlap:** 36 of the 72 pairs repeated at least once, and only 4 of those 36 had any overlap.

So the repeats cannot be explained by the learner seeing the same textbook passages again. The explanation from the Phase 1 scorecard ("if the same four passages come back on every turn…") is ruled out as the main cause.

## By arm

| Arm | Repeat rate, shared vs none | Difference [95% CI] | Rank correlation [95% CI] |
|---|---|---|---|
| RAG (committed run) | 2.2% vs 16.4% | −14.2 pts [−22.6, −5.1] | −0.26 [−0.40, −0.07] |
| RAG + teacher history | 8.9% vs 15.2% | −6.3 pts [−19.6, +9.0] | −0.12 [−0.33, +0.15] |

Repeats cluster at the last turn. Of all repeats, 27 were turn 3 repeating turn 2, 17 were turn 3 repeating turn 1, and 15 were turn 2 repeating turn 1, each out of 144 conversation-pairs.

## Checks

- **Counts match the scorecard:** the analysis finds a repeat in 23 of 72 RAG conversations and 24 of 72 teacher-history conversations, the same as `score_systems.py`.
- **Retrieval is reproducible:** a second run returned identical passages for all 72 sentences.
- **Committed vectorstore untouched:** it was copied to a temporary folder before being opened, and `git status` shows no changes to it.
- **Cost:** 144 embedding calls (two runs) with `text-embedding-3-small` via OpenRouter, a fraction of a cent. Nothing was generated.

## What it means for the paper

- Report this as the second pre-registered negative result on RAG's repetition. Neither the teacher's history nor overlapping retrieval explains it.
- The remaining candidates are on the generation side:
  - the student prompt's template ("Could you explain how…"), which every RAG question follows;
  - its instruction to assume the explanation was sufficient;
  - how the learner uses its memory of its own earlier replies.
- Testing these needs new generations with a changed prompt, which costs more than this analysis.
- Caveat: each lesson's turns and repeats are clustered, and only 15 pairs shared any passage, so the estimates are imprecise.
