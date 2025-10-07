from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .models import BBox, QuestionUnit
try:
    # Use storage migration/backfill when parsing GUI state files
    from storage import load_state  # type: ignore
except Exception:
    load_state = None  # type: ignore


@dataclass
class ExamAnnotations:
    exam_id: str
    pdf_path: str
    year: str
    group: str
    questions: List[QuestionUnit]


def load_all_exams(original_dir: str) -> List[ExamAnnotations]:
    exams: List[ExamAnnotations] = []
    json_files = sorted(glob.glob(os.path.join(original_dir, "*.json")))
    for jf in json_files:
        name = os.path.basename(jf)
        stem0 = os.path.splitext(name)[0]
        # Handle companion files named like "foo.pdf.json"
        pdf_stem = stem0[:-4] if stem0.endswith(".pdf") else stem0
        cand_pdf = os.path.join(original_dir, f"{pdf_stem}.pdf")
        if not os.path.exists(cand_pdf):
            continue
        ex = parse_exam_annotation(jf, cand_pdf)
        exams.append(ex)
    return exams


def parse_exam_annotation(json_path: str, pdf_path: str) -> ExamAnnotations:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Determine exam_id/year/group from file or filename
    base_id = os.path.splitext(os.path.basename(pdf_path))[0]
    exam_id = str(data.get("exam_id") or base_id)
    # Derive year/group from filename when not present
    try:
        from storage import extract_pdf_metadata_from_filename  # type: ignore

        meta = extract_pdf_metadata_from_filename(pdf_path) or {}
        year = str(data.get("year") or meta.get("year") or "")
        group = str(data.get("group") or meta.get("grade_group") or "")
    except Exception:
        year = str(data.get("year", ""))
        group = str(data.get("group", ""))

    questions: List[QuestionUnit] = []

    if data.get("questions"):
        # Direct schema supported
        items = data.get("questions") or []
        for q in items:
            qid = str(q.get("question_id"))
            problem_number = str(q.get("problem_number") or q.get("number") or q.get("index") or "")
            text_boxes = [
                BBox(
                    page_index=int(b["page_index"]),
                    x0=float(b["x0"]),
                    y0=float(b["y0"]),
                    x1=float(b["x1"]),
                    y1=float(b["y1"]),
                )
                for b in q.get("text_boxes", [])
            ]
            associated_images = [
                BBox(
                    page_index=int(b["page_index"]),
                    x0=float(b["x0"]),
                    y0=float(b["y0"]),
                    x1=float(b["x1"]),
                    y1=float(b["y1"]),
                )
                for b in q.get("associated_images", [])
            ]
            image_options_raw = q.get("image_options", {})
            image_options: Dict[str, BBox] = {}
            for letter, b in image_options_raw.items():
                image_options[str(letter)] = BBox(
                    page_index=int(b["page_index"]),
                    x0=float(b["x0"]),
                    y0=float(b["y0"]),
                    x1=float(b["x1"]),
                    y1=float(b["y1"]),
                )

            questions.append(
                QuestionUnit(
                    exam_id=exam_id,
                    question_id=qid,
                    problem_number=problem_number,
                    year=year,
                    group=group,
                    text_boxes=sorted(text_boxes, key=lambda r: (r.page_index, r.y0, r.x0)),
                    associated_images=associated_images,
                    image_options=image_options,
                )
            )
    elif data.get("pages"):
        # Convert GUI state schema (pages -> masks) into questions
        # Prefer loading via storage.load_state to migrate/backfill older files
        pages_source = data
        if callable(load_state):
            try:
                pages_source = load_state(pdf_path) or data
            except Exception:
                pages_source = data
        pages = pages_source.get("pages") or {}

        # Helper: convert pixel coordinates (assumed ~300 DPI) to PDF points
        def px_to_pt(v: float, dpi: int = 300) -> float:
            return float(v) * 72.0 / float(dpi)

        def bbox_from_points(pts: List[List[float]]) -> Tuple[float, float, float, float]:
            xs = [float(p[0]) for p in pts] if pts else [0.0]
            ys = [float(p[1]) for p in pts] if pts else [0.0]
            return min(xs), min(ys), max(xs), max(ys)

        # Accumulate groups across all pages, keyed by question_id or fallback id
        all_grouped: Dict[str, Dict[str, any]] = {}

        # Build quick lookup and group
        for page_str, pdat in pages.items():
            try:
                page_index = int(page_str) - 1
            except Exception:
                continue
            masks = pdat.get("masks", [])
            img_by_id: Dict[str, dict] = {}
            for m in masks:
                # Some older state files omit type for image masks; default missing type to image
                is_image = (m.get("type") == "image") or (m.get("type") is None)
                if is_image and m.get("points") and m.get("id"):
                    img_by_id[str(m.get("id"))] = m

            for m in masks:
                if m.get("type") != "question" or not m.get("points"):
                    continue
                qid = str(
                    m.get("question_group_id")
                    or m.get("question_id")
                    or f"p{page_str}_{m.get('id')}"
                )
                g = all_grouped.setdefault(qid, {"boxes": [], "assoc": [], "opts": {}, "pn": None, "first_box": None})

                pts_px = m.get("points") or []
                x0, y0, x1, y1 = bbox_from_points(pts_px)
                pts_pt = [(px_to_pt(px), px_to_pt(py)) for px, py in pts_px]
                bb = BBox(page_index=page_index, x0=px_to_pt(x0), y0=px_to_pt(y0), x1=px_to_pt(x1), y1=px_to_pt(y1), points=pts_pt)
                g["boxes"].append(bb)
                if g["first_box"] is None:
                    g["first_box"] = bb

                # Extract problem number from score_calculation like "question 1 of 24"
                pn = None
                sc = str(m.get("score_calculation") or "")
                mm = re.search(r"question\s+(\d+)\b", sc)
                if mm:
                    pn = mm.group(1)
                g["pn"] = g["pn"] or pn

                assoc_ids = m.get("associated_image_ids") or []
                for aid in assoc_ids:
                    im = img_by_id.get(str(aid))
                    if not im or not im.get("points"):
                        continue
                    ipts_px = im.get("points") or []
                    ix0, iy0, ix1, iy1 = bbox_from_points(ipts_px)
                    ipts_pt = [(px_to_pt(px), px_to_pt(py)) for px, py in ipts_px]
                    ibb = BBox(page_index=page_index, x0=px_to_pt(ix0), y0=px_to_pt(iy0), x1=px_to_pt(ix1), y1=px_to_pt(iy1), points=ipts_pt)
                    lab = str(im.get("option_label") or "").strip().upper()
                    checked = bool(im.get("option_label_checked"))
                    if lab in {"A", "B", "C", "D", "E"}:
                        # Prefer checked masks if duplicates exist
                        if lab not in g["opts"] or checked:
                            g["opts"][lab] = ibb
                    else:
                        g["assoc"].append(ibb)


        # Assign sequential problem numbers for any missing
        # Sort by page_index, y0, x0 of the first text box
        ordered = sorted(all_grouped.items(), key=lambda kv: (
            getattr(kv[1].get("first_box"), "page_index", 0),
            getattr(kv[1].get("first_box"), "y0", 0.0),
            getattr(kv[1].get("first_box"), "x0", 0.0),
        ))
        seq = 1
        for qid, g in ordered:
            if not g.get("pn"):
                g["pn"] = str(seq)
            seq += 1

        # Materialize QuestionUnit entries
        for qid, g in ordered:
            questions.append(
                QuestionUnit(
                    exam_id=exam_id,
                    question_id=qid,
                    problem_number=str(g.get("pn") or ""),
                    year=year,
                    group=group,
                    text_boxes=sorted(g.get("boxes") or [], key=lambda r: (r.page_index, r.y0, r.x0)),
                    associated_images=g.get("assoc") or [],
                    image_options=g.get("opts") or {},
                )
            )

    return ExamAnnotations(
        exam_id=exam_id,
        pdf_path=pdf_path,
        year=year,
        group=group,
        questions=questions,
    )
