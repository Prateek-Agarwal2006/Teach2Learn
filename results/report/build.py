"""Builds the RAG results report (HTML with inline SVG) and, given a second path, the dashboard data files.

Usage: python3 build.py OUT.html [DATA_DIR]; then print with Chrome:
google-chrome --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf=OUT.pdf file://OUT.html
"""
import glob, html, json, random, statistics as st, sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import t2l_eval as t

OUT = Path(sys.argv[1])
NAME = {"google/gemini-4-argon": "Gemini 4 Argon", "openai/gpt-6.1-sol": "GPT-6.1 Sol", "ibm-granite/granite-4.2-8b": "Granite 4.2 8B", "meta-llama/llama-3.1-8b-instruct": "Llama 3.1 8B", "qwen/qwen-2.5-7b-instruct": "Qwen 2.5 7B"}
ORDER = ["Gemini 4 Argon", "GPT-6.1 Sol", "Granite 4.2 8B", "Llama 3.1 8B", "Qwen 2.5 7B"]
COLOR = {"Gemini 4 Argon": "#3a8f4f", "GPT-6.1 Sol": "#b8455a", "Granite 4.2 8B": "#1f6f86", "Llama 3.1 8B": "#c4802b", "Qwen 2.5 7B": "#7b4f93"}
TEACH = {"good": "Accurate", "omit": "Leaves a step out", "vague": "Vague", "error": "Makes an error"}
DIMS = [("reliability", "Reliability"), ("questioning", "Questioning"), ("novice_role", "Beginner role"),
        ("flaw_catching", "Catching flaws"), ("no_false_alarms", "No false alarms"), ("responds_to_teaching", "Reacts to teaching")]
esc = html.escape
who = lambda s: NAME[s["model"]]

files = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(REPO / "results/rag_*.json")))]
dates = sorted(f["meta"]["started_utc"][:10] for f in files)
sessions = [s for f in files for s in f["sessions"]]
measured = [(s, t.measure(s)) for s in sessions]
derived = t.contrasts([(s, v) for s, v in measured if v.get("valid")])
cells = {NAME[k.split(" · ")[1]]: v for k, v in t.learner_cells(measured, derived).items()}
lessons = sorted({i for c in cells.values() for i in c})

# Final score, the same bootstrap as t2l_eval.composite (seed 0, 1000 draws).
rng, boot = random.Random(0), defaultdict(list)
for _ in range(1000):
    sample = rng.choices(lessons, k=len(lessons))
    got = {w: t.final_score(cells[w], sample, t.WEIGHTS)[0] for w in ORDER}
    best = max(got, key=got.get)
    for w, x in got.items():
        boot[w].append(x); boot[w + "!"].append(float(w == best))
def rank(weights):
    return {w: r for r, w in enumerate(sorted(ORDER, key=lambda w: -t.final_score(cells[w], lessons, weights)[0]), 1)}
main = rank(t.WEIGHTS)
flat = rank({d: (1 / len(t.WEIGHTS), ms) for d, (_, ms) in t.WEIGHTS.items()})
leave = {d: rank({k: v for k, v in t.WEIGHTS.items() if k != d}) for d in t.WEIGHTS}
final = {}
for w in ORDER:
    total, dims = t.final_score(cells[w], lessons, t.WEIGHTS); b = sorted(boot[w])
    final[w] = {"score": total, "lo": b[25], "hi": b[975], "first": st.mean(boot[w + "!"]), **dims}
ranked = sorted(ORDER, key=main.get)

def pooled(w, m, cond=None):
    xs = [v[m] for s, v in measured if who(s) == w and m in v and (cond is None or s["condition"] == cond)]
    return st.mean(xs) if xs else None
contrast = {w: {k: st.mean(v[k] for s, v in derived if NAME[s["model"]] == w and k in v) for k in
                [f"{c}_minus_good_{m}" for c in ("omit", "vague", "error") for m in ("turns", "completed")] + ["net_flaw_detection"]} for w in ORDER}
cut = {w: sum(1 for s in sessions if who(s) == w and not s["error"] and s["turns"] and s["turns"][-1]["learner"]["kind"] == "invalid") for w in ORDER}
per = {w: sum(1 for s in sessions if who(s) == w) for w in ORDER}
phr = {}
for w in ORDER:
    texts = [x["learner"]["text"] for s in sessions if who(s) == w for x in s["turns"] if x["learner"]["kind"] != "invalid"]
    top, n = Counter(" ".join(x.lower().split()[:3]) for x in texts).most_common(1)[0]
    pairs = [b for x in texts for b in zip(x.lower().split(), x.lower().split()[1:])]
    phr[w] = {"replies": len(texts), "top": top, "rate": n / len(texts), "distinct": len(set(pairs)) / len(pairs)}
questions = {w: sum(1 for s in sessions if who(s) == w for x in s["turns"] if x["learner"]["kind"] == "question") for w in ORDER}
replies = {w: sum(1 for s in sessions if who(s) == w for x in s["turns"]) for w in ORDER}

f1 = lambda x: f"{x:.1f}"; f2 = lambda x: f"{x:.2f}"; pct = lambda x: f"{x * 100:.0f}%"

def text_w(s, size):  # rough width for label room in SVG
    return len(s) * size * 0.56

def grouped(groups, value, vmax, fmt, ticks, title, tickfmt=None, bar=7, gout=13):
    tickfmt = tickfmt or fmt
    W, gin, top, bottom = 660, 2, 6, 24
    gh = len(ORDER) * bar + (len(ORDER) - 1) * gin
    H = top + len(groups) * gh + (len(groups) - 1) * gout + bottom
    left = max(text_w(g, 11) for g in groups) + 14
    right = text_w(fmt(vmax), 9.5) + 10
    x = lambda v: left + (W - left - right) * v / vmax
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{esc(title)}" class="chart">']
    for tk in ticks:
        out.append(f'<line x1="{x(tk):.1f}" x2="{x(tk):.1f}" y1="{top}" y2="{H - bottom}" class="grid"/>'
                   f'<text x="{x(tk):.1f}" y="{H - 7}" text-anchor="middle" class="tick">{esc(tickfmt(tk))}</text>')
    out.append(f'<line x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{top}" y2="{H - bottom}" class="axis"/>')
    for gi, g in enumerate(groups):
        y0 = top + gi * (gh + gout)
        out.append(f'<text x="{left - 8:.1f}" y="{y0 + gh / 2:.1f}" dy="0.35em" text-anchor="end" class="lab">{esc(g)}</text>')
        for si, w in enumerate(ORDER):
            v = value(g, w)
            if v is None:
                continue
            y = y0 + si * (bar + gin)
            out.append(f'<rect x="{x(0):.1f}" y="{y}" width="{max(1.5, x(v) - x(0)):.1f}" height="{bar}" rx="2.5" fill="{COLOR[w]}"/>'
                       f'<text x="{x(v) + 4:.1f}" y="{y + bar / 2}" dy="0.35em" class="val">{esc(fmt(v))}</text>')
    return "".join(out) + "</svg>"

def dots():
    W, rh, top, bottom = 660, 34, 8, 24
    H = top + len(ORDER) * rh + bottom
    left = max(text_w(w, 11) for w in ORDER) + 16
    x = lambda v: left + (W - left - 14) * v / 100
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Final score with 95% range" class="chart">']
    for tk in range(0, 101, 20):
        out.append(f'<line x1="{x(tk):.1f}" x2="{x(tk):.1f}" y1="{top}" y2="{H - bottom}" class="grid"/>'
                   f'<text x="{x(tk):.1f}" y="{H - 7}" text-anchor="middle" class="tick">{tk}</text>')
    for i, w in enumerate(ranked):
        r, cy = final[w], top + i * rh + rh / 2
        out.append(f'<text x="{left - 10:.1f}" y="{cy}" dy="0.35em" text-anchor="end" class="lab">{esc(w)}</text>'
                   f'<line x1="{x(r["lo"]):.1f}" x2="{x(r["hi"]):.1f}" y1="{cy}" y2="{cy}" stroke="{COLOR[w]}" stroke-width="3" stroke-linecap="round"/>'
                   f'<circle cx="{x(r["score"]):.1f}" cy="{cy}" r="5" fill="{COLOR[w]}" stroke="#fff" stroke-width="1.5"/>'
                   f'<text x="{x(r["hi"]) + 9:.1f}" y="{cy}" dy="0.35em" class="val">{f1(r["score"])} [{f1(r["lo"])}–{f1(r["hi"])}]</text>')
    return "".join(out) + "</svg>"

legend = '<div class="legend">' + "".join(f'<span><i style="background:{COLOR[w]}"></i>{esc(w)}</span>' for w in ORDER) + "</div>"

def table(head, rows, cls=""):
    h = "".join(f"<th>{esc(c)}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>'

METRICS = [
    ("Reliability", [("valid", "Sessions that didn't fail"), ("invalid_turns", "Unusable replies"), ("opening_is_question", "Opening is a question")]),
    ("Questioning", [("productive", "Productive questions"), ("deep_question", "Deep questions"), ("why_how", "Why/how questions (share of questions)"),
                     ("builds_on_earlier", "Builds on earlier turns"), ("no_question", "Replies that ask nothing"),
                     ("repeats", "Repeats an earlier question (judged)"), ("self_repeat", "Repeated wording (counted)")]),
    ("Beginner role", [("stays_novice", "Stays a beginner"), ("echo", "Wording overlap with the teacher"), ("distinct_2", "Varied wording")]),
    ("Catching flaws", [("challenge_when_flawed", "Challenges a wrong answer"), ("flaw_targeted", "Targets the actual mistake"),
                        ("flaw_caught", "Catches the flaw at least once")]),
    ("No false alarms", [("challenge_when_clean", "Challenges a correct answer")]),
    ("Not scored", [("turns", "Turns per session"), ("learner_words", "Words per reply"), ("learner_seconds", "Seconds per reply"),
                    ("elicited_score", "Judge's grade of the teacher's answers (0–2)"), ("key_points_covered", "Lesson points the teacher covered")]),
]
COUNT = {"turns": f1, "learner_words": lambda v: f"{v:.0f}", "learner_seconds": f1, "elicited_score": f2}
metric_rows = []
for group, ms in METRICS:
    metric_rows.append([f'<b>{esc(group)}</b>'] + [""] * len(ORDER))
    for m, label in ms:
        metric_rows.append([esc(label)] + [(COUNT.get(m, pct))(pooled(w, m)) if pooled(w, m) is not None else "—" for w in ORDER])

UNSCORED_PLAIN = [
    ("Words per reply, length ratio, turns", "neither direction is better"),
    ("Teacher words, lesson points covered", "these measure the simulated teacher"),
    ("Seconds per reply", "measures hardware: RAG calls an API from a laptop, fine-tuned runs on a local GPU"),
    ("Judge's grades of the teacher's answers", "they grade the teacher, not the learner"),
    ("Turn-count contrasts", "the same reaction as the completion contrasts"),
    ("Net flaw detection", "both of its parts are scored"),
    ("Detection delay", "scored as detection speed, which also counts flaws never caught"),
    ("Final feedback names the flaw", "written by the one shared judge, not by either system"),
]

css = Path(__file__).with_name("style.css").read_text()
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>RAG learner results</title><style>{css}</style></head><body>
<header>
    <h1>RAG learner results</h1>
  <p class="sub">{len(sessions)} sessions · 48 lessons × 4 teacher styles × {len(ORDER)} models · English · {dates[0]} to {dates[-1]}</p>
</header>



<section>
  <h2>Final score (0–100, 95% range)</h2>
  {dots()}
  {table(["Learner", "Score", "95% range", "Chance of first", *[d[1] for d in DIMS]],
         [[f"<b>{esc(w)}</b>", f1(final[w]['score']), f"{f1(final[w]['lo'])}–{f1(final[w]['hi'])}", pct(final[w]['first']),
           *[f1(final[w][d]) for d, _ in DIMS]] for w in ranked], "num")}
  <h3>Rank under other weightings</h3>
  {table(["Learner", "Agreed weights", "Equal weights", *[f"Without {d[1].lower()}" for d in DIMS]],
         [[esc(w), str(main[w]), str(flat[w]), *[str(leave[d][w]) for d, _ in DIMS]] for w in ranked], "num")}
</section>

<section>
  <h2>Score by group</h2>
  {legend}
  {grouped([d[1] for d in DIMS], lambda g, w: final[w][next(k for k, n in DIMS if n == g)], 100, f1, range(0, 101, 20), "Score by group", tickfmt=str, bar=6, gout=10)}
  <h2>Weights</h2>
  {table(["Group", "Weight"], [[n, pct(t.WEIGHTS[k][0])] for k, n in DIMS], "num")}
</section>

<section class="break">
  <h2>Questions</h2>
  {legend}
  {grouped(["Opens with a question", "Asks nothing", "Productive question", "Deep question", "Repeats a question"],
           lambda g, w: pooled(w, {"Opens with a question": "opening_is_question", "Asks nothing": "no_question", "Productive question": "productive",
                                   "Deep question": "deep_question", "Repeats a question": "repeats"}[g]), 1, pct, [0, .25, .5, .75, 1], "Question rates")}
  <h2>Flaws in the teaching</h2>
  {legend}
  {grouped(["Challenges wrong answer", "Targets the mistake", "Catches flaw in session", "Challenges right answer"],
           lambda g, w: pooled(w, {"Challenges wrong answer": "challenge_when_flawed", "Targets the mistake": "flaw_targeted",
                                   "Catches flaw in session": "flaw_caught", "Challenges right answer": "challenge_when_clean"}[g]), 1, pct, [0, .25, .5, .75, 1], "Flaw handling")}
</section>

<section class="break">
  <h2>Reaction to worse teaching</h2>
  {legend}
  <h3>Turns per session</h3>
  {grouped(list(TEACH.values()), lambda g, w: pooled(w, "turns", next(k for k, n in TEACH.items() if n == g)), 6, f1, range(0, 7), "Turns per session by teacher style", tickfmt=str)}
  <h3>Sessions marked as learned</h3>
  {grouped(list(TEACH.values()), lambda g, w: pooled(w, "completed", next(k for k, n in TEACH.items() if n == g)), 1, pct, [0, .25, .5, .75, 1], "Completion by teacher style")}
  <h3>Change from the accurate teacher (per lesson)</h3>
  {table(["Learner", "Leaves a step out: turns", "completed", "Vague: turns", "completed", "Error: turns", "completed", "Net flaw detection"],
         [[esc(w), *[f"{contrast[w][f'{c}_minus_good_{m}']:+.2f}" for c in ("omit", "vague", "error") for m in ("turns", "completed")],
           f"{contrast[w]['net_flaw_detection']:+.2f}"] for w in ORDER], "num")}

  <h2>Wording</h2>
  {table(["Learner", "Replies", "Most common opening", "Share starting that way", "Distinct word pairs"],
         [[esc(w), str(phr[w]['replies']), f"“{esc(phr[w]['top'])} …”", pct(phr[w]['rate']), pct(phr[w]['distinct'])] for w in ORDER], "num")}
</section>

<section class="break">
  <h2>Every metric</h2>
  {table(["Metric", *ORDER], metric_rows, "num metrics")}
</section>


</body></html>"""
OUT.write_text(page)
print("wrote", OUT, len(page))

# Dashboard data files, when a second path is given.
if len(sys.argv) > 2:
    D = Path(sys.argv[2]); D.mkdir(exist_ok=True)
    r3 = lambda v: None if v is None else round(v, 3)
    dump = lambda name, rows: (D / name).write_text(json.dumps(rows, indent=1))
    dump("final_scores.json", [{"learner": w, "system": "RAG", "score": round(final[w]["score"], 1), "ci_low": round(final[w]["lo"], 1),
                                "ci_high": round(final[w]["hi"], 1), "p_first": round(final[w]["first"], 2),
                                **{d: round(final[w][d], 1) for d, _ in DIMS}, "rank": main[w]} for w in ranked])
    dump("by_teacher.json", [{"learner": w, "teacher": n, "sessions": sum(1 for s in sessions if who(s) == w and s["condition"] == c),
                              **{m: r3(pooled(w, m, c)) for m in ("turns", "completed", "challenge_when_flawed", "flaw_caught")}}
                             for w in ORDER for c, n in TEACH.items()])
    GROUP = {"Beginner role": "Acting like a beginner"}
    rows = [{"metric": m, "label": label, "group": GROUP.get(g, g), **{w: r3(pooled(w, m)) for w in ORDER}} for g, ms in METRICS for m, label in ms]
    rows.insert(next(i for i, r in enumerate(rows) if r["group"] == "Not scored"),
                {"metric": "completed", "label": "Finishes the lesson", "group": "Reacts to teaching", **{w: r3(pooled(w, "completed")) for w in ORDER}})
    dump("key_metrics.json", rows)
    dump("phrasing.json", [{"learner": w, "replies": phr[w]["replies"], "template_rate": r3(phr[w]["rate"]), "top_opening": phr[w]["top"],
                            "distinct_2": r3(phr[w]["distinct"])} for w in ORDER])
    print("wrote dashboard data to", D)
