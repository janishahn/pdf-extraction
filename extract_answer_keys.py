"""
Extract answer keys from the central answer-key PDF into structured JSON files.

This script uses PyMuPDF (fitz) to deterministically read table-like regions
for each grade group (Klassenstufen) and map Aufgabe labels (e.g., A1..C10 or
numeric 1..30) to their corresponding Antwort letters (A-E). It supports both
modern ABC-layout years and older purely numeric layouts.

Outputs one JSON per detected year under an output directory (default:
answer_keys/), ready to be joined later with extracted questions.

Usage:
    python extract_answer_keys.py --pdf path/to/answers.pdf --out answer_keys

Optional flags:
    --overwrite    Overwrite existing year JSONs
    --debug        Emit additional logs and page-level diagnostics
    --strict       Fail on mismatched counts in a row-pair extraction

The extractor prioritizes fitz's table detection (page.find_tables()), and
falls back to a line-based pairing of "Aufgabe"/"Antwort" if table detection
is unavailable or fails to detect specific tables.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence, TypeAlias

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF is required. Install with: pip install PyMuPDF", file=sys.stderr)
    raise

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    raise

# ------------------------------ Regexes ------------------------------------

YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
# Be permissive with whitespace – some PDFs split tokens into multiple spans
# and our text join may still collapse irregular spacing.
GROUP_RE = re.compile(r"Klassenstufen\s*(\d+)\s*(?:und|bis)\s*(\d+)")

# Shared word tuple type used across extraction helpers
Word: TypeAlias = tuple[float, float, float, float, str]


# ----------------------------- Data Models ---------------------------------

@dataclass
class Heading:
    group: str  # normalized like "3-4"
    bbox: fitz.Rect
    y_center: float


@dataclass
class RowPair:
    labels: list[str]
    answers: list[str]
    bbox: fitz.Rect


@dataclass
class YearAccumulator:
    year: int
    source_pdf: str
    # group -> list of (labels, answers, bbox)
    per_group: dict[str, list[RowPair]]
    warnings: list[str]

    def __init__(self, year: int, source_pdf: str) -> None:
        self.year = year
        self.source_pdf = source_pdf
        self.per_group = {}
        self.warnings = []

    def add_rowpair(self, group: str, pair: RowPair) -> None:
        self.per_group.setdefault(group, []).append(pair)

    def to_json_obj(self) -> dict[str, Any]:
        grade_groups: dict[str, Any] = {}

        for group, pairs in self.per_group.items():
            # Sort pairs by their vertical position (page flow): top y then left x
            pairs_sorted = sorted(pairs, key=lambda p: (p.bbox.y0, p.bbox.x0))
            order: list[str] = []
            answers_by_label: dict[str, str] = {}

            missing: list[str] = []
            for p in pairs_sorted:
                # Normalize and fold in, keep label in order even if answer missing
                for lab, ans in zip(p.labels, p.answers):
                    lab_n = normalize_label(lab)
                    if not lab_n or not is_valid_label(lab_n):
                        continue
                    order.append(lab_n)
                    ans_n = normalize_answer(ans)
                    if ans_n:
                        # Last write wins; duplicates are rare but possible if PDF repeats
                        answers_by_label[lab_n] = ans_n
                    else:
                        missing.append(lab_n)

            # De-duplicate while retaining the first-seen order
            seen: set[str] = set()
            order_unique: list[str] = []
            for lab in order:
                if lab in seen:
                    continue
                seen.add(lab)
                order_unique.append(lab)

            scheme = guess_scheme(order_unique)

            gg: dict[str, Any] = {
                "scheme": scheme,
                "answers_by_label": answers_by_label,
                "order": order_unique,
                "counts": len(order_unique),
            }
            if missing:
                gg["missing_answers"] = sorted(list(set(missing)), key=lambda x: (x[0].isalpha(), x))
            grade_groups[group] = gg

        return {
            "year": self.year,
            "source_pdf": self.source_pdf,
            "extracted_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "grade_groups": grade_groups,
            **({"warnings": self.warnings} if self.warnings else {}),
        }


# ------------------------------ Utilities ----------------------------------

def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def clean_text(s: str) -> str:
    return (s or "").strip()


def normalize_label(s: str) -> str:
    s = clean_text(s)
    # Drop trailing/leading punctuation like '.' or ':'
    s = s.strip(" .:;,-")
    # Accept labels like A1, B10, C7 or numbers 1..30
    return s


def normalize_answer(s: str) -> str:
    s = clean_text(s).upper()
    if not s:
        return ""
    # Keep only a single letter A-E if present
    m = re.match(r"^[A-E]", s)
    return m.group(0) if m else ""


def guess_scheme(labels: Sequence[str]) -> str:
    for lab in labels:
        if lab and lab[0].isalpha():
            return "abc"
    return "numeric"


def is_valid_label(s: str) -> bool:
    s = clean_text(s)
    return bool(
        re.match(r"^[0-9]{1,2}$", s)
        or re.match(r"^[A-C][0-9]{1,2}$", s)
    )


def detect_year(page: fitz.Page, prior_year: int | None) -> int | None:
    text = page.get_text("text") or ""
    # Limit search to first quarter of page height to avoid footer numbers
    try:
        blocks = page.get_text("blocks") or []
        h = float(page.rect.height)
        cap_y = page.rect.y0 + 0.35 * h
        head_texts = [b[4] for b in blocks if b[1] < cap_y]
        text = "\n".join(head_texts)
    except Exception:
        pass

    m = YEAR_RE.search(text)
    if not m:
        return prior_year
    try:
        yy = int(m.group(0))
        if 1900 <= yy <= 2099:
            return yy
    except Exception:
        return prior_year
    return prior_year


def find_grade_headings(page: fitz.Page) -> list[Heading]:
    out: list[Heading] = []
    try:
        d = page.get_text("dict")
    except Exception:
        return out

    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            # IMPORTANT: preserve spacing between spans. Joining without spaces
            # produces strings like "Klassenstufen3und4" which breaks the
            # GROUP_RE (expects spaces). Using a space-join is robust across
            # different PDF span segmentation.
            text = " ".join(s.get("text", "") for s in spans)
            text_n = clean_text(text)
            if "Klassenstufen" not in text_n:
                continue
            m = GROUP_RE.search(text_n)
            if not m:
                continue
            g1, g2 = m.group(1), m.group(2)
            group = f"{int(g1)}-{int(g2)}"
            x0, y0, x1, y1 = line.get("bbox", [0, 0, 0, 0])
            rect = fitz.Rect(x0, y0, x1, y1)
            out.append(Heading(group=group, bbox=rect, y_center=(y0 + y1) / 2))
    # Sort top-to-bottom
    out.sort(key=lambda h: h.y_center)
    return out


def associate_group(headings: list[Heading], bbox: fitz.Rect) -> str | None:
    """Choose the most plausible grade heading for a table row bbox.

    Preference order:
    - Heading located above the bbox (allow tiny overlap tolerance)
    - Minimal vertical distance to the bbox
    - Among ties, prefer horizontal proximity/overlap
    """
    candidates = [h for h in headings if h.bbox.y1 <= bbox.y0 + 2]
    if not candidates:
        return headings[-1].group if headings else None

    def hdist(h: Heading) -> float:
        # Horizontal distance between heading box and row box (0 if overlapping)
        if h.bbox.x1 < bbox.x0:
            return bbox.x0 - h.bbox.x1
        if bbox.x1 < h.bbox.x0:
            return h.bbox.x0 - bbox.x1
        return 0.0

    best = min(
        candidates,
        key=lambda h: (
            1 if hdist(h) > 0 else 0,  # prefer headings that horizontally overlap
            hdist(h),
            abs(bbox.y0 - h.bbox.y1),
        ),
    )
    return best.group


# -------------------------- Table Extraction (fitz) -------------------------

def extract_tables_via_fitz(page: fitz.Page) -> list[RowPair]:
    rowpairs: list[RowPair] = []
    try:
        tf = page.find_tables()
    except Exception:
        return rowpairs

    if not tf or not getattr(tf, "tables", None):
        return rowpairs

    for tab in tf.tables:  # type: ignore[attr-defined]
        try:
            rows = tab.extract()
        except Exception:
            continue
        if not rows or len(rows) < 2:
            continue

        # We look for pairs of consecutive rows where first cell is "Aufgabe"
        # and the next row starts with "Antwort".
        for i in range(len(rows) - 1):
            r0 = [clean_text(x) for x in rows[i]]
            r1 = [clean_text(x) for x in rows[i + 1]]
            if not r0 or not r1:
                continue
            if (r0[0].lower().startswith("aufgabe") and r1[0].lower().startswith("antwort")):
                labels = [x for x in r0[1:] if x]
                answers = [x for x in r1[1:] if x]
                if not labels or not answers:
                    continue
                # Align lengths safely (tables may have ragged trailing cells)
                # Align answers to labels length; pad with empty strings if needed
                if len(answers) < len(labels):
                    answers = answers + [""] * (len(labels) - len(answers))
                elif len(answers) > len(labels):
                    answers = answers[: len(labels)]
                rowpairs.append(RowPair(labels=labels, answers=answers, bbox=fitz.Rect(*tab.bbox)))
    return rowpairs


# ------------------------- Fallback Extraction (words) ----------------------

def extract_tables_via_words(page: fitz.Page) -> list[RowPair]:
    """Fallback strategy using word lines to pair Aufgabe/Antwort rows.

    We group by (block, line) and look for consecutive lines where the first
    token is "Aufgabe" followed by numbers or labels, and the next line starts
    with "Antwort" followed by answer letters.
    """
    words = page.get_text("words") or []
    # word entries: x0, y0, x1, y1, text, block_no, line_no, word_no
    lines: dict[tuple[int, int], list[tuple[float, float, float, float, str]]] = {}
    for x0, y0, x1, y1, text, bno, lno, wno in words:
        key = (int(bno), int(lno))
        lines.setdefault(key, []).append((x0, y0, x1, y1, text))

    # Sort lines in reading order
    ordered_keys = sorted(lines.keys(), key=lambda k: (k[0], min(t[1] for t in lines[k])))

    # Build simple line objects
    line_objs: list[tuple[str, fitz.Rect, list[str]]] = []  # (text, bbox, tokens)
    for key in ordered_keys:
        ws = sorted(lines[key], key=lambda t: t[0])
        tokens = [w[4] for w in ws]
        text = " ".join(tokens)
        xs0 = min(w[0] for w in ws)
        ys0 = min(w[1] for w in ws)
        xs1 = max(w[2] for w in ws)
        ys1 = max(w[3] for w in ws)
        line_objs.append((text, fitz.Rect(xs0, ys0, xs1, ys1), tokens))

    # Now pair Aufgabe/Antwort lines
    rowpairs: list[RowPair] = []
    i = 0
    while i < len(line_objs) - 1:
        text0, bb0, toks0 = line_objs[i]
        text1, bb1, toks1 = line_objs[i + 1]
        if not toks0 or not toks1:
            i += 1
            continue
        if clean_text(toks0[0]).lower().startswith("aufgabe") and clean_text(toks1[0]).lower().startswith("antwort"):
            labels = [t for t in toks0[1:] if clean_text(t)]
            answers = [t for t in toks1[1:] if clean_text(t)]
            # Guard: sometimes labels spill over multiple spaces; limit to letters/numbers
            labels = [normalize_label(t) for t in labels]
            answers = [normalize_answer(t) for t in answers]
            labels = [t for t in labels if t]
            answers = [t for t in answers if t]
            if labels:
                if len(answers) < len(labels):
                    answers = answers + [""] * (len(labels) - len(answers))
                elif len(answers) > len(labels):
                    answers = answers[: len(labels)]
                rowpairs.append(RowPair(labels=labels, answers=answers, bbox=bb0 | bb1))
            i += 2
            continue
        i += 1

    return rowpairs

"""
Debug overlay utilities are defined above process_pdf so they are available
when debug overlays are requested from within process_pdf during script
execution (which happens before the end of file is executed).
"""

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: tuple[int, int, int] = (255, 255, 255)) -> None:
    x, y = xy
    pad = 4
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None  # type: ignore
    text_w, text_h = draw.textbbox((x, y), text, font=font)[2:]
    rect = [x - pad, y - pad, x + text_w + pad, y + text_h + pad]
    draw.rectangle(rect, fill=(0, 0, 0, 180), outline=(255, 255, 255))
    draw.text((x, y), text, fill=fill, font=font)


def save_page_debug_overlay(
    *,
    page: fitz.Page,
    page_index: int,
    year: int,
    out_dir: str,
    headings: list[Heading],
    associations: list[tuple[RowPair, str | None]],
    dpi: int = 144,
) -> None:
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)

    # Convert to PIL
    img_data = pix.tobytes("ppm")
    img = Image.open(__import__("io").BytesIO(img_data)).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    # Draw headings (blue)
    for h in headings:
        rect = [int(h.bbox.x0 * zoom), int(h.bbox.y0 * zoom), int(h.bbox.x1 * zoom), int(h.bbox.y1 * zoom)]
        draw.rectangle(rect, outline=(30, 144, 255, 255), width=3)
        _draw_label(draw, (rect[0] + 2, rect[1] + 2), f"{h.group}")

    # Draw rowpairs (green)
    for rp, grp in associations:
        rect = [int(rp.bbox.x0 * zoom), int(rp.bbox.y0 * zoom), int(rp.bbox.x1 * zoom), int(rp.bbox.y1 * zoom)]
        draw.rectangle(rect, outline=(50, 205, 50, 255), width=3)
        tag = f"{grp or 'UNASSIGNED'} | {len(rp.labels)} labels / {len(rp.answers)} answers"
        _draw_label(draw, (rect[0] + 2, rect[1] + 2), tag)

    debug_dir = Path(out_dir) / "debug"
    _ensure_dir(debug_dir)
    png_path = debug_dir / f"{year}_page_{page_index+1}.png"
    img.save(png_path)

    # Sidecar JSON with raw details for the page
    sidebar = {
        "year": year,
        "page": page_index + 1,
        "headings": [
            {"group": h.group, "bbox": [round(h.bbox.x0, 2), round(h.bbox.y0, 2), round(h.bbox.x1, 2), round(h.bbox.y1, 2)]}
            for h in headings
        ],
        "rowpairs": [
            {
                "group": grp,
                "bbox": [round(rp.bbox.x0, 2), round(rp.bbox.y0, 2), round(rp.bbox.x1, 2), round(rp.bbox.y1, 2)],
                "labels_count": len(rp.labels),
                "answers_count": len(rp.answers),
                "labels_preview": rp.labels[:5],
                "answers_preview": rp.answers[:5],
            }
            for rp, grp in associations
        ],
    }
    json_path = png_path.with_suffix(".json")
    atomic_write_json(json_path, sidebar)


# ----------------------- Region-guided Extraction ---------------------------

def _column_split(page: fitz.Page, headings: list[Heading]) -> float:
    # If we have headings on both sides, split between min and max center x
    if headings:
        xs = [0.5 * (h.bbox.x0 + h.bbox.x1) for h in headings]
        mn, mx = min(xs), max(xs)
        if mx - mn > 50:  # clear two-column layout
            return (mn + mx) / 2.0
    # Fallback: geometric middle of the page
    return (page.rect.x0 + page.rect.x1) / 2.0


def compute_group_regions(page: fitz.Page, headings: list[Heading]) -> dict[str, fitz.Rect]:
    """Compute a conservative region for each grade group based on headings.

    - Split the page into two columns at a vertical divider.
    - For each column, frame a region from each heading down to the next heading
      within the same column (or the page bottom), and horizontally from the
      column edge to the divider (left column) or divider to page edge (right).
    """
    if not headings:
        return {}

    split_x = _column_split(page, headings)
    left: list[Heading] = []
    right: list[Heading] = []
    for h in headings:
        cx = 0.5 * (h.bbox.x0 + h.bbox.x1)
        (left if cx < split_x else right).append(h)

    left.sort(key=lambda h: h.bbox.y0)
    right.sort(key=lambda h: h.bbox.y0)

    regions: dict[str, fitz.Rect] = {}
    margin = 6.0
    pad_x = 60.0  # allow table cells that slightly cross the visual column split
    for col, hs in (("left", left), ("right", right)):
        for i, h in enumerate(hs):
            top = h.bbox.y1 + margin
            bottom = (hs[i + 1].bbox.y0 - margin) if i + 1 < len(hs) else (page.rect.y1 - margin)
            if col == "left":
                x0, x1 = page.rect.x0 + margin, split_x - margin + pad_x
            else:
                x0, x1 = split_x + margin - pad_x, page.rect.x1 - margin
            # Build region
            regions[h.group] = fitz.Rect(max(x0, h.bbox.x0 - 10), top, x1, bottom)
    return regions


def extract_group_rowpairs(page: fitz.Page, region: fitz.Rect) -> list[RowPair]:
    """Extract Aufgabe/Antwort rowpairs constrained to a region.

    Steps: find anchors, collect tokens along the row, build label rows and
    answer rows, then pair each Aufgabe to the nearest Antwort below. We keep
    positional blanks in answers so alignment by index is correct, and we drop
    spurious Aufgabe anchors that yield fewer than 5 labels (e.g., footnotes).
    """
    words = page.get_text("words") or []
    wlist: list[Word] = [
        (float(x0), float(y0), float(x1), float(y1), str(t))
        for x0, y0, x1, y1, t, *_ in words
        if region.contains(fitz.Point((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    ]

    def y_center(w: Word) -> float:
        return (w[1] + w[3]) / 2.0

    anchors_auf = [w for w in wlist if clean_text(w[4]).lower().startswith("aufgabe")]
    anchors_ant = [w for w in wlist if clean_text(w[4]).lower().startswith("antwort")]
    anchors_auf.sort(key=lambda w: (w[1], w[0]))
    anchors_ant.sort(key=lambda w: (w[1], w[0]))

    if not anchors_auf or not anchors_ant:
        return []

    y_tol = 5.0

    def collect_row_tokens(anchor: Word) -> tuple[list[str], fitz.Rect]:
        ax1 = anchor[2]
        ay = y_center(anchor)
        toks: list[Word] = [w for w in wlist if (w is not anchor and abs(y_center(w) - ay) <= y_tol and w[0] >= ax1 - 4.0)]
        toks.sort(key=lambda w: w[0])
        if not toks:
            return [], fitz.Rect(ax1, anchor[1], ax1, anchor[3])
        xs = [w[0] for w in toks]
        ys0 = [w[1] for w in toks]
        xs1 = [w[2] for w in toks]
        ys1 = [w[3] for w in toks]
        rect = fitz.Rect(min(xs), min(ys0), max(xs1), max(ys1))
        return [clean_text(w[4]) for w in toks], rect

    # Build label and answer rows
    auf_rows: list[tuple[Word, list[str], fitz.Rect]] = []
    ant_rows: list[tuple[Word, list[str], fitz.Rect]] = []

    for a in anchors_auf:
        toks, bb = collect_row_tokens(a)
        toks = [normalize_label(t) for t in toks if t and t.lower() != "aufgabe"]
        toks = [t for t in toks if re.match(r"^[A-Z]?[0-9]{1,2}$", t)]
        if toks and len(toks) >= 5:
            auf_rows.append((a, toks, bb))

    for a in anchors_ant:
        toks, bb = collect_row_tokens(a)
        raw = [t for t in toks if t and t.lower() != "antwort"]
        toks = [normalize_answer(t) for t in raw]
        if raw:
            ant_rows.append((a, toks, bb))

    if not auf_rows or not ant_rows:
        return []

    # Pair Aufgabe rows to the nearest Antwort rows
    ant_used = [False] * len(anchors_ant)
    rowpairs: list[RowPair] = []
    for a_anchor, labels, a_bb in auf_rows:
        ay = y_center(a_anchor)
        best_j = -1
        best_d = 1e9
        for j, b in enumerate(anchors_ant):
            if ant_used[j]:
                continue
            dy = y_center(b) - ay
            if abs(dy) < best_d and abs(dy) <= 24.0:
                best_d = abs(dy)
                best_j = j
        if best_j < 0:
            continue
        ant_used[best_j] = True
        answers_raw, bb_b = collect_row_tokens(anchors_ant[best_j])
        ans = [normalize_answer(t) for t in answers_raw]
        if len(ans) < len(labels):
            ans = ans + [""] * (len(labels) - len(ans))
        elif len(ans) > len(labels):
            ans = ans[: len(labels)]
        rowpairs.append(RowPair(labels=labels, answers=ans, bbox=(a_bb | bb_b)))

    return rowpairs

def extract_tables_via_bands(page: fitz.Page) -> list[RowPair]:
    """Robust fallback using y-bands anchored at the tokens 'Aufgabe'/'Antwort'.

    Many Känguru PDFs split each cell into its own text block, so grouping by
    (block_no, line_no) fails to collect an entire row. Instead, we:
      1) Find every word 'Aufgabe' and 'Antwort'.
      2) For each such anchor, collect all words on nearly the same y (within
         a small tolerance) to the right of the anchor.
      3) Pair each Aufgabe-band to the nearest Antwort-band below it.
    """
    words = page.get_text("words") or []
    wlist: list[Word] = [(float(x0), float(y0), float(x1), float(y1), str(t)) for x0, y0, x1, y1, t, *_ in words]

    def y_center(w: Word) -> float:
        return (w[1] + w[3]) / 2.0

    aufgaben: list[Word] = [w for w in wlist if clean_text(w[4]).lower().startswith("aufgabe")]
    antworten: list[Word] = [w for w in wlist if clean_text(w[4]).lower().startswith("antwort")]

    if not aufgaben or not antworten:
        return []

    # Tolerances: rows are typically ~10-20pt tall in these PDFs
    y_tol = 5.0
    x_gap = 4.0

    # Collect row contents to the right of each anchor within a tight y band
    def right_bound_for(anchor: Word) -> float | None:
        ax1 = anchor[2]
        ay = y_center(anchor)
        # Find the next 'Aufgabe' (or 'Antwort') anchor to the right on nearly the same y
        candidates = [w for w in aufgaben + antworten if w is not anchor and abs(y_center(w) - ay) <= 20.0 and w[0] > ax1]
        if not candidates:
            return None
        nxt = min(candidates, key=lambda w: w[0])
        return (ax1 + nxt[0]) / 2.0

    def collect_row_tokens(anchor: Word) -> tuple[list[str], fitz.Rect]:
        ax1 = anchor[2]
        ay = y_center(anchor)
        rb = right_bound_for(anchor)
        mid_x = (float(page.rect.x0) + float(page.rect.x1)) / 2.0
        # Column-aware bound: keep tokens on the same side of the page as the anchor
        if anchor[0] < mid_x:
            bound = min(rb, mid_x) if rb is not None else mid_x
            def horiz_ok(x: float) -> bool:
                return x < bound
        else:
            bound = max(rb, mid_x) if rb is not None else mid_x
            def horiz_ok(x: float) -> bool:
                return x > bound
        # Gather candidate tokens solely by y and being to the right of the label
        candidates: list[tuple[float, Word]] = []
        for w in wlist:
            if w is anchor:
                continue
            if abs(y_center(w) - ay) <= y_tol and w[0] >= ax1 - x_gap:
                candidates.append((w[0], w))
        candidates.sort(key=lambda t: t[0])

        # Split into x-clusters to separate left vs right table bands
        clusters: list[list[Word]] = []
        cluster_gap = 40.0
        for _, w in candidates:
            if not clusters:
                clusters.append([w])
                continue
            prev = clusters[-1][-1]
            if w[0] - prev[0] > cluster_gap:
                clusters.append([w])
            else:
                clusters[-1].append(w)

        if not clusters:
            return [], fitz.Rect(ax1, anchor[1], ax1, anchor[3])

        # Choose the cluster whose mean x is closest to the anchor's right edge
        def mean_x(ws: list[Word]) -> float:
            return sum(w[0] for w in ws) / max(1, len(ws))

        chosen = min(clusters, key=lambda ws: abs(mean_x(ws) - ax1))

        # Apply the earlier column-aware bound as a final safety net
        chosen = [w for w in chosen if horiz_ok(w[0])]
        if not chosen:
            return [], fitz.Rect(ax1, anchor[1], ax1, anchor[3])

        min_x0 = min(w[0] for w in chosen)
        min_y0 = min(w[1] for w in chosen)
        max_x1 = max(w[2] for w in chosen)
        max_y1 = max(w[3] for w in chosen)

        tokens = [clean_text(w[4]) for w in chosen]
        return tokens, fitz.Rect(min_x0, min_y0, max_x1, max_y1)

    auf_rows: list[tuple[Word, list[str], fitz.Rect]] = []
    ant_rows: list[tuple[Word, list[str], fitz.Rect]] = []

    for a in aufgaben:
        toks, bb = collect_row_tokens(a)
        # Keep only plausible labels (A1..C10 or digits)
        toks = [normalize_label(t) for t in toks if t and t.lower() != "aufgabe"]
        toks = [t for t in toks if re.match(r"^[A-Z]?[0-9]{1,2}$", t)]
        # Drop spurious anchors (e.g., footnotes like "Bei Aufgabe 18 ...")
        if toks and len(toks) >= 5:
            auf_rows.append((a, toks, bb))

    for a in antworten:
        toks, bb = collect_row_tokens(a)
        raw = [t for t in toks if t and t.lower() != "antwort"]
        toks = [normalize_answer(t) for t in raw]
        # Keep positional blanks so that label/answer alignment by index is preserved
        if raw:
            ant_rows.append((a, toks, bb))

    if not auf_rows or not ant_rows:
        return []

    # Pair anchors by vertical proximity within region (after building rows)
    ant_used = [False] * len(ant_rows)
    rowpairs: list[RowPair] = []
    for a_anchor, labels, a_bb in auf_rows:
        ay = y_center(a_anchor)
        best_j = -1
        best_d = 1e9
        for j, (b_anchor, _, _) in enumerate(ant_rows):
            if ant_used[j]:
                continue
            dy = y_center(b_anchor) - ay
            if abs(dy) < best_d and abs(dy) <= 24.0:
                best_d = abs(dy)
                best_j = j
        if best_j < 0:
            continue
        ant_used[best_j] = True
        # Use the pre-collected normalized answers for the matched Antwort row
        _, ans, bb_b = ant_rows[best_j]
        if len(ans) < len(labels):
            ans = ans + [""] * (len(labels) - len(ans))
        elif len(ans) > len(labels):
            ans = ans[: len(labels)]
        rowpairs.append(RowPair(labels=labels, answers=ans, bbox=(a_bb | bb_b)))

    return rowpairs


# ------------------------------- Orchestration ------------------------------

def validate_year_obj(obj: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation warnings for a year JSON.

    The checks are conservative so they work across old numeric layouts and
    newer ABC layouts:
      - 'counts' matches the length of 'order'
      - No duplicates in 'order'
      - Labels match the declared scheme (numeric or abc)
      - Every answer is A-E
      - No answers for labels not present in 'order'
      - Missing labels (in order but no answer) are reported
      - counts are between 5 and 30 inclusive
    """
    warnings: list[str] = []
    gg = obj.get("grade_groups", {}) or {}
    for group, g in gg.items():
        scheme = g.get("scheme")
        order = g.get("order", []) or []
        counts = int(g.get("counts", len(order)))
        answers = g.get("answers_by_label", {}) or {}
        miss_decl = set(g.get("missing_answers", []) or [])

        if counts != len(order):
            warnings.append(f"{group}: counts field {counts} != len(order) {len(order)}")

        # duplicates
        seen = set()
        dups = [lab for lab in order if (lab in seen) or seen.add(lab)]
        if dups:
            warnings.append(f"{group}: duplicate labels in order: {sorted(set(dups))[:10]}")

        # scheme conformity
        if scheme not in {"numeric", "abc"}:
            warnings.append(f"{group}: unknown scheme '{scheme}'")
        pat_num = re.compile(r"^[0-9]{1,2}$")
        pat_abc = re.compile(r"^[A-C](?:[0-9]{1,2})$")
        bad_labels = []
        for lab in order:
            if scheme == "abc":
                if not pat_abc.match(str(lab)):
                    bad_labels.append(lab)
            else:
                if not pat_num.match(str(lab)):
                    bad_labels.append(lab)
        if bad_labels:
            warnings.append(f"{group}: labels not matching scheme {scheme}: {bad_labels[:10]}")

        # range check (not assuming exact, just a sanity range)
        if not (5 <= len(order) <= 30):
            warnings.append(f"{group}: unusual label count {len(order)} (expected 5..30)")

        # answers A-E only
        bad_ans = [k for k, v in answers.items() if str(v) not in {"A", "B", "C", "D", "E"}]
        if bad_ans:
            warnings.append(f"{group}: non A-E answers for labels {bad_ans[:10]}")

        # extra answers for labels not in order
        extra = [k for k in answers.keys() if k not in order]
        if extra:
            warnings.append(f"{group}: answers for unknown labels {extra[:10]}")

        # compute missing by order vs provided answers
        missing_actual = [lab for lab in order if lab not in answers]
        undisclosed_missing = [lab for lab in missing_actual if lab not in miss_decl]
        if undisclosed_missing:
            warnings.append(
                f"{group}: {len(undisclosed_missing)} missing answers not listed in missing_answers (e.g., {undisclosed_missing[:10]})"
            )

    if not gg:
        warnings.append("no grade_groups produced")
    return warnings

def process_pdf(
    pdf_path: str,
    out_dir: str,
    *,
    overwrite: bool = False,
    debug: bool = False,
    strict: bool = False,
    debug_overlays: bool = False,
) -> list[Path]:
    doc = fitz.open(pdf_path)
    created: list[Path] = []
    current_year: int | None = None
    accumulators: dict[int, YearAccumulator] = {}

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]

            # Year detection per page
            new_year = detect_year(page, current_year)
            if new_year is not None:
                current_year = new_year
            if current_year is None:
                # Skip until a year is detected
                continue

            acc = accumulators.get(current_year)
            if acc is None:
                acc = YearAccumulator(year=current_year, source_pdf=os.path.relpath(pdf_path))
                accumulators[current_year] = acc

            headings = find_grade_headings(page)
            # Preferred approach: region-guided extraction per detected group
            associations: list[tuple[RowPair, str | None]] = []
            regions = compute_group_regions(page, headings)
            if regions:
                for grp, region in regions.items():
                    rps = extract_group_rowpairs(page, region)
                    for rp in rps:
                        associations.append((rp, grp))
                        if strict and len(rp.labels) != len(rp.answers):
                            raise RuntimeError(
                                f"Label/Answer count mismatch on page {page_index+1} group {grp}: {len(rp.labels)} vs {len(rp.answers)}"
                            )
                        acc.add_rowpair(grp, rp)
            else:
                # Fallback to legacy association strategies
                rowpairs = extract_tables_via_fitz(page)
                if not rowpairs:
                    rowpairs = extract_tables_via_bands(page)
                if not rowpairs:
                    rowpairs = extract_tables_via_words(page)

                for rp in rowpairs:
                    grp = associate_group(headings, rp.bbox)
                    associations.append((rp, grp))
                    if not grp:
                        acc.warnings.append(
                            f"page {page_index+1}: could not associate a table at bbox {tuple(round(v,1) for v in rp.bbox)} to any group"
                        )
                        continue
                    if strict and len(rp.labels) != len(rp.answers):
                        raise RuntimeError(
                            f"Label/Answer count mismatch on page {page_index+1} group {grp}: {len(rp.labels)} vs {len(rp.answers)}"
                        )
                    acc.add_rowpair(grp, rp)

            # Optional debug overlays per page
            if debug_overlays and associations:
                try:
                    save_page_debug_overlay(
                        page=page,
                        page_index=page_index,
                        year=current_year,
                        out_dir=out_dir,
                        headings=headings,
                        associations=associations,
                    )
                except Exception as e:
                    # Non-fatal
                    if debug:
                        print(f"Debug overlay failed for page {page_index+1}: {e}")

        # After all pages, write one JSON per year
        for year, acc in sorted(accumulators.items()):
            obj = acc.to_json_obj()
            # Run basic structural validation and attach warnings
            v_warnings = validate_year_obj(obj)
            if v_warnings:
                obj["validation_warnings"] = v_warnings
                if strict:
                    raise RuntimeError(
                        f"Validation failed for year {year}: {len(v_warnings)} issue(s). First: {v_warnings[0]}"
                    )
            out_path = Path(out_dir) / f"{year}.json"
            if out_path.exists() and not overwrite:
                # Merge with existing? For safety, require overwrite flag
                raise FileExistsError(f"Refusing to overwrite existing {out_path}. Use --overwrite to allow.")
            atomic_write_json(out_path, obj)
            created.append(out_path)

        return created
    finally:
        doc.close()


# ---------------------------------- CLI ------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extract answer keys from central answer-key PDF using PyMuPDF.")
    p.add_argument("--pdf", required=True, help="Path to the central answer-key PDF")
    p.add_argument("--out", default="answer_keys", help="Output directory for per-year JSON files")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing JSON files")
    p.add_argument("--debug", action="store_true", help="Enable additional logging")
    p.add_argument("--strict", action="store_true", help="Fail on any label/answer count mismatches")
    p.add_argument("--debug-overlays", action="store_true", help="Save per-page debug PNG overlays under <out>/debug/")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pdf_path = args.pdf
    out_dir = args.out
    overwrite = bool(args.overwrite)
    debug = bool(args.debug)
    strict = bool(args.strict)
    debug_overlays = bool(getattr(args, "debug_overlays", False))

    if not os.path.exists(pdf_path):
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    try:
        created = process_pdf(
            pdf_path,
            out_dir,
            overwrite=overwrite,
            debug=debug,
            strict=strict,
            debug_overlays=debug_overlays,
        )
    except Exception as e:
        print(f"Extraction failed: {e}", file=sys.stderr)
        return 1

    if debug:
        for p in created:
            print(f"Wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
