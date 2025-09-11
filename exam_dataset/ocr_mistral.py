from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Optional

import requests

from .config import OCR

# Load environment variables from a .env file if available
try:  # optional dependency, handled via pyproject
    from dotenv import load_dotenv, find_dotenv  # type: ignore

    _HAVE_DOTENV = True
except Exception:  # pragma: no cover - optional
    load_dotenv = None  # type: ignore
    find_dotenv = None  # type: ignore
    _HAVE_DOTENV = False


@dataclass
class OcrResult:
    text: str
    model: str
    raw: Optional[dict]


class MistralOCR:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        if _HAVE_DOTENV and load_dotenv and find_dotenv:
            load_dotenv(find_dotenv(), override=False)

        self.api_key = api_key or os.environ.get(OCR.api_key_env)
        self.model = model or OCR.model
        if not self.api_key:
            raise RuntimeError("Mistral API key not set in environment")
        # Reuse a single HTTP session with connection pooling
        self.session = requests.Session()
        try:
            adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=0)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
        except Exception:
            pass

    def _guess_mime_and_type(self, path: str) -> tuple[str, str]:
        ext = os.path.splitext(path)[1].lower()
        if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".avif"}:
            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
                ".avif": "image/avif",
            }.get(ext, "image/png")
            return mime, "image_url"
        if ext == ".pdf":
            return "application/pdf", "document_url"
        return "image/png", "image_url"

    def _extract_text_from_response(self, data: dict) -> str:
        pages = data.get("pages") if isinstance(data, dict) else None
        if isinstance(pages, list):
            parts = []
            for p in pages:
                md = p.get("markdown") if isinstance(p, dict) else None
                if md:
                    parts.append(md)
            if parts:
                return "\n\n".join(parts).strip()
        if isinstance(data, dict) and isinstance(data.get("output"), str):
            return data.get("output", "").strip()
        return ""

    def ocr_image(self, image_path: str) -> OcrResult:
        """Run Mistral Document AI OCR on an image/PDF and return plain text."""
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")

        mime, url_key = self._guess_mime_and_type(image_path)
        data_url = f"data:{mime};base64,{b64}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "document": {
                "type": url_key,
                url_key: data_url,
            },
            "include_image_base64": False,
        }

        url = "https://api.mistral.ai/v1/ocr"

        last_err: Optional[Exception] = None
        for attempt in range(OCR.retry_limit + 1):
            try:
                resp = self.session.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                text = self._extract_text_from_response(data)
                if text or attempt == OCR.retry_limit:
                    return OcrResult(text=text, model=self.model, raw=data if isinstance(data, dict) else None)
            except Exception as e:
                last_err = e
                if attempt == OCR.retry_limit:
                    raise
            time.sleep(1.5 * (attempt + 1))

        raise last_err if last_err else RuntimeError("OCR failed with no further details")
