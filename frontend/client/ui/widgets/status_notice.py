from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class StatusNotice(QLabel):
    """Reserve space for operation feedback only when there is a message."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MutedLabel")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.hide()

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))
