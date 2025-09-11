from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Paths:
    root: str = os.getcwd()
    original_pdfs: str = os.path.join(root, "original_pdfs")
    base_output: str = os.path.join(root, "output", "dataset_builder")
    crops: str = os.path.join(base_output, "crops")
    ocr: str = os.path.join(base_output, "ocr")
    dataset: str = os.path.join(base_output, "dataset")
    reports: str = os.path.join(base_output, "reports")


@dataclass(frozen=True)
class RenderConfig:
    min_w_px: int = 1200
    min_h_px: int = 600
    min_dpi: int = 300
    max_dpi: int = 600
    grayscale: bool = True


@dataclass(frozen=True)
class OcrConfig:
    provider: str = "mistral"
    api_key_env: str = "MISTRAL_API_KEY"
    model: str = "mistral-ocr-latest"
    temperature: float = 0.0
    retry_limit: int = 2


PATHS = Paths()
RENDER = RenderConfig()
OCR = OcrConfig()
