"""Test whether turns that retrieve the same passages are the turns where RAG repeats a question.

    OPENROUTER_API_KEY=... python scripts/retrieval_overlap.py --out retrieval-overlap.json

Pre-registered in PHASE1_PREREGISTRATION.md ("Retrieval overlap and repeated questions") before this
script was run. Nothing is generated: each lesson sentence is sent to similarity_search(k=4) against the
committed vectorstore, exactly as the English sweep did, and the questions are read from the committed
sweepA-rag.json and sweepA-rag-history.json. Cost is one embedding call per teacher sentence (72).

The vectorstore is copied to a temporary directory before it is opened, so a newer chromadb cannot
migrate the committed files in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO / "teach2learn-portal" / "scripts"))
from score_systems import normalised, question_sentence  # noqa: E402  same normalisation as the scorecard

EMBEDDING_MODEL = "openai/text-embedding-3-small"
K = 4
SEED = 20260914
DRAWS = 5000
MIN_GROUP = 5


def passage_id(doc) -> str:
    meta = doc.metadata or {}
    digest = hashlib.sha1(doc.page_content.encode("utf-8")).hexdigest()[:12]
    return f"{Path(str(meta.get('source', '?'))).name}#p{meta.get('page', '?')}#{digest}"


def retrieve(lessons: list[dict], api_key: str) -> dict[str, list[list[str]]]:
    from langchain_community.vectorstores import Chroma
    from langchain_openai import OpenAIEmbeddings

    catalog = json.loads((ROOT / "vectorstore" / "catalog.json").read_text())
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL, base_url="https://openrouter.ai/api/v1",
                                  api_key=api_key, check_embedding_ctx_length=False)
    out: dict[str, list[list[str]]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        stores = {}
        for subject in sorted({lesson["subject"] for lesson in lessons}):
            copy = Path(tmp) / subject
            shutil.copytree(ROOT / catalog[subject]["vectorstore_path"], copy)
            stores[subject] = Chroma(persist_directory=str(copy), embedding_function=embeddings)
        for lesson in lessons:
            ids = []
            for sentence in lesson["script"]:
                docs = stores[lesson["subject"]].similarity_search(sentence, k=K)
                if len(docs) != K:
                    raise SystemExit(f"{lesson['id']}: expected {K} passages, got {len(docs)}")
                ids.append([passage_id(d) for d in docs])
            out[lesson["id"]] = ids
            print(f"retrieved {lesson['id']}", file=sys.stderr)
    return out


def followups_by_lesson(path: Path) -> dict[str, list[list[str]]]:
    grouped: dict[str, list[list[str]]] = {}
    for run in json.loads(path.read_text())["runs"]:
        grouped.setdefault(run["lesson_id"], []).append(run["baseline"]["questions"][1:])
    return grouped


def repeats(convo: list[str], i: int, j: int) -> bool:
    a, b = question_sentence(convo[i]), question_sentence(convo[j])
    return a is not None and b is not None and normalised(a) == normalised(b)


def jaccard(a: list[str], b: list[str]) -> float:
    return len(set(a) & set(b)) / len(set(a) | set(b))


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda k: values[k])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(x: list[float], y: list[float]) -> float | None:
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if not vx or not vy:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (vx * vy) ** 0.5


def difference(units: list[dict], key: str) -> float | None:
    hit = [u[key] for u in units if u["overlap"] > 0]
    miss = [u[key] for u in units if u["overlap"] == 0]
    if not hit or not miss:
        return None
    return sum(hit) / len(hit) - sum(miss) / len(miss)


def interval(values: list[float]) -> list[float]:
    values = sorted(values)
    return [values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]]


def bootstrap(units: list[dict], stat, rng: random.Random) -> dict:
    by_lesson: dict[str, list[dict]] = {}
    for unit in units:
        by_lesson.setdefault(unit["lesson_id"], []).append(unit)
    lessons = sorted(by_lesson)
    draws, skipped = [], 0
    for _ in range(DRAWS):
        sample = [u for lesson in (rng.choice(lessons) for _ in lessons) for u in by_lesson[lesson]]
        value = stat(sample)
        if value is None:
            skipped += 1
        else:
            draws.append(value)
    return {"ci95": interval(draws) if draws else None, "draws": len(draws), "skipped_draws": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lessons", default=str(REPO / "lessons.json"))
    parser.add_argument("--rag", default=str(ROOT / "sweepA-rag.json"))
    parser.add_argument("--rag-history", default=str(ROOT / "sweepA-rag-history.json"))
    parser.add_argument("--out", default=str(ROOT / "retrieval-overlap.json"))
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set")

    started = datetime.now(timezone.utc)
    bank = json.loads(Path(args.lessons).read_text())
    lessons = bank["lessons"]
    passages = retrieve(lessons, api_key)
    arms = {"rag": followups_by_lesson(Path(args.rag)), "rag_history": followups_by_lesson(Path(args.rag_history))}

    units = []
    for lesson in lessons:
        ids = passages[lesson["id"]]
        for i, j in combinations(range(len(lesson["script"])), 2):
            unit = {"lesson_id": lesson["id"], "subject": lesson["subject"], "pair": [i + 1, j + 1],
                    "overlap": jaccard(ids[i], ids[j]), "shared_passages": len(set(ids[i]) & set(ids[j]))}
            total = count = 0
            for arm, grouped in arms.items():
                convos = grouped.get(lesson["id"], [])
                hits = sum(repeats(c, i, j) for c in convos)
                unit[f"repeats_{arm}"] = hits
                unit[f"conversations_{arm}"] = len(convos)
                total, count = total + hits, count + len(convos)
            unit["repeat_rate"] = total / count if count else 0.0
            for arm in arms:
                n = unit[f"conversations_{arm}"]
                unit[f"repeat_rate_{arm}"] = unit[f"repeats_{arm}"] / n if n else 0.0
            units.append(unit)

    groups = {"overlap_gt_0": sum(u["overlap"] > 0 for u in units), "overlap_eq_0": sum(u["overlap"] == 0 for u in units)}
    rng = random.Random(SEED)
    use_difference = min(groups.values()) >= MIN_GROUP
    overlaps = lambda sample: [u["overlap"] for u in sample]
    results = {"primary_test": "difference" if use_difference else "spearman (fallback: a group had fewer than 5 units)"}
    for key in ("repeat_rate", "repeat_rate_rag", "repeat_rate_rag_history"):
        entry = {
            "difference": difference(units, key),
            "spearman": spearman(overlaps(units), [u[key] for u in units]),
            "rate_overlap_gt_0": (sum(u[key] for u in units if u["overlap"] > 0) / groups["overlap_gt_0"]) if groups["overlap_gt_0"] else None,
            "rate_overlap_eq_0": (sum(u[key] for u in units if u["overlap"] == 0) / groups["overlap_eq_0"]) if groups["overlap_eq_0"] else None,
        }
        entry["difference_bootstrap"] = bootstrap(units, lambda s, k=key: difference(s, k), rng)
        entry["spearman_bootstrap"] = bootstrap(units, lambda s, k=key: spearman(overlaps(s), [u[k] for u in s]), rng)
        results[key] = entry

    primary = results["repeat_rate"]["difference_bootstrap" if use_difference else "spearman_bootstrap"]["ci95"]
    verdict = ("hypothesis failed (interval includes zero)" if primary is None or primary[0] <= 0 <= primary[1]
               else "supported" if primary[0] > 0 else "contradicted (interval below zero)")

    distribution: dict[str, int] = {}
    for unit in units:
        distribution[f"{unit['shared_passages']} of {K}"] = distribution.get(f"{unit['shared_passages']} of {K}", 0) + 1

    report = {
        "provenance": {
            "preregistration": "PHASE1_PREREGISTRATION.md, 'Retrieval overlap and repeated questions', 2026-09-19T05:32:53Z",
            "started_utc": started.isoformat(timespec="seconds"),
            "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "embedding_model": EMBEDDING_MODEL, "k": K, "seed": SEED, "bootstrap_draws": DRAWS,
            "lessons": args.lessons, "lessons_version": bank.get("version"),
            "rag_results": Path(args.rag).name, "rag_history_results": Path(args.rag_history).name,
            "embedding_calls": sum(len(lesson["script"]) for lesson in lessons),
        },
        "groups": groups,
        "shared_passages_distribution": dict(sorted(distribution.items())),
        "identical_passage_sets": sum(u["shared_passages"] == K for u in units),
        "results": results,
        "verdict": verdict,
        "units": units,
        "passages": passages,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    json.dump({k: report[k] for k in ("groups", "shared_passages_distribution", "identical_passage_sets", "verdict")}
              | {"primary": results["repeat_rate"]}, sys.stdout, indent=2, default=str)
    print()


if __name__ == "__main__":
    main()
