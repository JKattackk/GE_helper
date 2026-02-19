from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QRect, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer, QObject
from PyQt6.QtGui import QColor, QPalette


class HistoryItemLabel(QLabel):
    """label that tracks item ID and emits signal on click"""
    clicked = pyqtSignal(str, str)  # emits (itemID, itemName)
    
    def __init__(self, text, item_id, parent=None):
        super().__init__(text, parent)
        self.item_id = item_id
        self.item_name = text
        
    def mousePressEvent(self, event):
        #emit clicked signal when label is clicked
        self.clicked.emit(self.item_id, self.item_name)
        super().mousePressEvent(event)


class SideBar(QWidget):
    """
    sidebar for displaying item history
    button sticks out and stays visible when collapsed
    draws over  main application
    """
    # Signal emitted when a history item is clicked
    history_item_clicked = pyqtSignal(str, str)  # Emits (itemID, itemName)
    
    def __init__(self, parent=None, top_offset=0):
        super().__init__(parent)
        self.is_expanded = False
        self.animation = None
        self.expanded_width = 300
        self.button_width = 16
        self.button_height = 24
        self.collapsed_width = self.button_width
        self.top_offset = top_offset  # offset from top of parent widget
        
        # set up as overlay widget
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # set transparent background color so underlying widgets show through
        self.setStyleSheet("background-color: transparent;")
        
        self.init_ui()
        
        if parent:
            QTimer.singleShot(50, self.position_sidebar)
        
    def init_ui(self):
        """Initialize the sidebar UI"""
        # Don't set background color on main widget - it will be transparent
        # Only child widgets have background colors
        
        # Main layout - horizontal to hold button and content side by side
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Toggle button (always visible on the left)
        self.toggle_button = QPushButton()
        self.toggle_button.setText("◀")
        self.toggle_button.setFixedSize(self.button_width, self.button_height)
        self.toggle_button.setStyleSheet("""
            QPushButton {
                color: #f5f5f5;
                background-color: rgb(80, 80, 80);
                border: 1px solid rgb(150, 150, 150);
                border-right: none;
                font-weight: bold;
                font-size: 14px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background-color: rgb(90, 90, 90);
            }
            QPushButton:pressed {
                background-color: rgb(60, 60, 60);
            }
        """)
        self.toggle_button.clicked.connect(self.toggle)
        self.main_layout.addWidget(self.toggle_button, 0, Qt.AlignmentFlag.AlignTop)
        
        # Sidebar content (collapsible)
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background-color: rgb(80, 80, 80);")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)

        # Header
        self.header_label = QLabel("History")
        self.header_label.setStyleSheet("""
            QLabel {
                color: #f5f5f5;         
                font-weight: bold;
                font-size: 14px;

            }
        """)
        self.content_layout.addWidget(self.header_label)
        
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        self.content_layout.addWidget(divider)
        
        # scroll area for history items
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: rgb(80, 80, 80);
            }
        """)
        
        # content area (placeholder for history items)
        self.history_content = QWidget()
        self.history_layout = QVBoxLayout(self.history_content)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        
        placeholder = QLabel("Item history will appear here")
        placeholder.setStyleSheet("color: #f5f5f5; font-style: italic;")
        self.history_layout.addWidget(placeholder)
        self.history_layout.addStretch()
        
        self.scroll_area.setWidget(self.history_content)
        self.content_layout.addWidget(self.scroll_area)
        
        self.main_layout.addWidget(self.content_widget, 1)
        
        # Start collapsed - content hidden
        self.content_widget.setVisible(False)
        
    def position_sidebar(self):
        """Position the sidebar at the right edge of the parent widget, below the header"""
        if self.parent():
            parent = self.parent()
            # get parent's geometry relative to itself
            parent_rect = parent.rect()
            # position at the right edge, starting from top_offset
            x = parent_rect.right() - self.collapsed_width
            y = self.top_offset
            height = parent_rect.height() - self.top_offset
            self.setGeometry(x, y, self.collapsed_width, height)
            self.raise_()  # ensure it draws on top
        
    def toggle(self):
        """Toggle between expanded and collapsed states"""
        if self.is_expanded:
            self.collapse()
        else:
            self.expand()
    
    def expand(self):
        """expand the sidebar"""
        if self.is_expanded:
            return
        
        self.is_expanded = True
        self.content_widget.setVisible(True)
        self.toggle_button.setText("▶")
        
        # animate from current width to expanded width
        self.animate_width(self.collapsed_width, self.button_width + self.expanded_width)
    
    def collapse(self):
        """Collapse the sidebar"""
        if not self.is_expanded:
            return
        
        self.is_expanded = False
        self.toggle_button.setText("◀")
        
        # animate from current width to collapsed width
        self.animate_width(self.width(), self.collapsed_width)
        
        # hide content after animation completes
        QTimer.singleShot(300, lambda: self.content_widget.setVisible(False))
    
    def animate_width(self, start_width, end_width):
        """Animate the width change"""
        if self.animation:
            self.animation.stop()
        
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        
        # get current geometry
        current_geom = self.geometry()
        parent = self.parent()
        
        if not parent:
            return
        
        parent_rect = parent.rect()
        
        # calculate start position (aligned to right edge)
        start_x = parent_rect.right() - start_width
        # calculate end position (aligned to right edge)
        end_x = parent_rect.right() - end_width
        
        # calculate height accounting for top offset
        height = parent_rect.height() - self.top_offset
        
        # set animation start and end values
        self.animation.setStartValue(QRect(start_x, self.top_offset, start_width, height))
        self.animation.setEndValue(QRect(end_x, self.top_offset, end_width, height))
        
        self.animation.start()
    
    def get_content_area(self):
        """
        returns the layout of the history content area for adding items.
        allows external code to add history items to the sidebar.
        """
        return self.history_layout
    
    def add_history_item(self, text, item_id=None):
        """
        adds a history item to the sidebar.
        
        args:
            text (str): The text to display for the history item
            item_id (str): The item ID associated with this history item
        """
        # remove placeholder if it exists and is the first item
        if self.history_layout.count() > 0:
            first_item = self.history_layout.itemAt(0)
            if first_item and isinstance(first_item.widget(), QLabel):
                label = first_item.widget()
                if "will appear here" in label.text():
                    self.history_layout.removeWidget(label)
                    label.deleteLater()

        # if the item is already in the history remove it
        for i in range(self.history_layout.count()):
            item = self.history_layout.itemAt(i)
            if item and isinstance(item.widget(), HistoryItemLabel):
                if item.widget().text() == text:
                    self.history_layout.removeWidget(item.widget())
                    break
                
        item_label = HistoryItemLabel(text, item_id)
        item_label.setStyleSheet("""
            QLabel {
                padding: 8px;
                background-color: rgb(120, 120, 120);
                border: 1px solid rgb(100, 100, 100);
                border-radius: 3px;
                color: #f5f5f5;
            }
            QLabel:hover {
                background-color: rgb(140, 140, 140);
            }
        """)
        item_label.setWordWrap(False)

        # Connect the clicked signal from the label to the sidebar's signal
        item_label.clicked.connect(self.history_item_clicked.emit)
        self.history_layout.insertWidget(0, item_label)

        # remove last item when total number of items in history exceeds 30
        if self.history_layout.count() > 30:
            self.history_layout.removeWidget(self.history_layout.itemAt(self.history_layout.count()-2).widget())

    def get_history(self):
        # placeholder for now
        history = []
        for i in range(self.history_layout.count()):
            item = self.history_layout.itemAt(i)
            if item and isinstance(item.widget(), QLabel):
                history.append(item.widget().text())
        return history
    
    def resizeEvent(self, event):
        """Handle parent resize events to adjust sidebar position"""
        super().resizeEvent(event)
        # don't adjust position here - let parent resize drive it
    
    def showEvent(self, event):
        """Handle show event to ensure proper positioning"""
        super().showEvent(event)
        self.position_sidebar()
    
    def moveEvent(self, event):
        """Handle parent widget moving"""
        super().moveEvent(event)
        # if parent moved, ensure we stay positioned correctly
        if self.parent():
            self.raise_()
    
    def mousePressEvent(self, event):
        """Handle mouse press events"""
        # propagate mouse events to child widgets
        super().mousePressEvent(event)


