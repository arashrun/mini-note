import sys

from PySide6.QtWidgets import QApplication

from notebook_app.window import NotebookWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Paperbound")
    window = NotebookWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
