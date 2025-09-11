from __future__ import annotations
import json
from typing import Dict, Tuple, Optional
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