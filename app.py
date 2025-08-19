import sys
import os
from pathlib import Path
from typing import List, Tuple, Dict, Any
import argparse

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF is required. Install with: pip install PyMuPDF")
    sys.exit(1)

try:
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
except ImportError:
    print("Error: PyQt6 is required. Install with: pip install PyQt6")
    sys.exit(1)

from storage import ensure_state_exists
from gui import MainWindow

def get_pdf_files(directory: str) -> List[str]:
    """Get all PDF files in the specified directory.

    Parameters
    ----------
    directory : str
        Path to directory containing PDFs

    Returns
    -------
    List[str]
        List of PDF file paths
    """
    pdf_files = []
    directory_path = Path(directory)

    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    if not directory_path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {directory}")

    for file_path in directory_path.glob("*.pdf"):
        if file_path.is_file():
            pdf_files.append(str(file_path.absolute()))

    return sorted(pdf_files)

def get_page_count(pdf_path: str) -> int:
    """Get the number of pages in a PDF file.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file

    Returns
    -------
    int
        Number of pages in the PDF
    """
    try:
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        doc.close()
        return page_count
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
        return 0

def initialize_pdf_states(pdf_files: List[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """Initialize JSON states for all PDF files.

    Parameters
    ----------
    pdf_files : List[str]
        List of PDF file paths

    Returns
    -------
    List[Tuple[str, Dict[str, Any]]]
        List of (pdf_path, state) tuples
    """
    pdf_states = []

    for pdf_path in pdf_files:
        print(f"Processing: {os.path.basename(pdf_path)}")

        page_count = get_page_count(pdf_path)
        if page_count == 0:
            print(f"Skipping {pdf_path}: Could not read PDF or no pages found")
            continue

        state = ensure_state_exists(pdf_path, page_count)
        pdf_states.append((pdf_path, state))

        print(f"  Pages: {page_count}, State: {'Loaded' if os.path.exists(f'{pdf_path}.json') else 'Created'}")

    return pdf_states

def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(
        description="PDF Image Extraction Tool - Review and extract image regions from PDFs"
    )
    parser.add_argument(
        "pdf_directory",
        nargs='?',  # Makes the argument optional
        default=None, # Sets default to None if not provided
        help="Path to directory containing PDF files (optional)"
    )

    args = parser.parse_args()

    # Create QApplication instance early for GUI dialogs
    app = QApplication(sys.argv)

    try:
        # If no directory was provided via CLI, prompt the user to select one
        if args.pdf_directory is None:
            selected_dir = QFileDialog.getExistingDirectory(
                None,  # Parent widget (can be None if no main window yet)
                "Select Directory Containing PDF Files", # Dialog title
                os.getcwd()  # Starting directory for the dialog
            )
            if not selected_dir:  # User cancelled the dialog
                QMessageBox.information(None, "Information", "No directory selected. Application will now exit.")
                sys.exit(0)
            target_directory = selected_dir
        else:
            target_directory = args.pdf_directory

        # Process the target directory
        pdf_files = get_pdf_files(target_directory)

        if not pdf_files:
            QMessageBox.critical(None, "Error", f"No PDF files found in: {target_directory}")
            sys.exit(1)

        print(f"Found {len(pdf_files)} PDF file(s) in {target_directory}")

        pdf_states = initialize_pdf_states(pdf_files)

        if not pdf_states:
            QMessageBox.critical(None, "Error", "No valid PDF files could be processed")
            sys.exit(1)

        print(f"\nInitialized {len(pdf_states)} PDF file(s)")
        print("Starting GUI...")

        main_window = MainWindow(pdf_states)
        main_window.show()

        sys.exit(app.exec())

    except (FileNotFoundError, NotADirectoryError) as e:
        QMessageBox.critical(None, "Error", f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        QMessageBox.critical(None, "Unexpected Error", f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
