from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 kurulu degil. Once: pip install -e '.[gui]'", file=sys.stderr)
        return 2

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("EPUB to M4B")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
