"""Entry point for the TCT Setup application."""
import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tct_gui import TCTMainWindow
from gui.style import apply_theme

_HERE = Path(__file__).parent


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    _setup_logging()
    # Opt-in QML chrome shell (TCT_QML_SHELL=1): pin the Qt Quick scene-graph to
    # OpenGL BEFORE any QQuickWidget/QApplication-driven Quick window exists, so
    # the chrome QQuickWidget and the Motor Stage GLViewWidget agree on one RHI
    # backend (docs/research/qml_hybrid_architecture.md §6). No-op by default.
    if os.environ.get("TCT_QML_SHELL") == "1":
        from gui.qml_shell import pin_opengl_rhi
        pin_opengl_rhi()
    app = QApplication(sys.argv)
    app.setApplicationName("TCT Setup")
    # Apply the last-used theme before building the window so there is no flash.
    from PySide6.QtCore import QSettings
    saved_theme = str(QSettings("TCT", "TCTSetup").value("theme", "light"))
    # Theme-editor customization (theme/* keys: palette overrides, glass
    # amount, typography, radius) loads alongside the saved dark/light choice
    # so the first QSS build already carries it (gui/theme_editor.py).
    from gui.style import load_theme_customization
    load_theme_customization()
    apply_theme(app, saved_theme)
    window = TCTMainWindow(config_path=str(_HERE / "configs" / "devices.yaml"))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
