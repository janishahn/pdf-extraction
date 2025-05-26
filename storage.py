import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional

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
    return {
        "page_count": page_count,
        "pages": {
            str(i + 1): {
                "approved": False,
                "masks": []
            }
            for i in range(page_count)
        }
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
            "masks": page.get("masks", [])
        }
    
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


def create_mask(points: List[List[float]]) -> Dict[str, Any]:
    """Create a new mask with a unique ID.
    
    Parameters
    ----------
    points : List[List[float]]
        List of [x, y] coordinate pairs defining the mask
        
    Returns
    -------
    Dict[str, Any]
        Mask dictionary with id and points
    """
    return {
        "id": str(uuid.uuid4()),
        "points": points
    }


def add_mask_to_page(state: Dict[str, Any], page_num: int, points: List[List[float]]) -> str:
    """Add a mask to a specific page.
    
    Parameters
    ----------
    state : Dict[str, Any]
        State dictionary
    page_num : int
        Page number (1-based)
    points : List[List[float]]
        List of [x, y] coordinate pairs defining the mask
        
    Returns
    -------
    str
        The UUID of the created mask
    """
    page_key = str(page_num)
    if page_key not in state["pages"]:
        raise ValueError(f"Page {page_num} does not exist in state")
    
    mask = create_mask(points)
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
