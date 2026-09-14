"""Score the fine-tuned and RAG students against each other, from raw results files.

    python3 scripts/score_systems.py \
        --finetuned-english sweepA-cp.stdout.json sweepA-dsa.json sweepA-oop_java.json sweepA-os.json \
        --finetuned-languages sweepB-*.json fix-*.json \
        --rag-english ".../sweepA-rag.json" --rag-languages ".../sweepB-rag.json" > scorecard.json

What is scored. Only signals that are (a) recorded by both harnesses and (b) produced by the
student rather than by the prompt design or the translation layer:

  fluency          45  judge fluency of the student's translated message, paired by
                       (lesson, language, turn); cluster bootstrap over (lesson, language)
  lexical variety  15  opener entropy over the student's actual questions, rarefied to equal n
  non-repetition   15  English conversations in which no question is asked twice word for word
  robustness       15  share of the 22 languages in the Ready tier
  reliability      10  boundary crossings with no retry, passthrough, or leak

The first version of this scorecard, fixed before either system's result was read, had a
single "variety" dimension worth 30 measured by opener entropy alone. Reading the matched
transcripts afterwards showed that metric rewarding a student for varying the first six words
of a question it then asks again verbatim within the same conversation. The dimension was
split evenly into the two above -- no new weight was introduced -- and the pre-split result is
still emitted as `predeclared` so the change is visible rather than silent.

Question depth was added afterwards, again fixed before any depth score existed: the share of a
system's questions that a blind judge places in Graesser & Person's deep categories, weight 20, with
the five dimensions above keeping their relative weights scaled by 0.8. It is scored only when the
judge agrees with itself on at least 70% of a re-judged sample; otherwise it is reported unscored
and the five-dimension scorecard stays primary. Both scorecards are always emitted.

`--rag-history-english` adds an experiment arm: the RAG student also given the teacher's earlier
sentences. It is compared with committed RAG (the experiment) and with the fine-tuned student. It has
no language sweep, so its composite is a projection that reuses RAG's fluency, robustness and
reliability, and is labelled as one.

A dimension goes to a system only when the 95% interval of the difference excludes zero
(Fisher's exact test for the reliability counts). Otherwise it is a tie. The composite is also
reported under alternative weightings, so a reader can see which conclusions survive a
different view of what matters.

Recorded but not scored, and why:
  fidelity       grades Sarvam's translation of the *teacher's* sentence -- identical input on
                 both sides -- so it measures the translation layer and the judge, not the
                 student. Kept as a control: on identical strings its gap is the noise floor.
  question rate  the RAG student is told "Assume the explanation was helpful enough" and may
                 return no question; the adapter is fine-tuned to always ask
  message length follows from each system's prompt, not from capability
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

FIVE = {"fluency": 45, "lexical_variety": 15, "non_repetition": 15, "robustness": 15, "reliability": 10}
PREDECLARED = {"fluency": 45, "lexical_variety": 30, "robustness": 15, "reliability": 10}
FIVE_ALTERNATIVES = {
    "equal": {"fluency": 20, "lexical_variety": 20, "non_repetition": 20, "robustness": 20, "reliability": 20},
    "multilingual-first": {"fluency": 60, "lexical_variety": 10, "non_repetition": 10, "robustness": 15, "reliability": 5},
    "conversation-first": {"fluency": 25, "lexical_variety": 10, "non_repetition": 40, "robustness": 15, "reliability": 10},
}
DEPTH_WEIGHT = 20
DEPTH_AGREEMENT_FLOOR = 0.70


def with_depth(weights: dict[str, int]) -> dict[str, float]:
    """Depth takes 20; every other dimension keeps its relative weight, scaled by 0.8."""
    return {**{k: v * 0.8 for k, v in weights.items()}, "question_depth": DEPTH_WEIGHT}


SIX = with_depth(FIVE)
SIX_ALTERNATIVES = {name: with_depth(w) for name, w in FIVE_ALTERNATIVES.items()}
SAMPLED = ("fluency", "lexical_variety", "non_repetition", "question_depth")
STOP = set("""a an the and or but if then so of to in on at by for with from as is are was were be been being it its
this that these those i i'm im you your we our they their he she them me my do does did done can could would should
will shall may might must have has had not no yes what which who whom whose when where why how about into over under
than more most less very just also only still one thing some any all each both such own same other there here up out
off again further once please explain understand get got think make makes sense unsure slightly really okay ok main
point bit little tell know mean specifically actually example give""".split())
FIXED = ("robustness", "reliability")
BOOTSTRAP = 5000
ENGLISH_DRAWS = 1000
RAREFY = 400
SEED = 20260914
SUBJECTS = ("cp", "dsa", "oop_java", "os")


def words(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9'+#-]*", (text or "").lower())


def opener(text: str) -> str:
    return " ".join(words(text)[:6])


def question_sentence(text: str) -> str | None:
    """The question itself, without a stock lead-in such as "That makes sense, but ..."."""
    parts = [p for p in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if p]
    asked = [p for p in parts if p.endswith("?")]
    return asked[-1] if asked else None


def normalised(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def repeats_itself(followups: list[str]) -> bool:
    """True when the conversation contains the same question twice, word for word."""
    seen: set[str] = set()
    for text in followups:
        asked = question_sentence(text)
        if asked is None:
            continue
        key = normalised(asked)
        if key in seen:
            return True
        seen.add(key)
    return False


def normalised_entropy(items: list[str]) -> float:
    counts = Counter(items)
    n = sum(counts.values())
    if n < 2:
        return 0.0
    return -sum(c / n * math.log(c / n) for c in counts.values()) / math.log(n)


def interval(values: list[float]) -> list[float]:
    ordered = sorted(values)
    return [ordered[int(0.025 * len(ordered))], ordered[int(0.975 * len(ordered)) - 1]]


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def fisher_two_sided(a: int, n1: int, b: int, n2: int) -> float:
    """Exact p for a 2x2 table of failures out of trials; small counts make a z-test wrong."""
    total, fails = n1 + n2, a + b

    def pmf(k: int) -> float:
        return math.comb(n1, k) * math.comb(n2, fails - k) / math.comb(total, fails)

    observed = pmf(a)
    lo, hi = max(0, fails - n2), min(fails, n1)
    return min(1.0, sum(pmf(k) for k in range(lo, hi + 1) if pmf(k) <= observed * (1 + 1e-9)))


def verdict(ci: list[float]) -> str:
    return "rag" if ci[0] > 0 else "ft" if ci[1] < 0 else "tie"


# ---------------------------------------------------------------- loading

def load_runs(paths: list[str]) -> list[dict[str, Any]]:
    runs = []
    for path in paths:
        try:
            runs.extend(json.loads(Path(path).read_text()).get("runs", []))
        except (OSError, json.JSONDecodeError):
            continue  # interrupted stdout captures are empty; the reporter skips them too
    return runs


def language_turns(runs: list[dict[str, Any]]) -> dict[tuple, tuple[str, dict]]:
    return {
        (run["lesson_id"], lang["code"], turn["turn"]): (run["subject"], turn)
        for run in runs
        for lang in run.get("sweep", [])
        for turn in lang.get("turns", [])
    }


def is_question(turn: dict[str, Any]) -> bool:
    kind = turn.get("outbound_kind")
    return kind != "reflection" if kind is not None else "?" in (turn.get("question_en") or "")


def score(turn: dict[str, Any], metric: str) -> int | None:
    return (turn.get(metric) or {}).get("score")


# ---------------------------------------------------------------- language sweep

def fluency(ft: dict, rag: dict, rng: random.Random) -> dict[str, Any]:
    pairs = []
    for key in sorted(set(ft) & set(rag)):
        (subject, a), (_, b) = ft[key], rag[key]
        fa, fb = score(a, "fluency"), score(b, "fluency")
        if fa is None or fb is None:
            continue
        pairs.append({
            "cluster": key[:2], "subject": subject, "language": key[1], "ft": fa, "rag": fb,
            "rag_question": is_question(b),
            "same_seed": a.get("teacher_local") == b.get("teacher_local"),
            "length_gap": abs(len((a.get("question_en") or "").split()) - len((b.get("question_en") or "").split())),
        })

    def summary(rows: list[dict], draws: int) -> dict[str, Any]:
        clusters = defaultdict(list)
        for row in rows:
            clusters[row["cluster"]].append(row)
        groups = list(clusters.values())
        ft_means, rag_means = [], []
        for _ in range(draws):
            sample = [row for group in (rng.choice(groups) for _ in groups) for row in group]
            ft_means.append(mean([r["ft"] for r in sample]))
            rag_means.append(mean([r["rag"] for r in sample]))
        ft_mean, rag_mean = mean([r["ft"] for r in rows]), mean([r["rag"] for r in rows])
        return {
            "n": len(rows), "clusters": len(groups), "ft": ft_mean, "rag": rag_mean, "delta": rag_mean - ft_mean,
            "delta_ci": interval([r - f for f, r in zip(ft_means, rag_means)]),
            "ft_draws": ft_means, "rag_draws": rag_means,
        }

    strip = lambda s: {k: v for k, v in s.items() if not k.endswith("_draws")}
    by_language = defaultdict(list)
    for row in pairs:
        by_language[row["language"]].append(row)
    language_means = {code: {"ft": mean([r["ft"] for r in rows]), "rag": mean([r["rag"] for r in rows]), "n": len(rows)}
                      for code, rows in by_language.items()}
    return {
        "overall": summary(pairs, BOOTSTRAP),
        "questions_only": strip(summary([r for r in pairs if r["rag_question"]], 2000)),
        "by_subject": {s: strip(summary([r for r in pairs if r["subject"] == s], 2000)) for s in SUBJECTS},
        "sarvam_identical_seed": strip(summary([r for r in pairs if r["same_seed"]], 2000)),
        "sarvam_divergent_seed": strip(summary([r for r in pairs if not r["same_seed"]], 2000)),
        "length_matched": strip(summary([r for r in pairs if r["length_gap"] <= 3], 2000)),
        "turn_outcomes": dict(Counter("rag" if r["rag"] > r["ft"] else "ft" if r["ft"] > r["rag"] else "tie" for r in pairs)),
        "languages_rag_higher": sum(v["rag"] > v["ft"] for v in language_means.values()),
        "languages_ft_higher": sum(v["ft"] > v["rag"] for v in language_means.values()),
        "languages_level": sum(v["ft"] == v["rag"] for v in language_means.values()),
        "by_language": language_means,
    }


def fidelity_control(ft: dict, rag: dict) -> dict[str, Any]:
    """Same judge, same prompt, and -- where Sarvam was deterministic -- the same string."""
    same, different = [], []
    for key in set(ft) & set(rag):
        (_, a), (_, b) = ft[key], rag[key]
        fa, fb = score(a, "fidelity"), score(b, "fidelity")
        if fa is None or fb is None:
            continue
        (same if a.get("teacher_local") == b.get("teacher_local") else different).append((fa, fb))

    def describe(rows: list[tuple[int, int]]) -> dict[str, Any]:
        return {"n": len(rows), "exact_agreement": mean([a == b for a, b in rows]),
                "mean_abs_gap": mean([abs(a - b) for a, b in rows]), "mean_delta": mean([b - a for a, b in rows])}

    divergence = Counter(k[1] for k in set(ft) & set(rag) if ft[k][1].get("teacher_local") != rag[k][1].get("teacher_local"))
    return {"identical_input": describe(same), "divergent_input": describe(different),
            "divergent_by_language": dict(divergence.most_common())}


def language_repeats(ft: dict, rag: dict) -> dict[str, Any]:
    def conversations(turns: dict) -> dict[tuple, list[str]]:
        grouped = defaultdict(list)
        for (lesson, code, number), (_, turn) in sorted(turns.items()):
            grouped[(lesson, code)].append(turn.get("question_en") or "")
        return grouped

    a, b = conversations(ft), conversations(rag)
    return {"ft": sum(map(repeats_itself, a.values())), "rag": sum(map(repeats_itself, b.values())),
            "conversations": {"ft": len(a), "rag": len(b)}}


def tiers(ft: dict, rag: dict) -> dict[str, Any]:
    def per_language(turns: dict) -> dict[str, str]:
        scores = defaultdict(lambda: {"fidelity": [], "fluency": []})
        for (_, code, _), (_, turn) in turns.items():
            for metric in ("fidelity", "fluency"):
                if score(turn, metric) is not None:
                    scores[code][metric].append(score(turn, metric))
        return {code: "Blocked" if mean(s["fidelity"]) < 2.0 else "Review" if mean(s["fidelity"]) < 3.5 or mean(s["fluency"]) < 4.0 else "Ready"
                for code, s in scores.items()}

    a, b = per_language(ft), per_language(rag)
    return {"ft_ready": sum(v == "Ready" for v in a.values()), "rag_ready": sum(v == "Ready" for v in b.values()),
            "languages": len(a), "agreement": sum(a[c] == b.get(c) for c in a)}


def reliability(ft: dict, rag: dict) -> dict[str, Any]:
    def failures(turns: dict) -> tuple[int, int]:
        fails = crossings = 0
        for _, turn in turns.values():
            crossings += 3  # seed, inbound, outbound
            fails += turn.get("retries", 0) + bool(turn.get("seed_untranslated")) \
                + bool(turn.get("outbound_untranslated")) + bool(turn.get("english_zone_leak"))
        return fails, crossings

    (fa, fc), (ra, rc) = failures(ft), failures(rag)
    return {"ft_failures": fa, "ft_crossings": fc, "rag_failures": ra, "rag_crossings": rc,
            "p_value": fisher_two_sided(fa, fc, ra, rc)}


# ---------------------------------------------------------------- English sweep

def content_words(text: str) -> set[str]:
    return {w for w in words(text) if w not in STOP and len(w) > 2}


def responsiveness(convos: list[list[str]], script: list[str]) -> tuple[int, int, int]:
    """(anchored questions, answering the current sentence, looking back to an earlier one).

    A question "answers" a sentence when it shares the most content words with it, uniquely; it
    "looks back" when an earlier sentence beats the current one. Word overlap is a crude proxy.
    """
    anchored = current = backward = 0
    for convo in convos:
        for turn, text in enumerate(convo):
            asked = question_sentence(text)
            words_q = content_words(asked or "")
            if not words_q:
                continue
            overlap = [len(words_q & content_words(sentence)) / len(words_q) for sentence in script]
            if max(overlap) == 0 or turn >= len(overlap):
                continue
            anchored += 1
            best = max(overlap)
            current += overlap[turn] == best and overlap.count(best) == 1
            backward += turn > 0 and max(overlap[:turn]) > overlap[turn]
    return anchored, current, backward


def conversation_behaviour(ft_runs: list, rag_runs: list, rng: random.Random,
                           scripts: dict[str, list[str]] | None = None,
                           ft_depth: dict[str, list[str]] | None = None,
                           rag_depth: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """English-sweep measures for two arms, computed on the same lessons so their draws stay paired.

    The arms are labelled ft/rag for the main comparison; the experiment reuses this with committed
    RAG in the ft slot and the teacher-history arm in the rag slot.
    """
    def by_lesson(runs: list) -> dict[str, list[list[str]]]:
        grouped = defaultdict(list)
        for run in runs:
            grouped[run["lesson_id"]].append(run["baseline"]["questions"][1:])
        return grouped

    ft_lessons, rag_lessons = by_lesson(ft_runs), by_lesson(rag_runs)
    lessons = sorted(set(ft_lessons) & set(rag_lessons))

    def asked(grouped: dict, chosen: list[str]) -> list[str]:
        return [q for lesson in chosen for convo in grouped[lesson] for q in convo if "?" in q]

    def clean_share(grouped: dict, chosen: list[str]) -> float:
        convos = [convo for lesson in chosen for convo in grouped[lesson]]
        return 1 - mean([repeats_itself(c) for c in convos])

    def rarefied(items: list[str], n: int, draws: int) -> float:
        if len(items) <= n:
            return normalised_entropy([opener(q) for q in items])
        return mean([normalised_entropy([opener(q) for q in rng.sample(items, n)]) for _ in range(draws)])

    def deep_share(depth: dict[str, list[str]], chosen: list[str]) -> float:
        labels = [d for lesson in chosen for d in depth.get(lesson, [])]
        return mean([d == "deep" for d in labels]) if labels else 0.0

    def response_shares(grouped: dict, chosen: list[str]) -> tuple[float, float]:
        totals = [responsiveness(grouped[lesson], scripts[lesson]) for lesson in chosen]
        anchored = sum(t[0] for t in totals)
        return (sum(t[1] for t in totals) / anchored, sum(t[2] for t in totals) / anchored) if anchored else (0.0, 0.0)

    def measure(chosen: list[str], rarefy_draws: int) -> dict[str, dict[str, float]]:
        fq, rq = asked(ft_lessons, chosen), asked(rag_lessons, chosen)
        m = min(len(fq), len(rq))
        out = {
            "lexical_variety": {"ft": rarefied(fq, m, rarefy_draws), "rag": rarefied(rq, m, rarefy_draws)},
            "non_repetition": {"ft": clean_share(ft_lessons, chosen), "rag": clean_share(rag_lessons, chosen)},
            "question_rate": {"ft": mean([("?" in q) for lesson in chosen for c in ft_lessons[lesson] for q in c]),
                              "rag": mean([("?" in q) for lesson in chosen for c in rag_lessons[lesson] for q in c])},
        }
        if ft_depth is not None and rag_depth is not None:
            out["question_depth"] = {"ft": deep_share(ft_depth, chosen), "rag": deep_share(rag_depth, chosen)}
        if scripts is not None:
            (fa, fb), (ra, rb) = response_shares(ft_lessons, chosen), response_shares(rag_lessons, chosen)
            out["answers_current"] = {"ft": fa, "rag": ra}
            out["looks_backward"] = {"ft": fb, "rag": rb}
        return out

    ft_q, rag_q = asked(ft_lessons, lessons), asked(rag_lessons, lessons)
    n = min(len(ft_q), len(rag_q))
    point = measure(lessons, RAREFY)

    # Resampling lessons *with* replacement duplicates their questions, and duplicates depress
    # entropy, so an ordinary bootstrap sits below its own point estimate. Draw half the lessons
    # *without* replacement instead: for a mean-like statistic that half-sample has the same
    # variance as the full sample (the finite-population correction cancels the halved n), and
    # it never repeats a question. Entropy's level still depends on n, so each distribution is
    # centred on its own mean and placed on the full-sample estimate. Draws stay paired by index.
    raw = {metric: {"ft": [], "rag": []} for metric in point}
    for _ in range(ENGLISH_DRAWS):
        drawn = measure(rng.sample(lessons, len(lessons) // 2), 20)
        for metric, sides in drawn.items():
            for side, value in sides.items():
                raw[metric][side].append(value)

    place = lambda draws, centre: [centre + v - mean(draws) for v in draws]
    result = {}
    for metric in point:
        ft_draws = place(raw[metric]["ft"], point[metric]["ft"])
        rag_draws = place(raw[metric]["rag"], point[metric]["rag"])
        result[metric] = {
            "ft": point[metric]["ft"], "rag": point[metric]["rag"],
            "delta": point[metric]["rag"] - point[metric]["ft"],
            "delta_ci": interval([r - f for f, r in zip(ft_draws, rag_draws)]),
            "ft_draws": ft_draws, "rag_draws": rag_draws,
        }
    result["lexical_variety"]["rarefied_to"] = n
    result["lexical_variety"]["questions"] = {"ft": len(ft_q), "rag": len(rag_q)}
    result["non_repetition"]["conversations"] = {"ft": sum(map(len, ft_lessons.values())), "rag": sum(map(len, rag_lessons.values()))}
    result["non_repetition"]["repeating"] = {
        "ft": sum(repeats_itself(c) for convos in ft_lessons.values() for c in convos),
        "rag": sum(repeats_itself(c) for convos in rag_lessons.values() for c in convos),
    }
    return result


def load_depth(path: str) -> tuple[dict[str, dict[str, list[str]]], dict[str, Any]]:
    """Depth labels grouped arm -> lesson, plus the instrument's agreement with itself."""
    state = json.loads(Path(path).read_text())
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for item in state.get("items", []):
        if item.get("depth") in ("shallow", "intermediate", "deep"):
            grouped[item["arm"]][item["lesson_id"]].append(item["depth"])
    labels, retest = state.get("labels", {}), state.get("retest", {})
    pairs = [(labels[t], v) for t, v in retest.items() if t in labels and v.get("depth") and labels[t].get("depth")]
    reliability_check = {
        "retest_n": len(pairs),
        "same_depth": mean([a["depth"] == b["depth"] for a, b in pairs]) if pairs else None,
        "same_category": mean([a["category"] == b["category"] for a, b in pairs]) if pairs else None,
        "model": state.get("model"),
    }
    distribution = {
        arm: dict(Counter(d for lesson in lessons.values() for d in lesson)) for arm, lessons in grouped.items()
    }
    reliability_check["distribution"] = distribution
    return grouped, reliability_check


def english_detail(ft_runs: list, rag_runs: list) -> dict[str, Any]:
    out = {}
    for subject in SUBJECTS:
        row = {}
        for label, runs in (("ft", ft_runs), ("rag", rag_runs)):
            chosen = [r for r in runs if r["subject"] == subject]
            questions = [q for r in chosen for q in r["baseline"]["questions"][1:] if "?" in q]
            stem, count = Counter(opener(q) for q in questions).most_common(1)[0]
            row[label] = {"model": chosen[0]["profile"], "questions": len(questions), "top_stem": stem,
                          "top_stem_share": count / len(questions),
                          "repeating": sum(repeats_itself(r["baseline"]["questions"][1:]) for r in chosen),
                          "conversations": len(chosen)}
        out[subject] = row
    return out


# ---------------------------------------------------------------- scorecard

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--finetuned-english", nargs="+", required=True)
    parser.add_argument("--finetuned-languages", nargs="+", required=True)
    parser.add_argument("--rag-english", nargs="+", required=True)
    parser.add_argument("--rag-languages", nargs="+", required=True)
    parser.add_argument("--rag-history-english", nargs="+", help="experiment arm: RAG given the teacher's earlier sentences")
    parser.add_argument("--depth", help="output of judge_question_depth.py")
    parser.add_argument("--lessons", default=str(Path(__file__).resolve().parents[2] / "lessons.json"))
    args = parser.parse_args()
    rng = random.Random(SEED)

    ft_lang, rag_lang = language_turns(load_runs(args.finetuned_languages)), language_turns(load_runs(args.rag_languages))
    ft_eng, rag_eng = load_runs(args.finetuned_english), load_runs(args.rag_english)

    scripts = {lesson["id"]: lesson["script"] for lesson in json.loads(Path(args.lessons).read_text())["lessons"]}
    depth, depth_check = load_depth(args.depth) if args.depth else ({}, None)
    depth_scored = bool(depth_check and depth_check["same_depth"] is not None and depth_check["same_depth"] >= DEPTH_AGREEMENT_FLOOR)
    has_depth = lambda arm: arm in depth

    flu = fluency(ft_lang, rag_lang, rng)
    convo = conversation_behaviour(ft_eng, rag_eng, rng, scripts,
                                   depth.get("finetuned") if has_depth("finetuned") else None,
                                   depth.get("rag") if has_depth("rag") else None)
    tier = tiers(ft_lang, rag_lang)
    rel = reliability(ft_lang, rag_lang)

    to_100 = lambda v: (v - 1) / 4 * 100
    components = {
        "fluency": {"ft": to_100(flu["overall"]["ft"]), "rag": to_100(flu["overall"]["rag"]),
                    "ft_draws": [to_100(v) for v in flu["overall"]["ft_draws"]],
                    "rag_draws": [to_100(v) for v in flu["overall"]["rag_draws"]],
                    "verdict": verdict(flu["overall"]["delta_ci"])},
        "robustness": {"ft": tier["ft_ready"] / tier["languages"] * 100, "rag": tier["rag_ready"] / tier["languages"] * 100,
                       "verdict": "tie" if tier["ft_ready"] == tier["rag_ready"] else ("rag" if tier["rag_ready"] > tier["ft_ready"] else "ft")},
        "reliability": {"ft": (1 - rel["ft_failures"] / rel["ft_crossings"]) * 100,
                        "rag": (1 - rel["rag_failures"] / rel["rag_crossings"]) * 100,
                        "verdict": "tie" if rel["p_value"] >= 0.05 else ("rag" if rel["rag_failures"] < rel["ft_failures"] else "ft")},
    }
    for metric in ("lexical_variety", "non_repetition", "question_depth"):
        if metric not in convo:
            continue
        c = convo[metric]
        components[metric] = {"ft": c["ft"] * 100, "rag": c["rag"] * 100,
                              "ft_draws": [v * 100 for v in c["ft_draws"]], "rag_draws": [v * 100 for v in c["rag_draws"]],
                              "verdict": verdict(c["delta_ci"])}

    def composite(weights: dict[str, int]) -> dict[str, Any]:
        total = sum(weights.values())
        point = {side: sum(w * components[k][side] for k, w in weights.items()) / total for side in ("ft", "rag")}
        # The language and English sweeps are independent samples, so their draws combine by
        # index; the two count-based components are fixed at their observed values.
        draws = min(len(components[k]["ft_draws"]) for k in weights if k in SAMPLED)
        combined = {side: [] for side in ("ft", "rag")}
        for i in range(draws):
            for side in ("ft", "rag"):
                combined[side].append(sum(
                    w * (components[k][f"{side}_draws"][i] if k in SAMPLED else components[k][side])
                    for k, w in weights.items()) / total)
        gap_ci = interval([r - f for f, r in zip(combined["ft"], combined["rag"])])
        return {"weights": weights, "ft": point["ft"], "rag": point["rag"], "gap": point["rag"] - point["ft"],
                "ft_ci": interval(combined["ft"]), "rag_ci": interval(combined["rag"]), "gap_ci": gap_ci,
                "leader": verdict(gap_ci)}

    primary, alternatives = (SIX, SIX_ALTERNATIVES) if depth_scored and "question_depth" in components else (FIVE, FIVE_ALTERNATIVES)
    verdicts = {k: components[k]["verdict"] for k in primary}
    tally = Counter(verdicts.values())
    dominant = "rag" if tally["rag"] and not tally["ft"] else "ft" if tally["ft"] and not tally["rag"] else None
    drop = lambda d: {k: v for k, v in d.items() if not k.endswith("_draws")}

    experiment = None
    if args.rag_history_english:
        hist_eng = load_runs(args.rag_history_english)
        vs_rag = conversation_behaviour(rag_eng, hist_eng, rng, scripts,
                                        depth.get("rag") if has_depth("rag") else None,
                                        depth.get("rag_history") if has_depth("rag_history") else None)
        vs_ft = conversation_behaviour(ft_eng, hist_eng, rng, scripts,
                                       depth.get("finetuned") if has_depth("finetuned") else None,
                                       depth.get("rag_history") if has_depth("rag_history") else None)
        # Projection: the arm has no language sweep, so its language-side components are RAG's.
        projected = {k: dict(components[k]) for k in ("fluency", "robustness", "reliability")}
        for k in projected:
            projected[k]["ft"] = components[k]["ft"]
        for metric in ("lexical_variety", "non_repetition", "question_depth"):
            if metric in vs_ft:
                c = vs_ft[metric]
                projected[metric] = {"ft": c["ft"] * 100, "rag": c["rag"] * 100,
                                     "ft_draws": [v * 100 for v in c["ft_draws"]], "rag_draws": [v * 100 for v in c["rag_draws"]],
                                     "verdict": verdict(c["delta_ci"])}
        saved = dict(components)
        components.clear(); components.update(projected)
        projection = composite(primary)
        components.clear(); components.update(saved)
        experiment = {
            "runs": len(hist_eng),
            "versus_rag": {k: drop(v) for k, v in vs_rag.items()},
            "versus_finetuned": {k: drop(v) for k, v in vs_ft.items()},
            "repeating": {"rag": vs_rag["non_repetition"]["repeating"]["ft"], "rag_history": vs_rag["non_repetition"]["repeating"]["rag"],
                          "finetuned": vs_ft["non_repetition"]["repeating"]["ft"], "conversations": len(hist_eng)},
            "projected_composite_vs_finetuned": projection,
            "projected_components": {k: drop(v) for k, v in projected.items()},
            "projection_note": "language-side components (fluency, robustness, reliability) reuse committed RAG values",
            "by_subject": english_detail(ft_eng, hist_eng),
        }

    print(json.dumps({
        "scorecard": "six-dimension" if primary is SIX else "five-dimension",
        "depth_scored": depth_scored,
        "depth_check": depth_check,
        "weights": primary,
        "components": {k: drop(v) for k, v in components.items()},
        "composite": composite(primary),
        "five_dimension": composite(FIVE),
        "predeclared": composite(PREDECLARED),
        "alternative_weightings": {name: composite(w) for name, w in alternatives.items()},
        "dimension_verdicts": verdicts,
        "dominant": dominant,
        "experiment": experiment,
        "english_behaviour": {k: drop(v) for k, v in convo.items() if k in ("answers_current", "looks_backward", "question_rate")},
        "fluency": {k: (drop(v) if isinstance(v, dict) and "delta" in v else v) for k, v in flu.items()},
        "lexical_variety": drop(convo["lexical_variety"]),
        "non_repetition": drop(convo["non_repetition"]),
        **({"question_depth": drop(convo["question_depth"])} if "question_depth" in convo else {}),
        "non_repetition_languages": language_repeats(ft_lang, rag_lang),
        "english_by_subject": english_detail(ft_eng, rag_eng),
        "tiers": tier,
        "reliability": rel,
        "fidelity_control": fidelity_control(ft_lang, rag_lang),
        "method": {"bootstrap": BOOTSTRAP, "english_draws": ENGLISH_DRAWS, "rarefaction_draws": RAREFY, "seed": SEED},
    }, indent=1))


if __name__ == "__main__":
    main()
