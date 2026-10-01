from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AppDialog(QDialog):
    """与主界面视觉一致的模态弹窗，避免使用系统原生消息框。"""

    CANCEL = 0
    PRIMARY = 1
    DESTRUCTIVE = 2

    def __init__(
        self,
        parent: QWidget,
        *,
        title: str,
        message: str,
        detail: str = "",
        primary_text: str = "确定",
        destructive_text: str | None = None,
        cancel_text: str | None = "取消",
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(470)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        surface = QFrame()
        surface.setObjectName("DialogSurface")
        shadow = QGraphicsDropShadowEffect(surface)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(72, 48, 103, 55))
        surface.setGraphicsEffect(shadow)
        content = QVBoxLayout(surface)
        content.setContentsMargins(0, 0, 0, 18)
        content.setSpacing(0)

        accent = QFrame()
        accent.setObjectName("DialogAccent")
        accent.setFixedHeight(5)
        content.addWidget(accent)

        header = QHBoxLayout()
        header.setContentsMargins(24, 20, 16, 0)
        header.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        close_button = QPushButton("×")
        close_button.setObjectName("DialogClose")
        close_button.setToolTip("关闭")
        close_button.clicked.connect(lambda: self.done(self.CANCEL))
        header.addWidget(title_label)
        header.addStretch()
        header.addWidget(close_button)
        content.addLayout(header)

        body = QVBoxLayout()
        body.setContentsMargins(24, 14, 24, 20)
        body.setSpacing(8)
        message_label = QLabel(message)
        message_label.setObjectName("DialogMessage")
        message_label.setWordWrap(True)
        body.addWidget(message_label)
        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("DialogDetail")
            detail_label.setWordWrap(True)
            body.addWidget(detail_label)
        content.addLayout(body)

        actions = QHBoxLayout()
        actions.setContentsMargins(24, 0, 24, 0)
        actions.setSpacing(10)
        actions.addStretch()
        if cancel_text:
            cancel_button = QPushButton(cancel_text)
            cancel_button.setObjectName("SecondaryButton")
            cancel_button.clicked.connect(lambda: self.done(self.CANCEL))
            actions.addWidget(cancel_button)
        if destructive_text:
            destructive_button = QPushButton(destructive_text)
            destructive_button.setObjectName("DangerButton")
            destructive_button.clicked.connect(lambda: self.done(self.DESTRUCTIVE))
            actions.addWidget(destructive_button)
        primary_button = QPushButton(primary_text)
        primary_button.setObjectName("PrimaryButton")
        primary_button.clicked.connect(lambda: self.done(self.PRIMARY))
        primary_button.setDefault(True)
        actions.addWidget(primary_button)
        content.addLayout(actions)

        root.addWidget(surface)

    @classmethod
    def show_error(cls, parent: QWidget, title: str, message: str) -> None:
        """显示只有一个确认操作的错误提示。"""
        cls(
            parent,
            title=title,
            message=message,
            detail="请检查输入内容或服务端连接后重试。",
            primary_text="知道了",
            cancel_text=None,
        ).exec()
