from typing import List, Tuple, Dict, Any, Optional
import os
import export
import vector_bbox
from editable_mask import EditableMaskItem

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF is required. Install with: pip install PyMuPDF")
    raise

try:
    from PyQt6.QtWidgets import (
        QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
        QLabel, QListWidget, QListWidgetItem, QPushButton,
        QSplitter, QGraphicsView, QGraphicsScene, QStatusBar,
        QMessageBox, QMenuBar, QDialog, QTextEdit, QDockWidget,
        QToolBar, QGraphicsPolygonItem, QGraphicsItem, QGraphicsRectItem,
        QApplication, QFileDialog, QAbstractItemView
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QTimer
    from PyQt6.QtGui import QPixmap, QImage, QShortcut, QKeySequence, QAction, QPolygonF, QPen, QBrush, QColor, QIcon
except ImportError:
    print("Error: PyQt6 is required. Install with: pip install PyQt6")
    raise

import storage

class MaskItem(QGraphicsPolygonItem):
    """A QGraphicsPolygonItem representing a mask with metadata."""

    def __init__(self, mask_id: str, points: List[List[float]], parent: Optional[QGraphicsItem] = None):
        super().__init__(parent)
        self.mask_id = mask_id
        self.setPolygon(QPolygonF([QPointF(p[0], p[1]) for p in points]))

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        self.default_brush = QBrush(QColor(0, 0, 255, 100))
        self.hover_brush = QBrush(QColor(0, 0, 255, 150))
        self.selected_brush = QBrush(QColor(255, 165, 0, 180))  # Orange for selection
        self.default_pen = QPen(QColor(0, 0, 255), 1)
        self.selected_pen = QPen(QColor(255, 165, 0), 2.5)  # Thicker orange pen for selection

        self.setBrush(self.default_brush)
        self.setPen(self.default_pen)

        self.setAcceptHoverEvents(True)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            # Update the appearance when selection state changes
            if self.isSelected():
                self.setBrush(self.selected_brush)
                self.setPen(self.selected_pen)
                # Notify scene that selection changed
                if self.scene() and hasattr(self.scene(), 'on_mask_selection_changed'):
                    self.scene().on_mask_selection_changed(self)
            else:
                self.setBrush(self.default_brush)
                self.setPen(self.default_pen)
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self.scene() and hasattr(self.scene(), 'on_mask_geometry_changed'):
                self.scene().on_mask_geometry_changed(self.mask_id)
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event) -> None:
        if not self.isSelected():
            self.setBrush(self.hover_brush)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        if not self.isSelected():
            self.setBrush(self.default_brush)
        super().hoverLeaveEvent(event)

    def get_points(self) -> List[List[float]]:
        """Return mask points as list of [x,y] lists."""
        polygon = self.polygon()
        return [[p.x(), p.y()] for p in polygon]

class PageScene(QGraphicsScene):
    """A QGraphicsScene for displaying a PDF page and its masks."""

    mask_created = pyqtSignal(list)
    mask_modified = pyqtSignal(str, list)
    mask_deleted = pyqtSignal(str)
    mask_selected = pyqtSignal(str)  # Signal emitted when a mask is selected in the scene
    rectangle_drawn = pyqtSignal(QRectF) # New signal for drawn rectangles

    MODE_SELECT = 0
    MODE_DRAW = 1

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.current_pixmap_item: Optional[QGraphicsItem] = None
        self.current_masks: Dict[str, EditableMaskItem] = {}
        self.mode = self.MODE_SELECT
        self.is_drawing_rectangle = False
        self.rectangle_start_point: Optional[QPointF] = None
        self.temp_rectangle_item: Optional[QGraphicsRectItem] = None

    def load_page(self, pdf_path: str, page_index: int, page_state: Dict[str, Any]):
        """Load and render a PDF page and its masks."""
        self.clear()
        self.current_masks.clear()
        self.is_drawing_rectangle = False
        self.rectangle_start_point = None
        # Don't need to remove temp_rectangle_item here since clear() handles it
        self.temp_rectangle_item = None

        pixmap = render_page(pdf_path, page_index)
        if pixmap:
            self.current_pixmap_item = self.addPixmap(pixmap)
            self.setSceneRect(self.current_pixmap_item.boundingRect())

            # Add existing masks from page state
            for mask_data in page_state.get("masks", []):
                mask_item = EditableMaskItem(mask_data["id"], mask_data["points"])
                self.addItem(mask_item)
                self.current_masks[mask_data["id"]] = mask_item

            # Auto-generate vector graphics bounding boxes if no masks exist
            if not page_state.get("masks", []):
                vector_boxes = vector_bbox.get_page_vector_boxes(pdf_path, page_index, dpi=300)
                for i, (x0, y0, x1, y1) in enumerate(vector_boxes):
                    points = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                    self.mask_created.emit(points)
        else:
            self.current_pixmap_item = None
            self.addText(f"Error rendering page {page_index + 1}")

    def on_mask_geometry_changed(self, mask_id: str):
        if mask_id in self.current_masks:
            mask_item = self.current_masks[mask_id]
            self.mask_modified.emit(mask_id, mask_item.get_points())

    def on_mask_selection_changed(self, mask_item: EditableMaskItem):
        """Handle mask selection in the scene."""
        if mask_item.isSelected():
            # Use a timer to debounce multiple rapid selection changes
            # This allows multiple items to be selected before updating the UI
            if hasattr(self, '_selection_timer'):
                self._selection_timer.stop()
            else:
                self._selection_timer = QTimer()
                self._selection_timer.timeout.connect(self._emit_selection_update)
                self._selection_timer.setSingleShot(True)
            
            self._selection_timer.start(50)  # 50ms delay to batch selection changes
    
    def _emit_selection_update(self):
        """Emit selection update after a brief delay to handle multi-selection."""
        selected_items = self.selectedItems()
        if selected_items:
            # Find the most recently selected item or just pick the first one
            for item in selected_items:
                if isinstance(item, EditableMaskItem):
                    self.mask_selected.emit(item.mask_id)
                    break
        else:
            # If nothing is selected, emit a signal to clear selection in the list
            self.mask_selected.emit("")

    def set_mode(self, mode: int):
        self.mode = mode
        self.cancel_current_drawing()

        if self.mode == self.MODE_SELECT:
            for item in self.items():
                if isinstance(item, EditableMaskItem):
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        elif self.mode == self.MODE_DRAW:
            for item in self.items():
                if isinstance(item, EditableMaskItem):
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)

    def cancel_current_drawing(self):
        """Cancel the current drawing operation and remove any temporary rectangle."""
        self.is_drawing_rectangle = False
        self.rectangle_start_point = None
        if self.temp_rectangle_item:
            if self.temp_rectangle_item.scene() is not None:
                self.temp_rectangle_item.scene().removeItem(self.temp_rectangle_item)
            self.temp_rectangle_item = None

    def mousePressEvent(self, event) -> None:
        if self.mode == self.MODE_DRAW and event.button() == Qt.MouseButton.LeftButton:
            # Discard any existing temporary rectangle first
            self.cancel_current_drawing()

            self.is_drawing_rectangle = True
            self.rectangle_start_point = event.scenePos()

            initial_rect = QRectF(self.rectangle_start_point, self.rectangle_start_point)
            self.temp_rectangle_item = self.addRect(
                initial_rect,
                QPen(QColor(255, 0, 0), 2, Qt.PenStyle.DashLine),
                QBrush(QColor(255, 0, 0, 50))
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self.mode == self.MODE_DRAW and
            self.is_drawing_rectangle and
            self.rectangle_start_point and
            self.temp_rectangle_item):

            current_pos = event.scenePos()
            rect = QRectF(self.rectangle_start_point, current_pos).normalized()
            self.temp_rectangle_item.setRect(rect)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (self.mode == self.MODE_DRAW and
            self.is_drawing_rectangle and
            event.button() == Qt.MouseButton.LeftButton and
            self.rectangle_start_point and
            self.temp_rectangle_item):

            current_pos = event.scenePos()
            rect = QRectF(self.rectangle_start_point, current_pos).normalized()

            if rect.width() > 5 and rect.height() > 5:
                # Stop the rectangle from following the mouse immediately
                self.is_drawing_rectangle = False
                self.rectangle_start_point = None
                # Keep temp_rectangle_item for accept/cancel workflow
                self.rectangle_drawn.emit(rect)
            else:
                self.cancel_current_drawing()

        super().mouseReleaseEvent(event)

    def accept_rectangle(self):
        """Accept the currently drawn rectangle as a mask."""
        if self.temp_rectangle_item:
            rect = self.temp_rectangle_item.rect()
            points = [
                [rect.left(), rect.top()],
                [rect.right(), rect.top()],
                [rect.right(), rect.bottom()],
                [rect.left(), rect.bottom()]
            ]

            # Clean up safely
            if self.temp_rectangle_item.scene() is not None:
                self.temp_rectangle_item.scene().removeItem(self.temp_rectangle_item)
            self.temp_rectangle_item = None
            self.is_drawing_rectangle = False
            self.rectangle_start_point = None

            # Create the mask
            self.mask_created.emit(points)
            # The mode is now controlled by MainWindow based on continuous draw mode

    def has_pending_rectangle(self) -> bool:
        """Check if there's a rectangle waiting to be accepted."""
        return (self.temp_rectangle_item is not None and
                not self.is_drawing_rectangle)

def render_page(pdf_path: str, page_index: int, dpi: int = 300) -> Optional[QPixmap]:
    """Render a PDF page to QPixmap at specified DPI.

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
    Optional[QPixmap]
        Rendered page as QPixmap, None if error occurred
    """
    try:
        doc = fitz.open(pdf_path)

        if doc.needs_pass:
            doc.close()
            print(f"PDF {pdf_path} is password protected")
            return None

        if doc.is_closed:
            print(f"PDF {pdf_path} appears to be corrupted")
            return None

        if page_index < 0 or page_index >= len(doc):
            doc.close()
            print(f"Page index {page_index} out of range for {pdf_path}")
            return None

        page = doc[page_index]

        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        pix = page.get_pixmap(matrix=mat)

        img_data = pix.tobytes("ppm")
        qimg = QImage.fromData(img_data, "PPM")

        qpixmap = QPixmap.fromImage(qimg)

        doc.close()
        return qpixmap

    except fitz.FileDataError:
        print(f"File data error: {pdf_path} may be corrupted")
        return None
    except fitz.FileNotFoundError:
        print(f"File not found: {pdf_path}")
        return None
    except Exception as e:
        print(f"Error rendering page {page_index} from {pdf_path}: {e}")
        return None

class HelpDialog(QDialog):
    """Help dialog showing keyboard shortcuts and usage information."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF Image Extraction Tool - Help")
        self.setModal(True)
        self.resize(500, 400)

        layout = QVBoxLayout(self)

        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml(self.get_help_content())

        layout.addWidget(help_text)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def get_help_content(self) -> str:
        """Get the HTML content for the help dialog."""
        return """
        <h2>PDF Image Extraction Tool - Help</h2>

        <h3>Navigation</h3>
        <table border="1" style="border-collapse: collapse; width: 100%;">
        <tr><td><b>Previous Page</b></td><td>← or Page Up</td></tr>
        <tr><td><b>Next Page</b></td><td>→ or Page Down</td></tr>
        <tr><td><b>Previous PDF</b></td><td>Ctrl + ↑</td></tr>
        <tr><td><b>Next PDF</b></td><td>Ctrl + ↓</td></tr>
        </table>

        <h3>Zoom Controls</h3>
        <table border="1" style="border-collapse: collapse; width: 100%;">
        <tr><td><b>Zoom In</b></td><td>Ctrl + +</td></tr>
        <tr><td><b>Zoom Out</b></td><td>Ctrl + -</td></tr>
        <tr><td><b>Fit to View</b></td><td>Ctrl + 0</td></tr>
        </table>

        <h3>Mask Controls</h3>
        <table border="1" style="border-collapse: collapse; width: 100%;">
        <tr><td><b>Accept Mask</b></td><td>Enter</td></tr>
        <tr><td><b>Delete Selected Mask</b></td><td>Delete or Backspace</td></tr>
        </table>

        <h3>Approval Controls</h3>
        <table border="1" style="border-collapse: collapse; width: 100%;">
        <tr><td><b>Approve Current Page</b></td><td>Ctrl + Enter</td></tr>
        <tr><td><b>Accept All Pages</b></td><td>Ctrl + Shift + Enter</td></tr>
        </table>

        <h3>Application</h3>
        <table border="1" style="border-collapse: collapse; width: 100%;">
        <tr><td><b>Show Help</b></td><td>F1</td></tr>
        </table>

        <h3>Usage Instructions</h3>
        <ul>
        <li><b>PDF Selection:</b> Click on any PDF in the left panel to view it</li>
        <li><b>Page Navigation:</b> Use buttons or keyboard shortcuts to navigate pages</li>
        <li><b>Zoom:</b> Use zoom controls or mouse wheel (with Ctrl) to zoom in/out</li>
        <li><b>Creating Masks:</b> Click "Draw Rectangle Mask", then drag to draw a rectangle. Press Enter or use Accept/Cancel buttons to save or discard.</li>
        <li><b>Editing Masks:</b> Select masks to move them around the page</li>
        <li><b>State Persistence:</b> All navigation state is automatically saved</li>
        <li><b>Bulk Approval:</b> Use "Accept All Pages" to approve all pages in the current PDF at once</li>
        </ul>

        <h3>File Information</h3>
        <ul>
        <li>Each PDF gets a companion <code>.json</code> file for state storage</li>
        <li>Page counts and navigation state are preserved between sessions</li>
        <li>Corrupted or encrypted PDFs are automatically skipped with warnings</li>
        </ul>
        """

class MainWindow(QMainWindow):
    """Main application window for PDF image extraction tool.

    Parameters
    ----------
    pdf_states : List[Tuple[str, Dict[str, Any]]]
        List of (pdf_path, state) tuples
    """

    def __init__(self, pdf_states: List[Tuple[str, Dict[str, Any]]]):
        super().__init__()
        self.pdf_states = pdf_states
        self.current_pdf_index = 0
        self.current_page_index = 0
        self.current_pixmap = None
        self.is_continuous_draw_mode: bool = False
        self.page_scene: Optional[PageScene] = None
        
        # Zoom state tracking
        self.zoom_mode = "none"  # "none", "fit_to_view", "fit_to_width", "manual"
        self.has_user_zoom_preference = False
        self.manual_zoom_transform = None

        self.init_ui()
        self.load_first_pdf()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("PDF Image Extraction Tool - Interactive Mask Editor")
        self.showMaximized()

        try:
            self.setWindowIcon(QIcon("icon.png"))
        except:
            pass

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        self.create_pdf_list_panel(splitter)
        self.create_viewer_panel(splitter)

        splitter.setSizes([300, 900])

        self.create_mask_dock()

        splitter.setSizes([200, 700])

        self.create_status_bar()
        self.create_toolbar()
        self.setup_shortcuts()
        self.create_menu_bar()

    def create_pdf_list_panel(self, parent):
        """Create the PDF list panel."""
        pdf_panel = QWidget()
        layout = QVBoxLayout(pdf_panel)

        layout.addWidget(QLabel("PDF Files:"))

        self.pdf_list = QListWidget()
        for pdf_path, state in self.pdf_states:
            item = QListWidgetItem(self.get_pdf_display_name(pdf_path, state))
            item.setData(Qt.ItemDataRole.UserRole, pdf_path)
            self.pdf_list.addItem(item)

        self.pdf_list.currentRowChanged.connect(self.on_pdf_selected)
        layout.addWidget(self.pdf_list)

        parent.addWidget(pdf_panel)

    def create_viewer_panel(self, parent):
        """Create the PDF viewer panel."""
        viewer_widget = QWidget()
        layout = QVBoxLayout(viewer_widget)

        self.page_info_label = QLabel("No PDF loaded")
        layout.addWidget(self.page_info_label)

        nav_layout = QHBoxLayout()
        self.prev_page_btn = QPushButton("Previous Page")
        self.prev_page_btn.clicked.connect(self.prev_page)
        self.next_page_btn = QPushButton("Next Page")
        self.next_page_btn.clicked.connect(self.next_page)

        self.zoom_in_btn = QPushButton("Zoom In")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.zoom_out_btn = QPushButton("Zoom Out")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.fit_to_view_btn = QPushButton("Fit to View")
        self.fit_to_view_btn.clicked.connect(self.fit_to_view)
        self.fit_to_width_btn = QPushButton("Fit to Width")
        self.fit_to_width_btn.clicked.connect(self.fit_to_width)

        self.recompute_masks_btn = QPushButton("Recompute Masks")
        self.recompute_masks_btn.clicked.connect(self.recompute_all_masks)

        nav_layout.addWidget(self.prev_page_btn)
        nav_layout.addWidget(self.next_page_btn)
        nav_layout.addWidget(self.zoom_out_btn)
        nav_layout.addWidget(self.zoom_in_btn)
        nav_layout.addWidget(self.fit_to_view_btn)
        nav_layout.addWidget(self.fit_to_width_btn)
        nav_layout.addWidget(self.recompute_masks_btn)
        nav_layout.addStretch()

        layout.addLayout(nav_layout)

        self.rectangle_controls_layout = QHBoxLayout()
        self.accept_rectangle_btn = QPushButton("Accept Mask")
        self.accept_rectangle_btn.clicked.connect(self.accept_rectangle)
        self.cancel_rectangle_btn = QPushButton("Cancel")
        self.cancel_rectangle_btn.clicked.connect(self.cancel_rectangle)

        self.accept_rectangle_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        self.cancel_rectangle_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; }")

        self.rectangle_controls_layout.addWidget(QLabel("Rectangle drawn:"))
        self.rectangle_controls_layout.addWidget(self.accept_rectangle_btn)
        self.rectangle_controls_layout.addWidget(self.cancel_rectangle_btn)
        self.rectangle_controls_layout.addStretch()

        self.rectangle_controls_widget = QWidget()
        self.rectangle_controls_widget.setLayout(self.rectangle_controls_layout)
        self.rectangle_controls_widget.hide()

        layout.addWidget(self.rectangle_controls_widget)

        self.graphics_view = QGraphicsView()
        self.page_scene = PageScene(self)
        self.graphics_view.setScene(self.page_scene)
        layout.addWidget(self.graphics_view)
        self.graphics_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

        self.page_scene.mask_created.connect(self.on_mask_created)
        self.page_scene.mask_modified.connect(self.on_mask_modified)
        self.page_scene.mask_selected.connect(self.on_mask_selected_in_scene)
        self.page_scene.rectangle_drawn.connect(self.on_rectangle_drawn)

        parent.addWidget(viewer_widget)

    def create_mask_dock(self):
        """Create the mask list dock widget."""
        self.mask_dock = QDockWidget("Masks", self)
        self.mask_list_widget = QListWidget()
        
        # Enable multi-selection
        self.mask_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self.mask_list_widget.setStyleSheet("""
            QListWidget::item:selected {
                background-color: #FFA500;
                color: white;
                font-weight: bold;
                border: 1px solid #FF8C00;
            }
            QListWidget::item:hover {
                background-color: #E0E0FF;
            }
        """)

        self.mask_dock.setWidget(self.mask_list_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.mask_dock)

        self.mask_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        delete_mask_action = QAction("Delete Selected Mask(s)", self)
        delete_mask_action.triggered.connect(self.delete_selected_mask_from_list)
        self.mask_list_widget.addAction(delete_mask_action)
        self.mask_list_widget.itemSelectionChanged.connect(self.on_mask_list_selection_changed)

    def create_toolbar(self):
        """Create the main toolbar."""
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        self.select_mode_action = QAction("Select/Move", self, checkable=True)
        self.select_mode_action.setChecked(True)
        self.select_mode_action.triggered.connect(self.activate_select_mode)
        toolbar.addAction(self.select_mode_action)

        self.draw_mode_action = QAction("Draw Rectangle Mask", self, checkable=True)
        self.draw_mode_action.triggered.connect(self.toggle_draw_mode)
        toolbar.addAction(self.draw_mode_action)

        toolbar.addSeparator()

        approve_page_action = QAction("Approve Page", self)
        approve_page_action.triggered.connect(self.approve_current_page)
        toolbar.addAction(approve_page_action)

        accept_all_action = QAction("Accept All Pages", self)
        accept_all_action.triggered.connect(self.accept_all_pages)
        toolbar.addAction(accept_all_action)

        delete_mask_action = QAction("Delete Selected Mask", self)
        delete_mask_action.triggered.connect(self.delete_selected_mask_from_scene)
        toolbar.addAction(delete_mask_action)

    def create_status_bar(self):
        """Create the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def create_menu_bar(self):
        """Create the application menu bar."""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        export_menu = menubar.addMenu("Export")
        help_menu = menubar.addMenu("Help")

        open_new_folder_action = QAction("Open New Target Folder", self)
        open_new_folder_action.triggered.connect(self.open_new_target_folder)
        file_menu.addAction(open_new_folder_action)

        export_all_action = QAction("Export All", self)
        export_all_action.triggered.connect(self.export_all_masks)
        export_menu.addAction(export_all_action)

        help_action = QAction("Show Help", self)
        help_action.setShortcut(QKeySequence("F1"))
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        QShortcut(QKeySequence("Left"), self, self.prev_page)
        QShortcut(QKeySequence("Right"), self, self.next_page)
        QShortcut(QKeySequence("Page_Up"), self, self.prev_page)
        QShortcut(QKeySequence("Page_Down"), self, self.next_page)

        QShortcut(QKeySequence("Ctrl+="), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self.fit_to_view)

        QShortcut(QKeySequence("Ctrl+Up"), self, self.prev_pdf)
        QShortcut(QKeySequence("Ctrl+Down"), self, self.next_pdf)

        QShortcut(QKeySequence("F1"), self, self.show_help)

        QShortcut(QKeySequence("Ctrl+Return"), self, self.approve_current_page)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.approve_current_page)

        QShortcut(QKeySequence("Ctrl+Shift+Return"), self, self.accept_all_pages)
        QShortcut(QKeySequence("Ctrl+Shift+Enter"), self, self.accept_all_pages)

        QShortcut(QKeySequence("Return"), self, self.handle_enter_key)
        QShortcut(QKeySequence("Enter"), self, self.handle_enter_key)
        QShortcut(QKeySequence("Delete"), self, self.handle_delete_key)
        QShortcut(QKeySequence("Backspace"), self, self.handle_delete_key)

    def handle_enter_key(self):
        """Handle Enter key press - accept rectangle if controls are visible."""
        if self.rectangle_controls_widget.isVisible() and self.page_scene.has_pending_rectangle():
            self.accept_rectangle()

    def handle_delete_key(self):
        """Handle Delete/Backspace key press - delete selected masks."""
        # Check scene selection first
        selected_scene_items = self.page_scene.selectedItems()
        editable_mask_items = [item for item in selected_scene_items if isinstance(item, EditableMaskItem)]
        
        if editable_mask_items:
            mask_ids_to_delete = [item.mask_id for item in editable_mask_items]
            for mask_id in mask_ids_to_delete:
                self.delete_mask_by_id(mask_id)
            return
        
        # Check list selection
        selected_list_items = self.mask_list_widget.selectedItems()
        if selected_list_items:
            mask_ids_to_delete = [item.data(Qt.ItemDataRole.UserRole) for item in selected_list_items]
            for mask_id in mask_ids_to_delete:
                self.delete_mask_by_id(mask_id)
            return
        
        self.status_bar.showMessage("No mask selected to delete.", 3000)

    def showEvent(self, event):
        """Override showEvent to ensure default zoom is applied on first show."""
        super().showEvent(event)
        if self.page_scene and not self.has_user_zoom_preference:
            self.fit_to_width()

    def load_first_pdf(self):
        """Load the first PDF in the list."""
        if self.pdf_states:
            self.pdf_list.setCurrentRow(0)

    def on_pdf_selected(self, index: int):
        """Handle PDF selection from the list."""
        if 0 <= index < len(self.pdf_states):
            self.current_pdf_index = index
            self.current_page_index = 0
            self.update_display()

    def prev_pdf(self):
        """Navigate to the previous PDF."""
        if len(self.pdf_states) > 1:
            new_index = (self.current_pdf_index - 1) % len(self.pdf_states)
            self.pdf_list.setCurrentRow(new_index)

    def next_pdf(self):
        """Navigate to the next PDF."""
        if len(self.pdf_states) > 1:
            new_index = (self.current_pdf_index + 1) % len(self.pdf_states)
            self.pdf_list.setCurrentRow(new_index)

    def prev_page(self):
        """Navigate to the previous page."""
        if not self.pdf_states:
            return

        _, state = self.pdf_states[self.current_pdf_index]
        if self.current_page_index > 0:
            self.current_page_index -= 1
            self.update_display()

    def next_page(self):
        """Navigate to the next page."""
        if not self.pdf_states:
            return

        _, state = self.pdf_states[self.current_pdf_index]
        if self.current_page_index < state["page_count"] - 1:
            self.current_page_index += 1
            self.update_display()

    def zoom_in(self):
        """Zoom in the graphics view."""
        self.graphics_view.scale(1.25, 1.25)
        self.zoom_mode = "manual"
        self.has_user_zoom_preference = True
        self.manual_zoom_transform = self.graphics_view.transform()

    def zoom_out(self):
        """Zoom out the graphics view."""
        self.graphics_view.scale(0.8, 0.8)
        self.zoom_mode = "manual"
        self.has_user_zoom_preference = True
        self.manual_zoom_transform = self.graphics_view.transform()

    def fit_to_view(self):
        """Fit the page to the view."""
        self.graphics_view.fitInView(self.page_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_mode = "fit_to_view"
        self.has_user_zoom_preference = True

    def fit_to_width(self):
        """Fit the page to the width of the view."""
        if not self.page_scene.sceneRect().isValid():
            return

        view_rect = self.graphics_view.viewport().rect()
        scene_rect = self.page_scene.sceneRect()

        scale_factor = view_rect.width() / scene_rect.width()

        self.graphics_view.resetTransform()
        self.graphics_view.scale(scale_factor, scale_factor)
        self.zoom_mode = "fit_to_width"
        self.has_user_zoom_preference = True

    def apply_zoom_preference(self):
        """Apply the user's zoom preference or default to fit_to_width for first time."""
        if not self.has_user_zoom_preference:
            # First time or no preference set - use default fit to width
            self.fit_to_width()
        elif self.zoom_mode == "fit_to_view":
            self.graphics_view.fitInView(self.page_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        elif self.zoom_mode == "fit_to_width":
            if self.page_scene.sceneRect().isValid():
                view_rect = self.graphics_view.viewport().rect()
                scene_rect = self.page_scene.sceneRect()
                scale_factor = view_rect.width() / scene_rect.width()
                self.graphics_view.resetTransform()
                self.graphics_view.scale(scale_factor, scale_factor)
        elif self.zoom_mode == "manual" and self.manual_zoom_transform:
            # For manual zoom, try to preserve the relative zoom level
            # Get the current scene rect and apply similar transform
            if self.page_scene.sceneRect().isValid():
                self.graphics_view.setTransform(self.manual_zoom_transform)

    def update_display(self):
        """Update the display with the current page."""
        if not self.pdf_states:
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        page_key = str(page_num)

        if page_key not in state["pages"]:
            storage.ensure_page_exists(state, page_num)

        page_state = state["pages"][page_key]

        self.page_scene.load_page(pdf_path, self.current_page_index, page_state)

        import os
        filename = os.path.basename(pdf_path)
        approved_text = " (APPROVED)" if page_state.get("approved", False) else ""
        self.page_info_label.setText(f"{filename} - Page {page_num}/{state['page_count']}{approved_text}")

        selected_mask_id = None
        if self.mask_list_widget.selectedItems():
            selected_mask_id = self.mask_list_widget.selectedItems()[0].data(Qt.ItemDataRole.UserRole)

        self.update_mask_list()

        if selected_mask_id and selected_mask_id in self.page_scene.current_masks:
            self.page_scene.blockSignals(True)
            self.mask_list_widget.blockSignals(True)

            mask_item = self.page_scene.current_masks[selected_mask_id]
            mask_item.setSelected(True)

            for i in range(self.mask_list_widget.count()):
                item = self.mask_list_widget.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == selected_mask_id:
                    item.setSelected(True)
                    break

            self.page_scene.blockSignals(False)
            self.mask_list_widget.blockSignals(False)

        self.prev_page_btn.setEnabled(self.current_page_index > 0)
        self.next_page_btn.setEnabled(self.current_page_index < state["page_count"] - 1)
        
        # Apply zoom only if user hasn't set a preference, or preserve their preference
        self.apply_zoom_preference()

    def update_mask_list(self):
        """Update the mask list widget for the current page."""
        self.mask_list_widget.clear()
        if not self.pdf_states:
            return

        _, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        page_key = str(page_num)

        if page_key in state["pages"]:
            for mask_data in state["pages"][page_key]["masks"]:
                item = QListWidgetItem(f"Mask {mask_data['id'][:8]}...")
                item.setData(Qt.ItemDataRole.UserRole, mask_data["id"])
                icon_color = QColor(0, 0, 255, 150)
                pixmap = QPixmap(16, 16)
                pixmap.fill(icon_color)
                item.setIcon(QIcon(pixmap))
                item.setToolTip(f"Mask ID: {mask_data['id']}")
                self.mask_list_widget.addItem(item)

    def on_mask_created(self, points: List[List[float]]):
        """Handle new mask creation from PageScene."""
        if not self.pdf_states:
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1

        mask_id = storage.add_mask_to_page(state, page_num, points)
        storage.save_state(pdf_path, state)

        self.update_display()

        if self.is_continuous_draw_mode:
            self.page_scene.set_mode(PageScene.MODE_DRAW)
            self.graphics_view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.draw_mode_action.setChecked(True)
            self.select_mode_action.setChecked(False)

    def toggle_draw_mode(self):
        """Toggle continuous mask drawing mode."""
        if not self.is_continuous_draw_mode:
            self.is_continuous_draw_mode = True
            self.page_scene.set_mode(PageScene.MODE_DRAW)
            self.draw_mode_action.setChecked(True)
            self.select_mode_action.setChecked(False)
            self.status_bar.showMessage("Continuous mask drawing mode activated.", 3000)
        else:
            self.is_continuous_draw_mode = False
            self.page_scene.set_mode(PageScene.MODE_SELECT)
            self.graphics_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.draw_mode_action.setChecked(False)
            self.select_mode_action.setChecked(True)
            self.status_bar.showMessage("Continuous mask drawing mode deactivated.", 3000)

    def activate_select_mode(self):
        """Activate select/move mode and deactivate continuous draw mode."""
        self.is_continuous_draw_mode = False
        self.page_scene.set_mode(PageScene.MODE_SELECT)
        self.graphics_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.select_mode_action.setChecked(True)
        self.draw_mode_action.setChecked(False)
        self.status_bar.showMessage("Select/Move mode activated.", 3000)

    def on_mask_modified(self, mask_id: str, points: List[List[float]]):
        """Handle mask modification from PageScene."""
        if not self.pdf_states:
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        page_key = str(page_num)

        if page_key in state["pages"]:
            for mask_data in state["pages"][page_key]["masks"]:
                if mask_data["id"] == mask_id:
                    mask_data["points"] = points
                    break
            storage.save_state(pdf_path, state)
            self.update_mask_list()

    def on_rectangle_drawn(self, rect: QRectF):
        """Handle rectangle completion - show accept/cancel controls."""
        self.rectangle_controls_widget.show()
        self.status_bar.showMessage("Rectangle drawn. Click 'Accept Mask' to save or 'Cancel' to discard.")

    def accept_rectangle(self):
        """Accept the drawn rectangle as a mask."""
        self.page_scene.accept_rectangle()
        self.rectangle_controls_widget.hide()
        self.status_bar.showMessage("Mask created successfully.")

    def cancel_rectangle(self):
        """Cancel the drawn rectangle."""
        self.page_scene.cancel_current_drawing()
        self.rectangle_controls_widget.hide()
        self.status_bar.showMessage("Rectangle drawing cancelled.")

    def delete_selected_mask_from_scene(self):
        """Delete selected masks from the PageScene."""
        selected_items = self.page_scene.selectedItems()
        if not selected_items:
            return
        
        # Collect all mask IDs to delete
        mask_ids_to_delete = []
        for item in selected_items:
            if isinstance(item, EditableMaskItem):
                mask_ids_to_delete.append(item.mask_id)
        
        # Delete all selected masks
        for mask_id in mask_ids_to_delete:
            self.delete_mask_by_id(mask_id)

    def delete_selected_mask_from_list(self):
        """Delete selected masks from the mask list widget."""
        selected_list_items = self.mask_list_widget.selectedItems()
        if not selected_list_items:
            return
        
        # Collect all mask IDs to delete
        mask_ids_to_delete = []
        for item in selected_list_items:
            mask_id = item.data(Qt.ItemDataRole.UserRole)
            mask_ids_to_delete.append(mask_id)
        
        # Delete all selected masks
        for mask_id in mask_ids_to_delete:
            self.delete_mask_by_id(mask_id)

    def delete_mask_by_id(self, mask_id: str):
        """Deletes a mask by its ID from state, scene, and list."""
        if not self.pdf_states:
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1

        self.status_bar.showMessage(f"Deleting mask {mask_id[:8]}...", 1000)

        if storage.remove_mask_from_page(state, page_num, mask_id):
            storage.save_state(pdf_path, state)
            
            # Remove from scene directly instead of full reload
            if mask_id in self.page_scene.current_masks:
                mask_item = self.page_scene.current_masks[mask_id]
                self.page_scene.removeItem(mask_item)
                del self.page_scene.current_masks[mask_id]
            
            # Update only the mask list
            self.update_mask_list()
            self.status_bar.showMessage(f"Mask {mask_id[:8]}... deleted successfully", 3000)
        else:
            QMessageBox.warning(self, "Error", "Could not delete mask.")

    def approve_current_page(self):
        """Approve the current page and advance."""
        if not self.pdf_states:
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1

        storage.approve_page(state, page_num)
        storage.save_state(pdf_path, state)

        self.update_pdf_list_item(self.current_pdf_index)

        total_pages = state["page_count"]
        for i in range(self.current_page_index + 1, total_pages):
            if not state["pages"][str(i + 1)]["approved"]:
                self.current_page_index = i
                self.update_display()
                return

        for i in range(self.current_page_index):
             if not state["pages"][str(i + 1)]["approved"]:
                self.current_page_index = i
                self.update_display()
                return

        for pdf_idx in range(len(self.pdf_states)):
            next_pdf_actual_idx = (self.current_pdf_index + 1 + pdf_idx) % len(self.pdf_states)
            _, next_pdf_state = self.pdf_states[next_pdf_actual_idx]
            for i in range(next_pdf_state["page_count"]):
                if not next_pdf_state["pages"][str(i+1)]["approved"]:
                    self.pdf_list.setCurrentRow(next_pdf_actual_idx)
                    self.current_page_index = i
                    self.update_display()
                    return

        QMessageBox.information(self, "All Pages Approved", "All pages in all PDFs are approved!")
        self.update_display()

    def accept_all_pages(self):
        """Accept all pages in the current PDF document."""
        if not self.pdf_states:
            QMessageBox.warning(self, "No PDFs", "No PDFs are loaded.")
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        total_pages = state["page_count"]

        confirm = QMessageBox.question(
            self,
            "Accept All Pages",
            f"Are you sure you want to accept all {total_pages} pages in {os.path.basename(pdf_path)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            for page_num in range(1, total_pages + 1):
                storage.approve_page(state, page_num)

            storage.save_state(pdf_path, state)
            self.update_pdf_list_item(self.current_pdf_index)
            self.update_display()

            QMessageBox.information(
                self,
                "Success",
                f"All {total_pages} pages in {os.path.basename(pdf_path)} have been accepted."
            )

    def on_mask_selected_in_scene(self, mask_id: str):
        """Handle mask selection from the scene and update list selection."""
        self.mask_list_widget.blockSignals(True)
        
        if mask_id == "": # No mask selected, clear all selections
            self.mask_list_widget.clearSelection()
            self.status_bar.showMessage("No mask selected", 3000)
        else:
            # Get all currently selected items in the scene
            selected_scene_items = self.page_scene.selectedItems()
            selected_mask_ids = []
            for item in selected_scene_items:
                if isinstance(item, EditableMaskItem):
                    selected_mask_ids.append(item.mask_id)

            self.mask_list_widget.clearSelection()

            # Select corresponding items in the list
            for i in range(self.mask_list_widget.count()):
                item = self.mask_list_widget.item(i)
                item_mask_id = item.data(Qt.ItemDataRole.UserRole)
                if item_mask_id in selected_mask_ids:
                    item.setSelected(True)
                    # Scroll to the first selected item
                    if item_mask_id == mask_id:
                        self.mask_list_widget.scrollToItem(item)

            # Update status bar based on number of selections
            if len(selected_mask_ids) == 1:
                if mask_id in self.page_scene.current_masks:
                    mask_item = self.page_scene.current_masks[mask_id]
                    rect = mask_item.rect()
                    width = round(rect.width())
                    height = round(rect.height())
                    self.status_bar.showMessage(
                        f"Selected mask: {mask_id[:8]}... (Width: {width}px, Height: {height}px)"
                    )
                else:
                    self.status_bar.showMessage(f"Selected mask: {mask_id[:8]}...")
            elif len(selected_mask_ids) > 1:
                self.status_bar.showMessage(f"Selected {len(selected_mask_ids)} masks")

        self.mask_list_widget.blockSignals(False)

    def on_mask_list_selection_changed(self):
        """Sync scene selection from mask list selection."""
        selected_list_items = self.mask_list_widget.selectedItems()
        if not selected_list_items:
            self.page_scene.clearSelection()
            self.status_bar.showMessage("No mask selected", 3000)
            return

        selected_mask_ids = [item.data(Qt.ItemDataRole.UserRole) for item in selected_list_items]

        self.page_scene.blockSignals(True)
        self.page_scene.clearSelection()

        # Select all corresponding masks in the scene
        selected_count = 0
        for mask_id in selected_mask_ids:
            if mask_id in self.page_scene.current_masks:
                mask_item = self.page_scene.current_masks[mask_id]
                mask_item.setSelected(True)
                selected_count += 1

        # Update status bar based on number of selections
        if selected_count == 1:
            mask_id = selected_mask_ids[0]
            if mask_id in self.page_scene.current_masks:
                mask_item = self.page_scene.current_masks[mask_id]
                rect = mask_item.rect()
                width = round(rect.width())
                height = round(rect.height())
                self.status_bar.showMessage(
                    f"Selected mask: {mask_id[:8]}... (Width: {width}px, Height: {height}px)"
                )
            else:
                self.status_bar.showMessage(f"Selected mask: {mask_id[:8]}...")
        elif selected_count > 1:
            self.status_bar.showMessage(f"Selected {selected_count} masks")

        # Ensure the first selected mask is visible
        if selected_count > 0 and selected_mask_ids[0] in self.page_scene.current_masks:
            first_mask = self.page_scene.current_masks[selected_mask_ids[0]]
            view = self.graphics_view
            view.ensureVisible(first_mask)

        self.page_scene.blockSignals(False)

    def get_pdf_display_name(self, pdf_path: str, state: Dict[str, Any]) -> str:
        """Get display name for PDF in the list."""
        import os
        filename = os.path.basename(pdf_path)

        total_pages = state["page_count"]
        approved_pages = sum(1 for page_data in state["pages"].values() if page_data.get("approved", False))

        if approved_pages == total_pages:
            return f"✓ {filename} ({approved_pages}/{total_pages})"
        else:
            return f"{filename} ({approved_pages}/{total_pages})"

    def update_pdf_list_item(self, pdf_index: int):
        """Update a specific PDF list item's display name."""
        if 0 <= pdf_index < len(self.pdf_states):
            pdf_path, state = self.pdf_states[pdf_index]
            new_name = self.get_pdf_display_name(pdf_path, state)
            self.pdf_list.item(pdf_index).setText(new_name)

    def show_help(self):
        """Show the help dialog."""
        help_dialog = HelpDialog(self)
        help_dialog.exec()

    def show_about(self):
        """Show the about dialog."""
        QMessageBox.about(self, "About",
                         "PDF Image Extraction Tool\n\n"
                         "A tool for extracting images from PDF files using polygon masks.\n\n"
                         "Features:\n"
                         "• Interactive PDF viewing\n"
                         "• Polygon mask creation and editing\n"
                         "• Page approval workflow\n"
                         "• Export functionality")

    def export_all_masks(self):
        """Export all approved masks to image files."""
        import os

        if not self.pdf_states:
            QMessageBox.warning(self, "No PDFs", "No PDFs are loaded.")
            return

        pdf_path, _ = self.pdf_states[self.current_pdf_index]

        try:
            export.export_all(pdf_path)
            QMessageBox.information(self, "Export Complete",
                                  f"Successfully exported all approved masks for {os.path.basename(pdf_path)}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export masks: {str(e)}")

    def open_new_target_folder(self):
        """Open a new target folder and reload the application with the new directory."""
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Directory Containing PDF Files",
            os.getcwd()
        )
        if not selected_dir:
            self.status_bar.showMessage("No directory selected.", 3000)
            return

        self.status_bar.showMessage(f"New directory selected: {selected_dir}", 3000)
        print(f"New directory selected: {selected_dir}")

    def recompute_all_masks(self):
        """Recompute all masks for the current PDF using the automatic detection algorithm."""
        if not self.pdf_states:
            QMessageBox.warning(self, "No PDFs", "No PDFs are loaded.")
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        pdf_filename = os.path.basename(pdf_path)

        confirm = QMessageBox.question(
            self,
            "Recompute All Masks",
            f"Are you sure you want to recompute all masks for ALL pages in '{pdf_filename}'?\n\n"
            "This will discard all existing masks for this PDF and generate new ones automatically.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.status_bar.showMessage(f"Recomputing masks for {pdf_filename}...", 0) # 0 means stay until new message

            total_pages = state["page_count"]
            for page_num in range(1, total_pages + 1):
                page_key = str(page_num)
                
                # Clear existing masks for the page
                if page_key not in state["pages"]:
                    storage.ensure_page_exists(state, page_num)
                state["pages"][page_key]["masks"] = []

                # Recompute and add new masks
                vector_boxes = vector_bbox.get_page_vector_boxes(pdf_path, page_num - 1, dpi=300)
                for x0, y0, x1, y1 in vector_boxes:
                    points = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                    storage.add_mask_to_page(state, page_num, points)
            
            storage.save_state(pdf_path, state)
            self.update_display()
            self.status_bar.showMessage(f"Successfully recomputed masks for {pdf_filename}.", 5000)
        else:
            self.status_bar.showMessage("Mask recomputation cancelled.", 3000)
