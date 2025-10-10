from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import PATHS
from .edits import (
    apply_file,
    load_edits,
    merge_record,
    needs_review,
    record_patch_from_form,
    save_edits,
)


import json


def _load_base_records(jsonl_path: str) -> Dict[str, dict]:
    recs: Dict[str, dict] = {}
    if not os.path.exists(jsonl_path):
        return recs
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            rid = str(obj.get("id"))
            recs[rid] = obj
    return recs


def create_app(
    jsonl_path: Optional[str] = None,
    edits_path: Optional[str] = None,
    crops_dir: Optional[str] = None,
    dataset_dir: Optional[str] = None,
) -> FastAPI:
    jsonl_path = jsonl_path or os.path.join(PATHS.dataset, "dataset.jsonl")
    edits_path = edits_path or os.path.join(PATHS.dataset, "edits.json")
    crops_dir = crops_dir or PATHS.crops
    dataset_dir = dataset_dir or PATHS.dataset

    app = FastAPI(title="Exam Dataset Review")
    templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "review_templates"))

    # State
    app.state.jsonl_path = jsonl_path
    app.state.edits_path = edits_path
    app.state.crops_dir = crops_dir
    app.state.dataset_dir = dataset_dir
    app.state.base_records = _load_base_records(jsonl_path)
    app.state.edits = load_edits(edits_path)

    # Static mounts for crops and dataset outputs (download edited JSONL)
    if os.path.isdir(crops_dir):
        app.mount("/crops", StaticFiles(directory=crops_dir), name="crops")
    if os.path.isdir(dataset_dir):
        app.mount("/dataset", StaticFiles(directory=dataset_dir), name="dataset")
    static_dir = os.path.join(os.path.dirname(__file__), "review_static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def _ensure_answer_flag(rec: dict) -> dict:
        out = dict(rec)
        quality = dict(out.get("quality") or {})
        answer = out.get("answer")
        answer_missing = (
            answer is None
            or (isinstance(answer, str) and answer.strip() == "")
            or (isinstance(answer, (list, tuple, set)) and len(answer) == 0)
        )
        quality["answer_missing"] = answer_missing
        out["quality"] = quality
        return out

    def merged_record(rid: str) -> Optional[dict]:
        base = app.state.base_records.get(rid)
        if not base:
            return None
        p = app.state.edits.get(rid, {})
        merged = merge_record(base, p) if p else dict(base)
        return _ensure_answer_flag(merged)

    def list_records(filter_type: str = "needs_review", q: str = "", year: str = "", group: str = "") -> List[dict]:
        recs = []
        qnorm = (q or "").strip().lower()
        for rid, base in app.state.base_records.items():
            m = merged_record(rid) or base
            if year and str(m.get("year")) != str(year):
                continue
            if group and str(m.get("group")) != str(group):
                continue
            if qnorm and qnorm not in (str(m.get("problem_statement") or "").lower() + " " + rid.lower()):
                continue
            flag = needs_review(m)
            if filter_type == "needs_review":
                if not flag:
                    continue
            elif filter_type == "unreviewed":
                ed = app.state.edits.get(rid, {})
                if ed.get("meta", {}).get("reviewed"):
                    continue
            # else: 'all' returns everything
            recs.append(m)
        # Stable order by id
        recs.sort(key=lambda r: str(r.get("id")))
        return recs

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, filter: str = "needs_review", q: str = "", year: str = "", group: str = ""):
        items = list_records(filter, q, year, group)
        stats = {
            "total": len(app.state.base_records),
            "edited": len(app.state.edits),
            "needs_review": sum(1 for _id in app.state.base_records if needs_review(merged_record(_id) or app.state.base_records[_id])),
        }
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "items": items,
                "filter": filter,
                "q": q,
                "year": year,
                "group": group,
                "stats": stats,
                "dataset_name": os.path.basename(app.state.jsonl_path),
            },
        )

    @app.get("/record/{rid}", response_class=HTMLResponse)
    def record_view(request: Request, rid: str):
        rec = merged_record(rid)
        if not rec:
            return HTMLResponse(f"<h3>Record not found: {rid}</h3>", status_code=404)

        # Derive image URLs
        qimg = f"/crops/question/{rid}.png"
        opt_imgs = {}
        opt_candidates = {}
        for L in ["A", "B", "C", "D", "E"]:
            v = rec.get(f"sol_{L}_image")
            if v:
                # If absolute path within crops, try to map to /crops
                if isinstance(v, str) and os.path.isabs(v) and os.path.commonpath([v, app.state.crops_dir]) == app.state.crops_dir:
                    rel = os.path.relpath(v, app.state.crops_dir)
                    opt_imgs[L] = f"/crops/{rel}"
                else:
                    opt_imgs[L] = v
            # Suggest known crop for this letter
            cand = os.path.join(app.state.crops_dir, "option_image", f"{rid}_opt{L}.png")
            if os.path.exists(cand):
                opt_candidates[L] = {
                    "path": cand,
                    "url": f"/crops/option_image/{rid}_opt{L}.png",
                }
        assoc_urls: List[str] = []
        assoc_candidates: List[dict] = []
        for p in rec.get("associated_images") or []:
            if isinstance(p, str) and os.path.isabs(p) and os.path.commonpath([p, app.state.crops_dir]) == app.state.crops_dir:
                assoc_urls.append(f"/crops/{os.path.relpath(p, app.state.crops_dir)}")
            else:
                assoc_urls.append(str(p))
        # Suggest all known assoc crops for this record id
        assoc_dir = os.path.join(app.state.crops_dir, "assoc_image")
        if os.path.isdir(assoc_dir):
            try:
                for name in sorted(os.listdir(assoc_dir)):
                    if name.startswith(f"{rid}_img") and name.endswith(".png"):
                        assoc_candidates.append({
                            "path": os.path.join(assoc_dir, name),
                            "url": f"/crops/assoc_image/{name}",
                            "name": name,
                        })
            except Exception:
                pass

        # Neighbor ids
        ids = sorted(app.state.base_records.keys())
        idx = ids.index(rid) if rid in ids else -1
        prev_id = ids[idx - 1] if idx > 0 else None
        next_id = ids[idx + 1] if idx >= 0 and idx + 1 < len(ids) else None

        return templates.TemplateResponse(
            "record.html",
            {
                "request": request,
                "rec": rec,
                "rid": rid,
                "qimg": qimg,
                "opt_imgs": opt_imgs,
                "opt_candidates": opt_candidates,
                "assoc_urls": assoc_urls,
                "assoc_candidates": assoc_candidates,
                "prev_id": prev_id,
                "next_id": next_id,
                "dataset_name": os.path.basename(app.state.jsonl_path),
            },
        )

    @app.post("/record/{rid}")
    async def update_record(
        request: Request,
        rid: str,
        problem_statement: str = Form(default=""),
        problem_number: str = Form(default=""),
        points: str = Form(default=""),
        language: str = Form(default=""),
        sol_A: str = Form(default=""),
        sol_B: str = Form(default=""),
        sol_C: str = Form(default=""),
        sol_D: str = Form(default=""),
        sol_E: str = Form(default=""),
        sol_A_image: str = Form(default=""),
        sol_B_image: str = Form(default=""),
        sol_C_image: str = Form(default=""),
        sol_D_image: str = Form(default=""),
        sol_E_image: str = Form(default=""),
        associated_images: str = Form(default=""),  # newline-separated
        answer: str = Form(default=""),
        needs_review_flag: Optional[str] = Form(alias="needs_review", default=None),
        options_missing_or_extra: Optional[str] = Form(default=None),
        ocr_short_text: Optional[str] = Form(default=None),
        key_mismatch: Optional[str] = Form(default=None),
        reviewed: Optional[str] = Form(default=None),
        notes: Optional[str] = Form(default=None),
        action: str = Form(default="save"),
    ):
        base = app.state.base_records.get(rid)
        if not base:
            return HTMLResponse(f"Record not found: {rid}", status_code=404)

        form = {
            "problem_statement": problem_statement,
            "problem_number": problem_number,
            "points": points,
            "language": language,
            "sol_A": sol_A,
            "sol_B": sol_B,
            "sol_C": sol_C,
            "sol_D": sol_D,
            "sol_E": sol_E,
            "sol_A_image": sol_A_image,
            "sol_B_image": sol_B_image,
            "sol_C_image": sol_C_image,
            "sol_D_image": sol_D_image,
            "sol_E_image": sol_E_image,
            "associated_images": associated_images,
            "answer": (answer or None),
            "needs_review": needs_review_flag,
            "options_missing_or_extra": options_missing_or_extra,
            "ocr_short_text": ocr_short_text,
            "key_mismatch": key_mismatch,
            "reviewed": reviewed,
            "notes": notes,
        }

        patch = record_patch_from_form(base, form)
        # Merge into in-memory edits and persist
        cur = app.state.edits.get(rid, {})
        # Shallow merge for top-level; nested merge for quality/meta handled simply here
        for k, v in patch.items():
            if k == "quality":
                q = dict(cur.get("quality", {}))
                q.update(v)
                cur["quality"] = q
            elif k == "meta":
                m = dict(cur.get("meta", {}))
                m.update(v)
                cur["meta"] = m
            else:
                cur[k] = v
        # If marking reviewed via explicit action
        if action == "mark_reviewed":
            cur.setdefault("meta", {})["reviewed"] = True
            cur.setdefault("quality", {})["needs_review"] = False
        app.state.edits[rid] = cur
        save_edits(app.state.edits_path, app.state.edits)

        # Redirect back to record
        return RedirectResponse(url=f"/record/{rid}", status_code=303)

    @app.post("/open/{rid}")
    def open_in_annotator(rid: str):
        rec = merged_record(rid)
        if not rec:
            return JSONResponse({"ok": False, "error": "record not found"}, status_code=404)
        pdf = rec.get("provenance", {}).get("pdf_path")
        try:
            cmd = [sys.executable, os.path.join(os.getcwd(), "gui.py")]
            if pdf:
                cmd.extend(["--pdf", str(pdf)])
            # Best-effort non-blocking spawn
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/apply-edits")
    async def apply_edits(request: Request, only_reviewed: Optional[str] = Form(default=None)):
        # Write edits next to the base dataset with a dataset-specific name
        base_dir = os.path.dirname(app.state.jsonl_path) or app.state.dataset_dir
        base_stem = os.path.splitext(os.path.basename(app.state.jsonl_path))[0]
        out_path = os.path.join(base_dir, f"{base_stem}.edited.jsonl")
        try:
            apply_file(
                app.state.jsonl_path,
                app.state.edits_path,
                out_path,
                only_reviewed=True if (only_reviewed in ("on", "true", True)) else False,
            )
            # Ensure dataset mount exists
            if not any(r.mount_path == "/dataset" for r in app.router.routes if hasattr(r, "mount_path")):
                if os.path.isdir(app.state.dataset_dir):
                    app.mount("/dataset", StaticFiles(directory=app.state.dataset_dir), name="dataset")
            # Show link to download
            return RedirectResponse(url=f"/download?path={os.path.basename(out_path)}", status_code=303)
        except Exception as e:
            return HTMLResponse(f"<h3>Apply failed</h3><pre>{str(e)}</pre>", status_code=500)

    @app.get("/download", response_class=HTMLResponse)
    def download(request: Request, path: str):
        # Simple page with a link to the file under /dataset
        return templates.TemplateResponse(
            "download.html",
            {
                "request": request,
                "file_rel": path,
                "file_url": f"/dataset/{path}",
                "dataset_name": os.path.basename(app.state.jsonl_path),
            },
        )

    @app.post("/reload")
    def reload_data():
        app.state.base_records = _load_base_records(app.state.jsonl_path)
        app.state.edits = load_edits(app.state.edits_path)
        return RedirectResponse(url="/", status_code=303)

    return app


__all__ = ["create_app"]
