"""Paint the soft ambient background underneath translucent native widgets."""

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


def soft_shadow(widget: QWidget, blur: int = 26, opacity: int = 20, offset: int = 7) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setColor(QColor(63, 45, 96, opacity))
    effect.setOffset(0, offset)
    widget.setGraphicsEffect(effect)


class AmbientBackground(QWidget):
    """Resolution-independent lavender, peach and aqua light fields."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        base = QLinearGradient(0, 0, w * 0.7, h)
        base.setColorAt(0, QColor("#EFEBE8"))
        base.setColorAt(0.5, QColor("#EEEDF2"))
        base.setColorAt(1, QColor("#D9E3E8"))
        painter.fillRect(self.rect(), base)
        for x, y, radius, color in (
            (0.04, 1.07, 0.64, QColor(225, 156, 142, 200)),
            (0.46, 0.89, 0.62, QColor(183, 160, 222, 195)),
            (0.98, 0.95, 0.53, QColor(149, 202, 211, 195)),
            (0.77, 0.18, 0.50, QColor(255, 255, 255, 220)),
        ):
            glow = QRadialGradient(QPointF(w * x, h * y), h * radius)
            glow.setColorAt(0, color)
            glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            painter.fillRect(self.rect(), glow)
        wave = QPainterPath(QPointF(-20, h * 0.88))
        wave.cubicTo(w * 0.32, h * 0.93, w * 0.61, h * 0.47, w + 20, h * 0.56)
        wave.lineTo(w + 20, h + 20)
        wave.lineTo(-20, h + 20)
        wave.closeSubpath()
        painter.fillPath(wave, QColor(255, 255, 255, 42))
        painter.end()
