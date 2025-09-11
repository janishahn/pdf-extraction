from __future__ import annotations
import glob
import json
import os
from typing import Dict, Tuple, Optional, List
# Mapping: (exam_id, problem_number) -> answer letter
AnswerMap = Dict[Tuple[str, str], str]
def load_answer_key(path: str) -> AnswerMap:
    """Load answer key JSON.
    Supported formats:
    1. {"exam_id": {"problem_number": "A", ...}, ...}
    2. [{"exam_id": "id", "problem_number": "1", "answer": "B"}, ...]
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    mapping: AnswerMap = {}
    if isinstance(data, dict):
        for exam_id, qdict in data.items():
            if isinstance(qdict, dict):
                for pn, ans in qdict.items():
                    mapping[(str(exam_id), str(pn))] = str(ans).strip().upper()
    elif isinstance(data, list):
        for row in data:
            exam_id = str(row.get("exam_id"))
            pn = str(row.get("problem_number") or row.get("number") or row.get("id"))
            ans = row.get("answer")
            if exam_id and pn and ans:
                mapping[(exam_id, pn)] = str(ans).strip().upper()
    return mapping
def lookup_answer(mapping: AnswerMap, exam_id: str, problem_number: str) -> Optional[str]:
    return mapping.get((exam_id, problem_number))


def _load_year_file(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _label_is_numeric(label: str) -> bool:
    try:
        int(label)
        return True
    except Exception:
        return False


def build_answer_map_from_year_files(keys_dir: str, original_pdfs_dir: str) -> AnswerMap:
    """Build an AnswerMap by joining per-year answer key JSONs to exam PDFs.

    - keys_dir: directory containing files like "YYYY.json" with structure from extract_answer_keys.py
    - original_pdfs_dir: directory containing exam PDFs named like "YY_34.pdf", "14_1113.pdf", etc.

    Strategy:
    - For each PDF in original_pdfs_dir, derive (year, group) from filename using storage.extract_pdf_metadata_from_filename.
    - Open the corresponding year JSON and group entry.
    - Use its "order" to map ordinal indices (1-based) to answers; also map numeric labels directly when applicable.
    - Store answers under keys (exam_id, problem_number) where exam_id is the PDF stem and problem_number is either
      the ordinal index string or the numeric label string when available.
    """
    from storage import extract_pdf_metadata_from_filename  # local import to avoid circulars

    mapping: AnswerMap = {}
    pdf_paths: List[str] = sorted(glob.glob(os.path.join(original_pdfs_dir, "*.pdf")))
    for pdf_path in pdf_paths:
        meta = extract_pdf_metadata_from_filename(pdf_path)
        if not meta:
            continue
        year = meta.get("year")
        group = meta.get("grade_group")
        if not year or not group:
            continue
        year_file = os.path.join(keys_dir, f"{int(year)}.json")
        obj = _load_year_file(year_file)
        if not obj:
            continue
        gg = (obj.get("grade_groups") or {}).get(group)
        if not gg:
            continue
        order = gg.get("order") or []
        ans_by = gg.get("answers_by_label") or {}
        stem = os.path.splitext(os.path.basename(pdf_path))[0]
        stem_pdf = stem + ".pdf"

        # Build both ordinal and numeric-label mappings for robustness
        for idx, label in enumerate(order, start=1):
            ans = ans_by.get(label)
            if not ans:
                continue
            ans_u = str(ans).strip().upper()
            mapping[(stem, str(idx))] = ans_u
            mapping[(stem_pdf, str(idx))] = ans_u
            if _label_is_numeric(label):
                mapping[(stem, str(label))] = ans_u
                mapping[(stem_pdf, str(label))] = ans_u

    return mapping
