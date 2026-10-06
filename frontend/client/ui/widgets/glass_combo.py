"""Shared pearl dropdowns, retaining Qt's selection and keyboard behavior."""

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainterPath, QPen, QRegion, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QListView, QStyle, QStyledItemDelegate,
)

class _OptionDelegate(QStyledItemDelegate):
    def __init__(self, combo: QComboBox):
        super().__init__(combo)
        self.combo = combo

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width() + 64, max(36, size.height() + 12))

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(3, 1, -3, -1)
        current = index.row() == self.combo.currentIndex()
        active = bool(option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        if current or active:
            fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
            fill.setColorAt(0, QColor("#F1EAFB" if current else "#F7F3FC"))
            fill.setColorAt(1, QColor("#E8DDF7" if current else "#F0EAF8"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 8, 8)
        text_rect = rect.adjusted(12, 0, -30, 0)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if self.combo.property("statusSelector"):
            ink = {"Offer": "#7B9A8A", "已结束": "#B5AEBD", "全部": "#A69BB6"}.get(text, "#AE96D8")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ink))
            painter.drawEllipse(QPointF(rect.left() + 15, rect.center().y()), 3, 3)
            text_rect.adjust(14, 0, 0, 0)
        painter.setFont(option.font)
        painter.setPen(QColor("#A59CAB" if not enabled else "#72559F" if current else "#554B63"))
        label = option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        if current:
            painter.setPen(QPen(QColor("#9C7CCC"), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x, y = rect.right() - 19, rect.center().y()
            painter.drawLine(QPointF(x - 4, y), QPointF(x - 1, y + 3))
            painter.drawLine(QPointF(x - 1, y + 3), QPointF(x + 5, y - 3))
        painter.restore()


class GlassComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMaxVisibleItems(7)
        view = QListView()
        view.setObjectName("ComboPopup")
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setSpacing(2)
        view.setMouseTracking(True)
        view.setUniformItemSizes(True)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setView(view)
        self.setItemDelegate(_OptionDelegate(self))
        popup = view.window()
        popup.setObjectName("ComboPopupWindow")
        # Opaque popup + a native rounded mask avoids Windows rendering the
        # translucent shadow gutter as a black rectangle.
        popup.setStyleSheet(
            "QFrame#ComboPopupWindow { background: #F8F4FD; "
            "border: 1px solid #E1D5EF; border-radius: 13px; }"
        )
        popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        popup.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        if isinstance(popup, QFrame):
            popup.setFrameShape(QFrame.Shape.NoFrame)
        popup.layout().setContentsMargins(1, 1, 1, 1)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """未展开时把滚轮事件交给父容器，避免意外改变当前选项。"""
        event.ignore()

    def showPopup(self) -> None:
        if not self.count():
            return
        widest = max(self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count()))
        self.view().setMinimumWidth(max(176, widest + 80, self.width() - 2))
        super().showPopup()
        popup = self.view().window()
        # Keep the menu below its control when possible, and inside the screen.
        screen = self.screen().availableGeometry()
        view = self.view()
        margins = view.contentsMargins()
        inset = margins.top() + margins.bottom()
        row_height = view.sizeHintForRow(0) + 2 * view.spacing()
        height_limit = min(view.maximumHeight(), screen.height() - 2)
        rows = min(self.count(), self.maxVisibleItems(), max(1, (height_limit - inset) // row_height))
        popup.resize(popup.width(), rows * row_height + inset + 2)
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(popup.rect()), 13, 13)
        popup.setMask(QRegion(outline.toFillPolygon().toPolygon()))
        below = self.mapToGlobal(QPoint(0, self.height() + 4))
        above = self.mapToGlobal(QPoint(0, -4))
        x = max(screen.left(), min(below.x(), screen.right() - popup.width() + 1))
        y = below.y()
        if y + popup.height() > screen.bottom() + 1:
            y = above.y() - popup.height()
        popup.move(x, max(screen.top(), y))
        self.view().scrollTo(self.view().currentIndex(), QAbstractItemView.ScrollHint.EnsureVisible)
