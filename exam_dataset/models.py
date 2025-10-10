from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class BBox:
    page_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    points: Optional[List[Tuple[float, float]]] = None


@dataclass
class QuestionUnit:
    exam_id: str
    question_id: str
    problem_number: str
    year: str
    group: str
    text_boxes: List[BBox]
    associated_images: List[BBox] = field(default_factory=list)
    image_options: Dict[str, BBox] = field(default_factory=dict)


@dataclass
class Provenance:
    pdf_path: str
    pdf_sha256: Optional[str]
    text_boxes: List[BBox]
    associated_images: List[BBox]
    image_options: Dict[str, BBox]
    dpi_used: Dict[str, int]
    renderer: str
    ocr_engine: str
    annotation_version: Optional[str] = None


@dataclass
class Quality:
    ocr_short_text: bool = False
    options_missing_or_extra: bool = False
    key_mismatch: bool = False
    answer_missing: bool = False
    needs_review: bool = False


@dataclass
class DatasetRecord:
    id: str
    year: str
    group: str
    points: int
    problem_number: str
    problem_statement: str
    sol_A: Optional[str]
    sol_B: Optional[str]
    sol_C: Optional[str]
    sol_D: Optional[str]
    sol_E: Optional[str]
    sol_A_image: Optional[str]
    sol_B_image: Optional[str]
    sol_C_image: Optional[str]
    sol_D_image: Optional[str]
    sol_E_image: Optional[str]
    associated_images: List[str]
    language: str
    multimodal: bool
    answer: Optional[str]
    provenance: Provenance
    quality: Quality
