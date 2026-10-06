from __future__ import annotations

from PySide6.QtCore import QDateTime, QTime, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from client.ui.widgets.glass_combo import GlassComboBox


class DateTimePickerDialog(QDialog):
    """同时提供日历、小时和分钟的完整日期时间选择弹窗。"""

    def __init__(
        self,
        parent: QWidget,
        *,
        title: str,
        value: QDateTime | None,
    ) -> None:
        super().__init__(parent)
        self.result_value: QDateTime | None = value if value and value.isValid() else None
        initial = self.result_value or QDateTime.currentDateTime()

        self.setModal(True)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(540)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        surface = QFrame()
        surface.setObjectName("DateTimePickerSurface")
        content = QVBoxLayout(surface)
        content.setContentsMargins(0, 0, 0, 20)
        content.setSpacing(0)

        accent = QFrame()
        accent.setObjectName("DialogAccent")
        accent.setFixedHeight(5)
        content.addWidget(accent)

        header = QHBoxLayout()
        header.setContentsMargins(24, 18, 16, 10)
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        close_button = QPushButton("×")
        close_button.setObjectName("DialogClose")
        close_button.setToolTip("关闭")
        close_button.clicked.connect(self.reject)
        header.addWidget(title_label)
        header.addStretch()
        header.addWidget(close_button)
        content.addLayout(header)

        self.calendar = QCalendarWidget()
        self.calendar.setObjectName("DateTimeCalendar")
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setSelectedDate(initial.date())
        content.addWidget(self.calendar)

        time_row = QHBoxLayout()
        time_row.setContentsMargins(24, 14, 24, 16)
        time_row.setSpacing(10)
        time_label = QLabel("具体时间")
        time_label.setObjectName("PickerFieldLabel")
        self.hour_combo = GlassComboBox()
        self.hour_combo.setObjectName("TimePartCombo")
        self.hour_combo.addItems([f"{hour:02d} 时" for hour in range(24)])
        self.hour_combo.setCurrentIndex(initial.time().hour())
        self.minute_combo = GlassComboBox()
        self.minute_combo.setObjectName("TimePartCombo")
        self.minute_combo.addItems([f"{minute:02d} 分" for minute in range(60)])
        self.minute_combo.setCurrentIndex(initial.time().minute())
        for combo in (self.hour_combo, self.minute_combo):
            combo.setMaxVisibleItems(8)
            combo.view().setMaximumHeight(344)
            combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        time_row.addWidget(time_label)
        time_row.addStretch()
        time_row.addWidget(self.hour_combo)
        time_row.addWidget(QLabel(":"))
        time_row.addWidget(self.minute_combo)
        content.addLayout(time_row)

        actions = QHBoxLayout()
        actions.setContentsMargins(24, 0, 24, 0)
        actions.setSpacing(10)
        clear_button = QPushButton("清空时间")
        clear_button.setObjectName("DangerButton")
        clear_button.clicked.connect(self._clear_value)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("SecondaryButton")
        cancel_button.clicked.connect(self.reject)
        confirm_button = QPushButton("确定")
        confirm_button.setObjectName("PrimaryButton")
        confirm_button.setDefault(True)
        confirm_button.clicked.connect(self._accept_value)
        actions.addWidget(clear_button)
        actions.addStretch()
        actions.addWidget(cancel_button)
        actions.addWidget(confirm_button)
        content.addLayout(actions)
        root.addWidget(surface)

    def _accept_value(self) -> None:
        """组合选中的日期、小时和分钟并返回。"""
        self.result_value = QDateTime(
            self.calendar.selectedDate(),
            QTime(self.hour_combo.currentIndex(), self.minute_combo.currentIndex()),
        )
        self.accept()

    def _clear_value(self) -> None:
        """明确清空当前时间，而不是将其替换为今天。"""
        self.result_value = None
        self.accept()


class DateTimePicker(QWidget):
    """表格中的日期时间选择器入口，点击后打开完整选择弹窗。"""

    dateTimeChanged = Signal()

    def __init__(self, value: str | None, title: str, parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self._value = _parse_datetime(value)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        self.button = QPushButton()
        self.button.setObjectName("DateTimePickerButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._open_picker)
        layout.addWidget(self.button)
        self._refresh_text()

    def value(self) -> str | None:
        if self._value is None:
            return None
        return self._value.toString("yyyy-MM-dd HH:mm")

    def set_value(self, value: str | None) -> None:
        self._value = _parse_datetime(value)
        self._refresh_text()

    def _open_picker(self) -> None:
        dialog = DateTimePickerDialog(self, title=self.title, value=self._value)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.result_value == self._value:
            return
        self._value = dialog.result_value
        self._refresh_text()
        self.dateTimeChanged.emit()

    def _refresh_text(self) -> None:
        if self._value is None:
            self.button.setText("选择时间")
            self.button.setProperty("empty", True)
            self.button.setToolTip(f"点击{self.title}")
        else:
            text = self._value.toString("yyyy-MM-dd HH:mm")
            self.button.setText(text)
            self.button.setProperty("empty", False)
            self.button.setToolTip(f"{text} · 点击重新选择")
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """滚轮只能继续传递给表格，不能修改选择器中的时间。"""
        event.ignore()


def _parse_datetime(value: str | None) -> QDateTime | None:
    """解析 Mock 和服务端返回的常见日期时间格式。"""
    if not value:
        return None
    for date_format in ("yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm"):
        parsed = QDateTime.fromString(value, date_format)
        if parsed.isValid():
            return parsed
    parsed = QDateTime.fromString(value, Qt.DateFormat.ISODate)
    return parsed if parsed.isValid() else None
