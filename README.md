# PDF Image Extraction Tool

A powerful interactive tool for extracting images from PDF files using polygon masks. This application provides a complete **staged workflow** from PDF viewing to mask creation, association, OCR labeling, validation, approval, and export.

## Quick Start

### Installation

This project uses **uv** for dependency management. Install dependencies with:

```bash
uv sync
```

### Running the Application

```bash
uv run python app.py /path/to/pdf/directory
```

### Example Usage

```bash
# Process PDFs in the original_pdfs directory
uv run python app.py original_pdfs

# Process PDFs in a custom directory
uv run python app.py ~/Documents/my_pdfs
```

## Features

*   **Staged Workflow**: 6-stage guided workflow prevents data loss and ensures quality
*   **Interactive PDF Viewing**: Navigate through multiple PDFs and pages with smooth rendering
*   **Flexible Mask Creation**: Draw rectangular masks over PDF content, or automatically generate masks from vector graphics. Supports both image and question mask types
*   **Automatic Option Label Detection**: Uses Tesseract OCR to automatically detect option labels (A-E) in image masks for multiple choice questions (triggered in Stage 4)
*   **Advanced Mask Editing**: Move, resize, delete, merge, split, expand, and add masks with visual feedback via keyboard shortcuts
*   **Multi-page Question Support**: Define questions that span across multiple pages with dashed visual feedback
*   **Validation & Approval**: Robust validation checks before approval (floating images, unlabeled masks, unassociated questions)
*   **Batch Export**: Export all approved masks to PNG files with associated metadata
*   **State Persistence**: All work is automatically saved with atomic writes and backward-compatible migration

## Staged Workflow

The application enforces a **6-stage workflow** to ensure data quality and prevent accidental data loss:

### Stage 1: Image Regions
- **Draw or auto-compute image mask regions** (option graphics)
- Destructive operations available: "Recompute All Masks" from vector graphics
- **Tools**: Draw Image | Select
- **Keyboard**: M (merge), S (split), E (expand), A (add masks)

### Stage 2: Question Regions
- **Draw or auto-compute question masks** from text layout
- Multi-page question support with visual feedback
- Destructive: "Auto-Compute Q" replaces question masks
- **Tools**: Draw Question | Auto-Compute Q | Multi-page toggle
- **Keyboard**: Q (toggle multi-page), Enter (complete multi-page)

### Stage 3: Association
- **Associate image masks with question masks**
- Visual highlighting of associations
- **Tools**: Associate (X)
- **Keyboard**: X or Ctrl+L (associate selected)

### Stage 4: Option Labels
- **OCR runs automatically** on first entry to this stage
- Manually edit labels in Metadata Dock
- Verify all image masks have checked labels
- **Tools**: Detect Labels (force re-run)

### Stage 5: Validation
- **Automatic validation** checks:
  - No floating images (unassociated with questions)
  - No unlabeled images
  - No questions without images
- Approval blocked unless validation passes (or override)
- Validation status shown in page info label

### Stage 6: Approval
- **Approve pages** after validation passes
- Export requires all pages approved
- **Keyboard**: Ctrl+Enter (approve page), Ctrl+Shift+Enter (approve all)

## User Interface

### Main Window Layout
*   **PDF List Panel** (Left): All loaded PDFs with approval counts (✓ when complete)
*   **Viewer Panel** (Center): PDF page with zoom and navigation controls
*   **Masks Panel** (Right): Current page masks (I* = associated image, Q = question)
*   **Toolbar** (Top): Stage selector and stage-specific tools
*   **Metadata Dock** (Left): PDF metadata and option label editing
*   **Mask Properties Dock** (Right): Selected mask dimensions and properties

### Navigation
*   **PDFs**: Click in list or use `Ctrl + ↑`/`Ctrl + ↓`
*   **Pages**: `←`/`→` or `Page Up`/`Page Down`
*   **Zoom**: Combined zoom button, "Fit to View", "Fit to Width", or `Ctrl + +`/`-`/`0`

### Working with Masks
1.  **Creating**: Select draw tool, click and drag. Press `Enter`/`Space` to accept or `Escape` to discard
2.  **Editing**: Select and move/resize with handles. Use keyboard shortcuts for advanced operations
3.  **Deleting**: Select and press `Delete` or `Backspace`

## Automatic Option Label Detection

The tool includes Tesseract OCR-based option label detection for multiple choice questions:
*   **Stage 4 Trigger**: OCR runs automatically when first entering Stage 4 (Option Labels)
*   **Non-Overwrite**: Only processes unchecked image masks on first run
*   **Manual Re-run**: Use "Detect Labels" button to force re-run with overwrite confirmation
*   **Manual Editing**: Edit detected labels in the Metadata Dock; changes auto-mark as checked

## Export Process

**All pages** in a PDF must be approved (complete Stage 6) before export. Use **File → Export All** menu to generate:
- `output/<pdf-name>/` directory with PNG files for each mask
- `manifest.json` with complete metadata (bounding boxes, points, scale factors)

Export uses the same DPI (300) as the GUI for coordinate consistency.

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
| **Drawing & Editing** | |
| Accept Mask / Complete Multi-page | `Enter` or `Space` |
| Discard Mask | `Escape` |
| Delete Selected Mask(s) | `Delete` or `Backspace` |
| Select All Masks | `Ctrl + A` |
| **Mask Operations (Stage 1)** | |
| Merge Selected Masks | `M` |
| Split Selected Mask | `S` |
| Expand Selected Mask | `E` |
| Add Selected Masks | `A` |
| **Questions & Association** | |
| Toggle Multi-page Question | `Q` |
| Associate Images → Question | `X` or `Ctrl + L` |
| **Approval** | |
| Approve Current Page | `Ctrl + Enter` |
| Approve All Pages in PDF | `Ctrl + Shift + Enter` |
| **Application** | |
| Show Help | `F1` |

## File Structure and Data Storage

### State Files (JSON Sidecars)
Each PDF has a companion `.json` file (e.g., `document.pdf.json`) storing:
- Mask definitions (points, type, associations)
- Approval status per page
- Workflow stage per page
- Option labels and checked status
- PDF metadata (year, grade group)

**Automatic Migration**: Old state files are automatically migrated to new format:
- `question_id` → `question_group_id` for multi-page questions
- Backfills `workflow.stage` (defaults to stage 1)

### Export Structure
- `output/<pdf-name>/`: Directory with individual mask PNG crops
- `manifest.json`: Complete metadata with bounding boxes, scale factors, provenance

## Technical Details

Built with Python and PyQt6, leveraging PyMuPDF for PDF rendering and Pillow for image processing.

### Core Modules
*   `app.py`: Application entry point, initializes PDFs and launches GUI
*   `gui.py`: PyQt6 GUI with staged workflow, validation, and gating logic
*   `storage.py`: State persistence with automatic migration and atomic writes
*   `export.py`: Exports approved masks to PNG with coordinate scaling
*   `config.py`: Shared configuration (RENDER_DPI = 300)

### Feature Modules
*   `option_label_ocr.py`: Tesseract OCR for option label detection (A-E)
*   `vector_bbox.py`: Auto-detection of image regions from vector graphics
*   `question_bbox.py`: Auto-detection of question regions from text layout
*   `editable_mask.py`: Interactive polygon masks with handles and visual feedback

### Architecture Highlights
- **Stage Gating**: Actions enabled/disabled based on current workflow stage
- **Validation Pipeline**: Multi-level checks before approval (floating masks, labels, associations)
- **Backward Compatibility**: Automatic state file migration preserves existing work
- **Atomic Saves**: Temp file + rename pattern prevents corruption on crash

## Troubleshooting

### Common Issues

*   **Missing Python packages**: Run `uv sync` to install all dependencies
*   **Tesseract OCR unavailable**: Install Tesseract binary for your OS:
    - macOS: `brew install tesseract`
    - Ubuntu/Debian: `sudo apt-get install tesseract-ocr`
    - Windows: Download installer from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)
*   **"Cannot export: pages not approved"**: All pages must reach Stage 6 (Approval) before export
*   **"Approval Validation Failed"**: Check validation errors (floating images, unlabeled masks, etc.). You can override if needed
*   **"Stage Restriction" warnings**: Destructive operations are stage-gated to prevent data loss
*   **PDF not rendering**: Verify PDF is not corrupted or password-protected
*   **Masks not appearing**: Ensure you're in the correct stage and draw mode is active

## Additional Tools

### Answer Key Extraction
*   `extract_answer_keys.py`: Extracts answer keys from PDFs with optional debug overlays
    ```bash
    uv run python extract_answer_keys.py --debug-overlays
    ```
*   `validate_results.py`: Summarizes counts and anomalies across extracted answer keys
    ```bash
    uv run python validate_results.py
    ```

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
- `quality` (flags: `ocr_short_text`, `options_missing_or_extra`, `key_mismatch`, `answer_missing`, `needs_review`)

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
