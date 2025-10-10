from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Dict, Iterable, Tuple


# Keys that can be edited from the web UI (top-level of record)
EDITABLE_TOP_LEVEL_KEYS = {
    "problem_statement",
    "problem_number",
    "points",
    "language",
    "sol_A",
    "sol_B",
    "sol_C",
    "sol_D",
    "sol_E",
    "sol_A_image",
    "sol_B_image",
    "sol_C_image",
    "sol_D_image",
    "sol_E_image",
    "associated_images",
    "answer",
}


def load_edits(path: str) -> Dict[str, dict]:
    """Load edits overlay file. Returns empty dict if missing or invalid."""
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _atomic_write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".edits.", suffix=".tmp", dir=d, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # Replace atomically
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def save_edits(path: str, data: Dict[str, dict]) -> None:
    """Persist edits overlay atomically."""
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    _atomic_write(path, payload)


def _merge_quality(base_q: dict | None, patch_q: dict | None) -> dict:
    out = dict(base_q or {})
    for k, v in (patch_q or {}).items():
        out[k] = v
    return out


def merge_record(base: dict, patch: dict) -> dict:
    """Return a merged view of a base record and its patch.

    - Only applies known editable keys and nested quality flags.
    """
    merged = dict(base)
    for k in EDITABLE_TOP_LEVEL_KEYS:
        if k in patch:
            merged[k] = patch[k]
    if "quality" in patch and isinstance(patch["quality"], dict):
        merged["quality"] = _merge_quality(base.get("quality"), patch["quality"])  # type: ignore[arg-type]
    quality = dict(merged.get("quality") or {})
    answer = merged.get("answer")
    answer_missing = (
        answer is None
        or (isinstance(answer, str) and answer.strip() == "")
        or (isinstance(answer, (list, tuple, set)) and len(answer) == 0)
    )
    quality["answer_missing"] = answer_missing
    merged["quality"] = quality
    return merged


def needs_review(rec: dict) -> bool:
    """Apply the same review criteria used by the HTML report."""
    # No options present at all (neither text nor images)
    no_opts = True
    for letter in ["A", "B", "C", "D", "E"]:
        if rec.get(f"sol_{letter}") or rec.get(f"sol_{letter}_image"):
            no_opts = False
            break
    q = rec.get("quality") or {}
    answer = rec.get("answer")
    no_answer = (
        answer is None
        or (isinstance(answer, str) and answer.strip() == "")
        or (isinstance(answer, (list, tuple, set)) and len(answer) == 0)
    )
    return bool(
        no_opts
        or q.get("answer_missing")
        or no_answer
        or q.get("needs_review")
        or q.get("ocr_short_text")
        or q.get("key_mismatch")
        or q.get("options_missing_or_extra")
    )


def _iter_jsonl(path: str) -> Iterable[Tuple[dict, str]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            obj = json.loads(s)
            yield obj, line


def apply_file(base_jsonl_path: str, edits_path: str, out_jsonl_path: str, only_reviewed: bool = False) -> None:
    """Stream-apply edits to a JSONL file and write a new JSONL.

    - If only_reviewed is True, only include records where edits.meta.reviewed is True, otherwise use base record.
    - If False, always merge edits when present regardless of reviewed flag.
    """
    edits = load_edits(edits_path)
    os.makedirs(os.path.dirname(out_jsonl_path) or ".", exist_ok=True)
    tmp_path = out_jsonl_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as out:
        for base, _line in _iter_jsonl(base_jsonl_path):
            rid = str(base.get("id"))
            p = edits.get(rid)
            if p:
                if only_reviewed and not (p.get("meta", {}).get("reviewed")):
                    # Skip patch if not reviewed
                    merged = base
                else:
                    merged = merge_record(base, p)
            else:
                merged = base
            out.write(json.dumps(merged, ensure_ascii=False) + "\n")
    os.replace(tmp_path, out_jsonl_path)


def record_patch_from_form(base: dict, form: dict) -> dict:
    """Create a minimal patch dict from form values by diffing against base.

    - Only include fields that changed
    - Parse booleans for quality flags and reviewed
    """
    patch: dict = {}

    def set_if_changed(key: str, value):
        if key in base:
            if base.get(key) != value:
                patch[key] = value
        else:
            # If base doesn't have it, set if non-empty
            if value not in (None, ""):
                patch[key] = value

    # Normalize blank strings to None for certain fields
    def _norm_text(v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # Top-level editable fields from form
    # problem_statement can be an empty string (we keep as-is), others normalize blanks to None
    if "problem_statement" in form:
        set_if_changed("problem_statement", form.get("problem_statement"))

    # Optional numeric points
    if "points" in form:
        try:
            val = int(form.get("points")) if str(form.get("points")).strip() != "" else None
        except Exception:
            val = None
        if val is not None:
            set_if_changed("points", val)

    # Optional problem number / language
    if "problem_number" in form:
        set_if_changed("problem_number", str(form.get("problem_number") or ""))
    if "language" in form:
        set_if_changed("language", str(form.get("language") or "").strip() or "de")

    for k in ["sol_A", "sol_B", "sol_C", "sol_D", "sol_E"]:
        if k in form:
            set_if_changed(k, _norm_text(form.get(k)))
    for k in ["sol_A_image", "sol_B_image", "sol_C_image", "sol_D_image", "sol_E_image"]:
        if k in form:
            set_if_changed(k, _norm_text(form.get(k)))
    if "answer" in form:
        set_if_changed("answer", _norm_text(form.get("answer")))

    # associated_images: comma-separated list
    if "associated_images" in form:
        raw = form.get("associated_images") or ""
        arr = [s.strip() for s in raw.split("\n") if s.strip()] if isinstance(raw, str) else []
        set_if_changed("associated_images", arr)

    # quality flags
    q_base = base.get("quality") or {}
    q_patch: dict = {}
    for qk in ["needs_review", "options_missing_or_extra", "ocr_short_text", "key_mismatch"]:
        val = True if (form.get(qk) in ("on", "true", True)) else False
        if bool(q_base.get(qk, False)) != val:
            q_patch[qk] = val
    if q_patch:
        patch["quality"] = q_patch

    # meta.reviewed + notes
    meta_base = {}
    m_patch: dict = {}
    if form.get("reviewed") is not None:
        rev = True if (form.get("reviewed") in ("on", "true", True)) else False
        if rev:
            m_patch["reviewed"] = True
    if form.get("notes") is not None:
        notes = str(form.get("notes") or "").strip()
        if notes:
            m_patch["notes"] = notes
    if m_patch:
        m_patch["updated_at"] = datetime.now(timezone.utc).isoformat()
        patch["meta"] = m_patch

    return patch


__all__ = [
    "load_edits",
    "save_edits",
    "merge_record",
    "needs_review",
    "apply_file",
    "record_patch_from_form",
]
