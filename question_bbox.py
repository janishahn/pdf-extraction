from typing import List, Tuple

import fitz


def _find_enumeration_indices(lines: List[Tuple[float, float, float, float]],
                             max_enum_width: float,
                             left_margin_max: float,
                             min_height: float,
                             top_min_y: float) -> List[int]:
    """Return indices in lines that look like question enumeration markers.

    Parameters
    ----------
    lines : List[Tuple[float, float, float, float]]
        Line bounding boxes in PDF point coordinates, sorted by ascending y.
    max_enum_width : float
        Maximum width of the first span/line to be treated as an enumeration marker.
    left_margin_max : float
        Maximum left x-coordinate to still count as being within the left margin.
    min_height : float
        Minimum line height to filter out tiny artefacts.
    top_min_y : float
        Minimum y (from top) a marker must have to not be considered part of the header.

    Returns
    -------
    List[int]
        Indices of lines that match the enumeration marker heuristic.
    """
    indices: List[int] = []
    for idx, (x0, y0, x1, y1) in enumerate(lines):
        if y0 < top_min_y:
            continue
        if (x1 - x0) <= max_enum_width and x0 <= left_margin_max and (y1 - y0) >= min_height:
            indices.append(idx)
    return indices


def get_page_question_boxes(
    pdf_path: str,
    page_index: int,
    dpi: int = 300,
    *,
    max_enum_width: float = 60.0,
    left_margin_max: float = 90.0,
    line_gap_threshold: float = 6.0,
    min_height: float = 8.0,
    top_margin_ratio: float = 0.05,
) -> List[Tuple[float, float, float, float]]:
    """Return bounding boxes for individual questions on a page.

    The improved algorithm looks for *enumeration markers*—short text fragments
    placed near the left margin (such as "A1", "A2", "7.", "10" …).  Those
    markers delineate the beginning of each question.  Using their vertical
    positions we group all subsequent text lines until the next enumeration
    marker (or the end of the page).  Finally, for every group we compute a
    rectangular bounding box which is returned in *dpi* coordinates.

    If no enumeration markers can be detected, the function automatically
    falls back to a simple paragraph-based grouping similar to the previous
    implementation.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.
    page_index : int
        Zero-based page index.
    dpi : int, optional
        Target DPI for output coordinates, by default 300.
    max_enum_width : float, optional
        Maximum width (in PDF points) of a first-span to be considered an enumeration marker.
    left_margin_max : float, optional
        Maximum left x (in PDF points) for a marker to be considered near the left margin.
    line_gap_threshold : float, optional
        Threshold (in PDF points) to group adjacent lines when no markers are found.
    min_height : float, optional
        Minimum height (in PDF points) to consider a line as valid text (filters artefacts).
    top_margin_ratio : float, optional
        Fraction of page height considered as top header area to ignore when detecting
        enumeration markers (helps avoid treating header page numbers as questions). Default 0.03.

    Returns
    -------
    List[Tuple[float, float, float, float]]
        A list of bounding boxes (x0, y0, x1, y1) in DPI coordinates for detected questions.
    """
    doc = fitz.open(pdf_path)
    try:
        if page_index >= len(doc):
            return []

        page = doc[page_index]
        text_dict = page.get_text("dict")
        scale = dpi / 72.0  # convert from PDF points → requested dpi
        page_rect = page.rect
        top_min_y = page_rect.y0 + top_margin_ratio * page_rect.height

        # Collect all text line bounding boxes
        lines: List[Tuple[float, float, float, float, float, str]] = []
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue  # skip non-text blocks
            for line in block.get("lines", []):
                # Bounding box of the whole line
                lx0, ly0, lx1, ly1 = line["bbox"]
                if (ly1 - ly0) < min_height:
                    continue

                # Bounding box of the first span (usually the enumeration marker or first word)
                span_bbox = None
                first_text = ""
                spans = line.get("spans", [])
                if spans:
                    span_bbox = spans[0].get("bbox")
                    first_text = spans[0].get("text", "")

                lines.append((lx0, ly0, lx1, ly1, span_bbox, first_text))

        if not lines:
            return []

        # Sort lines by their vertical position (top-to-bottom)
        lines.sort(key=lambda b: b[1])

        # Helper to access line bbox without span
        def line_bbox(idx):
            return lines[idx][0:4]

        # Build enumeration indices using first-span geometry when available
        enum_indices: List[int] = []
        for idx, line in enumerate(lines):
            span_bbox = line[4]
            if span_bbox is None:
                continue
            sx0, sy0, sx1, sy1 = span_bbox
            # Exclude header markers within the top margin
            if sy0 < top_min_y:
                continue
            if (sx1 - sx0) <= max_enum_width and sx0 <= left_margin_max and (sy1 - sy0) >= min_height:
                first_text = line[5] if len(line) > 5 else ""
                if first_text.startswith("("):
                    # Skip answer choice line
                    continue
                enum_indices.append(idx)

        if not enum_indices:
            # fallback try whole-line metrics
            enum_indices = _find_enumeration_indices(
                [l[:4] for l in lines],
                max_enum_width,
                left_margin_max,
                min_height,
                top_min_y,
            )

        if not enum_indices:
            # --- fallback: simple vertical gap grouping (legacy behaviour) ---
            groups: List[List[Tuple[float, float, float, float]]] = []
            current: List[Tuple[float, float, float, float]] = []
            prev_y1 = None
            for idx, l in enumerate(lines):
                x0, y0, x1, y1 = l[:4]
                if prev_y1 is None or (y0 - prev_y1) <= line_gap_threshold:
                    current.append((x0, y0, x1, y1))
                else:
                    if current:
                        groups.append(current)
                    current = [(x0, y0, x1, y1)]
                prev_y1 = y1
            if current:
                groups.append(current)

            boxes: List[Tuple[float, float, float, float]] = []
            for grp in groups:
                gx0 = min(b[0] for b in grp) * scale
                gy0 = min(b[1] for b in grp) * scale
                gx1 = max(b[2] for b in grp) * scale
                gy1 = max(b[3] for b in grp) * scale
                boxes.append((gx0, gy0, gx1, gy1))
            return boxes

        # --- enumeration-based grouping ---
        enum_indices.append(len(lines))  # sentinel for the last question
        boxes: List[Tuple[float, float, float, float]] = []
        for i in range(len(enum_indices) - 1):
            start = enum_indices[i]
            end = enum_indices[i + 1]  # exclusive
            group_lines = [line_bbox(j) for j in range(start, end)]
            if not group_lines:
                continue
            gx0 = min(b[0] for b in group_lines) * scale
            gy0 = min(b[1] for b in group_lines) * scale
            gx1 = max(b[2] for b in group_lines) * scale
            gy1 = max(b[3] for b in group_lines) * scale
            boxes.append((gx0, gy0, gx1, gy1))

        return boxes
    finally:
        doc.close() 