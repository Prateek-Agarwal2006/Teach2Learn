# RAG teacher-history experiment — written before the run

Written: 2026-09-14T18:31:32Z

## Change under test
The RAG student receives the teacher's earlier sentences in the current lesson, in addition to its
own earlier replies. The live app already records these (main.py:147, :335, ConversationBufferMemory)
but never passes them to student_chain.invoke (main.py:345-347). Nothing else changes: same prompt
text plus one history block, same gpt-4o via OpenRouter, temperature 0.25, top-p 0.9, same k=4
retrieval, same 24 lessons x 3 repeats, and the SAME opening question per lesson, reused from the
committed sweepA-rag.json so openings cannot differ between arms.

## Primary metric (decided now)
English conversations containing a question asked twice, word for word.
Baseline RAG: 23 of 72. Fine-tuned: 0 of 72.

## Prediction
Falls from 23/72 toward 0/72. The prediction fails if the new arm's 95% interval for the change
includes zero.

## Secondary, reported whatever they show
Looks-backward share, answers-current-sentence share, lexical variety (rarefied opener entropy),
share of follow-ups that are questions, question depth (blinded judge, run after this).

## Analysis
Same scripts/score_systems.py, same seed 20260914. The new arm is added as a third column;
the committed RAG numbers are not replaced. No language sweep is run, so fluency for the new arm
is not measured, and any composite for it is labelled a projection that assumes RAG's fluency.

---

# Question depth — written before any depth score exists

Written: 2026-09-14T18:35:26Z

## Instrument
Each follow-up question's question sentence (a stock lead-in such as "That makes sense, but ..." is
stripped) goes to the same judge model, openai/gpt-5.6-luna, alone: no system name, no subject, no
teacher sentence, and all three arms shuffled together. The judge names one of the 18 question
categories of Graesser & Person (1994). Grouping into depth levels is fixed here:
- shallow: verification, disjunctive, concept completion, feature specification, quantification
- intermediate: definition, example, comparison, interpretation
- deep: causal antecedent, causal consequence, goal orientation, instrumental/procedural,
  enablement, expectational, judgmental
- not a question: assertion, request/directive (excluded from the denominator)
Reflections (RAG replies with no question) are excluded, as they are from lexical variety.

## Reliability check
A random 60 of the judged questions are judged a second time. Agreement on depth level is reported
next to the result. If it falls below 70%, depth is reported but not scored.

## Scored dimension
"Question depth" = share of a system's questions classified deep. Weight 20. The five existing
dimensions keep their relative weights, scaled by 0.8: fluency 36, lexical variety 12,
non-repetition 12, robustness 12, reliability 8. Verdict rule unchanged: 95% interval of the
difference must exclude zero. The previous five-dimension scorecard stays on the page.
