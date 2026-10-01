from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from client.api import HybridApiClient
from client.ui.main_window import MainWindow


def main() -> int:
    """启动桌面客户端，并在退出时关闭 HTTP 连接池。
    
    返回值:
        Qt 应用退出码。
    """
    app = QApplication(sys.argv)
    app.setApplicationName("Interview Assistant")
    api = HybridApiClient()
    app.aboutToQuit.connect(api.close)
    window = MainWindow(api)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
