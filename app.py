# Byte Exploder — By AGlegend (https://github.com/AGlegendery)
"""
app.py
------
Entry point for the Byte Exploder desktop app (webview UI: web/ + web_api.py).
The older Qt UI is still available as app_qt.py.

Run:
    python app.py
Open an image directly (file association / double-click):
    python app.py path/to/image.png
"""

import os
import sys

try:
    import webview
except ImportError:  # pragma: no cover
    sys.exit(
        "Byte Exploder needs pywebview:  pip install pywebview\n"
        "(the older Qt UI is still available: python app_qt.py)"
    )

from web_api import Api

HERE = os.path.dirname(os.path.abspath(__file__))


def _gui():
    """On Linux use GTK/WebKit2 when available: pywebview would otherwise try a
    Qt web engine first (and print a traceback if it is missing)."""
    if sys.platform.startswith("linux"):
        try:
            import gi  # noqa: F401
            return "gtk"
        except ImportError:
            pass
    return None


def main() -> int:
    initial_image = None
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith((".png", ".expld")):
        initial_image = os.path.abspath(sys.argv[1])

    api = Api(initial_image=initial_image)
    window = webview.create_window(
        "Byte Exploder — By AGlegend",
        url=os.path.join(HERE, "web", "index.html"),
        js_api=api,
        width=1100,
        height=780,
        min_size=(880, 640),
    )
    api._attach(window)
    webview.start(gui=_gui(), debug=bool(os.environ.get("BYTE_EXPLODER_DEBUG")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
