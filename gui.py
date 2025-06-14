from typing import List, Tuple, Dict, Any, Optional
import os
import export
from export import check_all_pages_approved
import vector_bbox
import question_bbox
from editable_mask import EditableMaskItem
from shapely.geometry import Polygon, box, LineString

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
    """A QGraphicsPolygonItem representing a mask with metadata.

    Parameters
    ----------
    mask_id : str
        Unique identifier of the mask
    points : List[List[float]]
        Polygon points in scene coordinates
    mask_type : str, optional
        Either "image" or "question", default "image"
    parent : Optional[QGraphicsItem]
        Parent graphics item
    """

    def __init__(self, mask_id: str, points: List[List[float]], mask_type: str = "image", parent: Optional[QGraphicsItem] = None):
        super().__init__(parent)
        self.mask_id = mask_id
        self.mask_type = mask_type
        self.setPolygon(QPolygonF([QPointF(p[0], p[1]) for p in points]))

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        # Color depends on mask type
        if self.mask_type == "question":
            base_color = QColor(0, 150, 0)
        else:
            base_color = QColor(0, 0, 255)

        self.default_brush = QBrush(QColor(base_color.red(), base_color.green(), base_color.blue(), 100))
        self.hover_brush = QBrush(QColor(base_color.red(), base_color.green(), base_color.blue(), 150))
        self.selected_brush = QBrush(QColor(255, 165, 0, 180))  # Orange for selection
        self.default_pen = QPen(base_color, 1)
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
    eraser_rectangle = pyqtSignal(QRectF)  # New signal for eraser rectangles

    MODE_SELECT = 0
    MODE_DRAW = 1

    GRID_SIZE = 20

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.current_pixmap_item: Optional[QGraphicsItem] = None
        self.current_masks: Dict[str, EditableMaskItem] = {}
        self.mode = self.MODE_SELECT
        self.is_drawing_rectangle = False
        self.rectangle_start_point: Optional[QPointF] = None
        self.temp_rectangle_item: Optional[QGraphicsRectItem] = None
        self.is_erasing_draw = False  # Track if current rectangle is eraser
        self.current_draw_ctrl = False  # Track whether Ctrl/Cmd was held during current rectangle
        self.last_mask_ctrl_flag = False  # Exposed flag for MainWindow to inspect

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

            # Draw the grid after setting the scene rect
            self.draw_grid()

            # Add existing masks from page state
            for mask_data in page_state.get("masks", []):
                points = mask_data["points"]
                m_type = mask_data.get("type", "image")
                if len(points) != 4:
                    mask_item = MaskItem(mask_data["id"], points, m_type)
                else:
                    mask_item = EditableMaskItem(mask_data["id"], points, m_type)
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

    def draw_grid(self) -> None:
        """Draws a slightly opaque grid over the scene for orientation."""
        if not self.sceneRect().isValid():
            return

        pen = QPen(QColor(100, 100, 100, 50))  # Light gray, 50 alpha (slightly opaque)
        pen.setWidth(1)

        # Draw vertical lines
        x = self.sceneRect().left()
        while x <= self.sceneRect().right():
            self.addLine(x, self.sceneRect().top(), x, self.sceneRect().bottom(), pen)
            x += self.GRID_SIZE

        # Draw horizontal lines
        y = self.sceneRect().top()
        while y <= self.sceneRect().bottom():
            self.addLine(self.sceneRect().left(), y, self.sceneRect().right(), y, pen)
            y += self.GRID_SIZE

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
            if self.views():
                self.views()[0].setCursor(Qt.CursorShape.ArrowCursor)
        elif self.mode == self.MODE_DRAW:
            for item in self.items():
                if isinstance(item, EditableMaskItem):
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            if self.views():
                self.views()[0].setCursor(Qt.CursorShape.CrossCursor)

    def cancel_current_drawing(self):
        """Cancel the current drawing operation and remove any temporary rectangle."""
        self.is_drawing_rectangle = False
        self.rectangle_start_point = None
        self.is_erasing_draw = False  # Reset eraser mode
        self.current_draw_ctrl = False  # Reset ctrl flag
        if self.temp_rectangle_item:
            if self.temp_rectangle_item.scene() is not None:
                self.temp_rectangle_item.scene().removeItem(self.temp_rectangle_item)
            self.temp_rectangle_item = None

    def mousePressEvent(self, event) -> None:
        if self.mode == self.MODE_DRAW and event.button() == Qt.MouseButton.LeftButton:
            self.cancel_current_drawing()
            self.is_erasing_draw = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            # Detect Ctrl (Windows/Linux) or Meta (Command on macOS)
            ctrl_or_cmd = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
            self.current_draw_ctrl = bool(event.modifiers() & ctrl_or_cmd)
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

            # Clean up safely
            if self.temp_rectangle_item.scene() is not None:
                self.temp_rectangle_item.scene().removeItem(self.temp_rectangle_item)
            self.temp_rectangle_item = None
            self.is_drawing_rectangle = False
            self.rectangle_start_point = None

            if self.is_erasing_draw:
                # Emit eraser rectangle signal for erasing masks
                self.eraser_rectangle.emit(rect)
                self.is_erasing_draw = False
            else:
                # Create the mask
                points = [
                    [rect.left(), rect.top()],
                    [rect.right(), rect.top()],
                    [rect.right(), rect.bottom()],
                    [rect.left(), rect.bottom()]
                ]
                # Store the ctrl flag for MainWindow to evaluate BEFORE emitting signal
                self.last_mask_ctrl_flag = self.current_draw_ctrl
                self.current_draw_ctrl = False
                self.mask_created.emit(points)

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
        <tr><td><b>Accept Mask</b></td><td>Enter or Space</td></tr>
        <tr><td><b>Discard Mask</b></td><td>Escape</td></tr>
        <tr><td><b>Delete Selected Mask</b></td><td>Delete or Backspace</td></tr>
        <tr><td><b>Merge Selected Masks</b></td><td>M</td></tr>
        <tr><td><b>Split Selected Mask</b></td><td>S</td></tr>
        <tr><td><b>Expand Selected Mask</b></td><td>E</td></tr>
        </table>

        <h3>Approval Controls</h3>
        <table border="1" style="border-collapse: collapse; width: 100%;">
        <tr><td><b>Approve Current Page</b></td><td>Ctrl + Enter</td></tr>
        <tr><td><b>Accept All Pages</b></td><td>Ctrl + Shift + Enter</td></tr>
        </table>

        <h3>Application</h3>
        <table border="1" style="border-collapse: collapse; width: 100%;">
        <tr><td><b>Show Help</b></td><td>F1</td></tr>
        <tr><td><b>Select All Masks</b></td><td>Ctrl + A</td></tr>
        </table>

        <h3>Usage Instructions</h3>
        <ul>
        <li><b>PDF Selection:</b> Click on any PDF in the left panel to view it</li>
        <li><b>Page Navigation:</b> Use keyboard shortcuts (← → or Page Up/Down) to navigate pages</li>
        <li><b>Zoom:</b> Use the combined zoom button or keyboard shortcuts to zoom in/out</li>
        <li><b>Creating Masks:</b> Click "Draw Rectangle Mask", then drag to draw a rectangle. Press Enter/Space to accept or Escape to discard.</li>
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

class MaskPropertiesDock(QDockWidget):
    """A dock widget to display properties of the selected mask."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Mask Properties", parent)
        self.init_ui()

    def init_ui(self):
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        self.properties_labels: Dict[str, QLabel] = {}

        # Helper to add a property row
        def add_property_row(label_text: str, key: str):
            row_layout = QHBoxLayout()
            row_layout.addWidget(QLabel(f"<b>{label_text}:</b>"))
            value_label = QLabel("N/A")
            self.properties_labels[key] = value_label
            row_layout.addWidget(value_label)
            row_layout.addStretch()
            layout.addLayout(row_layout)

        add_property_row("Mask ID", "id")
        add_property_row("Top-Left X", "x")
        add_property_row("Top-Left Y", "y")
        add_property_row("Width", "width")
        add_property_row("Height", "height")
        add_property_row("Area", "area")
        add_property_row("Aspect Ratio", "aspect_ratio")

        layout.addStretch() # Push content to top

        self.setWidget(content_widget)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)

    def update_properties(self, mask_item: Optional[EditableMaskItem]):
        """
        Update the displayed properties based on the selected mask.

        Parameters
        ----------
        mask_item : Optional[EditableMaskItem]
            The selected EditableMaskItem, or None if no mask is selected or multiple are selected.
        """
        if mask_item is None:
            for key in self.properties_labels:
                self.properties_labels[key].setText("N/A")
            self.setWindowTitle("Mask Properties")
        else:
            try:
                mask_id = mask_item.mask_id
                points = mask_item.get_points()
                
                # Points are [top-left, top-right, bottom-right, bottom-left]
                x0, y0 = points[0][0], points[0][1]
                x1, y1 = points[2][0], points[2][1] # bottom-right

                width = x1 - x0
                height = y1 - y0
                area = width * height
                aspect_ratio = width / height if height != 0 else float('inf')

                self.properties_labels["id"].setText(f"{mask_id[:8]}...")
                self.properties_labels["x"].setText(f"{x0:.2f} px")
                self.properties_labels["y"].setText(f"{y0:.2f} px")
                self.properties_labels["width"].setText(f"{width:.2f} px")
                self.properties_labels["height"].setText(f"{height:.2f} px")
                self.properties_labels["area"].setText(f"{area:.2f} px²")
                self.properties_labels["aspect_ratio"].setText(f"{aspect_ratio:.2f}")
                self.setWindowTitle(f"Mask Properties: {mask_id[:8]}...")

            except Exception as e:
                # Fallback in case of error
                for key in self.properties_labels:
                    self.properties_labels[key].setText("Error")
                self.setWindowTitle("Mask Properties (Error)")
                print(f"Error updating mask properties: {e}")


class CombinedZoomButton(QWidget):
    """A combined zoom button with zoom in and zoom out functionality."""
    
    zoom_in_clicked = pyqtSignal()
    zoom_out_clicked = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the combined zoom button UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Zoom out button (left half)
        self.zoom_out_btn = QPushButton()
        self.zoom_out_btn.clicked.connect(self.zoom_out_clicked.emit)
        self.zoom_out_btn.setToolTip("Zoom Out")
        
        # Zoom in button (right half)
        self.zoom_in_btn = QPushButton()
        self.zoom_in_btn.clicked.connect(self.zoom_in_clicked.emit)
        self.zoom_in_btn.setToolTip("Zoom In")
        
        # Try to use standard icons, fallback to text
        try:
            style = self.style()
            # Use proper zoom icons from the standard set
            self.zoom_out_btn.setText("−")
            self.zoom_in_btn.setText("+")
        except:
            pass # Fallback to text is now the primary method, no specific error handling needed
        
        # Style the buttons to look like a single split button
        button_style = """
            QPushButton {
                border: 1px solid #888;
                background-color: #f0f0f0;
                padding: 2px 6px;
                font-size: 16px;
                color: #333;
                min-width: 30px;
                min-height: 16px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
        """
        
        # Left button (zoom out) - rounded left corners only
        zoom_out_style = button_style + """
            QPushButton {
                border-top-left-radius: 4px;
                border-bottom-left-radius: 4px;
                border-right: 0.5px solid #666;
            }
        """
        
        # Right button (zoom in) - rounded right corners only  
        zoom_in_style = button_style + """
            QPushButton {
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                border-left: 0.5px solid #666;
            }
        """
        
        self.zoom_out_btn.setStyleSheet(zoom_out_style)
        self.zoom_in_btn.setStyleSheet(zoom_in_style)
        
        layout.addWidget(self.zoom_out_btn)
        layout.addWidget(self.zoom_in_btn)

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
        self.mask_properties_dock: Optional[MaskPropertiesDock] = None # New instance variable
        
        # Zoom state tracking
        self.zoom_mode = "none"  # "none", "fit_to_view", "fit_to_width", "manual"
        self.has_user_zoom_preference = False
        self.manual_zoom_transform = None

        self.current_draw_type = "image"  # default draw type
        self.pending_question_group_id: Optional[str] = None  # For multi-page question masks
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
        self.create_mask_properties_dock() # New call to create properties dock

        splitter.setSizes([200, 700])

        self.create_status_bar()
        self.create_toolbar()
        self.setup_shortcuts()
        self.create_menu_bar()

    def create_mask_properties_dock(self):
        """Create the mask properties dock widget."""
        self.mask_properties_dock = MaskPropertiesDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.mask_properties_dock)

    def create_pdf_list_panel(self, parent):
        """Create the PDF list panel."""
        pdf_panel = QWidget()
        layout = QVBoxLayout(pdf_panel)

        layout.addWidget(QLabel("PDF Files:"))

        # Add approval counter
        self.approval_counter_label = QLabel()
        self.update_approval_counter()
        layout.addWidget(self.approval_counter_label)

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
        
        # Create combined zoom button
        self.combined_zoom_btn = CombinedZoomButton()
        self.combined_zoom_btn.zoom_in_clicked.connect(self.zoom_in)
        self.combined_zoom_btn.zoom_out_clicked.connect(self.zoom_out)
        
        self.fit_to_view_btn = QPushButton("Fit to View")
        self.fit_to_view_btn.clicked.connect(self.fit_to_view)
        self.fit_to_width_btn = QPushButton("Fit to Width")
        self.fit_to_width_btn.clicked.connect(self.fit_to_width)

        self.recompute_masks_btn = QPushButton("Recompute Masks")
        self.recompute_masks_btn.clicked.connect(self.recompute_all_masks)

        self.merge_masks_btn = QPushButton("Merge Selected Masks")
        self.merge_masks_btn.clicked.connect(self.merge_selected_masks)
        self.merge_masks_btn.setEnabled(False) # Initially disabled

        self.split_mask_btn = QPushButton("Split Selected Mask")
        self.split_mask_btn.clicked.connect(self.split_selected_mask)
        self.split_mask_btn.setEnabled(False) # Initially disabled

        nav_layout.addWidget(self.combined_zoom_btn)
        nav_layout.addWidget(self.fit_to_view_btn)
        nav_layout.addWidget(self.fit_to_width_btn)
        nav_layout.addWidget(self.recompute_masks_btn)
        nav_layout.addWidget(self.merge_masks_btn)
        nav_layout.addWidget(self.split_mask_btn)
        nav_layout.addStretch()

        layout.addLayout(nav_layout)

        self.graphics_view = QGraphicsView()
        self.page_scene = PageScene(self)
        self.graphics_view.setScene(self.page_scene)
        layout.addWidget(self.graphics_view)
        self.graphics_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

        self.page_scene.mask_created.connect(self.on_mask_created)
        self.page_scene.mask_modified.connect(self.on_mask_modified)
        self.page_scene.mask_selected.connect(self.on_mask_selected_in_scene)
        self.page_scene.rectangle_drawn.connect(self.on_rectangle_drawn)
        self.page_scene.eraser_rectangle.connect(self.on_eraser_rectangle)

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

        # Draw actions for different mask types
        self.draw_mode_action = QAction("Draw Image Region", self, checkable=True)
        self.draw_mode_action.triggered.connect(lambda checked: self.toggle_draw_mode("image", checked))
        toolbar.addAction(self.draw_mode_action)

        self.draw_question_action = QAction("Draw Question Region", self, checkable=True)
        self.draw_question_action.triggered.connect(lambda checked: self.toggle_draw_mode("question", checked))
        toolbar.addAction(self.draw_question_action)

        # Automatic computation of question masks for entire PDF
        compute_qm_action = QAction("Compute Question Masks", self)
        compute_qm_action.triggered.connect(self.compute_question_masks)
        toolbar.addAction(compute_qm_action)

        # Multi-page question toggle placed next to compute action
        self.multi_page_question_action = QAction("Multi-page Q", self, checkable=True)
        self.multi_page_question_action.setToolTip("Toggle multi-page question drawing mode")
        toolbar.addAction(self.multi_page_question_action)

        # Keyboard shortcut to toggle multi-page mode (key 'Q')
        QShortcut(QKeySequence("Q"), self, lambda: self.multi_page_question_action.trigger())

        toolbar.addSeparator()

        self.merge_masks_action = QAction("Merge Selected Masks", self)
        self.merge_masks_action.triggered.connect(self.merge_selected_masks)
        self.merge_masks_action.setEnabled(False) # Initially disabled
        toolbar.addAction(self.merge_masks_action)

        self.split_mask_action = QAction("Split Selected Mask", self)
        self.split_mask_action.triggered.connect(self.split_selected_mask)
        self.split_mask_action.setEnabled(False) # Initially disabled
        toolbar.addAction(self.split_mask_action)

        self.expand_mask_action = QAction("Expand Mask", self)
        self.expand_mask_action.triggered.connect(self.expand_selected_mask)
        self.expand_mask_action.setEnabled(False) # Initially disabled
        toolbar.addAction(self.expand_mask_action)

        self.add_mask_action = QAction("Add Selected Masks", self)
        self.add_mask_action.triggered.connect(self.add_selected_masks)
        toolbar.addAction(self.add_mask_action)

        # Associate images with question
        self.associate_action = QAction("Associate Images → Question", self)
        self.associate_action.triggered.connect(self.associate_selected_masks)
        toolbar.addAction(self.associate_action)

        # Keyboard shortcut for association (Ctrl+L)
        QShortcut(QKeySequence("Ctrl+L"), self, self.associate_selected_masks)

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
        QShortcut(QKeySequence("Space"), self, self.handle_enter_key) # Accept mask with Spacebar
        QShortcut(QKeySequence("Escape"), self, self.handle_escape_key) # Discard mask with Escape
        QShortcut(QKeySequence("Delete"), self, self.handle_delete_key)
        QShortcut(QKeySequence("Backspace"), self, self.handle_delete_key)
        QShortcut(QKeySequence("M"), self, self.merge_selected_masks) # Shortcut for merging
        QShortcut(QKeySequence("S"), self, self.split_selected_mask) # New shortcut for splitting
        QShortcut(QKeySequence("Ctrl+A"), self, self.select_all_masks) # Select all masks
        QShortcut(QKeySequence("E"), self, self.expand_selected_mask) # New shortcut for expanding mask
        QShortcut(QKeySequence("A"), self, self.add_selected_masks) # Shortcut for add-to-mask

    def handle_enter_key(self):
        """
        Handle Enter or Space key press - accept rectangle if pending.
        """
        if self.page_scene.has_pending_rectangle():
            self.accept_rectangle()

    def handle_escape_key(self):
        """
        Handle Escape key press - discard the currently drawn rectangle if pending.
        """
        if self.page_scene.has_pending_rectangle():
            self.cancel_rectangle()

    def handle_delete_key(self):
        """Handle Delete/Backspace key press - delete selected masks."""
        selected_scene_items = self.page_scene.selectedItems()
        mask_items = [item for item in selected_scene_items if isinstance(item, (EditableMaskItem, MaskItem))]
        if mask_items:
            for item in mask_items:
                self.delete_mask_by_id(item.mask_id)
            return

        # Otherwise delete from the list selection
        self.delete_selected_mask_from_list()

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

        # Apply zoom only if user hasn't set a preference, or preserve their preference
        self.apply_zoom_preference()

        # Re-apply dashed highlight for pending multi-page question segment
        if getattr(self, 'pending_question_group_id', None):
            pend_id = self.pending_question_group_id
            if pend_id in self.page_scene.current_masks:
                pen = QPen(QColor(255, 165, 0), 2, Qt.PenStyle.DashLine)
                self.page_scene.current_masks[pend_id].setPen(pen)

    def update_mask_list(self):
        """Update the mask list widget for the current page."""
        self.mask_list_widget.clear()
        if not self.pdf_states:
            return

        _, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        page_key = str(page_num)

        if page_key in state["pages"]:
            page_masks = state["pages"][page_key]["masks"]
            # Pre-compute reverse association: image_id -> list[question_id]
            image_links: Dict[str, List[str]] = {}
            for m in page_masks:
                if m.get("type") == "question":
                    for img_id in m.get("associated_image_ids", []):
                        image_links.setdefault(img_id, []).append(m["id"])

            for mask_data in page_masks:
                m_type = mask_data.get("type", "image")
                if m_type == "question":
                    assoc = mask_data.get("associated_image_ids", [])
                    text = f"Q {mask_data['id'][:8]} ({len(assoc)} img)"
                    # Check for multi-page grouping
                    group_id = mask_data.get("question_id")
                    if group_id and group_id != mask_data["id"]:
                        text += " Part of multi-page question"
                else:  # image
                    linked_q = image_links.get(mask_data["id"], [])
                    star = "*" if linked_q else ""
                    text = f"I{star} {mask_data['id'][:8]}..."

                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, mask_data["id"])

                # Icon colour
                icon_color = QColor(0, 150, 0, 150) if m_type == "question" else QColor(0, 0, 255, 150)
                pixmap = QPixmap(16, 16)
                pixmap.fill(icon_color)
                item.setIcon(QIcon(pixmap))

                tooltip_lines = [f"Mask ID: {mask_data['id']}", f"Type: {m_type}"]
                if m_type == "question":
                    tooltip_lines.append(f"Associated images: {len(assoc)}")
                else:
                    if image_links.get(mask_data["id"]):
                        tooltip_lines.append(f"Linked to {len(image_links[mask_data['id']])} question(s)")
                item.setToolTip("\n".join(tooltip_lines))

                self.mask_list_widget.addItem(item)

    def on_mask_created(self, points: List[List[float]]):
        """Handle new mask creation from PageScene, with support for multi-page question masks."""
        if not self.pdf_states:
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1

        # Check whether multi-page mode is active (toolbar toggle)
        is_multi_page_mode = self.multi_page_question_action.isChecked()

        # Detect if Ctrl/Cmd was pressed during the draw operation (legacy fallback)
        ctrl_flag = getattr(self.page_scene, 'last_mask_ctrl_flag', False)
        self.page_scene.last_mask_ctrl_flag = False

        multi_page_triggered = is_multi_page_mode or ctrl_flag

        question_group_id: Optional[str] = None

        # Logic for multi-page question masks
        if self.current_draw_type == "question" and multi_page_triggered:
            # If this is the first part, initialise a new group. Otherwise reuse the pending group.
            if getattr(self, 'pending_question_group_id', None) is None:
                # First segment – create mask normally, then assign its own id as group id
                mask_id = storage.add_mask_to_page(state, page_num, points, self.current_draw_type)

                # Set its question_id to its own id so subsequent segments can reference it
                page_key = str(page_num)
                for mask in state["pages"][page_key]["masks"]:
                    if mask["id"] == mask_id:
                        mask["question_id"] = mask_id
                        break

                self.pending_question_group_id = mask_id

                # Visual feedback – dashed pen for the first segment
                if mask_id in self.page_scene.current_masks:
                    first_item = self.page_scene.current_masks[mask_id]
                    pen = QPen(QColor(255, 165, 0), 2, Qt.PenStyle.DashLine)
                    first_item.setPen(pen)

                self.status_bar.showMessage("First part of multi-page question saved. Navigate to the next page, draw the next part and confirm.", 5000)
            else:
                # Second (or subsequent) segment – reuse existing group id
                question_group_id = self.pending_question_group_id
                mask_id = storage.add_mask_to_page(
                    state,
                    page_num,
                    points,
                    self.current_draw_type,
                    question_id=question_group_id
                )

                # Clear pending state
                self.pending_question_group_id = None

                # Automatically disable multi-page toggle after completion
                if self.multi_page_question_action.isChecked():
                    self.multi_page_question_action.setChecked(False)

                # Restore pen of the first segment if it is currently visible
                if question_group_id in self.page_scene.current_masks:
                    original_item = self.page_scene.current_masks[question_group_id]
                    if hasattr(original_item, 'default_pen'):
                        original_item.setPen(original_item.default_pen)

                self.status_bar.showMessage("Multi-page question saved successfully.", 4000)
        else:
            # Normal mask creation
            mask_id = storage.add_mask_to_page(state, page_num, points, self.current_draw_type)

        storage.save_state(pdf_path, state)

        # Refresh the scene to include the newly created mask
        self.update_display()

        if self.is_continuous_draw_mode:
            # Keep drawing mode active for current type
            self.page_scene.set_mode(PageScene.MODE_DRAW)
            self.graphics_view.setDragMode(QGraphicsView.DragMode.NoDrag)
            if self.current_draw_type == "image":
                self.draw_mode_action.setChecked(True)
                if hasattr(self, 'draw_question_action'):
                    self.draw_question_action.setChecked(False)
            else:
                if hasattr(self, 'draw_question_action'):
                    self.draw_question_action.setChecked(True)
                self.draw_mode_action.setChecked(False)
            self.select_mode_action.setChecked(False)

        # Apply dashed pen highlight for the very first segment if still pending
        if getattr(self, 'pending_question_group_id', None) == mask_id:
            if mask_id in self.page_scene.current_masks:
                pen = QPen(QColor(255, 165, 0), 2, Qt.PenStyle.DashLine)
                self.page_scene.current_masks[mask_id].setPen(pen)

    def toggle_draw_mode(self, mask_type: str, checked: bool):
        """Toggle continuous draw mode for a given mask type (image/question)."""
        # Ensure mutual exclusivity of draw actions
        if mask_type == "image":
            other_action = self.draw_question_action
            current_action = self.draw_mode_action
        else:
            other_action = self.draw_mode_action
            current_action = self.draw_question_action

        if checked:
            # Activate draw mode for the requested type
            self.current_draw_type = mask_type
            self.is_continuous_draw_mode = True
            self.page_scene.set_mode(PageScene.MODE_DRAW)
            self.graphics_view.setDragMode(QGraphicsView.DragMode.NoDrag)

            current_action.setChecked(True)
            other_action.setChecked(False)
            self.select_mode_action.setChecked(False)

            self.status_bar.showMessage(f"Continuous drawing mode activated for {mask_type} masks.", 3000)
        else:
            # Deactivate draw mode – switch to select
            self.is_continuous_draw_mode = False
            self.page_scene.set_mode(PageScene.MODE_SELECT)
            self.graphics_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

            current_action.setChecked(False)
            self.select_mode_action.setChecked(True)

            self.status_bar.showMessage("Continuous drawing mode deactivated.", 3000)

    def activate_select_mode(self):
        """Activate select/move mode and deactivate continuous draw mode."""
        self.is_continuous_draw_mode = False
        self.page_scene.set_mode(PageScene.MODE_SELECT)
        self.graphics_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.select_mode_action.setChecked(True)
        self.draw_mode_action.setChecked(False)
        if hasattr(self, 'draw_question_action'):
            self.draw_question_action.setChecked(False)
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
        """Handle rectangle completion - show status message for keyboard shortcuts."""
        self.status_bar.showMessage("Rectangle drawn. Press Enter/Space to save or Escape to discard.")

    def accept_rectangle(self):
        """Accept the drawn rectangle as a mask."""
        self.page_scene.accept_rectangle()
        self.status_bar.showMessage("Mask created successfully.")

    def cancel_rectangle(self):
        """Cancel the drawn rectangle."""
        self.page_scene.cancel_current_drawing()
        self.status_bar.showMessage("Rectangle drawing cancelled.")

    def delete_selected_mask_from_scene(self):
        """Delete selected masks from the PageScene."""
        selected_items = self.page_scene.selectedItems()
        if not selected_items:
            return
        
        # Collect all mask IDs to delete
        mask_ids_to_delete = []
        for item in selected_items:
            if isinstance(item, (EditableMaskItem, MaskItem)):
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

        # Determine if mask is part of multi-page question
        group_id_for_cascade: Optional[str] = None

        # Find mask data to inspect question_id
        target_mask_data = None
        for p_key, p_data in state["pages"].items():
            for m in p_data["masks"]:
                if m["id"] == mask_id:
                    target_mask_data = m
                    break
            if target_mask_data:
                break

        if target_mask_data and target_mask_data.get("type") == "question":
            group_id_for_cascade = target_mask_data.get("question_id") or target_mask_data["id"]

        if storage.remove_mask_from_page(state, page_num, mask_id):
            storage.save_state(pdf_path, state)

            # NEW: Remove the mask item from the current scene immediately
            if mask_id in self.page_scene.current_masks:
                scene_item = self.page_scene.current_masks[mask_id]
                if scene_item.scene() is not None:
                    self.page_scene.removeItem(scene_item)
                del self.page_scene.current_masks[mask_id]

            # Cascade delete other segments in the same group across pages
            if group_id_for_cascade and group_id_for_cascade == mask_id:
                for p_key, p_data in state["pages"].items():
                    masks_to_remove = [m["id"] for m in p_data["masks"] if m.get("question_id") == group_id_for_cascade and m["id"] != mask_id]
                    for mid in masks_to_remove:
                        storage.remove_mask_from_page(state, int(p_key), mid)
                        # If segment is currently visible, remove from scene
                        if mid in self.page_scene.current_masks:
                            seg_item = self.page_scene.current_masks[mid]
                            self.page_scene.removeItem(seg_item)
                            del self.page_scene.current_masks[mid]
                storage.save_state(pdf_path, state)

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

        for page_num in range(1, total_pages + 1):
            storage.approve_page(state, page_num)

        storage.save_state(pdf_path, state)
        self.update_pdf_list_item(self.current_pdf_index)
        self.update_display()
        
        self.status_bar.showMessage(f"All {total_pages} pages in {os.path.basename(pdf_path)} have been approved!", 4000)

    def on_mask_selected_in_scene(self, mask_id: str):
        """Handle mask selection from the scene and update list selection."""
        self.mask_list_widget.blockSignals(True)
        
        if mask_id == "": # No mask selected, clear all selections
            self.mask_list_widget.clearSelection()
            self.status_bar.showMessage("No mask selected", 3000)
            selected_count = 0 # No masks selected
        else:
            # Get all currently selected items in the scene
            selected_scene_items = self.page_scene.selectedItems()
            selected_mask_ids = []
            for item in selected_scene_items:
                if isinstance(item, EditableMaskItem):
                    selected_mask_ids.append(item.mask_id)
            selected_count = len(selected_mask_ids)

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
            if selected_count == 1:
                mask_item = self.page_scene.current_masks.get(mask_id)
                if mask_item:
                    rect = mask_item.rect()
                    width = round(rect.width())
                    height = round(rect.height())
                    self.status_bar.showMessage(
                        f"Selected mask: {mask_id[:8]}... (Width: {width}px, Height: {height}px)"
                    )
                    self.mask_properties_dock.update_properties(mask_item)
                else:
                    self.status_bar.showMessage(f"Selected mask: {mask_id[:8]}...")
                    self.mask_properties_dock.update_properties(None) # Should not happen if mask_id is valid
            elif selected_count > 1:
                self.status_bar.showMessage(f"Selected {selected_count} masks")
                self.mask_properties_dock.update_properties(None) # Clear properties for multi-selection
            else:
                self.status_bar.showMessage("No mask selected", 3000)
                self.mask_properties_dock.update_properties(None) # Clear properties for no selection
        
        can_merge = selected_count >= 2
        self.merge_masks_btn.setEnabled(can_merge)
        self.merge_masks_action.setEnabled(can_merge)

        can_split = selected_count == 1
        self.split_mask_btn.setEnabled(can_split)
        self.split_mask_action.setEnabled(can_split)

        can_expand = selected_count == 1
        self.expand_mask_action.setEnabled(can_expand)

        self.mask_list_widget.blockSignals(False)

    def on_mask_list_selection_changed(self):
        """Sync scene selection from mask list selection."""
        selected_list_items = self.mask_list_widget.selectedItems()
        
        selected_mask_ids = [item.data(Qt.ItemDataRole.UserRole) for item in selected_list_items]

        self.page_scene.blockSignals(True)
        self.page_scene.clearSelection()

        # Select all corresponding masks in the scene
        selected_count = 0
        selected_mask_item: Optional[EditableMaskItem] = None
        for mask_id in selected_mask_ids:
            if mask_id in self.page_scene.current_masks:
                mask_item = self.page_scene.current_masks[mask_id]
                mask_item.setSelected(True)
                selected_count += 1
                if selected_count == 1: # Keep track of the first selected item for properties display
                    selected_mask_item = mask_item

        # Update status bar and properties dock based on number of selections
        if selected_count == 1:
            if selected_mask_item:
                if hasattr(selected_mask_item, 'rect'):
                    rect = selected_mask_item.rect()
                else:
                    rect = selected_mask_item.sceneBoundingRect()
                width = round(rect.width())
                height = round(rect.height())
                self.status_bar.showMessage(
                    f"Selected mask: {selected_mask_item.mask_id[:8]}... (Width: {width}px, Height: {height}px)"
                )
                self.mask_properties_dock.update_properties(selected_mask_item)
            else:
                self.status_bar.showMessage("No mask selected", 3000) # Should not happen
                self.mask_properties_dock.update_properties(None)
        elif selected_count > 1:
            self.status_bar.showMessage(f"Selected {selected_count} masks")
            self.mask_properties_dock.update_properties(None) # Clear properties for multi-selection
        else:
            self.status_bar.showMessage("No mask selected", 3000)
            self.mask_properties_dock.update_properties(None) # Clear properties for no selection

        can_merge = selected_count >= 2
        self.merge_masks_btn.setEnabled(can_merge)
        self.merge_masks_action.setEnabled(can_merge)

        can_split = selected_count == 1
        self.split_mask_btn.setEnabled(can_split)
        self.split_mask_action.setEnabled(can_split)

        can_expand = selected_count == 1
        self.expand_mask_action.setEnabled(can_expand)

        # Ensure the first selected mask is visible
        if selected_mask_item:
            view = self.graphics_view
            view.ensureVisible(selected_mask_item)

        self.page_scene.blockSignals(False)

    def _get_bounding_box_from_points(self, points: List[List[float]]) -> QRectF:
        """
        Calculates the bounding box (QRectF) from a list of polygon points.
        """
        min_x = min(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_x = max(p[0] for p in points)
        max_y = max(p[1] for p in points)
        return QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

    def expand_selected_mask(self):
        """
        Expands the currently selected mask to include adjacent small vector graphics (letters).
        """
        selected_items = self.page_scene.selectedItems()
        if len(selected_items) != 1:
            self.status_bar.showMessage("Select exactly one mask to expand.", 3000)
            return

        mask_to_expand = selected_items[0]
        if not isinstance(mask_to_expand, EditableMaskItem):
            self.status_bar.showMessage("Selected item is not a mask.", 3000)
            return

        self.status_bar.showMessage("Expanding mask...", 0)

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        
        # Get all vector graphics on the current page
        all_vector_boxes = vector_bbox.get_page_vector_boxes(pdf_path, page_num - 1, dpi=300)
        
        initial_mask_rect = mask_to_expand.sceneBoundingRect()
        
        # Define a tolerance for adjacency (e.g., 30 pixels)
        ADJACENCY_TOLERANCE = 30.0 

        # List to store all adjacent vector rectangles found
        adjacent_vector_rects = []

        # Expand the initial mask rect by the tolerance for checking adjacency
        expanded_initial_mask_rect = initial_mask_rect.adjusted(
            -ADJACENCY_TOLERANCE, -ADJACENCY_TOLERANCE,
            ADJACENCY_TOLERANCE, ADJACENCY_TOLERANCE
        )

        for vb_x0, vb_y0, vb_x1, vb_y1 in all_vector_boxes:
            vector_rect = QRectF(vb_x0, vb_y0, vb_x1 - vb_x0, vb_y1 - vb_y0)
            
            # Expand both rectangles by tolerance and check for intersection
            expanded_vector_rect = vector_rect.adjusted(
                -ADJACENCY_TOLERANCE, -ADJACENCY_TOLERANCE,
                ADJACENCY_TOLERANCE, ADJACENCY_TOLERANCE
            )

            if expanded_initial_mask_rect.intersects(expanded_vector_rect):
                adjacent_vector_rects.append(vector_rect)
        
        if not adjacent_vector_rects:
            self.status_bar.showMessage("No adjacent vector graphics found to expand the mask.", 3000)
            return

        # Calculate the new combined bounding box by uniting the initial mask rect
        # with all found adjacent vector rectangles.
        new_combined_rect = initial_mask_rect
        for adj_rect in adjacent_vector_rects:
            new_combined_rect = new_combined_rect.united(adj_rect)
        
        # Only proceed if the new combined rectangle is actually larger than the original
        if new_combined_rect == initial_mask_rect:
            self.status_bar.showMessage("Mask did not expand further (no new adjacent graphics found).", 3000)
            return

        # Delete original mask
        self.delete_mask_by_id(mask_to_expand.mask_id)

        # Create new expanded mask
        new_mask_points = [
            [new_combined_rect.left(), new_combined_rect.top()],
            [new_combined_rect.right(), new_combined_rect.top()],
            [new_combined_rect.right(), new_combined_rect.bottom()],
            [new_combined_rect.left(), new_combined_rect.bottom()]
        ]
        
        storage.add_mask_to_page(state, page_num, new_mask_points)
        storage.save_state(pdf_path, state)

        self.update_display()
        self.status_bar.showMessage("Mask expanded successfully.", 3000)

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
            self.update_approval_counter()

    def update_approval_counter(self):
        """Update the approval counter label showing how many PDFs are completely approved."""
        total_pdfs = len(self.pdf_states)
        approved_pdfs = 0
        
        for pdf_path, _ in self.pdf_states:
            is_approved, _ = check_all_pages_approved(pdf_path)
            if is_approved:
                approved_pdfs += 1
        
        self.approval_counter_label.setText(f"Approved: {approved_pdfs}/{total_pdfs} PDFs")
        
        if approved_pdfs == total_pdfs and total_pdfs > 0:
            self.approval_counter_label.setStyleSheet(
                "color: white; background-color: #2d5a27; font-weight: bold; "
                "padding: 4px 8px; border-radius: 4px; border: 1px solid #1e3d1b;"
            )
        else:
            self.approval_counter_label.setStyleSheet(
                "color: white; background-color: #424242; font-weight: bold; "
                "padding: 4px 8px; border-radius: 4px; border: 1px solid #333333;"
            )

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

    def merge_selected_masks(self):
        """
        Merges all currently selected masks into a single new mask that encompasses their combined area.
        The original selected masks are then deleted.
        """
        selected_items = self.page_scene.selectedItems()
        masks_to_merge = [item for item in selected_items if isinstance(item, EditableMaskItem)]

        if len(masks_to_merge) < 2:
            self.status_bar.showMessage("Select at least two masks to merge.", 3000)
            return

        # Calculate combined bounding box
        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')

        for mask_item in masks_to_merge:
            # Use sceneBoundingRect to get coordinates in the scene's coordinate system
            rect = mask_item.sceneBoundingRect()
            min_x = min(min_x, rect.left())
            min_y = min(min_y, rect.top())
            max_x = max(max_x, rect.right())
            max_y = max(max_y, rect.bottom())

        new_mask_points = [
            [min_x, min_y],
            [max_x, min_y],
            [max_x, max_y],
            [min_x, max_y]
        ]

        # Determine merged mask type: if all selected masks are question type, keep it as question
        merged_mask_type = "question" if all(getattr(item, 'mask_type', 'image') == 'question' for item in masks_to_merge) else "image"

        # Delete original masks
        for mask_item in masks_to_merge:
            self.delete_mask_by_id(mask_item.mask_id)

        # Create new merged mask with appropriate type
        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        storage.add_mask_to_page(state, page_num, new_mask_points, mask_type=merged_mask_type)
        storage.save_state(pdf_path, state)

        self.update_display()
        self.status_bar.showMessage(f"Successfully merged {len(masks_to_merge)} masks.", 3000)

    def split_selected_mask(self):
        """
        Splits the currently selected mask into two new masks based on its largest dimension.
        The original selected mask is then deleted.
        """
        selected_items = self.page_scene.selectedItems()
        
        if len(selected_items) != 1:
            self.status_bar.showMessage("Select exactly one mask to split.", 3000)
            return

        mask_to_split = selected_items[0]
        if not isinstance(mask_to_split, EditableMaskItem):
            self.status_bar.showMessage("Selected item is not a mask.", 3000)
            return

        rect = mask_to_split.sceneBoundingRect()
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        width = x1 - x0
        height = y1 - y0

        new_mask_points_1 = []
        new_mask_points_2 = []

        if width > height: # Split horizontally
            mid_x = x0 + width / 2
            new_mask_points_1 = [
                [x0, y0], [mid_x, y0], [mid_x, y1], [x0, y1]
            ]
            new_mask_points_2 = [
                [mid_x, y0], [x1, y0], [x1, y1], [mid_x, y1]
            ]
        else: # Split vertically
            mid_y = y0 + height / 2
            new_mask_points_1 = [
                [x0, y0], [x1, y0], [x1, mid_y], [x0, mid_y]
            ]
            new_mask_points_2 = [
                [x0, mid_y], [x1, mid_y], [x1, y1], [x0, y1]
            ]
        
        # Delete original mask
        self.delete_mask_by_id(mask_to_split.mask_id)

        # Create new split masks
        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        
        storage.add_mask_to_page(state, page_num, new_mask_points_1)
        storage.add_mask_to_page(state, page_num, new_mask_points_2)
        storage.save_state(pdf_path, state)

        self.update_display()
        self.status_bar.showMessage("Mask split successfully into two new masks.", 3000)

    def select_all_masks(self):
        """Selects all masks on the current page."""
        if not self.page_scene:
            return

        self.page_scene.blockSignals(True) # Block signals to prevent multiple updates during selection
        self.page_scene.clearSelection() # Clear existing selection first

        selected_count = 0
        for item in self.page_scene.items():
            if isinstance(item, EditableMaskItem):
                item.setSelected(True)
                selected_count += 1
        
        self.page_scene.blockSignals(False)
        self.on_mask_selected_in_scene("") # Trigger update to sync list and status bar
        self.status_bar.showMessage(f"Selected {selected_count} masks.", 3000)

    def on_eraser_rectangle(self, rect: QRectF):
        """Handle eraser rectangle by removing intersecting mask areas as a single polygon."""
        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        modified = False
        for mask_id, mask_item in list(self.page_scene.current_masks.items()):
            pts = mask_item.get_points()
            mask_poly = Polygon(pts)
            eraser_poly = box(rect.left(), rect.top(), rect.right(), rect.bottom())
            diff = mask_poly.difference(eraser_poly)
            if not diff.is_empty and diff.geom_type == 'Polygon':
                # Remove the old mask
                storage.remove_mask_from_page(state, page_num, mask_id)
                if mask_item.scene() is not None:
                    self.page_scene.removeItem(mask_item)
                del self.page_scene.current_masks[mask_id]
                # Add the new mask as a single polygon
                new_points = list(diff.exterior.coords)
                # Remove duplicate last point if present
                if len(new_points) > 1 and new_points[0] == new_points[-1]:
                    new_points = new_points[:-1]
                new_id = storage.add_mask_to_page(state, page_num, new_points)
                new_item = MaskItem(new_id, new_points)
                self.page_scene.addItem(new_item)
                self.page_scene.current_masks[new_id] = new_item
                modified = True
            elif not diff.is_empty and diff.geom_type == 'MultiPolygon':
                # If the result is a MultiPolygon, keep only the largest piece
                largest = max(diff.geoms, key=lambda g: g.area)
                new_points = list(largest.exterior.coords)
                if len(new_points) > 1 and new_points[0] == new_points[-1]:
                    new_points = new_points[:-1]
                storage.remove_mask_from_page(state, page_num, mask_id)
                if mask_item.scene() is not None:
                    self.page_scene.removeItem(mask_item)
                del self.page_scene.current_masks[mask_id]
                new_id = storage.add_mask_to_page(state, page_num, new_points)
                new_item = MaskItem(new_id, new_points)
                self.page_scene.addItem(new_item)
                self.page_scene.current_masks[new_id] = new_item
                modified = True
            elif mask_poly.intersects(eraser_poly):
                # If the mask is completely erased, just remove it
                storage.remove_mask_from_page(state, page_num, mask_id)
                if mask_item.scene() is not None:
                    self.page_scene.removeItem(mask_item)
                del self.page_scene.current_masks[mask_id]
                modified = True
        if modified:
            storage.save_state(pdf_path, state)
            self.update_mask_list()
            self.status_bar.showMessage("Eraser applied successfully.", 3000)
        else:
            self.status_bar.showMessage("No mask intersects eraser rectangle.", 3000)

    def add_selected_masks(self):
        """Add one mask to another, connecting with a Manhattan step if needed."""
        selected_items = self.page_scene.selectedItems()
        mask_items = [item for item in selected_items if isinstance(item, (EditableMaskItem, MaskItem))]
        if len(mask_items) != 2:
            self.status_bar.showMessage("Select exactly two masks to add.", 3000)
            return
        mask1, mask2 = mask_items
        poly1 = Polygon(mask1.get_points())
        poly2 = Polygon(mask2.get_points())
        if poly1.intersects(poly2) or poly1.touches(poly2):
            union = poly1.union(poly2)
        else:
            # Connect masks with a full-size Manhattan bridge
            # Compute bounding boxes
            b1_minx, b1_miny, b1_maxx, b1_maxy = poly1.bounds
            b2_minx, b2_miny, b2_maxx, b2_maxy = poly2.bounds
            # Calculate positive gaps
            gap_x = max(0, b2_minx - b1_maxx, b1_minx - b2_maxx)
            gap_y = max(0, b2_miny - b1_maxy, b1_miny - b2_maxy)
            if gap_x >= gap_y:
                # Horizontal connector with height of smaller mask
                h1 = b1_maxy - b1_miny
                h2 = b2_maxy - b2_miny
                small_miny, small_maxy = (b1_miny, b1_maxy) if h1 < h2 else (b2_miny, b2_maxy)
                # Determine left/right extents
                if b1_maxx < b2_minx:
                    x0, x1 = b1_maxx, b2_minx
                else:
                    x0, x1 = b2_maxx, b1_minx
                connector = box(x0, small_miny, x1, small_maxy)
            else:
                # Vertical connector with width of smaller mask
                w1 = b1_maxx - b1_minx
                w2 = b2_maxx - b2_minx
                small_minx, small_maxx = (b1_minx, b1_maxx) if w1 < w2 else (b2_minx, b2_maxx)
                # Determine top/bottom extents
                if b1_maxy < b2_miny:
                    y0, y1 = b1_maxy, b2_miny
                else:
                    y0, y1 = b2_maxy, b1_miny
                connector = box(small_minx, y0, small_maxx, y1)
            # Merge with connector
            union = poly1.union(poly2).union(connector)
        # Only keep the largest polygon if union is multipolygon
        if union.geom_type == 'MultiPolygon':
            union = max(union.geoms, key=lambda g: g.area)
        new_points = list(union.exterior.coords)
        if len(new_points) > 1 and new_points[0] == new_points[-1]:
            new_points = new_points[:-1]
        # Remove old masks
        for item in mask_items:
            self.delete_mask_by_id(item.mask_id)
        # Add new mask
        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        new_id = storage.add_mask_to_page(state, page_num, new_points)
        new_item = MaskItem(new_id, new_points)
        self.page_scene.addItem(new_item)
        self.page_scene.current_masks[new_id] = new_item
        storage.save_state(pdf_path, state)
        self.update_mask_list()
        self.status_bar.showMessage("Masks added successfully.", 3000)

    # ------------------------------------------------------------------
    # Question ↔ Image association helpers
    # ------------------------------------------------------------------

    def associate_selected_masks(self):
        """Associate selected image masks with a single selected question mask."""
        selected_items = self.page_scene.selectedItems()
        if not selected_items:
            self.status_bar.showMessage("No masks selected for association.", 3000)
            return

        question_items = [it for it in selected_items if getattr(it, 'mask_type', 'image') == 'question']
        image_items = [it for it in selected_items if getattr(it, 'mask_type', 'image') == 'image']

        if len(question_items) != 1:
            self.status_bar.showMessage("Select exactly one question mask and one or more image masks.", 4000)
            return
        if not image_items:
            self.status_bar.showMessage("Select at least one image mask to associate.", 4000)
            return

        q_item = question_items[0]
        q_id = q_item.mask_id
        image_ids = [it.mask_id for it in image_items]

        # Update state
        pdf_path, state = self.pdf_states[self.current_pdf_index]
        page_num = self.current_page_index + 1
        page_key = str(page_num)

        updated = False
        if page_key in state['pages']:
            for mask_data in state['pages'][page_key]['masks']:
                if mask_data['id'] == q_id:
                    assoc_list = mask_data.setdefault('associated_image_ids', [])
                    for img_id in image_ids:
                        if img_id not in assoc_list:
                            assoc_list.append(img_id)
                            updated = True
                    break

        if updated:
            storage.save_state(pdf_path, state)
            self.update_mask_list()
            self.status_bar.showMessage("Associated image masks with question.", 3000)
        else:
            self.status_bar.showMessage("Nothing to associate (already linked).", 3000)

    def compute_question_masks(self):
        """Compute question masks for the entire PDF."""
        if not self.pdf_states:
            QMessageBox.warning(self, "No PDFs", "No PDFs are loaded.")
            return

        pdf_path, state = self.pdf_states[self.current_pdf_index]
        pdf_filename = os.path.basename(pdf_path)

        self.status_bar.showMessage(f"Computing question masks for {pdf_filename}...", 0)

        total_pages = state["page_count"]
        for page_num in range(1, total_pages + 1):
            page_key = str(page_num)
            
            # Ensure page exists
            if page_key not in state["pages"]:
                storage.ensure_page_exists(state, page_num)
            
            # Remove existing question masks but keep others
            existing_masks = state["pages"][page_key]["masks"]
            state["pages"][page_key]["masks"] = [m for m in existing_masks if m.get("type", "image") != "question"]

            # Compute question boxes via text analysis
            q_boxes = question_bbox.get_page_question_boxes(pdf_path, page_num - 1, dpi=300)
            for x0, y0, x1, y1 in q_boxes:
                pts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                storage.add_mask_to_page(state, page_num, pts, mask_type="question")
        
        storage.save_state(pdf_path, state)
        self.update_display()
        self.status_bar.showMessage(f"Successfully computed question masks for {pdf_filename}.", 5000)
