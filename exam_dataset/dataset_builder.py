from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image
import fitz
from tqdm import tqdm

from .annotation_loader import ExamAnnotations, load_all_exams
from .answer_key_loader import AnswerMap, load_answer_key, lookup_answer
from .config import PATHS
from .models import BBox, DatasetRecord, Provenance, Quality, QuestionUnit
from .ocr_mistral import MistralOCR
from .option_parser import split_options
from .pdf_render import ensure_dir, pdf_sha256, render_bbox, stack_vertical
from .points import points_for_index


def render_text_crop(exam: ExamAnnotations, q: QuestionUnit, doc: Optional[fitz.Document] = None) -> Tuple[str, int]:
    # Mask only this question's own image masks to avoid over-masking text.
    overlaps: List[BBox] = list(q.associated_images) + list(q.image_options.values())
    imgs: List[Image.Image] = []
    dpis: List[int] = []
    for tb in q.text_boxes:
        img = render_bbox(exam.pdf_path, tb, mask_overlaps=overlaps, doc=doc)
        imgs.append(img)
        dpis.append(round(img.info.get("dpi", (300, 300))[0]) if img.info.get("dpi") else 0)
    if len(imgs) == 1:
        out = imgs[0]
    else:
        out = stack_vertical(imgs)
    qdir = os.path.join(PATHS.crops, "question")
    ensure_dir(qdir)
    out_path = os.path.join(qdir, f"{q.exam_id}_{q.question_id}.png")
    out.save(out_path)
    used_dpi = max([d for d in dpis if d], default=0)
    return out_path, used_dpi


def render_image_crops(exam: ExamAnnotations, q: QuestionUnit, doc: Optional[fitz.Document] = None) -> Tuple[Dict[str, str], List[str], Dict[str, int]]:
    opt_dir = os.path.join(PATHS.crops, "option_image")
    assoc_dir = os.path.join(PATHS.crops, "assoc_image")
    ensure_dir(opt_dir)
    ensure_dir(assoc_dir)

    dpi_used: Dict[str, int] = {}
    option_paths: Dict[str, str] = {}
    for letter, bb in q.image_options.items():
        im = render_bbox(exam.pdf_path, bb, grayscale=False, doc=doc)
        p = os.path.join(opt_dir, f"{q.exam_id}_{q.question_id}_opt{letter}.png")
        im.save(p)
        option_paths[letter] = p
        dpi_used[f"opt_{letter}"] = round(im.info.get("dpi", (0, 0))[0]) if im.info.get("dpi") else 0

    assoc_paths: List[str] = []
    for i, bb in enumerate(q.associated_images, start=1):
        im = render_bbox(exam.pdf_path, bb, grayscale=False, doc=doc)
        p = os.path.join(assoc_dir, f"{q.exam_id}_{q.question_id}_img{i}.png")
        im.save(p)
        assoc_paths.append(p)
        dpi_used[f"img_{i}"] = round(im.info.get("dpi", (0, 0))[0]) if im.info.get("dpi") else 0

    return option_paths, assoc_paths, dpi_used


def assemble_record(
    exam: ExamAnnotations,
    q: QuestionUnit,
    idx1: int,
    total_questions: int,
    text_path: str,
    ocr_text: str,
    option_images: Dict[str, str],
    assoc_images: List[str],
    dpi_map: Dict[str, int],
    answer: Optional[str] = None,
) -> DatasetRecord:
    stem, options = split_options(ocr_text)

    multimodal = bool(assoc_images or option_images)
    letters = ["A", "B", "C", "D", "E"]
    sols_text: Dict[str, Optional[str]] = {k: None for k in letters}
    for k in letters:
        if k in options and options[k].strip():
            sols_text[k] = options[k].strip()

    prov = Provenance(
        pdf_path=exam.pdf_path,
        pdf_sha256=pdf_sha256(exam.pdf_path),
        text_boxes=q.text_boxes,
        associated_images=q.associated_images,
        image_options=q.image_options,
        dpi_used=dpi_map,
        renderer="pymupdf",
        ocr_engine="mistral-ocr",
        annotation_version=None,
    )

    quality = Quality()
    if not stem.strip():
        quality.ocr_short_text = True

    have = len([k for k in letters if sols_text.get(k) or option_images.get(k)])
    if have != 5:
        quality.options_missing_or_extra = True
        quality.needs_review = True

    if answer and answer not in letters:
        quality.key_mismatch = True
        quality.needs_review = True

    rec_id = f"{exam.exam_id}_{q.question_id}"
    points = points_for_index(total_questions, idx1)

    return DatasetRecord(
        id=rec_id,
        year=exam.year,
        group=exam.group,
        points=points,
        problem_number=q.problem_number,
        problem_statement=stem.strip(),
        sol_A=sols_text["A"],
        sol_B=sols_text["B"],
        sol_C=sols_text["C"],
        sol_D=sols_text["D"],
        sol_E=sols_text["E"],
        sol_A_image=option_images.get("A"),
        sol_B_image=option_images.get("B"),
        sol_C_image=option_images.get("C"),
        sol_D_image=option_images.get("D"),
        sol_E_image=option_images.get("E"),
        associated_images=assoc_images,
        language="de",
        multimodal=multimodal,
        answer=answer,
        provenance=prov,
        quality=quality,
    )


def _ocr_images_in_batches(
    paths: List[str],
    client: MistralOCR,
    batch_size: int = 5,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> List[str]:
    """Run OCR on image paths in batches, preserving order.

    - Submits at most `batch_size` concurrent requests per batch.
    - Returns a list of texts aligned with `paths`.
    """
    texts: List[str] = [""] * len(paths)

    def worker(idx: int) -> str:
        p = paths[idx]
        try:
            res = client.ocr_image(p)
            return res.text or ""
        except Exception:
            return ""

    for start in range(0, len(paths), batch_size):
        end = min(start + batch_size, len(paths))
        with ThreadPoolExecutor(max_workers=batch_size) as ex:
            futures = {ex.submit(worker, i): i for i in range(start, end)}
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    texts[i] = fut.result()
                except Exception:
                    texts[i] = ""
        if progress_cb:
            try:
                progress_cb(end - start)
            except Exception:
                pass
    return texts


def run_build(
    output_jsonl: str,
    use_ocr: bool = True,
    answer_key: Optional[str] = None,
    report_html: Optional[str] = None,
    answer_dir: Optional[str] = None,
    ocr_batch_size: int = 5,
) -> None:
    ensure_dir(PATHS.crops)
    ensure_dir(PATHS.ocr)
    ensure_dir(PATHS.dataset)
    ensure_dir(PATHS.reports)
    exams = load_all_exams(PATHS.original_pdfs)

    ans_map: AnswerMap = {}
    if answer_key and os.path.exists(answer_key):
        try:
            ans_map = load_answer_key(answer_key)
        except Exception:
            ans_map = {}
    # Merge in per-year answer keys if a directory is provided
    if answer_dir and os.path.isdir(answer_dir):
        try:
            from .answer_key_loader import build_answer_map_from_year_files

            dir_map = build_answer_map_from_year_files(answer_dir, PATHS.original_pdfs)
            ans_map.update(dir_map)
        except Exception:
            pass

    ocr_client = None
    if use_ocr:
        try:
            ocr_client = MistralOCR()
        except Exception:
            ocr_client = None

    out_records: List[dict] = []
    report_items: List[Tuple[str, DatasetRecord]] = []
    total_all = sum(len(ex.questions) for ex in exams)
    global_bar = tqdm(total=total_all, desc="build", unit="q")
    for exam in exams:
        total = len(exam.questions)

        # First pass: render crops and collect per-question artifacts
        q_img_paths: List[str] = []
        dpi_texts: List[int] = []
        option_paths_list: List[Dict[str, str]] = []
        assoc_paths_list: List[List[str]] = []
        dpi_maps_list: List[Dict[str, int]] = []

        # Open the PDF once per exam and reuse it for all crops
        doc = fitz.open(exam.pdf_path)
        try:
            for q in exam.questions:
                q_img_path, dpi_text = render_text_crop(exam, q, doc=doc)
                option_paths, assoc_paths, dpi_map = render_image_crops(exam, q, doc=doc)
                dpi_map["question"] = dpi_text

                q_img_paths.append(q_img_path)
                dpi_texts.append(dpi_text)
                option_paths_list.append(option_paths)
                assoc_paths_list.append(assoc_paths)
                dpi_maps_list.append(dpi_map)
        finally:
            doc.close()

        # OCR in batches for this exam
        if ocr_client and use_ocr and q_img_paths:
            ocr_texts = _ocr_images_in_batches(
                q_img_paths,
                ocr_client,
                batch_size=max(1, int(ocr_batch_size)),
                progress_cb=global_bar.update,
            )
            # Light retry for empty results (bounded to a small number per exam)
            retries = 0
            for i, txt in enumerate(ocr_texts):
                if retries >= 3:
                    break
                if not (txt or "").strip():
                    try:
                        res = ocr_client.ocr_image(q_img_paths[i])
                        if res.text and res.text.strip():
                            ocr_texts[i] = res.text
                            retries += 1
                    except Exception:
                        pass
        else:
            ocr_texts = [""] * len(q_img_paths)

        # Assemble records with aligned OCR results
        for idx, q in enumerate(exam.questions, start=1):
            q_img_path = q_img_paths[idx - 1]
            option_paths = option_paths_list[idx - 1]
            assoc_paths = assoc_paths_list[idx - 1]
            dpi_map = dpi_maps_list[idx - 1]
            ocr_text = ocr_texts[idx - 1]

            answer = lookup_answer(ans_map, exam.exam_id, q.problem_number)
            rec = assemble_record(
                exam=exam,
                q=q,
                idx1=idx,
                total_questions=total,
                text_path=q_img_path,
                ocr_text=ocr_text,
                option_images=option_paths,
                assoc_images=assoc_paths,
                dpi_map=dpi_map,
                answer=answer,
            )
            out_records.append(_record_to_json(rec))
            report_items.append((q_img_path, rec))
            if not (ocr_client and use_ocr):
                global_bar.update(1)

    global_bar.close()

    with open(output_jsonl, "w", encoding="utf-8") as f:
        for r in out_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if report_html:
        from .report import write_html_report

        write_html_report(report_items, report_html)

    # Validation summary
    try:
        total = len(out_records)
        answers_present = sum(1 for r in out_records if r.get("answer"))
        multimodal_true = sum(1 for r in out_records if r.get("multimodal"))
        ocr_nonempty = sum(1 for r in out_records if (r.get("problem_statement") or ""))
        needs_review_true = sum(1 for r in out_records if (r.get("quality") or {}).get("needs_review"))
        options_full = 0
        for r in out_records:
            have = 0
            for k in ["A", "B", "C", "D", "E"]:
                if r.get(f"sol_{k}") or r.get(f"sol_{k}_image"):
                    have += 1
            if have == 5:
                options_full += 1
        print("\n--- Build Summary ---")
        print(f"Records: {total}")
        print(f"Problem statements non-empty: {ocr_nonempty}")
        print(f"Options complete (5/5 via text or image): {options_full}")
        print(f"Answers joined: {answers_present}")
        print(f"Multimodal (any images): {multimodal_true}")
        print(f"Needs review: {needs_review_true}")
        print(f"JSONL: {output_jsonl}")
        if report_html:
            print(f"Report: {report_html}")
    except Exception:
        pass


def _record_to_json(rec: DatasetRecord) -> dict:
    return {
        "id": rec.id,
        "year": rec.year,
        "group": rec.group,
        "points": rec.points,
        "problem_number": rec.problem_number,
        "problem_statement": rec.problem_statement,
        "sol_A": rec.sol_A,
        "sol_B": rec.sol_B,
        "sol_C": rec.sol_C,
        "sol_D": rec.sol_D,
        "sol_E": rec.sol_E,
        "sol_A_image": rec.sol_A_image,
        "sol_B_image": rec.sol_B_image,
        "sol_C_image": rec.sol_C_image,
        "sol_D_image": rec.sol_D_image,
        "sol_E_image": rec.sol_E_image,
        "associated_images": rec.associated_images,
        "language": rec.language,
        "multimodal": rec.multimodal,
        "answer": rec.answer,
        "provenance": {
            "pdf_path": rec.provenance.pdf_path,
            "pdf_sha256": rec.provenance.pdf_sha256,
            "text_boxes": [b.__dict__ for b in rec.provenance.text_boxes],
            "associated_images": [b.__dict__ for b in rec.provenance.associated_images],
            "image_options": {k: v.__dict__ for k, v in rec.provenance.image_options.items()},
            "dpi_used": rec.provenance.dpi_used,
            "renderer": rec.provenance.renderer,
            "ocr_engine": rec.provenance.ocr_engine,
            "annotation_version": rec.provenance.annotation_version,
        },
        "quality": rec.quality.__dict__,
    }
