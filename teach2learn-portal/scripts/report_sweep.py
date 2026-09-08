"""Turn one or more results files into the markdown tables the write-up needs.

    python3 scripts/report_sweep.py sweepA-*.json > results-english.md
    python3 scripts/report_sweep.py sweepB-*.json > results-languages.md

Reads whatever it is given and emits only the sections the data supports, so a run
stopped after two subjects still produces a table for those two. Every figure that
comes from more than one observation carries its range, because the test bed exists
to make a subject average mean more than one script run once: where two ranges
overlap, the difference between them is not a finding.

Nothing here recomputes a judgement. Fidelity and fluency are the judge's scores as
recorded, distinct-question counts are the harness's, and the Bloom levels are the
adapter's own evaluation block. This only groups and averages them.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SUBJECT_NAMES = {
    "cp": "Computer Programming",
    "dsa": "Data Structures and Algorithms",
    "oop_java": "OOP with Java",
    "os": "Operating Systems",
}

# The adapter's own Score field, ordered so a mean means something.
SCORE_RANK = {"low": 0, "medium": 1, "moderate": 1, "high": 2}
BLOOM = ("remember", "understand", "apply", "analy", "evaluat", "create")


def spread(values: list[float], places: int = 2) -> str:
    """A mean, plus its range when there is more than one observation behind it."""
    if not values:
        return "-"
    mean = sum(values) / len(values)
    if len(values) == 1:
        return f"{mean:.{places}f}"
    return f"{mean:.{places}f} ({min(values):.{places}f}-{max(values):.{places}f})"


def load(paths: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runs: list[dict[str, Any]] = []
    beds: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(Path(path).read_text())
        except json.JSONDecodeError as exc:
            # An incremental write caught mid-flight, or a run still going.
            print(f"skipping {path}: {exc}", file=sys.stderr)
            continue
        beds.append(payload.get("test_bed", {}) | {"_path": path})
        runs.extend(payload.get("runs", []))
    return runs, beds


def report_test_bed(beds: list[dict[str, Any]], runs: list[dict[str, Any]]) -> None:
    print("## Test bed\n")
    lessons = sorted({run["lesson_id"] for run in runs})
    subjects = sorted({run["subject"] for run in runs})
    repeats = sorted({run["repeat"] for run in runs})
    backends = sorted({bed.get("backend") for bed in beds if bed.get("backend")})
    languages = sorted({code for bed in beds for code in bed.get("languages") or []})
    fake = any(bed.get("results_are_fake") for bed in beds)
    unreviewed = any(bed.get("results_are_unreviewed") for bed in beds)

    print("| | |")
    print("|---|---|")
    print(f"| Subjects | {len(subjects)} — {', '.join(SUBJECT_NAMES.get(s, s) for s in subjects)} |")
    print(f"| Lessons | {len(lessons)} |")
    print(f"| Repeats per lesson | {max(repeats) if repeats else 0} |")
    print(f"| Languages | {len(languages) if languages else 'English only'} |")
    print(f"| Backend | {', '.join(backends)} |")
    for bed in beds[:1]:
        print(f"| Decoding | temperature {bed.get('temperature')}, top-p {bed.get('top_p')} |")
        print(f"| Judge | {bed.get('judge_model') or 'not used'} |")
        print(f"| Lesson bank | {bed.get('lessons_source')} v{bed.get('lessons_version')} |")
        print(f"| Run at | {bed.get('generated_utc')} |")
    print(f"| Total runs | {len(runs)} |")
    print()
    if fake:
        print("> **These results are from the fake backend and describe a canned string, "
              "not a model. They must not be reported.**\n")
    if unreviewed:
        print("> **At least one lesson had no human review.**\n")


def report_english(runs: list[dict[str, Any]]) -> None:
    """Does the learner vary its questions, and how deeply does it probe?"""
    with_baseline = [run for run in runs if run.get("baseline")]
    if not with_baseline:
        return

    print("## Question variety, by subject\n")
    print("Distinct questions as a fraction of questions asked, and how often a follow-up")
    print("reused an opening phrase. Higher variety is better; repeated openers are the")
    print("formulaic-learner failure the baseline check exists to catch.\n")
    print("| Subject | Model | Lessons | Runs | Distinct question ratio | Runs with repeated openers | Most repeated opening |")
    print("|---|---|---:|---:|---|---:|---|")

    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in with_baseline:
        by_subject[run["subject"]].append(run)

    for subject in sorted(by_subject):
        subject_runs = by_subject[subject]
        ratios = [
            run["baseline"]["distinct"] / max(len(run["baseline"]["questions"]), 1)
            for run in subject_runs
        ]
        templated = sum(1 for run in subject_runs if run["baseline"].get("templated_openers"))
        lessons = len({run["lesson_id"] for run in subject_runs})
        profile = sorted({run["profile"] for run in subject_runs})
        repeats = Counter()
        for run in subject_runs:
            for item in run["baseline"].get("templated_openers") or []:
                repeats[item["opener"]] += item["count"]
        top = repeats.most_common(1)
        worst = f"{top[0][1]}x \u201c{top[0][0]}\u2026\u201d" if top else "none"
        print(
            f"| {SUBJECT_NAMES.get(subject, subject)} | {', '.join(profile)} | {lessons} | "
            f"{len(subject_runs)} | {spread(ratios)} | {templated}/{len(subject_runs)} | {worst} |"
        )
    print()
    print("The distinct-question ratio counts whole strings, so it reads 1.00 even when every")
    print("follow-up opens with the same clause. The last column is what that ratio hides: how")
    print("often one opening phrase recurred, out of roughly four questions per run.\n")

    print("### Per lesson\n")
    print("| Lesson | Runs | Distinct question ratio | Bloom level reached | Adapter score |")
    print("|---|---:|---|---|---|")
    by_lesson: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in with_baseline:
        by_lesson[run["lesson_id"]].append(run)
    for lesson_id in sorted(by_lesson):
        lesson_runs = by_lesson[lesson_id]
        ratios = [
            run["baseline"]["distinct"] / max(len(run["baseline"]["questions"]), 1)
            for run in lesson_runs
        ]
        evaluations = [
            item
            for run in lesson_runs
            for item in run["baseline"].get("evaluations") or []
            if item
        ]
        print(
            f"| `{lesson_id}` | {len(lesson_runs)} | {spread(ratios)} | "
            f"{_bloom(evaluations)} | {_score(evaluations)} |"
        )
    print()


def _bloom(evaluations: list[dict[str, Any]]) -> str:
    levels = [str(item.get("level", "")).strip().lower() for item in evaluations]
    ranked = [
        next((index for index, name in reversed(tuple(enumerate(BLOOM))) if name in level), 0)
        for level in levels
        if level
    ]
    if not ranked:
        return "-"
    top = Counter(levels).most_common(1)[0][0].title()
    return f"{top} ({spread([float(value) for value in ranked], places=1)})"


def _score(evaluations: list[dict[str, Any]]) -> str:
    ranked = [
        float(SCORE_RANK[key])
        for item in evaluations
        for key in [str(item.get("score", "")).strip().lower()]
        if key in SCORE_RANK
    ]
    if not ranked:
        return "-"
    return f"{spread(ranked, places=1)} of 2"


def report_languages(runs: list[dict[str, Any]]) -> None:
    with_sweep = [run for run in runs if run.get("sweep")]
    if not with_sweep:
        return

    # language -> every judged cell across lessons, subjects and repeats
    fidelity: dict[str, list[float]] = defaultdict(list)
    fluency: dict[str, list[float]] = defaultdict(list)
    names: dict[str, str] = {}
    failures: dict[str, list[str]] = defaultdict(list)
    mechanical = {"seed": 0, "outbound": 0, "leak": 0, "turns": 0, "retries": 0}

    for run in with_sweep:
        for record in run["sweep"]:
            code = record["code"]
            names[code] = record["language"]
            if record.get("error"):
                failures[code].append(f"{run['lesson_id']}: {record['error'][:60]}")
                continue
            for turn in record["turns"]:
                mechanical["turns"] += 1
                mechanical["seed"] += bool(turn["seed_untranslated"])
                mechanical["outbound"] += bool(turn["outbound_untranslated"])
                mechanical["leak"] += bool(turn["english_zone_leak"])
                mechanical["retries"] += turn.get("retries", 0)
                if (turn.get("fidelity") or {}).get("score"):
                    fidelity[code].append(float(turn["fidelity"]["score"]))
                if (turn.get("fluency") or {}).get("score"):
                    fluency[code].append(float(turn["fluency"]["score"]))

    print("## Mechanical checks\n")
    print("No judgement involved. These are the figures to quote.\n")
    print("| | Count | Over |")
    print("|---|---:|---:|")
    print(f"| Untranslated participant text | {mechanical['seed']} | {mechanical['turns']} turns |")
    print(f"| Untranslated text shown back | {mechanical['outbound']} | {mechanical['turns']} turns |")
    print(f"| Native script reaching the English zone | {mechanical['leak']} | {mechanical['turns']} turns |")
    print(f"| Crossings needing a retry | {mechanical['retries']} | {mechanical['turns'] * 3} crossings |")
    print()

    print("## Judged quality, by language\n")
    print("Fidelity is whether the meaning survived; fluency is whether a native reader")
    print("would accept the sentence. Both are an independent model's opinion, 1-5, and")
    print("both are directional until a native reader confirms them.\n")
    print("| Language | Code | Cells | Fidelity | Fluency |")
    print("|---|---|---:|---|---|")
    for code in sorted(names, key=lambda c: -(sum(fluency[c]) / len(fluency[c]) if fluency[c] else 0)):
        note = "  **FAILED**" if failures[code] else ""
        print(
            f"| {names[code]}{note} | `{code}` | {len(fidelity[code])} | "
            f"{spread(fidelity[code], places=1)} | {spread(fluency[code], places=1)} |"
        )
    print()

    if any(failures.values()):
        print("### Languages that failed to run\n")
        for code, reasons in sorted(failures.items()):
            if reasons:
                print(f"- **{names[code]}** (`{code}`): {reasons[0]}")
        print()


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        raise SystemExit(__doc__)
    runs, beds = load(paths)
    if not runs:
        raise SystemExit("no runs found in " + ", ".join(paths))
    print("# Results\n")
    report_test_bed(beds, runs)
    report_english(runs)
    report_languages(runs)


if __name__ == "__main__":
    main()
