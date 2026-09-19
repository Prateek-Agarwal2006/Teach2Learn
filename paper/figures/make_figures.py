"""Build the paper's figures as vector PDFs from the committed Phase 1 results.

    python3 paper/figures/make_figures.py

Each figure is written as an HTML page holding inline SVG (or an HTML table, for the
Devanagari example), then printed to PDF with headless Chrome. Chrome shapes Indic
scripts correctly, which pdflatex and most plotting libraries do not. No third-party
Python packages are needed.

Numbers come from the same files the paper's tables cite: PHASE1_RESULTS.md and
PHASE1_RESULTS_RAG.md (language x subject matrices), PHASE1_SCORECARD.md (fluency cuts,
repeats per subject, depth by arm), and the Sweep B results JSON (the Hindi example).
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RAG_DIR = ROOT / "LbT (RAG Based) tool Implementaion files-20260907T102315Z-1-001" / "LbT (RAG Based) tool Implementaion files"
CHROME = "google-chrome"

# Reference palette (dataviz skill), light mode only: journal figures are printed.
SURFACE = "#ffffff"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#8a8985"
GRID = "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # validated all-pairs, light
BLUE = {100: "#cde2fb", 150: "#b7d3f6", 200: "#9ec5f4", 250: "#86b6ef", 300: "#6da7ec",
        350: "#5598e7", 400: "#3987e5", 450: "#2a78d6", 500: "#256abf", 550: "#1c5cab",
        600: "#184f95", 650: "#104281", 700: "#0d366b"}
DEPTH = {"Deep": BLUE[650], "Intermediate": BLUE[450], "Shallow": BLUE[250]}  # ordinal, validated
FONT = "'Noto Sans', 'Noto Sans Devanagari', 'DejaVu Sans', sans-serif"


# ------------------------------------------------------------------ data

def md_rows(path: Path, header_start: str) -> list[list[str]]:
    lines = path.read_text().splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith(header_start))
    rows = []
    for line in lines[i + 2:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def fluency_matrix(path: Path) -> dict[str, dict]:
    out = {}
    for lang, _script, code, *cells, mean, _status in md_rows(path, "| Language | Script | Code |"):
        name = lang.replace("†", "").strip()
        out[code.strip("`")] = {
            "name": name,
            "cells": [float(c.split("/")[1]) for c in cells],
            "mean": float(mean.strip("*").split("/")[1]),
        }
    return out


def num(text: str) -> float:
    return float(text.replace("−", "-").replace("±", "").replace("+", ""))


# ------------------------------------------------------------------ rendering

def render(name: str, width: int, height: int, body: str) -> None:
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: {width}px {height}px; margin: 0; }}
html, body {{ margin: 0; padding: 0; background: {SURFACE}; }}
body {{ width: {width}px; height: {height}px; overflow: hidden; font-family: {FONT}; color: {INK}; }}
svg {{ display: block; }}
svg text {{ font-family: {FONT}; }}
</style></head><body>{body}</body></html>"""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"{name}.html"
        src.write_text(page, encoding="utf-8")
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={OUT / (name + '.pdf')}", src.as_uri()],
            check=True, capture_output=True,
        )
    print("wrote", OUT / f"{name}.pdf")


def t(x, y, text, size=13, anchor="start", fill=INK, weight=400, extra=""):
    return (f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" '
            f'font-weight="{weight}" {extra}>{html.escape(str(text))}</text>')


# ------------------------------------------------------------------ Figure 1: architecture

def fig_architecture() -> None:
    w, h = 790, 400
    box = lambda x, y, bw, bh, fill, stroke, dash="": (
        f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="6" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="1.5" {dash}/>')
    arrow = lambda x1, y1, x2, y2: (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK_2}" stroke-width="1.6" marker-end="url(#a)"/>')
    s = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">',
         f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{INK_2}"/></marker></defs>']

    # Participant column
    s.append(box(14, 70, 170, 250, "#f6f5f2", GRID))
    s.append(t(99, 94, "Participant", 14, "middle", weight=600))
    s.append(t(99, 112, "reads and writes in one", 11.5, "middle", INK_2))
    s.append(t(99, 126, "of 22 Indian languages", 11.5, "middle", INK_2))
    s.append(box(30, 150, 138, 44, SURFACE, GRID))
    s.append(t(99, 176, "Types an answer", 12, "middle"))
    s.append(box(30, 240, 138, 44, SURFACE, GRID))
    s.append(t(99, 262, "Speaks an answer", 12, "middle"))
    s.append(t(99, 276, "(audio never stored)", 10.5, "middle", INK_2))

    # Speech to text
    s.append(box(206, 236, 120, 52, SURFACE, INK_2))
    s.append(t(266, 257, "Speech-to-text", 12, "middle", weight=600))
    s.append(t(266, 273, "Saaras or Whisper", 10.5, "middle", INK_2))
    s.append(arrow(168, 262, 204, 262))
    s.append(f'<path d="M 326 262 L 346 262 L 346 172" fill="none" stroke="{INK_2}" stroke-width="1.6"/>')
    s.append(arrow(168, 172, 452, 172))
    s.append(t(192, 164, "answer, typed or dictated", 10.5, "start", INK_2))
    s.append(t(266, 304, "text joins the typed path", 10.5, "middle", INK_2))

    # Translation boundary
    s.append(f'<line x1="372" y1="40" x2="372" y2="360" stroke="{INK}" stroke-width="1.5" stroke-dasharray="6 5"/>')
    s.append(t(372, 30, "Translation boundary", 13, "middle", weight=600))
    s.append(t(372, 378, "sarvam-translate:v1, one shared module", 11, "middle", INK_2))
    s.append(t(372, 393, "(passes text through on failure; rejects schema payloads)", 10.5, "middle", INK_2))
    s.append(t(380, 164, "to English", 11, "start", INK_2))
    s.append(arrow(452, 204, 188, 204))
    s.append(t(192, 222, "questions and feedback,", 10.5, "start", INK_2))
    s.append(t(192, 236, "in the participant's language", 10.5, "start", INK_2))

    # English zone
    s.append(box(454, 50, 322, 300, "#eef4fc", BLUE[300]))
    s.append(t(615, 72, "English zone (unchanged)", 14, "middle", weight=600))
    s.append(box(470, 88, 290, 78, SURFACE, BLUE[400]))
    s.append(t(615, 108, "Learner", 12.5, "middle", weight=600))
    s.append(t(615, 126, "Fine-tuned: LoRA adapter per subject", 11, "middle", INK_2))
    s.append(t(615, 142, "RAG: GPT-4o + 4 retrieved textbook passages", 11, "middle", INK_2))
    s.append(t(615, 158, "asks a follow-up question in English", 11, "middle", INK_2))
    s.append(box(470, 178, 140, 70, SURFACE, BLUE[400]))
    s.append(t(540, 200, "Private evaluation", 11.5, "middle", weight=600))
    s.append(t(540, 216, "Bloom level, score;", 10.5, "middle", INK_2))
    s.append(t(540, 230, "decides completion", 10.5, "middle", INK_2))
    s.append(t(540, 244, "(never translated)", 10.5, "middle", INK_2))
    s.append(box(620, 178, 140, 70, SURFACE, BLUE[400]))
    s.append(t(690, 200, "Feedback judge", 11.5, "middle", weight=600))
    s.append(t(690, 216, "reads the English", 10.5, "middle", INK_2))
    s.append(t(690, 230, "answer; writes English", 10.5, "middle", INK_2))
    s.append(t(690, 244, "feedback", 10.5, "middle", INK_2))
    s.append(box(470, 262, 290, 70, SURFACE, BLUE[400]))
    s.append(t(615, 284, "Database and transcripts", 11.5, "middle", weight=600))
    s.append(t(615, 300, "English only; translated again for display", 10.5, "middle", INK_2))
    s.append(t(615, 316, "(the participant's original wording is not kept)", 10.5, "middle", INK_2))
    s.append("</svg>")
    render("fig1-boundary", w, h, "".join(s))


# ------------------------------------------------------------------ Figure 2: Hindi example

def sweep_turn(path: Path, lesson: str, code: str, turn: int) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for run in data["runs"]:
        if run.get("lesson_id") != lesson:
            continue
        for record in run["sweep"]:
            if record.get("code") == code:
                return record["turns"][turn - 1]
    raise LookupError(f"{lesson} {code} turn {turn} not in {path}")


def fig_example() -> None:
    lesson = "os/threads-scheduling/cpu-scheduling"
    ft = sweep_turn(ROOT / "teach2learn-portal" / "sweepB-os.json", lesson, "hi", 1)
    rag = sweep_turn(RAG_DIR / "sweepB-rag.json", lesson, "hi", 1)
    assert ft["teacher_local"] == rag["teacher_local"], "the example needs identical Hindi input"
    rows = [
        ("Teacher's sentence (lesson script)", ft["teacher_en"], "en"),
        ("What the participant types (Hindi)", ft["teacher_local"], "hi"),
        ("What both learners receive (inbound)", ft["teacher_back_en"], "en"),
        ("Fine-tuned learner asks (Granite 3.3 8B)", ft["question_en"], "en"),
        ("Participant reads", ft["question_local"], "hi"),
        ("RAG learner asks (GPT-4o)", rag["question_en"], "en"),
        ("Participant reads", rag["question_local"], "hi"),
    ]
    zone = {0: "source", 1: "participant", 2: "english", 3: "english", 4: "participant", 5: "english", 6: "participant"}
    shade = {"participant": "#f6f5f2", "english": "#eef4fc", "source": SURFACE}
    trs = []
    for i, (label, text, lang) in enumerate(rows):
        top = "border-top: 1.5px solid #52514e;" if i in (3, 5) else ""
        trs.append(
            f'<tr style="background:{shade[zone[i]]};{top}"><th>{html.escape(label)}</th>'
            f'<td lang="{lang}">{html.escape(text)}</td></tr>')
    body = f"""<div style="padding:10px 12px;">
<table style="border-collapse:collapse;width:100%;font-size:13px;line-height:1.45;">
<style>th{{text-align:left;vertical-align:top;font-weight:600;width:190px;padding:7px 10px;color:{INK_2};font-size:12px}}
td{{padding:7px 10px;vertical-align:top}} td[lang=hi]{{font-family:'Noto Sans Devanagari',sans-serif;font-size:14px}}
tr{{border-bottom:1px solid {GRID}}}</style>
{''.join(trs)}
</table>
<div style="font-size:11px;color:{INK_2};margin-top:6px;">
Shaded blue: text inside the English zone. Shaded grey: text the participant sees.
Lesson <span style="font-family:monospace">{lesson}</span>, turn 1, Sweep B. Both systems received the same Hindi translation.</div>
</div>"""
    render("fig2-example-hindi", 760, 440, body)


# ------------------------------------------------------------------ Figure 3: heatmap

def ramp(value: float) -> tuple[str, str]:
    """Fluency 1-5 onto the sequential blue ramp; returns (fill, text ink)."""
    lo, hi = 2.5, 5.0
    steps = sorted(BLUE)
    k = round((min(max(value, lo), hi) - lo) / (hi - lo) * (len(steps) - 1))
    step = steps[k]
    return BLUE[step], (INK if step <= 300 else "#ffffff")


def fig_heatmap() -> None:
    ft = fluency_matrix(ROOT / "PHASE1_RESULTS.md")
    rag = fluency_matrix(ROOT / "PHASE1_RESULTS_RAG.md")
    order = sorted(ft, key=lambda c: -(ft[c]["mean"] + rag[c]["mean"]) / 2)
    subjects = ["cp", "dsa", "oop_java", "os"]
    cw, ch, gap = 50, 19, 2
    left, top = 104, 58
    panel_w = 5 * (cw + gap)  # four subjects + mean
    panel_gap = 38
    w = left + 2 * panel_w + panel_gap + 12
    h = top + len(order) * (ch + gap) + 64
    s = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
    for p, (title, data) in enumerate((("Fine-tuned learners", ft), ("RAG learner (GPT-4o)", rag))):
        x0 = left + p * (panel_w + panel_gap)
        s.append(t(x0, 20, title, 13.5, weight=600))
        for j, label in enumerate(subjects + ["mean"]):
            s.append(t(x0 + j * (cw + gap) + cw / 2, top - 8, label, 11, "middle", INK_2,
                       weight=600 if label == "mean" else 400))
        for i, code in enumerate(order):
            y = top + i * (ch + gap)
            values = data[code]["cells"] + [data[code]["mean"]]
            for j, v in enumerate(values):
                fill, ink = ramp(v)
                x = x0 + j * (cw + gap) + (4 if j == 4 else 0)
                s.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="2" fill="{fill}"/>')
                s.append(t(x + cw / 2, y + ch / 2 + 4, f"{v:.1f}", 10.5, "middle", ink))
    for i, code in enumerate(order):
        s.append(t(left - 8, top + i * (ch + gap) + ch / 2 + 4, ft[code]["name"], 11.5, "end"))
    # Tier boundary at fluency 4.0 is not drawn: tiers also depend on fidelity.
    ly = h - 30
    s.append(t(left, ly - 8, "Judged fluency, 1-5 (darker is more fluent)", 11, "start", INK_2))
    for k, step in enumerate(sorted(BLUE)):
        s.append(f'<rect x="{left + k * 26}" y="{ly}" width="24" height="10" rx="2" fill="{BLUE[step]}"/>')
    s.append(t(left, ly + 24, "2.5 or less", 10.5, "start", INK_2))
    s.append(t(left + 13 * 26 - 2, ly + 24, "5.0", 10.5, "end", INK_2))
    s.append("</svg>")
    render("fig3-heatmap-fluency", w, h, "".join(s))


# ------------------------------------------------------------------ Figure 4: forest plot

def fig_forest() -> None:
    rows = md_rows(ROOT / "PHASE1_SCORECARD.md", "| Cut | Paired turns |")
    data = []
    for cut, n, _ft, _rag, delta, ci in rows:
        lo, hi = (num(v) for v in ci.strip("[]").split(","))
        data.append((cut, int(n.replace(",", "")), num(delta), lo, hi))
    w, row_h = 700, 30
    left, right_col, top = 230, 150, 34
    plot_w = w - left - right_col
    h = top + len(data) * row_h + 58
    xmin, xmax = -0.2, 0.4
    X = lambda v: left + (v - xmin) / (xmax - xmin) * plot_w
    s = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
    s.append(t(left - 12, 20, "Comparison", 11.5, "end", INK_2, 600))
    s.append(t(w - right_col + 12, 20, "RAG minus FT [95% CI]", 11.5, "start", INK_2, 600))
    for tick in (-0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4):
        x = X(tick)
        s.append(f'<line x1="{x}" y1="{top - 6}" x2="{x}" y2="{top + len(data) * row_h}" '
                 f'stroke="{INK_2 if tick == 0 else GRID}" stroke-width="{1.4 if tick == 0 else 1}"/>')
        s.append(t(x, top + len(data) * row_h + 18, f"{tick:+.1f}" if tick else "0", 11, "middle", INK_2))
    s.append(t(left + plot_w / 2, top + len(data) * row_h + 40,
               "Difference in judged fluency, 1-5 scale (positive favours RAG)", 11.5, "middle", INK_2))
    for i, (cut, n, delta, lo, hi) in enumerate(data):
        y = top + i * row_h + row_h / 2
        if i == 4:
            s.append(f'<line x1="12" y1="{y - row_h / 2}" x2="{w - 12}" y2="{y - row_h / 2}" stroke="{GRID}"/>')
        s.append(t(left - 12, y + 4, f"{cut} (n={n})", 11.5, "end"))
        s.append(f'<line x1="{X(lo)}" y1="{y}" x2="{X(hi)}" y2="{y}" stroke="{SERIES[0]}" stroke-width="2"/>')
        s.append(f'<circle cx="{X(delta)}" cy="{y}" r="5" fill="{SERIES[0]}" stroke="{SURFACE}" stroke-width="2"/>')
        s.append(t(w - right_col + 12, y + 4, f"{delta:+.2f} [{lo:+.2f}, {hi:+.2f}]", 11.5))
    s.append("</svg>")
    render("fig4-fluency-forest", w, h, "".join(s))


# ------------------------------------------------------------------ Figure 5: repeats per subject

def fig_repeats() -> None:
    rows = md_rows(ROOT / "PHASE1_SCORECARD.md", "| Subject | Fine-tuned | RAG | RAG + teacher history |")
    labels = {"Computer programming": "Computer\nProgramming", "Data structures": "Data Structures\nand Algorithms",
              "OOP with Java": "OOP with\nJava", "Operating systems": "Operating\nSystems"}
    arms = ["Fine-tuned", "RAG", "RAG + teacher history"]
    data = [(labels[r[0]], [int(v) for v in r[1:]]) for r in rows]
    w, h = 640, 330
    left, top, bottom = 54, 58, 64
    plot_h = h - top - bottom
    group_w = (w - left - 16) / len(data)
    bw, bgap = 30, 2
    Y = lambda v: top + plot_h - v / 18 * plot_h
    s = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
    lx = left
    for k, arm in enumerate(arms):  # legend, one row above the plot
        s.append(f'<rect x="{lx}" y="14" width="12" height="12" rx="2" fill="{SERIES[k]}"/>')
        s.append(t(lx + 18, 24, arm, 12))
        lx += 18 + len(arm) * 7.2 + 24
    for tick in (0, 6, 12, 18):
        s.append(f'<line x1="{left}" y1="{Y(tick)}" x2="{w - 16}" y2="{Y(tick)}" stroke="{GRID if tick else INK_2}"/>')
        s.append(t(left - 8, Y(tick) + 4, tick, 11, "end", INK_2))
    s.append(t(16, top + plot_h / 2, "Conversations with a repeated question (of 18)", 11.5, "middle", INK_2,
               extra=f'transform="rotate(-90 16 {top + plot_h / 2})"'))
    for g, (label, values) in enumerate(data):
        gx = left + g * group_w + (group_w - (3 * bw + 2 * bgap)) / 2
        for k, v in enumerate(values):
            x = gx + k * (bw + bgap)
            if v:
                y = Y(v)
                r = 4
                s.append(f'<path d="M{x},{Y(0)} L{x},{y + r} Q{x},{y} {x + r},{y} L{x + bw - r},{y} '
                         f'Q{x + bw},{y} {x + bw},{y + r} L{x + bw},{Y(0)} Z" fill="{SERIES[k]}"/>')
            s.append(t(x + bw / 2, Y(v) - 6, v, 11.5, "middle", INK))
        for n, part in enumerate(label.split("\n")):
            s.append(t(left + g * group_w + group_w / 2, Y(0) + 20 + n * 14, part, 11.5, "middle"))
    s.append("</svg>")
    render("fig5-repeats", w, h, "".join(s))


# ------------------------------------------------------------------ Figure 6: depth

def fig_depth() -> None:
    rows = md_rows(ROOT / "PHASE1_SCORECARD.md", "| Arm | Questions | Deep |")
    names = {"Fine-tuned": "Fine-tuned", "RAG": "RAG", "RAG + teacher history (experiment)": "RAG + teacher history"}
    data = [(names[r[0]], int(r[1]), [int(v.strip("%")) for v in r[2:5]]) for r in rows]
    w, h = 680, 226
    left, top, bh, gap = 200, 54, 30, 22
    plot_w = w - left - 24
    s = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
    lx = left
    for level in ("Deep", "Intermediate", "Shallow"):
        s.append(f'<rect x="{lx}" y="14" width="12" height="12" rx="2" fill="{DEPTH[level]}"/>')
        s.append(t(lx + 18, 24, level, 12))
        lx += 18 + len(level) * 7.2 + 24
    for i, (arm, n, shares) in enumerate(data):
        y = top + i * (bh + gap)
        s.append(t(left - 10, y + bh / 2 + 4, f"{arm} (n={n})", 12, "end"))
        x = left
        for level, share in zip(("Deep", "Intermediate", "Shallow"), shares):
            seg = share / 100 * plot_w
            s.append(f'<rect x="{x}" y="{y}" width="{max(seg - 2, 0)}" height="{bh}" rx="2" fill="{DEPTH[level]}"/>')
            if seg >= 40:
                ink = "#ffffff" if level != "Shallow" else INK
                s.append(t(x + seg / 2 - 1, y + bh / 2 + 4, f"{share}%", 11.5, "middle", ink))
            x += seg
        small = [f"{lvl.lower()} {sh}%" for lvl, sh in zip(("Deep", "Intermediate", "Shallow"), shares) if sh / 100 * plot_w < 40]
        if small:
            s.append(t(w - 20, y - 4, ", ".join(small), 10.5, "end", INK_2))
    s.append(t(left, h - 12, "Share of questions, by level, from a judge blind to system and lesson", 11, "start", INK_2))
    s.append("</svg>")
    render("fig6-depth", w, h, "".join(s))


if __name__ == "__main__":
    fig_architecture()
    fig_example()
    fig_heatmap()
    fig_forest()
    fig_repeats()
    fig_depth()
