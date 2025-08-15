import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def get_json_path(pdf_path: str) -> str:
    """Get the JSON sidecar file path for a given PDF."""
    return f"{pdf_path}.json"


def get_pdf_page_count(pdf_path: str) -> int:
    """Get the number of pages in a PDF file.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
        
    Returns
    -------
    int
        Number of pages in the PDF
        
    Raises
    ------
    RuntimeError
        If PyMuPDF is not available or PDF cannot be read
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF is required but not available")
    
    try:
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        doc.close()
        return page_count
    except Exception as e:
        raise RuntimeError(f"Error reading PDF {pdf_path}: {e}")


def create_initial_state(pdf_path: str, page_count: int) -> Dict[str, Any]:
    """Create initial JSON state for a PDF file.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
    page_count : int
        Number of pages in the PDF
        
    Returns
    -------
    Dict[str, Any]
        Initial state dictionary
    """
    # Try to extract minimal PDF metadata from the filename
    pdf_metadata = extract_pdf_metadata_from_filename(pdf_path)

    return {
        "page_count": page_count,
        "pages": {
            str(i + 1): {
                "approved": False,
                "masks": []
            }
            for i in range(page_count)
        },
        **({"pdf_metadata": pdf_metadata} if pdf_metadata else {})
    }


def migrate_old_state_format(old_state: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate old state format (list-based pages) to new format (dict-based pages).
    
    Parameters
    ----------
    old_state : Dict[str, Any]
        Old state dictionary with pages as a list
        
    Returns
    -------
    Dict[str, Any]
        New state dictionary with pages as a dict
    """
    if isinstance(old_state.get("pages"), dict):
        return old_state
    
    if not isinstance(old_state.get("pages"), list):
        raise ValueError("Invalid state format: pages must be list or dict")
    
    new_pages = {}
    for page in old_state["pages"]:
        page_num = str(page["page_number"])
        new_pages[page_num] = {
            "approved": page["approved"],
            "masks": []
        }
        for mask in page.get("masks", []):
            new_mask = mask.copy()
            # Ensure backward compatibility – default to image type if missing
            if "type" not in new_mask:
                new_mask["type"] = "image"
            new_pages[page_num]["masks"].append(new_mask)
    
    return {
        "page_count": old_state["page_count"],
        "pages": new_pages
    }


def load_state(pdf_path: str) -> Dict[str, Any]:
    """Load JSON state for a PDF file.
    
    If the JSON file exists, loads and returns it.
    Otherwise, queries the PDF for its page count and builds a fresh state object.
    Automatically migrates old format to new format if needed.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
        
    Returns
    -------
    Dict[str, Any]
        State dictionary
        
    Raises
    ------
    RuntimeError
        If PDF cannot be read when JSON doesn't exist
    """
    json_path = get_json_path(pdf_path)
    
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
                migrated_state = migrate_old_state_format(state)

                # Ensure top-level pdf_metadata exists and is minimally populated
                if "pdf_metadata" not in migrated_state:
                    meta = extract_pdf_metadata_from_filename(pdf_path)
                    if meta:
                        migrated_state["pdf_metadata"] = meta

                # Backfill image mask fields if missing (non-destructive)
                for p_data in migrated_state.get("pages", {}).values():
                    for m in p_data.get("masks", []):
                        m_type = m.get("type", "image")
                        if m_type == "image":
                            if "option_label" not in m:
                                m["option_label"] = ""
                            if "option_label_checked" not in m:
                                m["option_label_checked"] = False

                if migrated_state != state:
                    save_state(pdf_path, migrated_state)
                return migrated_state
        except (json.JSONDecodeError, IOError, ValueError):
            pass
    
    page_count = get_pdf_page_count(pdf_path)
    return create_initial_state(pdf_path, page_count)


def save_state(pdf_path: str, state: Dict[str, Any]) -> bool:
    """Save JSON state for a PDF file using atomic writes.
    
    Uses atomic writes (write to temp + rename) to avoid corrupt files on crash.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
    state : Dict[str, Any]
        State dictionary to save
        
    Returns
    -------
    bool
        True if successful, False otherwise
    """
    json_path = get_json_path(pdf_path)
    
    try:
        json_dir = os.path.dirname(json_path)
        with tempfile.NamedTemporaryFile(
            mode='w', 
            encoding='utf-8', 
            dir=json_dir, 
            delete=False,
            suffix='.tmp'
        ) as temp_file:
            json.dump(state, temp_file, indent=2, ensure_ascii=False)
            temp_path = temp_file.name
        
        os.rename(temp_path, json_path)
        return True
    except (IOError, OSError):
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        return False


def ensure_state_exists(pdf_path: str, page_count: int) -> Dict[str, Any]:
    """Ensure JSON state exists for a PDF, create if necessary.
    
    Parameters
    ----------
    pdf_path : str
        Path to the PDF file
    page_count : int
        Number of pages in the PDF (ignored, kept for compatibility)
        
    Returns
    -------
    Dict[str, Any]
        Loaded or newly created state dictionary
    """
    return load_state(pdf_path)


def create_mask(points: List[List[float]], mask_type: str = "image", associated_image_ids: Optional[List[str]] = None, question_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a new mask with a unique ID and metadata.
    
    Parameters
    ----------
    points : List[List[float]]
        List of [x, y] coordinate pairs defining the mask
    mask_type : str, optional
        Semantic type of the mask ("image" or "question"), by default "image"
    associated_image_ids : Optional[List[str]], optional
        List of image‐mask IDs associated with the question mask. Only relevant if mask_type == "question".
    question_id : Optional[str], optional
        Identifier for grouping multiple masks into a single question mask
    
    Returns
    -------
    Dict[str, Any]
        Mask dictionary with id, type, points and optional associations
    """
    mask: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "type": mask_type,
        "points": points,
    }
    # If a grouping/question identifier is provided, store it. This allows
    # representing questions that span multiple pages while keeping each
    # drawn polygon as an individual mask.
    if question_id is not None:
        mask["question_id"] = question_id
    if mask_type == "question":
        mask["associated_image_ids"] = associated_image_ids or []
    else:
        # Default framework fields for image masks
        if "option_label" not in mask:
            mask["option_label"] = ""
        if "option_label_checked" not in mask:
            mask["option_label_checked"] = False
    return mask


def add_mask_to_page(state: Dict[str, Any], page_num: int, points: List[List[float]], mask_type: str = "image", associated_image_ids: Optional[List[str]] = None, question_id: Optional[str] = None) -> str:
    """Add a mask to a specific page.
    
    Parameters
    ----------
    state : Dict[str, Any]
        State dictionary
    page_num : int
        Page number (1-based)
    points : List[List[float]]
        List of [x, y] coordinate pairs defining the mask
    mask_type : str, optional
        Semantic type of the mask ("image" or "question"), by default "image"
    associated_image_ids : Optional[List[str]], optional
        List of associated image mask IDs when creating a question mask
    question_id : Optional[str], optional
        Identifier for grouping multiple masks into a single question mask
    
    Returns
    -------
    str
        The UUID of the created mask
    """
    page_key = str(page_num)
    if page_key not in state["pages"]:
        raise ValueError(f"Page {page_num} does not exist in state")
    
    mask = create_mask(points, mask_type, associated_image_ids, question_id)
    state["pages"][page_key]["masks"].append(mask)
    return mask["id"]


def remove_mask_from_page(state: Dict[str, Any], page_num: int, mask_id: str) -> bool:
    """Remove a mask from a specific page.
    
    Parameters
    ----------
    state : Dict[str, Any]
        State dictionary
    page_num : int
        Page number (1-based)
    mask_id : str
        UUID of the mask to remove
        
    Returns
    -------
    bool
        True if mask was found and removed, False otherwise
    """
    page_key = str(page_num)
    if page_key not in state["pages"]:
        return False
    
    masks = state["pages"][page_key]["masks"]
    for i, mask in enumerate(masks):
        if mask["id"] == mask_id:
            masks.pop(i)
            return True
    
    return False


def ensure_page_exists(state: Dict[str, Any], page_num: int) -> None:
    """Ensure a page exists in the state dictionary.
    
    Parameters
    ----------
    state : Dict[str, Any]
        State dictionary
    page_num : int
        Page number (1-based)
    """
    page_key = str(page_num)
    if page_key not in state["pages"]:
        state["pages"][page_key] = {
            "approved": False,
            "masks": []
        }


def approve_page(state: Dict[str, Any], page_num: int) -> None:
    """Mark a page as approved.
    
    Parameters
    ----------
    state : Dict[str, Any]
        State dictionary
    page_num : int
        Page number (1-based)
        
    Raises
    ------
    ValueError
        If page does not exist
    """
    page_key = str(page_num)
    if page_key not in state["pages"]:
        raise ValueError(f"Page {page_num} does not exist in state")
    
    state["pages"][page_key]["approved"] = True


def unapprove_page(state: Dict[str, Any], page_num: int) -> None:
    """Mark a page as not approved.
    
    Parameters
    ----------
    state : Dict[str, Any]
        State dictionary
    page_num : int
        Page number (1-based)
        
    Raises
    ------
    ValueError
        If page does not exist
    """
    page_key = str(page_num)
    if page_key not in state["pages"]:
        raise ValueError(f"Page {page_num} does not exist in state")
    
    state["pages"][page_key]["approved"] = False


def extract_pdf_metadata_from_filename(pdf_path: str) -> Optional[Dict[str, Any]]:
    """Extract minimal PDF metadata (year, grade_group) from filename.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys 'year' (int) and 'grade_group' (str, e.g., '5-6'), or None if parse fails.
    """
    try:
        basename = os.path.basename(pdf_path)
        stem = os.path.splitext(basename)[0]
        parts = stem.split("_")
        if len(parts) < 2:
            return None
        yy = parts[0]
        grade_code = parts[1]

        if not yy.isdigit():
            return None
        year_ending = int(yy)
        # Heuristic: map 90-99 to 1900s, others to 2000s
        year = 1900 + year_ending if year_ending >= 90 else 2000 + year_ending

        grade_map = {
            "34": "3-4",
            "56": "5-6",
            "78": "7-8",
            "910": "9-10",
            "1113": "11-13",
        }
        grade_group = grade_map.get(grade_code)
        if not grade_group:
            return None

        return {"year": year, "grade_group": grade_group}
    except Exception:
        return None
