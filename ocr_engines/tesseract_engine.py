from typing import List
from PIL import Image

try:
    import pytesseract
except ImportError:
    pytesseract = None


def recognise(img: Image.Image) -> List[str]:
    """Recognize text from PIL Image using pytesseract.
    
    Parameters
    ----------
    img : Image.Image
        PIL Image in RGB format
        
    Returns
    -------
    List[str]
        List of recognized text strings
        
    Raises
    ------
    ImportError
        If pytesseract is not available
    RuntimeError
        If OCR processing fails
    """
    if pytesseract is None:
        raise ImportError("pytesseract is not available. Install with: pip install pytesseract>=0.3.10")
    
    try:
        # Use pytesseract to extract text
        text = pytesseract.image_to_string(img, config='--psm 6')
        
        # Split into lines and filter out empty strings
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        return lines
        
    except Exception as e:
        raise RuntimeError(f"Tesseract OCR processing failed: {str(e)}")
