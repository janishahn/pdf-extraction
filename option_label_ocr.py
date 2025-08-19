from typing import List, Dict, Any, Callable, Optional, NewType
import re
import io
from PIL import Image
import numpy as np
from enum import Enum

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from ocr_engines import tesseract_engine
except ImportError:
    tesseract_engine = None

# Type alias for mask IDs
MaskID = NewType("MaskID", str)

# OCR Backend enum - only Tesseract supported
class OCRBackend(str, Enum):
    TESSERACT = "tesseract"

# Global active backend
_active_backend: OCRBackend = OCRBackend.TESSERACT

# ----------------------------------------------------------------------
# Backend selection API
# ----------------------------------------------------------------------
def set_backend(backend: OCRBackend) -> None:
    """Set the active OCR backend.
    
    Parameters
    ----------
    backend : OCRBackend
        The OCR backend to use (must be TESSERACT)
        
    Raises
    ------
    ValueError
        If backend is not TESSERACT
    """
    global _active_backend
    if backend != OCRBackend.TESSERACT:
        raise ValueError(f"Only {OCRBackend.TESSERACT} backend is supported")
    _active_backend = backend

def get_backend() -> OCRBackend:
    """Get the currently active OCR backend.
    
    Returns
    -------
    OCRBackend
        The currently active OCR backend (always TESSERACT)
    """
    return _active_backend

def _ensure_tesseract_available() -> None:
    """Ensure Tesseract is available and raise if not.
    
    Raises
    ------
    OCRUnavailableError
        If Tesseract is not available
    """
    if tesseract_engine is None:
        raise OCRUnavailableError("pytesseract is not available. Install with: pip install pytesseract>=0.3.10")

def _run_ocr_engine(img: np.ndarray) -> List[str]:
    """Run OCR on image using Tesseract.
    
    Parameters
    ----------
    img : np.ndarray
        Image array in RGB format
        
    Returns
    -------
    List[str]
        List of recognized text strings
        
    Raises
    ------
    OCRUnavailableError
        If Tesseract is not available
    """
    _ensure_tesseract_available()
    
    try:
        # Convert numpy array to PIL Image
        pil_img = Image.fromarray(img)
        return tesseract_engine.recognise(pil_img)
    except Exception as e:
        print(f"Tesseract OCR failed: {e}")
        return []

# ----------------------------------------------------------------------
# OCR availability helpers
# ----------------------------------------------------------------------
class OCRUnavailableError(RuntimeError):
    """Raised when Tesseract or its dependencies are not available."""
    pass

_ocr_available_cache: Optional[tuple[bool, str]] = None

def is_available(force_refresh: bool = False) -> tuple[bool, str]:
    """Check whether Tesseract and its runtime dependencies are usable.

    Parameters
    ----------
    force_refresh : bool, optional
        If True, re-probe even if cached result exists, by default False

    Returns
    -------
    tuple[bool, str]
        (True, "") if OCR can be used, otherwise (False, error_message)
    """
    global _ocr_available_cache
    if _ocr_available_cache is not None and not force_refresh:
        return _ocr_available_cache
    
    try:
        # Ensure pytesseract and the tesseract binary are available
        try:
            import pytesseract as _pyt
        except ModuleNotFoundError as e:
            _ocr_available_cache = (False, f"Module not found: {e.name}")
        else:
            try:
                # This will raise if the tesseract binary isn't available or is misconfigured
                _ = _pyt.get_tesseract_version()
                _ocr_available_cache = (True, "")
            except Exception as e:
                _ocr_available_cache = (False, f"Tesseract binary not available or failed: {str(e)}")

    except Exception as e:
        # Catch-all for unexpected probe errors
        _ocr_available_cache = (False, f"OCR availability probe failed: {str(e)}")
    
    return _ocr_available_cache

def _sanitize_bbox(page, bbox: List[float], zoom: float) -> Optional[Any]:
    """Sanitize bounding box to ensure valid dimensions for rendering.
    
    Parameters
    ----------
    page : fitz.Page
        PDF page object
    bbox : List[float]
        Bounding box as [x0, y0, x1, y1] in PDF coordinates
    zoom : float
        Zoom factor for rendering
        
    Returns
    -------
    Optional[fitz.Rect]
        Sanitized rectangle with valid dimensions, or None if mask is too small
    """
    x0, y0, x1, y1 = bbox
    
    # Ensure correct ordering
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    
    # Calculate original center and dimensions
    center_x = (x0 + x1) / 2
    center_y = (y0 + y1) / 2
    width = x1 - x0
    height = y1 - y0
    
    # Minimum size in PDF points (4 pt ≈ 1/16 inch → ~16 px at 300 dpi)
    min_pdf_size = 4.0
    
    # Expand to minimum size if needed
    if width < min_pdf_size:
        width = min_pdf_size
    if height < min_pdf_size:
        height = min_pdf_size
    
    # Recalculate bbox from center and expanded dimensions
    x0 = center_x - width / 2
    x1 = center_x + width / 2
    y0 = center_y - height / 2
    y1 = center_y + height / 2
    
    # Clamp to page boundaries
    page_rect = page.rect
    x0 = max(x0, page_rect.x0)
    y0 = max(y0, page_rect.y0)
    x1 = min(x1, page_rect.x1)
    y1 = min(y1, page_rect.y1)
    
    # Check if bbox is completely outside page or has zero area after clamping
    if x0 >= x1 or y0 >= y1:
        return None
    
    # Final device-space check - ensure at least 1 pixel
    dev_width = (x1 - x0) * zoom
    dev_height = (y1 - y0) * zoom
    
    if dev_width < 1.0 or dev_height < 1.0:
        return None
    
    return fitz.Rect(x0, y0, x1, y1)

def _extract_pixmap(page, bbox: List[float], dpi: int = 300) -> Image.Image:
    """Extract a cropped image from a PDF page at the specified bounding box.
    
    Parameters
    ----------
    page : fitz.Page
        PDF page object (already opened)
    bbox : List[float]
        Bounding box as [x0, y0, x1, y1] in PDF coordinates
    dpi : int, optional
        Rendering DPI, by default 300
        
    Returns
    -------
    Image.Image
        PIL Image of the cropped region
        
    Raises
    ------
    RuntimeError
        If page cannot be rendered
    """
    if fitz is None:
        raise ImportError("PyMuPDF is required but not available")
    
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        
        # Sanitize and create clip rectangle from bbox
        clip_rect = _sanitize_bbox(page, bbox, zoom)
        
        # Check if sanitized bbox is valid (None means mask is too small)
        if clip_rect is None:
            raise ValueError("Mask is too small to render reliably")
        
        # Additional safety check
        if clip_rect.width <= 0 or clip_rect.height <= 0:
            raise ValueError("Bounding box results in zero or negative dimensions")
        
        # Render the clipped region
        pix = page.get_pixmap(matrix=mat, clip=clip_rect)
        
        # Convert to PIL Image
        img_data = pix.tobytes("ppm")
        pil_image = Image.open(io.BytesIO(img_data))
        
        return pil_image
        
    except Exception as e:
        raise RuntimeError(f"Error extracting image from PDF: {e}")

def _detect_letter(texts: List[str]) -> str:
    """Detect option letter (A-E) from OCR text results.
    
    Parameters
    ----------
    texts : List[str]
        List of recognized text strings from OCR
        
    Returns
    -------
    str
        Detected letter (A-E) or empty string if none found
    """
    pattern = re.compile(r'\(([A-E])\)')
    
    for text in texts:
        match = pattern.search(text)
        if match:
            return match.group(1)
    
    return ""

def _process_single_mask(page, mask_data: Dict[str, Any], overwrite: bool, dpi: int = 300) -> tuple[MaskID, str, bool]:
    """Process a single mask for option label detection.
    
    Parameters
    ----------
    page : fitz.Page
        PDF page object (already opened)
    mask_data : Dict[str, Any]
        Mask data dictionary
    overwrite : bool
        Whether to overwrite existing labels
    dpi : int, optional
        Rendering DPI, by default 300
        
    Returns
    -------
    tuple[MaskID, str, bool]
        (mask_id, detected_label, was_processed)
    """
    mask_id = MaskID(mask_data["id"])
    
    # Skip if already checked and not overwriting
    if mask_data.get("option_label_checked", False) and not overwrite:
        return mask_id, mask_data.get("option_label", ""), False
    
    # Calculate bounding box from points
    points = mask_data["points"]
    x_coords = [p[0] for p in points]
    y_coords = [p[1] for p in points]
    
    # Convert from device pixels (300 DPI) to PDF points
    # Mask points are stored in device pixel coordinates from GUI rendering at 300 DPI
    # Convert back to PDF points using: pdf_points = device_pixels / (dpi / 72)
    zoom_factor = dpi / 72.0
    pdf_x_coords = [x / zoom_factor for x in x_coords]
    pdf_y_coords = [y / zoom_factor for y in y_coords]
    
    bbox = [min(pdf_x_coords), min(pdf_y_coords), max(pdf_x_coords), max(pdf_y_coords)]
    
    try:
        # Extract image from PDF
        pil_image = _extract_pixmap(page, bbox, dpi)
        
        # Convert to RGB to avoid palette/mode issues
        pil_image = pil_image.convert("RGB")
        
        # Convert PIL image to numpy array for OCR
        img_array = np.array(pil_image)
        
        # Run OCR using Tesseract
        try:
            texts = _run_ocr_engine(img_array)
        except Exception as ocr_error:
            print(f"OCR processing failed for mask {mask_id}: {ocr_error}")
            return mask_id, "", True
        
        # Detect option letter
        detected_label = _detect_letter(texts)
        
        return mask_id, detected_label, True
        
    except Exception as e:
        print(f"Error processing mask {mask_id}: {e}")
        return mask_id, "", True  # Mark as checked even if failed

def process_pdf(pdf_path: str, state: Dict[str, Any], overwrite: bool = False, 
                progress_callback: Optional[Callable[[int, int], None]] = None, 
                dpi: int = 300) -> bool:
    """Process all image masks in a PDF for option label detection.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
    state : Dict[str, Any]
        PDF state dictionary
    overwrite : bool, optional
        Whether to overwrite existing option labels, by default False
    progress_callback : Optional[Callable[[int, int], None]], optional
        Progress callback function (current, total), by default None
        
    Returns
    -------
    bool
        True if any masks were processed or modified, False otherwise
    """
    ok, err = is_available()
    if not ok:
        raise OCRUnavailableError(err)
    
    # Collect all image masks that need processing
    masks_to_process = []
    
    for page_key, page_data in state.get("pages", {}).items():
        page_idx = int(page_key) - 1  # Convert to zero-based
        
        for mask_data in page_data.get("masks", []):
            if mask_data.get("type", "image") == "image":
                # Skip if already checked and not overwriting
                if not overwrite and mask_data.get("option_label_checked", False):
                    continue
                
                masks_to_process.append((page_idx, mask_data, page_key))
    
    if not masks_to_process:
        return False
    
    total_masks = len(masks_to_process)
    processed_count = 0
    any_changed = False
    any_processed = False
    
    if fitz is None:
        raise ImportError("PyMuPDF is required but not available")
    
    # Open PDF document once and keep it open for all processing
    doc = fitz.open(pdf_path)
    try:
        # Group masks by page for efficient processing
        pages_cache = {}
        
        # Process masks sequentially to avoid PyMuPDF thread safety issues
        for page_idx, mask_data, page_key in masks_to_process:
            try:
                # Get page object (cache pages to avoid repeated access)
                if page_idx not in pages_cache:
                    if page_idx < 0 or page_idx >= len(doc):
                        raise ValueError(f"Page index {page_idx} out of range")
                    pages_cache[page_idx] = doc[page_idx]
                
                page = pages_cache[page_idx]
                mask_id, detected_label, was_processed = _process_single_mask(page, mask_data, overwrite, dpi)
                
                if was_processed:
                    any_processed = True
                    # Update mask data
                    old_label = mask_data.get("option_label", "")
                    mask_data["option_label"] = detected_label
                    mask_data["option_label_checked"] = True
                    
                    if old_label != detected_label:
                        any_changed = True
                
                processed_count += 1
                
                if progress_callback:
                    progress_callback(processed_count, total_masks)
                    
            except Exception as e:
                print(f"Error processing mask: {e}")
                processed_count += 1
                
                if progress_callback:
                    progress_callback(processed_count, total_masks)
    
    finally:
        # Always close the document
        doc.close()
    
    # Return True if any mask was processed or changed to ensure persistence
    return any_changed or any_processed
