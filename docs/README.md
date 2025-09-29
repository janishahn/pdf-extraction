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

## Dataset Builder CLI (exam_dataset)

This project includes a robust dataset builder that turns annotated Känguru PDFs into a structured JSONL dataset, an HTML report for quick QA, and an optional Parquet package with embedded images.

### What it does

- Renders polygon-accurate crops for:
  - Question text (with any overlapping image masks masked to white)
  - Option images (A–E)
  - Associated images (figures)
- Runs OCR on the question text crops (Mistral OCR by default).
- Parses options from OCR text, including inline tables and LaTeX.
- Joins answers from a yearly answer-key directory (or a single combined JSON).
- Emits:
  - JSONL: one record per question with text, image paths, provenance, quality flags
  - HTML report: “Needs Review” section and all items, with images and extracted text/options
  - Parquet (optional): a single file with all images embedded as PNG bytes

### Prerequisites

- Place the annotated PDFs and their companion JSONs in `original_pdfs/` (e.g., `YY_34.pdf` + `YY_34.pdf.json`).
- Optionally provide yearly answer keys under `answer_keys/` (files `YYYY.json` as produced by `extract_answer_keys.py`).
- For OCR, set `MISTRAL_API_KEY` in your `.env` at the project root.

### Commands

Build the dataset (OCR on):

```bash
uv run -q python -m exam_dataset.cli build \
  --answer-dir answer_keys \
  --ocr-batch-size 1 \
  --out output/dataset_builder/dataset/dataset.jsonl \
  --report output/dataset_builder/reports/report.html
```

Notes:
- `--ocr-batch-size` controls per-exam OCR concurrency. For free endpoints, smaller (1–5) is more reliable.
- To disable OCR: add `--no-ocr` (text will be empty; image-only questions are still supported).
- To use a single combined answer key JSON instead: pass `--answer-key path/to/combined.json` instead of `--answer-dir`.

Pack to Parquet with embedded images:

```bash
uv run -q python -m exam_dataset.cli pack \
  --jsonl output/dataset_builder/dataset/dataset.jsonl \
  --out output/dataset_builder/dataset/dataset.parquet
```

### Output structure

- JSONL record (fields):
  - `id`, `year`, `group`, `points`, `problem_number`, `problem_statement`, `language`, `multimodal`, `answer`
  - `sol_A..sol_E` (text), `sol_A_image..sol_E_image` (paths), `associated_images` (paths)
  - `provenance` (pdf path/hash, BBoxes, DPI map, renderer, OCR engine)
  - `quality` (flags: `ocr_short_text`, `options_missing_or_extra`, `key_mismatch`, `needs_review`)

- Report HTML:
  - “Needs Review” section (first), then “All Items”
  - Each item shows question crop, extracted text, extracted options (text/images), associated images, badges

- Parquet file:
  - Same core fields as JSONL
  - Binary columns for images: `question_image`, `sol_A_image_bin..sol_E_image_bin`, and `associated_images_bin` (list<binary>)

### Quality and performance

- OCR retries: builder retries a small number of empty OCR results per exam.
- Progress bars: a single global bar updates as OCR batches complete.
- Reuse: keeps one HTTP session for OCR and one open PDF (fitz.Document) per exam for speed.


## Review Web App (FastAPI)

Use the browser-based review tool to quickly fix OCR text, answers, and image associations. Edits are saved to an overlay file (`output/dataset_builder/dataset/edits.json`) and applied non-destructively when exporting.

### Quick start (uv)

- Build the dataset and report:
  - `uv run -q python -m exam_dataset.cli build --report`
- Run the review server and open it:
  - `uv run -q python -m exam_dataset.cli review --open-browser`
  - Defaults:
    - JSONL: `output/dataset_builder/dataset/dataset.jsonl`
    - Edits: If not provided, derived from the JSONL name as `<stem>.edits.json` in the same folder
    - Crops: `output/dataset_builder/crops/`
- Apply edits via the web UI:
  - Click “Apply Edits” in the header (optionally tick “only reviewed”).
  - A merged file is created next to the loaded JSONL, named `<stem>.edited.jsonl` (e.g., `dataset_full.edited.jsonl`), and offered as a download.
- Or apply edits via CLI:
  - `uv run -q python -m exam_dataset.cli apply-edits --in output/dataset_builder/dataset/dataset.jsonl --edits output/dataset_builder/dataset/edits.json --out output/dataset_builder/dataset/dataset.edited.jsonl [--only-reviewed]`

### What you can edit

- Problem: `problem_statement`, `problem_number`, `points`, `language`.
- Options (A–E):
  - Text: edit; leaving blank removes it in the overlay.
  - Image: paste a path, click “Use candidate” (suggested crop), or “Clear” to remove.
- Associated images: manage a newline-separated list; use “Associate From Candidates” to replace/append from detected crops; “Clear All” removes all.
- Answer: set A–E or clear.
- Quality: toggle flags; “Save + Mark Reviewed” clears `needs_review`.
- Annotator integration: “Open in Annotator” launches the PyQt tool for precise bbox/image fixes (re-run build afterwards).

Notes:
- Year/group come from the source annotations/filenames and typically shouldn’t be changed here.
- Provenance and bounding boxes are read-only in the web app; use the annotator for these.

### Regenerating crops after mask edits

If you adjust masks in the annotator:
- Rebuild: `uv run -q python -m exam_dataset.cli build --report`
- In the review app, click “Reload Data”; then re-apply edits if needed using “Apply Edits”.

## License

This project is provided as-is for educational and research purposes.
