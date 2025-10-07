import json
import io
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF is required. Install with: pip install PyMuPDF")
    raise

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    raise

from storage import load_state
from config import RENDER_DPI


def compute_bounding_box(points: List[List[float]]) -> Tuple[float, float, float, float]:
    """Compute bounding box from a list of points.
    
    Parameters
    ----------
    points : List[List[float]]
        List of [x, y] coordinate pairs
        
    Returns
    -------
    Tuple[float, float, float, float]
        Bounding box as (min_x, min_y, max_x, max_y)
    """
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    
    x_coords = [p[0] for p in points]
    y_coords = [p[1] for p in points]
    
    return (min(x_coords), min(y_coords), max(x_coords), max(y_coords))


def render_page_at_dpi(pdf_path: str, page_index: int, dpi: int = 300) -> Optional[Image.Image]:
    """Render a PDF page to PIL Image at specified DPI.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
    page_index : int
        Zero-based page index
    dpi : int, optional
        Rendering DPI (default: 300)
        
    Returns
    -------
    Optional[Image.Image]
        Rendered page as PIL Image, None if error occurred
    """
    try:
        doc = fitz.open(pdf_path)
        
        if doc.needs_pass:
            doc.close()
            print(f"PDF {pdf_path} is password protected")
            return None
        
        if doc.is_closed:
            doc.close()
            print(f"PDF {pdf_path} appears to be corrupted")
            return None
        
        if page_index < 0 or page_index >= len(doc):
            doc.close()
            print(f"Page index {page_index} out of range for {pdf_path}")
            return None
        
        page = doc[page_index]
        
        # Calculate zoom factor for desired DPI
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page to pixmap
        pix = page.get_pixmap(matrix=mat)
        
        # Convert to PIL Image
        img_data = pix.tobytes("ppm")
        pil_image = Image.open(io.BytesIO(img_data))
        
        doc.close()
        return pil_image
        
    except Exception as e:
        print(f"Error rendering page {page_index} from {pdf_path}: {e}")
        return None


def crop_image_with_mask(image: Image.Image, points: List[List[float]]) -> Image.Image:
    """Crop image using mask bounding box.
    
    Parameters
    ----------
    image : Image.Image
        Source PIL Image
    points : List[List[float]]
        List of [x, y] coordinate pairs defining the mask
        
    Returns
    -------
    Image.Image
        Cropped PIL Image
    """
    bbox = compute_bounding_box(points)
    min_x, min_y, max_x, max_y = bbox
    
    # Ensure coordinates are within image bounds
    width, height = image.size
    min_x = max(0, int(min_x))
    min_y = max(0, int(min_y))
    max_x = min(width, int(max_x))
    max_y = min(height, int(max_y))
    
    # Crop the image
    return image.crop((min_x, min_y, max_x, max_y))


def check_all_pages_approved(pdf_path: str) -> Tuple[bool, List[int]]:
    """Check if all pages in a PDF are approved.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
        
    Returns
    -------
    Tuple[bool, List[int]]
        (all_approved, list_of_unapproved_page_numbers)
    """
    state = load_state(pdf_path)
    if not state:
        return False, []
    
    unapproved_pages = []
    
    for page_num_str, page_data in state.get("pages", {}).items():
        if not page_data.get("approved", False):
            unapproved_pages.append(int(page_num_str))
    
    return len(unapproved_pages) == 0, unapproved_pages


def export_all(pdf_path: str, dpi: int = 300) -> Dict[str, Any]:
    """Export all approved masks from a PDF to PNG files and create manifest.
    
    This is the main export function that implements Phase 5 requirements:
    1. Load JSON state and confirm all pages have approved = True
    2. For each approved page and each mask:
       - Re-render at DPI
       - Compute bounding box from mask's point list
       - Crop the image and save PNG to output/<pdf-stem>/page-<n>-mask-<id>.png
    3. Generate output/<pdf-stem>/manifest.json
    4. Error reporting if any page wasn't approved
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
    dpi : int, optional
        Rendering DPI for export (default: 300)
        
    Returns
    -------
    Dict[str, Any]
        Export results with success status and details
        
    Raises
    ------
    ValueError
        If any pages are not approved or state cannot be loaded
    """
    
    # Load state
    state = load_state(pdf_path)
    if not state:
        raise ValueError(f"Could not load state for PDF: {pdf_path}")
    
    # Check if all pages are approved
    all_approved, unapproved_pages = check_all_pages_approved(pdf_path)
    if not all_approved:
        unapproved_list = ", ".join(map(str, sorted(unapproved_pages)))
        raise ValueError(f"Cannot export: The following pages are not approved: {unapproved_list}. "
                        f"Please approve all pages before exporting.")
    
    # Create output directory
    pdf_stem = Path(pdf_path).stem
    output_dir = Path("output") / pdf_stem
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize manifest
    manifest = {
        "pdf_path": pdf_path,
        "pdf_stem": pdf_stem,
        "export_dpi": dpi,
        "total_pages": state.get("page_count", 0),
        "total_masks": 0,
        "exported_masks": []
    }
    
    total_exported = 0
    
    # GUI render DPI (from gui.py render_page function)
    gui_render_dpi = float(RENDER_DPI)
    scale_factor = dpi / gui_render_dpi
    
    # Process each page
    for page_num_str, page_data in state.get("pages", {}).items():
        page_num = int(page_num_str)
        page_index = page_num - 1  # Convert to 0-based index
        
        # Skip if page not approved (should not happen due to earlier check)
        if not page_data.get("approved", False):
            continue
        
        masks = page_data.get("masks", [])
        if not masks:
            continue
        
        # Render page at export DPI
        page_image = render_page_at_dpi(pdf_path, page_index, dpi)
        if page_image is None:
            print(f"Warning: Could not render page {page_num}, skipping masks")
            continue
        
        # Process each mask on this page
        for mask_data in masks:
            mask_id = mask_data.get("id", "unknown")
            original_points = mask_data.get("points", [])
            
            if not original_points:
                print(f"Warning: Mask {mask_id} has no points, skipping")
                continue
            
            try:
                # Scale points to match export DPI
                scaled_points = [[p[0] * scale_factor, p[1] * scale_factor] for p in original_points]
                
                # Compute bounding box using scaled points
                bbox = compute_bounding_box(scaled_points)
                
                # Crop image using scaled mask points
                cropped_image = crop_image_with_mask(page_image, scaled_points)
                
                # Generate PNG filename
                png_filename = f"page-{page_num}-mask-{mask_id}.png"
                png_path = output_dir / png_filename
                
                # Save PNG
                cropped_image.save(png_path, "PNG")
                
                # Add to manifest (store original points for reference)
                manifest["exported_masks"].append({
                    "page": page_num,
                    "mask_id": mask_id,
                    "type": mask_data.get("type", "image"),
                    "bbox": list(bbox),
                    "points": original_points,
                    "scaled_points": scaled_points,
                    "scale_factor": scale_factor,
                    "png_path": str(png_path)
                })
                
                total_exported += 1
                
            except Exception as e:
                print(f"Error exporting mask {mask_id} from page {page_num}: {e}")
                continue
    
    manifest["total_masks"] = total_exported
    
    # Save manifest
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    return {
        "success": True,
        "pdf_path": pdf_path,
        "output_directory": str(output_dir),
        "manifest_path": str(manifest_path),
        "total_masks_exported": total_exported,
        "manifest": manifest
    }


def get_approved_masks(pdf_path: str) -> List[Dict[str, Any]]:
    """Get all approved masks from a PDF's state.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
        
    Returns
    -------
    List[Dict[str, Any]]
        List of approved mask objects with metadata
    """
    state = load_state(pdf_path)
    if not state:
        return []
    
    approved_masks = []
    
    for page_num_str, page_data in state.get("pages", {}).items():
        if not page_data.get("approved", False):
            continue
        
        page_number = int(page_num_str)
        
        for mask in page_data.get("masks", []):
            mask_with_metadata = mask.copy()
            mask_with_metadata["pdf_path"] = pdf_path
            mask_with_metadata["page_number"] = page_number
            approved_masks.append(mask_with_metadata)
    
    return approved_masks


def export_masks(pdf_paths: List[str], output_dir: str) -> Dict[str, Any]:
    """Export approved masks to PNG files and create manifest.
    
    Parameters
    ----------
    pdf_paths : List[str]
        List of PDF file paths to process
    output_dir : str
        Directory to save exported images and manifest
        
    Returns
    -------
    Dict[str, Any]
        Export manifest with metadata
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        "export_info": {
            "total_pdfs": len(pdf_paths),
            "total_masks": 0,
            "output_directory": str(output_path.absolute())
        },
        "exported_masks": []
    }
    
    for pdf_path in pdf_paths:
        approved_masks = get_approved_masks(pdf_path)
        manifest["export_info"]["total_masks"] += len(approved_masks)
        
        for mask in approved_masks:
            manifest["exported_masks"].append({
                "pdf_path": mask["pdf_path"],
                "page_number": mask["page_number"],
                "mask_id": mask.get("id", "unknown"),
                "bbox": mask.get("bbox", []),
                "points": mask.get("points", []),
                "png_path": "TODO: implement PNG export"
            })
    
    manifest_path = output_path / "export_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    return manifest


def export_single_pdf(pdf_path: str, output_dir: str) -> Dict[str, Any]:
    """Export approved masks from a single PDF.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
    output_dir : str
        Directory to save exported images
        
    Returns
    -------
    Dict[str, Any]
        Export results for the PDF
    """
    return export_masks([pdf_path], output_dir)
