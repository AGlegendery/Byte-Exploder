# Byte Exploder — By AGlegend (https://github.com/AGlegendery)
"""
app_qt.py
---------
Entry point for the older Qt (PySide6) UI of Byte Exploder. The main app is
now app.py (webview UI); this one needs PySide6 with QtUiTools.

Run:
    python app_qt.py
Open a file directly:
    python app_qt.py path/to/image.png
"""

import os

# Raise the memory Qt allows for loading an image (in MB).
os.environ.setdefault("QT_IMAGEIO_MAXALLOC", "2048")

import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    # Allow opening a .png/.expld by passing it as an argument.
    if len(sys.argv) > 1:
        path = sys.argv[1]
        try:
            if isinstance(path, str) and path.lower().endswith((".png", ".expld")):
                window.le_image_file.setText(path)
                window.show_preview(path)
        except Exception:
            pass

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
