from typing import List, Dict, Any, Optional
from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsItem, QGraphicsEllipseItem, QGraphicsTextItem
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPen, QBrush, QColor, QCursor, QFont, QPainterPath


class EdgeHandle(QGraphicsEllipseItem):
    """A small handle for resizing mask edges."""

    def __init__(self, edge: str, parent_mask: 'EditableMaskItem'):
        super().__init__(-4, -4, 8, 8)
        self.edge = edge
        self.parent_mask = parent_mask
        self.is_being_dragged = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setCursor(self._get_cursor())

        self.setBrush(QBrush(QColor(255, 255, 255, 200)))
        self.setPen(QPen(QColor(0, 0, 0), 1))

        self.setZValue(10)

    def mousePressEvent(self, event):
        """Handle mouse press to start dragging."""
        self.is_being_dragged = True
        event.accept()  # Accept the event to maintain mouse capture
        self.grabMouse()  # Explicitly grab mouse to prevent capture loss
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse movement during dragging."""
        if self.is_being_dragged:
            event.accept()  # Keep accepting events to maintain capture
            # Calculate the movement delta and apply it
            new_pos = self.pos() + event.pos() - event.lastPos()
            self.setPos(new_pos)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release to end dragging."""
        self.is_being_dragged = False
        self.ungrabMouse()  # Release mouse capture
        event.accept()  # Accept the release event
        super().mouseReleaseEvent(event)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        """Handle item changes, particularly position changes during dragging."""
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.is_being_dragged:
            # This is called when Qt wants to change our position during dragging
            # We can modify the value to constrain the movement
            new_pos = value
            rect = self.parent_mask.rect()
            min_size = 10

            if self.edge == 'top':
                new_pos.setY(min(new_pos.y(), rect.bottom() - min_size))
                new_pos.setX(rect.center().x())
            elif self.edge == 'bottom':
                new_pos.setY(max(new_pos.y(), rect.top() + min_size))
                new_pos.setX(rect.center().x())
            elif self.edge == 'left':
                new_pos.setX(min(new_pos.x(), rect.right() - min_size))
                new_pos.setY(rect.center().y())
            elif self.edge == 'right':
                new_pos.setX(max(new_pos.x(), rect.left() + min_size))
                new_pos.setY(rect.center().y())

            return new_pos
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self.is_being_dragged:
            # This is called after our position has actually changed
            # Notify parent to update the mask geometry
            self.parent_mask.handle_moved(self.edge, self.pos())

        return super().itemChange(change, value)

    def _get_cursor(self) -> QCursor:
        """Get appropriate cursor for the edge."""
        if self.edge in ['top', 'bottom']:
            return QCursor(Qt.CursorShape.SizeVerCursor)
        elif self.edge in ['left', 'right']:
            return QCursor(Qt.CursorShape.SizeHorCursor)
        return QCursor(Qt.CursorShape.ArrowCursor)

    def shape(self) -> QPainterPath:
        """Return a larger shape for mouse interaction while keeping visual size small."""
        # Create a larger rectangular area around the handle for easier clicking
        # The visual handle is only 8x8 pixels, but we'll make the clickable area much larger
        hit_margin = 12  # pixels of extra margin around the visual handle

        # Create a rectangle that's much larger than the visual 8x8 circle
        # The handle is centered at (0,0) with size (-4,-4,8,8), so we expand around that
        larger_rect = QRectF(-4 - hit_margin, -4 - hit_margin,
                            8 + 2 * hit_margin, 8 + 2 * hit_margin)

        path = QPainterPath()
        path.addRect(larger_rect)
        return path
    

class OptionLabelDisplay(QGraphicsTextItem):
    """A small text display for showing option labels in the top-left corner of image masks."""
    
    def __init__(self, parent_mask: 'EditableMaskItem'):
        super().__init__()
        self.parent_mask = parent_mask
        self.setParentItem(parent_mask)
        
        # Set up the visual appearance
        font = QFont()
        font.setPointSize(30)  # Tripled from 10 to 30
        font.setBold(True)
        self.setFont(font)
        
        # Position at top-left corner with larger padding for bigger text
        self.setPos(8, 8)
        
        # Set z-value to appear above the mask
        self.setZValue(20)
        
        # Make it non-interactive
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        
        # Initially hidden
        self.setVisible(False)
        
    def update_label(self, option_label: str):
        """Update the displayed option label text."""
        if option_label and option_label.strip():
            self.setPlainText(option_label.strip())
            # Reposition label to the top-left of the parent mask's bounding box
            try:
                parent_rect = self.parent_mask.boundingRect()
                # Add a small padding so the text isn't flush to the edge
                pad_x, pad_y = 8, 8
                self.setPos(parent_rect.left() + pad_x, parent_rect.top() + pad_y)
            except Exception:
                # Fallback to the original small offset
                self.setPos(8, 8)

            # Set white text for visibility and show the label
            self.setDefaultTextColor(QColor(255, 255, 255))
            self.setVisible(True)
        else:
            # Hide if no label
            self.setVisible(False)
    
    def paint(self, painter, option, widget):
        """Override paint to draw background box."""
        if self.isVisible() and self.toPlainText():
            # Draw background box
            rect = self.boundingRect()
            background_rect = rect.adjusted(-6, -4, 6, 4)  # Doubled padding for larger text
            
            # Semi-transparent dark background
            painter.fillRect(background_rect, QColor(0, 0, 0, 180))
            
            # Draw border with thicker line for visibility
            painter.setPen(QPen(QColor(255, 255, 255), 2))  # Increased from 1 to 2
            painter.drawRect(background_rect)
        
        # Draw the text
        super().paint(painter, option, widget)


class EditableMaskItem(QGraphicsRectItem):
    """An editable rectangular mask with edge drag handles.

    Parameters
    ----------
    mask_id : str
        Unique identifier of the mask
    points : List[List[float]]
        Four corner points of the rectangle (GUI coordinates)
    mask_type : str, optional
        Either "image" or "question" to distinguish semantics, default "image".
    parent : Optional[QGraphicsItem]
        Optional parent graphics item
    """
    
    def __init__(self, mask_id: str, points: List[List[float]], mask_type: str = "image", parent: Optional[QGraphicsItem] = None):
        # Convert points to rectangle
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        x0, y0 = min(x_coords), min(y_coords)
        x1, y1 = max(x_coords), max(y_coords)
        
        # Create rect at origin with proper size
        super().__init__(0, 0, x1 - x0, y1 - y0, parent)
        
        # Set the item position to the top-left coordinate
        self.setPos(x0, y0)
        
        self.mask_id = mask_id
        self.mask_type = mask_type
        self.handles: Dict[str, EdgeHandle] = {}
        self.is_updating_handles = False
        
        # Create option label display for image masks
        self.option_label_display: Optional[OptionLabelDisplay] = None
        if self.mask_type == "image":
            self.option_label_display = OptionLabelDisplay(self)
        
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        
        # Color scheme depends on mask type
        if self.mask_type == "question":
            base_color = QColor(0, 150, 0)  # greenish
        else:  # image
            base_color = QColor(0, 0, 255)

        self.default_brush = QBrush(QColor(base_color.red(), base_color.green(), base_color.blue(), 100))
        self.hover_brush = QBrush(QColor(base_color.red(), base_color.green(), base_color.blue(), 150))
        self.selected_brush = QBrush(QColor(255, 165, 0, 180))  # Orange for primary selection
        self.associated_brush = QBrush(QColor(255, 215, 0, 130))  # Gold for associated selection
        
        self.default_pen = QPen(base_color, 1)
        self.selected_pen = QPen(QColor(255, 165, 0), 2.5)
        self.associated_pen = QPen(QColor(255, 215, 0), 2)  # Gold pen for associated items
        
        self.setBrush(self.default_brush)
        self.setPen(self.default_pen)
        self.setAcceptHoverEvents(True)
        
        self._create_handles()
        self._update_handle_positions()
        self._set_handles_visible(False)
        
        # Track if this mask is being shown as associated
        self.is_showing_as_associated = False
    
    def _create_handles(self):
        """Create edge handles for resizing."""
        for edge in ['top', 'bottom', 'left', 'right']:
            handle = EdgeHandle(edge, self)
            handle.setParentItem(self)
            self.handles[edge] = handle
    
    def _update_handle_positions(self, force: bool = False):
        """Update handle positions based on current rectangle.

        Parameters
        ----------
        force : bool, optional
            If True, update the handle positions even when a resize operation
            is already in progress. This is required to keep the handles in
            sync while the user is actively dragging one of them. The default
            is False which avoids recursive updates when handles are moved
            indirectly (e.g. when the entire mask is moved).
        """
        if self.is_updating_handles and not force:
            return

        rect = self.rect()
        # Temporarily mark as updating to prevent recursive geometry updates
        prev_state = self.is_updating_handles
        self.is_updating_handles = True
        positions = {
            'top': QPointF(rect.center().x(), rect.top()),
            'bottom': QPointF(rect.center().x(), rect.bottom()),
            'left': QPointF(rect.left(), rect.center().y()),
            'right': QPointF(rect.right(), rect.center().y())
        }
        
        for edge, pos in positions.items():
            self.handles[edge].setPos(pos)
        
        # Restore previous updating state
        self.is_updating_handles = prev_state
    
    def _set_handles_visible(self, visible: bool):
        """Show or hide the edge handles."""
        for handle in self.handles.values():
            handle.setVisible(visible)
    
    def handle_moved(self, edge: str, new_pos: QPointF):
        """Handle movement of an edge handle."""
        if self.is_updating_handles:
            return

        self.is_updating_handles = True

        rect = self.rect()
        min_size = 10

        if edge == 'top':
            new_top = new_pos.y()
            if rect.bottom() - new_top >= min_size:
                rect.setTop(new_top)
        elif edge == 'bottom':
            new_bottom = new_pos.y()
            if new_bottom - rect.top() >= min_size:
                rect.setBottom(new_bottom)
        elif edge == 'left':
            new_left = new_pos.x()
            if rect.right() - new_left >= min_size:
                rect.setLeft(new_left)
        elif edge == 'right':
            new_right = new_pos.x()
            if new_right - rect.left() >= min_size:
                rect.setRight(new_right)

        self.setRect(rect)
        # Force-update positions of all handles so they stay aligned while
        # the user continues dragging.
        self._update_handle_positions(force=True)

        self.is_updating_handles = False

        # Only notify scene of changes if we're not in the middle of a drag operation
        # This prevents interference with active mouse capture
        if self.scene() and hasattr(self.scene(), 'on_mask_geometry_changed'):
            # Check if any handle is currently being dragged
            any_handle_dragging = any(handle.is_being_dragged for handle in self.handles.values())
            if not any_handle_dragging:
                self.scene().on_mask_geometry_changed(self.mask_id)
    
    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if self.isSelected():
                # Primary selection
                self.setBrush(self.selected_brush)
                self.setPen(self.selected_pen)
                self._set_handles_visible(True)
                self.is_showing_as_associated = False
                if self.scene() and hasattr(self.scene(), 'on_mask_selection_changed'):
                    self.scene().on_mask_selection_changed(self)
            else:
                # Clear selection highlighting
                if not self.is_showing_as_associated:
                    self.setBrush(self.default_brush)
                    self.setPen(self.default_pen)
                self._set_handles_visible(False)
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._update_handle_positions()
            if self.scene() and hasattr(self.scene(), 'on_mask_geometry_changed'):
                self.scene().on_mask_geometry_changed(self.mask_id)
        return super().itemChange(change, value)
    
    def hoverEnterEvent(self, event) -> None:
        if not self.isSelected() and not self.is_showing_as_associated:
            self.setBrush(self.hover_brush)
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event) -> None:
        if not self.isSelected() and not self.is_showing_as_associated:
            self.setBrush(self.default_brush)
        super().hoverLeaveEvent(event)
    
    def get_points(self) -> List[List[float]]:
        """Return mask points as list of [x,y] lists."""
        rect = self.rect()
        pos = self.pos()
        
        # Adjust coordinates by item position
        x0 = rect.left() + pos.x()
        y0 = rect.top() + pos.y()
        x1 = rect.right() + pos.x()
        y1 = rect.bottom() + pos.y()
        
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    
    def show_as_associated(self):
        """Highlight this mask as being associated with the selected mask."""
        if not self.isSelected():  # Only modify appearance if not primarily selected
            self.setBrush(self.associated_brush)
            self.setPen(self.associated_pen)
            self.is_showing_as_associated = True
            self._set_handles_visible(False)  # Associated items don't show handles
    
    def clear_associated_display(self):
        """Clear the associated highlight if it was being shown."""
        if self.is_showing_as_associated and not self.isSelected():
            self.setBrush(self.default_brush)
            self.setPen(self.default_pen)
            self.is_showing_as_associated = False
    
    def update_option_label(self, option_label: str):
        """Update the option label display for image masks."""
        if self.option_label_display and self.mask_type == "image":
            self.option_label_display.update_label(option_label)
