from __future__ import annotations

import hashlib
import os
from typing import List, Optional, Tuple

import fitz
from PIL import Image, ImageDraw

from .config import RENDER
from .models import BBox


def pdf_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dpi_for_bbox(pt_w: float, pt_h: float) -> int:
    scale_w = RENDER.min_w_px / (pt_w * 1.0) / (1.0)
    scale_h = RENDER.min_h_px / (pt_h * 1.0) / (1.0)
    base = max(scale_w, scale_h, RENDER.min_dpi / 72.0)
    dpi = int(min(RENDER.max_dpi, max(RENDER.min_dpi, round(base * 72.0))))
    return dpi


def render_bbox(
    pdf_path: str,
    bbox: BBox,
    dpi: Optional[int] = None,
    mask_overlaps: Optional[List[BBox]] = None,
    grayscale: Optional[bool] = None,
    doc: Optional[fitz.Document] = None,
) -> Image.Image:
    _doc = None
    try:
        if doc is None:
            _doc = fitz.open(pdf_path)
            page = _doc.load_page(bbox.page_index)
        else:
            page = doc.load_page(bbox.page_index)
        rect = fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
        pt_w, pt_h = rect.width, rect.height
        use_dpi = dpi if dpi is not None else dpi_for_bbox(pt_w, pt_h)
        scale = use_dpi / 72.0
        mat = fitz.Matrix(scale, scale)
        pm = page.get_pixmap(matrix=mat, clip=rect, alpha=False, colorspace=fitz.csGRAY if (grayscale or RENDER.grayscale) else fitz.csRGB)
        img = Image.frombytes("L" if (grayscale or RENDER.grayscale) else "RGB", [pm.width, pm.height], pm.samples)
        img.info["dpi"] = (use_dpi, use_dpi)
    finally:
        if _doc is not None:
            _doc.close()

    # Apply polygonal mask if available on bbox
    if getattr(bbox, "points", None):
        mask = Image.new("L", img.size, 0)
        draw_poly = ImageDraw.Draw(mask)
        pts = []
        for x, y in bbox.points:  # type: ignore[attr-defined]
            sx = (x - bbox.x0) * scale
            sy = (y - bbox.y0) * scale
            pts.append((sx, sy))
        if len(pts) >= 3:
            draw_poly.polygon(pts, fill=255)
            white = 255 if img.mode == "L" else (255, 255, 255)
            bg = Image.new(img.mode, img.size, white)
            img = Image.composite(img, bg, mask)

    if mask_overlaps:
        draw = ImageDraw.Draw(img)
        white = 255 if img.mode == "L" else (255, 255, 255)
        for ob in mask_overlaps:
            if ob.page_index != bbox.page_index:
                continue
            # Prefer precise polygon masking when available
            if getattr(ob, "points", None):
                pts = []
                for x, y in ob.points:  # type: ignore[attr-defined]
                    sx = (x - bbox.x0) * scale
                    sy = (y - bbox.y0) * scale
                    pts.append((sx, sy))
                if len(pts) >= 3:
                    draw.polygon(pts, fill=white)
                    continue
            # Fallback to rectangular intersection mask
            rx0 = max(bbox.x0, ob.x0)
            ry0 = max(bbox.y0, ob.y0)
            rx1 = min(bbox.x1, ob.x1)
            ry1 = min(bbox.y1, ob.y1)
            if rx1 <= rx0 or ry1 <= ry0:
                continue
            sx = (rx0 - bbox.x0) * scale
            sy = (ry0 - bbox.y0) * scale
            ex = (rx1 - bbox.x0) * scale
            ey = (ry1 - bbox.y0) * scale
            draw.rectangle([sx, sy, ex, ey], fill=white)
    return img


def stack_vertical(images: List[Image.Image]) -> Image.Image:
    if not images:
        raise ValueError("No images to stack")
    widths = [im.width for im in images]
    max_w = max(widths)
    total_h = sum(im.height for im in images)
    mode = images[0].mode
    bg = 255 if mode == "L" else (255, 255, 255)
    canvas = Image.new(mode, (max_w, total_h), color=bg)
    y = 0
    for im in images:
        if im.width != max_w:
            im = im.resize((max_w, int(im.height * (max_w / im.width))), Image.BICUBIC)
        canvas.paste(im, (0, y))
        y += im.height
    return canvas


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
