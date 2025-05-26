from typing import List, Tuple, Optional
import fitz


def get_page_vector_boxes(pdf_path: str, page_index: int, dpi: int = 300, merge_tolerance: float = 10.0, max_area_ratio: float = 0.8, padding: float = 6.0) -> List[Tuple[float, float, float, float]]:
    """
    Extract and cluster vector graphics bounding boxes from a PDF page, scaled to match rendered DPI.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
    page_index : int
        Zero-based page index
    dpi : int, optional
        Target DPI for coordinate scaling to match rendered image, by default 300
    merge_tolerance : float, optional
        Distance tolerance for merging nearby bounding boxes, by default 10.0
    max_area_ratio : float, optional
        Maximum ratio of page area a bounding box can cover before being filtered out, by default 0.8
    padding : float, optional
        Padding in pixels to add around each detected bounding box, by default 3.0
        
    Returns
    -------
    List[Tuple[float, float, float, float]]
        List of bounding boxes as (x0, y0, x1, y1) tuples, scaled to match rendered DPI with padding applied
    """
    try:
        doc = fitz.open(pdf_path)
        if page_index >= len(doc):
            doc.close()
            return []
            
        page = doc[page_index]
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        
        # Calculate scaling factor to match rendered DPI
        # PyMuPDF native coordinates are at 72 DPI
        scale_factor = dpi / 72.0
        
        drawings = page.get_drawings()
        doc.close()
        
        if not drawings:
            return []
            
        raw_boxes = []
        for drawing in drawings:
            if 'rect' in drawing:
                rect = drawing['rect']
                # Scale coordinates to match rendered DPI
                scaled_box = (
                    rect.x0 * scale_factor,
                    rect.y0 * scale_factor,
                    rect.x1 * scale_factor,
                    rect.y1 * scale_factor
                )
                raw_boxes.append(scaled_box)
        
        if not raw_boxes:
            return []
            
        # Scale tolerance to match DPI
        scaled_tolerance = merge_tolerance * scale_factor
        clustered_boxes = _cluster_boxes(raw_boxes, scaled_tolerance)
        
        # Filter based on scaled page area
        scaled_page_area = page_area * (scale_factor ** 2)
        filtered_boxes = []
        for box in clustered_boxes:
            x0, y0, x1, y1 = box
            box_area = (x1 - x0) * (y1 - y0)
            if box_area / scaled_page_area <= max_area_ratio:
                filtered_boxes.append(box)
        
        # Apply padding to final filtered boxes
        padded_boxes = []
        for x0, y0, x1, y1 in filtered_boxes:
            padded_box = (
                max(0, x0 - padding),  # Ensure we don't go below 0
                max(0, y0 - padding),  # Ensure we don't go below 0
                x1 + padding,
                y1 + padding
            )
            padded_boxes.append(padded_box)
                
        return padded_boxes
        
    except Exception:
        return []


def _cluster_boxes(boxes: List[Tuple[float, float, float, float]], tolerance: float) -> List[Tuple[float, float, float, float]]:
    """
    Cluster nearby bounding boxes by iteratively merging overlapping expanded boxes.
    
    Parameters
    ----------
    boxes : List[Tuple[float, float, float, float]]
        List of bounding boxes as (x0, y0, x1, y1) tuples
    tolerance : float
        Distance tolerance for merging
        
    Returns
    -------
    List[Tuple[float, float, float, float]]
        List of clustered bounding boxes
    """
    if not boxes:
        return []
        
    clusters = [list(box) for box in boxes]
    
    changed = True
    while changed:
        changed = False
        new_clusters = []
        used = set()
        
        for i, box1 in enumerate(clusters):
            if i in used:
                continue
                
            merged_box = box1[:]
            used.add(i)
            
            for j, box2 in enumerate(clusters):
                if j in used or i == j:
                    continue
                    
                if _boxes_should_merge(merged_box, box2, tolerance):
                    merged_box = _merge_boxes(merged_box, box2)
                    used.add(j)
                    changed = True
                    
            new_clusters.append(tuple(merged_box))
            
        clusters = new_clusters
        
    return clusters


def _boxes_should_merge(box1: List[float], box2: List[float], tolerance: float) -> bool:
    """
    Check if two bounding boxes should be merged based on tolerance.
    
    Parameters
    ----------
    box1 : List[float]
        First bounding box as [x0, y0, x1, y1]
    box2 : List[float]
        Second bounding box as [x0, y0, x1, y1]
    tolerance : float
        Distance tolerance for merging
        
    Returns
    -------
    bool
        True if boxes should be merged
    """
    expanded1 = [
        box1[0] - tolerance,
        box1[1] - tolerance,
        box1[2] + tolerance,
        box1[3] + tolerance
    ]
    
    expanded2 = [
        box2[0] - tolerance,
        box2[1] - tolerance,
        box2[2] + tolerance,
        box2[3] + tolerance
    ]
    
    return not (expanded1[2] < expanded2[0] or expanded2[2] < expanded1[0] or 
                expanded1[3] < expanded2[1] or expanded2[3] < expanded1[1])


def _merge_boxes(box1: List[float], box2: List[float]) -> List[float]:
    """
    Merge two bounding boxes into their union.
    
    Parameters
    ----------
    box1 : List[float]
        First bounding box as [x0, y0, x1, y1]
    box2 : List[float]
        Second bounding box as [x0, y0, x1, y1]
        
    Returns
    -------
    List[float]
        Merged bounding box as [x0, y0, x1, y1]
    """
    return [
        min(box1[0], box2[0]),
        min(box1[1], box2[1]),
        max(box1[2], box2[2]),
        max(box1[3], box2[3])
    ]
