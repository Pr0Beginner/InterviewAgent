"""Render the actual Qt client with in-memory demo data, without network access.

Usage: .venv/Scripts/python -m scripts.preview_client --output docs/ui-preview
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase

from client.api.mock_api import MockApiClient
from client.ui.main_window import MainWindow


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/ui-preview"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    # Qt's Windows offscreen backend starts with an empty font database.
    if sys.platform == "win32":
        font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisb.ttf"):
            QFontDatabase.addApplicationFont(str(font_dir / filename))
        app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow(MockApiClient())
    window.show()
    deadline = time.monotonic() + 5
    while window.jobs_page.runner.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if window.jobs_page.runner.busy:
        window.close()
        raise RuntimeError("Preview data did not finish loading")
    for index, name in enumerate(("applications", "recommendations", "interview")):
        window._navigate_to(index, window.nav_buttons[index])
        if app.focusWidget():
            app.focusWidget().clearFocus()
        window.resize(1680, 960)
        app.processEvents()
        app.processEvents()
        path = args.output / f"{name}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"Cannot save {path}")
        print(path.resolve())
    window._navigate_to(0, window.nav_buttons[0])
    if app.focusWidget():
        app.focusWidget().clearFocus()
    window.resize(1180, 720)
    app.processEvents()
    app.processEvents()
    window.grab().save(str(args.output / "applications-compact.png"))
    print(f"Compact window: {window.width()} x {window.height()}")
    window.close()
    app.processEvents()


if __name__ == "__main__":
    main()
