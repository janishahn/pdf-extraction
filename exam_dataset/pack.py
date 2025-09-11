from __future__ import annotations

import io
import json
import os
from typing import List, Optional

from PIL import Image
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm
from .config import PATHS


def _read_image_bytes(path: Optional[str]) -> Optional[bytes]:
    if not path:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None


def pack_jsonl_to_parquet(jsonl_path: str, out_path: str, limit: Optional[int] = None) -> None:
    """Pack dataset JSONL into a Parquet file with embedded image bytes.

    Columns include core fields, option texts, binary columns for images, and list<binary> for associated images.
    """
    ids: List[str] = []
    years: List[str] = []
    groups: List[str] = []
    points: List[int] = []
    problem_numbers: List[str] = []
    statements: List[str] = []
    answers: List[Optional[str]] = []
    multimodal: List[bool] = []
    sol_A: List[Optional[str]] = []
    sol_B: List[Optional[str]] = []
    sol_C: List[Optional[str]] = []
    sol_D: List[Optional[str]] = []
    sol_E: List[Optional[str]] = []
    qimg: List[Optional[bytes]] = []
    oA: List[Optional[bytes]] = []
    oB: List[Optional[bytes]] = []
    oC: List[Optional[bytes]] = []
    oD: List[Optional[bytes]] = []
    oE: List[Optional[bytes]] = []
    assoc_bins: List[List[bytes]] = []

    # Count total lines for progress bar
    with open(jsonl_path, "r", encoding="utf-8") as f:
        total_lines = sum(1 for line in f if line.strip())
    
    if limit:
        total_lines = min(total_lines, limit)

    with open(jsonl_path, "r", encoding="utf-8") as f:
        pbar = tqdm(total=total_lines, desc="Packing dataset", unit="entries")
        processed = 0
        
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            ids.append(str(obj.get("id")))
            years.append(str(obj.get("year")))
            groups.append(str(obj.get("group")))
            points.append(int(obj.get("points", 0) or 0))
            problem_numbers.append(str(obj.get("problem_number") or ""))
            statements.append(str(obj.get("problem_statement") or ""))
            answers.append(obj.get("answer"))
            multimodal.append(bool(obj.get("multimodal", False)))
            sol_A.append(obj.get("sol_A"))
            sol_B.append(obj.get("sol_B"))
            sol_C.append(obj.get("sol_C"))
            sol_D.append(obj.get("sol_D"))
            sol_E.append(obj.get("sol_E"))

            q_path = os.path.join(PATHS.crops, "question", f"{obj.get('id')}.png")
            qimg.append(_read_image_bytes(q_path))

            def opt(letter: str) -> Optional[bytes]:
                return _read_image_bytes(obj.get(f"sol_{letter}_image"))

            oA.append(opt("A"))
            oB.append(opt("B"))
            oC.append(opt("C"))
            oD.append(opt("D"))
            oE.append(opt("E"))

            abins: List[bytes] = []
            for p in obj.get("associated_images") or []:
                b = _read_image_bytes(p)
                if b:
                    abins.append(b)
            assoc_bins.append(abins)

            processed += 1
            pbar.update(1)
            
            if limit and processed >= int(limit):
                break
        
        pbar.close()

    table = pa.table(
        {
            "id": pa.array(ids, type=pa.string()),
            "year": pa.array(years, type=pa.string()),
            "group": pa.array(groups, type=pa.string()),
            "points": pa.array(points, type=pa.int32()),
            "problem_number": pa.array(problem_numbers, type=pa.string()),
            "problem_statement": pa.array(statements, type=pa.string()),
            "answer": pa.array(answers, type=pa.string()),
            "multimodal": pa.array(multimodal, type=pa.bool_()),
            "sol_A": pa.array(sol_A, type=pa.string()),
            "sol_B": pa.array(sol_B, type=pa.string()),
            "sol_C": pa.array(sol_C, type=pa.string()),
            "sol_D": pa.array(sol_D, type=pa.string()),
            "sol_E": pa.array(sol_E, type=pa.string()),
            "question_image": pa.array(qimg, type=pa.binary()),
            "sol_A_image_bin": pa.array(oA, type=pa.binary()),
            "sol_B_image_bin": pa.array(oB, type=pa.binary()),
            "sol_C_image_bin": pa.array(oC, type=pa.binary()),
            "sol_D_image_bin": pa.array(oD, type=pa.binary()),
            "sol_E_image_bin": pa.array(oE, type=pa.binary()),
            "associated_images_bin": pa.array(assoc_bins, type=pa.list_(pa.binary())),
        }
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    pq.write_table(table, out_path, compression="zstd")


__all__ = ["pack_jsonl_to_parquet"]
