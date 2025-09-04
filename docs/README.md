# PDF Image Extraction Tool

A powerful interactive tool for extracting images from PDF files using polygon masks. This application provides a complete workflow from PDF viewing to mask creation, approval, and export.

## Quick Start

### Installation

1.  **Install Dependencies**
    ```bash
    uv pip install -r requirements.txt
    ```

2.  **Run the Application**
    ```bash
    uv run python app.py /path/to/pdf/directory
    ```

### Example Usage

```bash
# Process PDFs in the test_pdfs directory
python app.py test_pdfs

# Process PDFs in a custom directory
python app.py ~/Documents/my_pdfs
```

## Features

*   **Interactive PDF Viewing**: Navigate through multiple PDFs and pages with smooth rendering.
*   **Flexible Mask Creation**: Draw rectangular masks over PDF content, or automatically generate masks from vector graphics. Supports both image and question mask types.
*   **Automatic Option Label Detection**: Uses Tesseract OCR to automatically detect option labels (A-E) in image masks for multiple choice questions.
*   **Advanced Mask Editing**: Move, resize, delete, merge, split, expand, and add masks with visual feedback.
*   **Multi-page Question Support**: Define questions that span across multiple pages.
*   **Page Approval Workflow**: Systematic approval process for quality control.
*   **Batch Export**: Export all approved masks to PNG files with associated metadata.
*   **State Persistence**: All work is automatically saved and restored between sessions using companion JSON files.

## User Interface Overview

The application features a main window with:
*   **PDF List Panel** (Left): Lists all loaded PDFs and their approval status.
*   **Viewer Panel** (Center): Displays the current PDF page with navigation and zoom controls.
*   **Masks Panel** (Right): Lists all masks for the current page, allowing selection and management.
*   **Toolbar** (Top): Provides quick access to drawing tools, mask operations, and OCR functions.
*   **Metadata Dock** (Left): Allows editing PDF-level metadata and image mask option labels.
*   **Mask Properties Dock** (Right): Displays detailed properties of selected masks.

### Basic Navigation

*   **PDFs**: Select PDFs from the left panel or use `Ctrl + ↑`/`Ctrl + ↓`.
*   **Pages**: Navigate pages using `←`/`→` or `Page Up`/`Page Down`.
*   **Zoom**: Use the combined zoom button, "Fit to View", "Fit to Width", or `Ctrl + +`/`-`/`0`.

### Working with Masks

1.  **Creating**: Select a "Draw Image Region" or "Draw Question Region" tool, then click and drag on the PDF. Press `Enter`/`Space` to accept or `Escape` to discard. Masks can also be automatically generated.
2.  **Editing**: Select masks to move or resize them using handles.
3.  **Management**: Select masks in the viewer or list. Use `Delete`/`Backspace` to remove. Merge, split, expand, or add masks using toolbar actions or keyboard shortcuts.

## Automatic Option Label Detection

The tool includes OCR-based option label detection for multiple choice questions:
*   **Automatic Processing**: OCR runs automatically on unchecked image masks when a PDF is opened.
*   **Manual Trigger**: Use "Detect Option Labels" in the toolbar to manually re-run OCR.
*   **Customization**: Manually edit detected labels in the Metadata Panel.

## Export Process

All pages in a PDF must be approved before export. Click "Export All" to generate an `output/<pdf-name>/` directory containing individual PNG files for each mask and a `manifest.json` with complete metadata.

## Keyboard Shortcuts

| Action | Shortcut |
|---|---|
| **Navigation** | |
| Previous Page | `←` or `Page Up` |
| Next Page | `→` or `Page Down` |
| Previous PDF | `Ctrl + ↑` |
| Next PDF | `Ctrl + ↓` |
| **Zoom** | |
| Zoom In | `Ctrl + +` |
| Zoom Out | `Ctrl + -` |
| Fit to View | `Ctrl + 0` |
| **Mask Operations** | |
| Accept Mask | `Enter` or `Space` |
| Discard Mask | `Escape` |
| Delete Selected Mask | `Delete` or `Backspace` |
| Merge Selected Masks | `M` |
| Split Selected Mask | `S` |
| Expand Selected Mask | `E` |
| Associate Images with Question | `X` or `Ctrl + L` |
| Select All Masks | `Ctrl + A` |
| Add Selected Masks | `A` |
| **Workflow** | |
| Approve Current Page | `Ctrl + Enter` |
| Accept All Pages in PDF | `Ctrl + Shift + Enter` |
| **Application** | |
| Show Help | `F1` |
| Toggle Multi-page Question Mode | `Q` |

## File Structure and Data Storage

*   **State Files**: Each PDF has a companion `.json` file (e.g., `document.pdf.json`) storing mask definitions, approval status, and metadata.
*   **Export Structure**: Exported images and a `manifest.json` are saved in `output/<pdf-name>/`.

## Technical Details

The application is built with Python and PyQt6, leveraging PyMuPDF for PDF rendering and Pillow for image processing. Key modules include:
*   `app.py`: Main application entry point.
*   `gui.py`: Implements the graphical user interface and handles user interactions.
*   `storage.py`: Manages state persistence for PDFs and masks.
*   `export.py`: Handles the export of approved masks to image files.
*   `option_label_ocr.py`: Provides OCR functionality for option label detection using Tesseract.
*   `vector_bbox.py`: Detects and extracts bounding boxes from vector graphics.
*   `question_bbox.py`: Automatically detects question regions in PDFs.

## Troubleshooting

### Common Issues

*   **Missing Python packages**: Ensure all dependencies are installed via `pip install -r requirements.txt`.
*   **Tesseract OCR unavailable**: Install the Tesseract binary for your operating system (e.g., `brew install tesseract` on macOS, `sudo apt-get install tesseract-ocr` on Ubuntu/Debian) and then `pip install pytesseract`.
*   **"Cannot export: pages not approved"**: All pages in a PDF must be approved before export.
*   **PDF not rendering**: Verify the PDF is not corrupted or password-protected.

## Answer Key Verification

The repository includes scripts for answer key verification:
*   `extract_answer_keys.py`: Used to extract answer keys from PDFs, with an option for debug overlays (`--debug-overlays`).
*   `validate_results.py`: Summarizes counts and anomalies across extracted answer keys.

## License

This project is provided as-is for educational and research purposes.
