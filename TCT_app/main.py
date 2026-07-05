"""Entry point for the TCT Setup application."""
import logging
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
    app = QApplication(sys.argv)
    app.setApplicationName("TCT Setup")
    # Apply the last-used theme before building the window so there is no flash.
    from PySide6.QtCore import QSettings
    saved_theme = str(QSettings("TCT", "TCTSetup").value("theme", "light"))
    apply_theme(app, saved_theme)
    window = TCTMainWindow(config_path=str(_HERE / "configs" / "devices.yaml"))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
