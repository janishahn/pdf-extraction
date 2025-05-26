from typing import List, Tuple, Dict, Any, Optional
from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsItem, QGraphicsEllipseItem
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPen, QBrush, QColor, QCursor


class EdgeHandle(QGraphicsEllipseItem):
    """A small handle for resizing mask edges."""
    
    def __init__(self, edge: str, parent_mask: 'EditableMaskItem'):
        super().__init__(-4, -4, 8, 8)
        self.edge = edge
        self.parent_mask = parent_mask
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(self._get_cursor())
        
        self.setBrush(QBrush(QColor(255, 255, 255, 200)))
        self.setPen(QPen(QColor(0, 0, 0), 1))
        
        self.setZValue(10)
        
    def _get_cursor(self) -> QCursor:
        """Get appropriate cursor for the edge."""
        if self.edge in ['top', 'bottom']:
            return QCursor(Qt.CursorShape.SizeVerCursor)
        elif self.edge in ['left', 'right']:
            return QCursor(Qt.CursorShape.SizeHorCursor)
        return QCursor(Qt.CursorShape.ArrowCursor)
    
    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
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
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.parent_mask.handle_moved(self.edge, self.pos())
        return super().itemChange(change, value)


class EditableMaskItem(QGraphicsRectItem):
    """An editable rectangular mask with edge drag handles."""
    
    def __init__(self, mask_id: str, points: List[List[float]], parent: Optional[QGraphicsItem] = None):
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
        self.handles: Dict[str, EdgeHandle] = {}
        self.is_updating_handles = False
        
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        
        self.default_brush = QBrush(QColor(0, 0, 255, 100))
        self.hover_brush = QBrush(QColor(0, 0, 255, 150))
        self.selected_brush = QBrush(QColor(255, 165, 0, 180))
        self.default_pen = QPen(QColor(0, 0, 255), 1)
        self.selected_pen = QPen(QColor(255, 165, 0), 2.5)
        
        self.setBrush(self.default_brush)
        self.setPen(self.default_pen)
        self.setAcceptHoverEvents(True)
        
        self._create_handles()
        self._update_handle_positions()
        self._set_handles_visible(False)
    
    def _create_handles(self):
        """Create edge handles for resizing."""
        for edge in ['top', 'bottom', 'left', 'right']:
            handle = EdgeHandle(edge, self)
            handle.setParentItem(self)
            self.handles[edge] = handle
    
    def _update_handle_positions(self):
        """Update handle positions based on current rectangle."""
        if self.is_updating_handles:
            return
            
        rect = self.rect()
        positions = {
            'top': QPointF(rect.center().x(), rect.top()),
            'bottom': QPointF(rect.center().x(), rect.bottom()),
            'left': QPointF(rect.left(), rect.center().y()),
            'right': QPointF(rect.right(), rect.center().y())
        }
        
        for edge, pos in positions.items():
            self.handles[edge].setPos(pos)
    
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
        self._update_handle_positions()
        
        self.is_updating_handles = False
        
        if self.scene() and hasattr(self.scene(), 'on_mask_geometry_changed'):
            self.scene().on_mask_geometry_changed(self.mask_id)
    
    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if self.isSelected():
                self.setBrush(self.selected_brush)
                self.setPen(self.selected_pen)
                self._set_handles_visible(True)
                if self.scene() and hasattr(self.scene(), 'on_mask_selection_changed'):
                    self.scene().on_mask_selection_changed(self)
            else:
                self.setBrush(self.default_brush)
                self.setPen(self.default_pen)
                self._set_handles_visible(False)
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._update_handle_positions()
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
        rect = self.rect()
        pos = self.pos()
        
        # Adjust coordinates by item position
        x0 = rect.left() + pos.x()
        y0 = rect.top() + pos.y()
        x1 = rect.right() + pos.x()
        y1 = rect.bottom() + pos.y()
        
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
