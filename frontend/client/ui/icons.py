"""Resolution-independent line icons for the desktop interface."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def app_icon(kind: str, color: str = "#8B819B", active: str = "#9273D5") -> QIcon:
    icon = QIcon()
    for state, ink in ((QIcon.State.Off, color), (QIcon.State.On, active)):
        pixmap = QPixmap(48, 48)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(ink), 1.7, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if kind == "grid":
            for x, y in ((4, 4), (14, 4), (4, 14), (14, 14)):
                painter.drawRoundedRect(x, y, 6, 6, 1.5, 1.5)
        elif kind == "search":
            painter.drawEllipse(4, 4, 12, 12)
            painter.drawLine(15, 15, 21, 21)
        elif kind == "case":
            painter.drawRoundedRect(3, 7, 18, 14, 3, 3)
            painter.drawRoundedRect(8, 3, 8, 4, 1, 1)
            painter.drawLine(3, 12, 21, 12)
            painter.drawLine(12, 11, 12, 15)
        elif kind == "mail":
            painter.drawRoundedRect(3, 5, 18, 14, 3, 3)
            painter.drawLine(4, 7, 12, 13)
            painter.drawLine(12, 13, 20, 7)
        elif kind == "sync":
            painter.drawArc(4, 4, 16, 16, 35 * 16, 145 * 16)
            painter.drawArc(4, 4, 16, 16, 215 * 16, 145 * 16)
            painter.drawLine(4, 6, 4, 12)
            painter.drawLine(4, 12, 9, 12)
            painter.drawLine(20, 12, 20, 18)
            painter.drawLine(20, 12, 15, 12)
        elif kind == "calendar":
            painter.drawRoundedRect(4, 5, 16, 16, 3, 3)
            painter.drawLine(4, 10, 20, 10)
            painter.drawLine(8, 3, 8, 7)
            painter.drawLine(16, 3, 16, 7)
            painter.drawLine(8, 14, 11, 14)
            painter.drawLine(14, 17, 16, 17)
        elif kind == "check":
            painter.drawEllipse(3, 3, 18, 18)
            painter.drawLine(7, 12, 10, 15)
            painter.drawLine(10, 15, 17, 8)
        elif kind == "spark":
            path = QPainterPath(QPointF(12, 2))
            for x, y in ((14.8, 9.2), (22, 12), (14.8, 14.8),
                         (12, 22), (9.2, 14.8), (2, 12), (9.2, 9.2)):
                path.lineTo(x, y)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawRoundedRect(3, 4, 18, 14, 3, 3)
            painter.drawLine(7, 9, 17, 9)
            painter.drawLine(7, 13, 14, 13)
            painter.drawLine(8, 18, 6, 21)
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon
