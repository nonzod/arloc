"""Avvio dell'interfaccia grafica."""
from __future__ import annotations

import sys


def run() -> int:
    from PySide6.QtWidgets import QApplication

    from arloc.ui.common import style_path
    from arloc.ui.main_window import MainWindow

    from PySide6.QtCore import QLocale
    QLocale.setDefault(QLocale(QLocale.Italian, QLocale.Italy))
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Arloc")
    app.setOrganizationName("Arloc")
    try:
        app.setStyleSheet(style_path().read_text(encoding="utf-8"))
    except OSError:
        pass
    win = MainWindow()
    win.show()
    return app.exec()
