# PDF Image Extraction Tool

A powerful interactive tool for extracting images from PDF files using polygon masks. This application provides a complete workflow from PDF viewing to mask creation, approval, and export.

## Quick Start

### Installation

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Application**
   ```bash
   python app.py /path/to/pdf/directory
   ```

### Example Usage

```bash
# Process PDFs in the test_pdfs directory
python app.py test_pdfs

# Process PDFs in a custom directory
python app.py ~/Documents/my_pdfs
```

## Features

- **Interactive PDF Viewing**: Navigate through multiple PDFs and pages with smooth rendering
- **Rectangle Mask Creation**: Draw rectangular masks over PDF content using drag-and-drop, or automatically generate masks from vector graphics
- **Mask Editing**: Move, resize using edge handles, and delete masks with visual feedback
- **Page Approval Workflow**: Systematic approval process for quality control
- **Batch Export**: Export all approved masks to PNG files with metadata
- **State Persistence**: All work is automatically saved and restored between sessions

## User Interface Guide

### Main Window Layout

The application window consists of four main areas:

1. **PDF List Panel** (Left): Shows all loaded PDFs with approval status
2. **Viewer Panel** (Center): Displays the current PDF page with navigation controls
3. **Mask Panel** (Right): Lists all masks for the current page
4. **Toolbar** (Top): Quick access to common actions

### Navigation Controls

#### PDF Navigation
- **Mouse**: Click any PDF in the left panel to switch to it
- **Keyboard**: 
  - `Ctrl + ↑` - Previous PDF
  - `Ctrl + ↓` - Next PDF

#### Page Navigation
- **Keyboard**:
  - `←` or `Page Up` - Previous page
  - `→` or `Page Down` - Next page

#### Zoom Controls
- **Combined Zoom Button**: Split button with zoom out (left) and zoom in (right) functionality
- **Keyboard**:
  - `Ctrl + +` - Zoom in
  - `Ctrl + -` - Zoom out
  - `Ctrl + 0` - Fit to view
- **Mouse**: Scroll wheel with Ctrl held down (planned feature)

### Working with Masks

#### Creating Masks
1. Click "Draw Rectangle Mask" in the toolbar.
2. Click and drag on the PDF page to draw a rectangle.
3. Release the mouse button to complete the rectangle.
4. Press **Enter** or **Space** to accept the mask, or **Escape** to discard it.
5. Masks can also be automatically generated using the "Recompute Masks" button.

#### Editing Masks
1. Ensure "Select/Move" mode is active (default).
2. Click on any mask to select it.
3. Drag the mask to move it.
4. Drag the small circular handles on the edges of a selected mask to resize it.
5. Use the mask panel or keyboard shortcuts to delete masks.

#### Mask Management
- **Selection**: Click masks in the viewer or mask list to select them. Multi-selection is supported using `Ctrl` + click.
- **Deletion**: Select masks and press `Delete` or `Backspace`, or right-click masks in the list and choose "Delete Selected Mask(s)".
- **Visual Feedback**: Masks highlight when hovered over.

### Page Approval Workflow

1. **Review**: Examine the page and create/edit masks as needed
2. **Approve**: Click "Approve Page" or press `Ctrl + Enter`
3. **Auto-Navigation**: The tool automatically moves to the next unapproved page
4. **Status Tracking**: PDF list shows approval progress (e.g., "✓ document.pdf (3/5)")
5. **Bulk Approval**: Click "Accept All Pages" to approve all pages in the current PDF.

### Export Process

1. **Prerequisite**: All pages in a PDF must be approved before export
2. **Trigger**: Click "Export All" in the toolbar
3. **Output**: Creates `output/<pdf-name>/` directory with:
   - Individual PNG files for each mask
   - `manifest.json` with complete metadata

## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| **Navigation** |
| Previous Page | `←` or `Page Up` |
| Next Page | `→` or `Page Down` |
| Previous PDF | `Ctrl + ↑` |
| Next PDF | `Ctrl + ↓` |
| **Zoom** |
| Zoom In | `Ctrl + +` |
| Zoom Out | `Ctrl + -` |
| Fit to View | `Ctrl + 0` |
| **Workflow** |
| Accept Mask | `Enter` |
| Delete Selected Mask | `Delete` or `Backspace` |
| Merge Selected Masks | `M` |
| Split Selected Mask | `S` |
| Approve Current Page | `Ctrl + Enter` |
| Accept All Pages in PDF | `Ctrl + Shift + Enter` |
| Show Help | `F1` |

## File Structure and Data Storage

### State Files

Each PDF gets a companion `.json` file that stores:
- Page count and navigation state
- Mask definitions with coordinates
- Approval status for each page
- Metadata and timestamps

**Example**: `document.pdf` → `document.pdf.json`

### Export Structure

```
output/
└── document_name/
    ├── manifest.json
    ├── page-1-mask-abc123.png
    ├── page-1-mask-def456.png
    └── page-2-mask-ghi789.png
```

## JSON Schema Reference

### State File Schema (`*.pdf.json`)

```json
{
  "page_count": 5,
  "pages": {
    "1": {
      "approved": true,
      "masks": [
        {
          "id": "unique-mask-id",
          "points": [[x1, y1], [x2, y2], [x3, y3], ...],
          "created_at": "2024-01-01T12:00:00Z"
        }
      ]
    }
  },
  "created_at": "2024-01-01T12:00:00Z",
  "updated_at": "2024-01-01T12:30:00Z"
}
```

### Export Manifest Schema (`manifest.json`)

```json
{
  "pdf_path": "path/to/source.pdf",
  "pdf_stem": "source",
  "export_dpi": 300,
  "total_pages": 5,
  "total_masks": 12,
  "exported_masks": [
    {
      "page": 1,
      "mask_id": "unique-mask-id",
      "bbox": [x_min, y_min, x_max, y_max],
      "points": [[x1, y1], [x2, y2], ...],
      "png_path": "output/source/page-1-mask-unique-mask-id.png"
    }
  ]
}
```

## Technical Details

### Dependencies

- **PyQt6**: Modern GUI framework
- **PyMuPDF (fitz)**: PDF rendering and processing
- **Pillow**: Image processing and export
- **Python 3.8+**: Core runtime

### Core Modules

- `app.py`: Main application entry point, handles PDF loading and GUI initialization.
- `gui.py`: Implements the main graphical user interface, including PDF viewer, navigation, and mask management.
- `editable_mask.py`: Defines interactive `QGraphicsItem` subclasses for drawing and resizing masks within the GUI.
- `storage.py`: Manages the persistence of application state, including mask data and page approval status, using JSON sidecar files.
- `export.py`: Handles the export of approved masks to image files and generates manifest files.
- `vector_bbox.py`: Provides functionality for automatic detection and extraction of bounding boxes from vector graphics in PDFs.

### Performance Considerations

- **Rendering**: Pages are rendered at 300 DPI for both viewing and export to maintain consistency and quality.
- **Memory**: Large PDFs are processed page-by-page to minimize memory usage.
- **Storage**: State files use efficient JSON format with minimal overhead.

### Error Handling

- **Corrupted PDFs**: Automatically skipped with console warnings.
- **Password-protected PDFs**: Detected and skipped with user notification.
- **Missing files**: Graceful degradation with error messages.
- **Export errors**: Detailed error reporting with recovery suggestions.

## Troubleshooting

### Common Issues

**"No module named 'PyMuPDF'"**
```bash
pip install PyMuPDF
```

**"No module named 'Pillow'"**
```bash
pip install Pillow
```

**"Cannot export: pages not approved"**
- Ensure all pages in the PDF are approved before attempting export
- Check the PDF list for approval status indicators

**PDF not rendering**
- Verify the PDF is not corrupted or password-protected
- Check console output for specific error messages

### Performance Tips

- **Large PDFs**: Process in smaller batches for better responsiveness
- **Memory usage**: Close and reopen the application periodically for very large datasets
- **Export speed**: Lower DPI settings export faster but with reduced quality

## Development

### Project Structure

```
pdf-extraction/
├── app.py              # Main application entry point
├── editable_mask.py    # Interactive mask drawing and resizing
├── export.py           # Export functionality and image processing
├── gui.py              # GUI components and main window
├── requirements.txt    # Python dependencies
├── storage.py          # State management and persistence
├── vector_bbox.py      # Automatic vector graphics bounding box detection
├── docs/
│   └── README.md      # This documentation
├── original_pdfs/      # Directory for original PDF files
├── output/             # Directory for exported images and manifests
└── test_pdfs/          # Sample PDFs for testing
```

### Architecture

- **MVC Pattern**: Clear separation between GUI, logic, and data
- **Event-driven**: PyQt signals and slots for responsive UI
- **Modular design**: Each component handles specific functionality
- **State management**: Centralized storage with automatic persistence

## License

This project is provided as-is for educational and research purposes.
