"""Entry point for the TCT Setup application."""
import logging
import os
import sys
from pathlib import Path

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from tct_gui import TCTMainWindow
from gui.app_settings import theme_mode
from gui.style import apply_theme

_HERE = Path(__file__).parent


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def _enable_translucent_window_surface() -> None:
    """Request an 8-bit alpha channel on the DEFAULT window surface, BEFORE the
    QApplication exists — the documented Qt remedy (Qt forum #142890) for a
    QMainWindow whose client would otherwise carry no per-pixel alpha down to
    DWM, so a Mica/Acrylic backdrop can actually composite through the
    translucent window canvas (docs/research/dwm_backdrop_blur_recipe.md item 2).

    Scoped, not clobbering: it MERGES an alpha channel into whatever default
    format is already in effect rather than replacing it. It does not collide
    with the opt-in QML shell's OpenGL RHI pin (that sets the graphics API via
    QQuickWindow.setGraphicsApi, not QSurfaceFormat). And it is inert for the
    plot stack: the raster pyqtgraph plots do not use a QSurfaceFormat at all,
    so the extra buffer is simply unused there — it only matters for the
    window's own translucent canvas.

    (Until 2026-07-13 this note also had to reason about the Motor-Stage
    GLViewWidget; that render-to-texture child is gone with the 3D stage view,
    which is exactly what lets the classic window carry a DWM material at all —
    see tests/test_no_render_to_texture_children_in_gui.py.)"""
    fmt = QSurfaceFormat.defaultFormat()
    if fmt.alphaBufferSize() < 8:
        fmt.setAlphaBufferSize(8)
        QSurfaceFormat.setDefaultFormat(fmt)


def main() -> None:
    _setup_logging()
    # Opt-in QML chrome shell (TCT_QML_SHELL=1): pin the Qt Quick scene-graph to
    # OpenGL BEFORE any QQuickWidget/QApplication-driven Quick window exists, so
    # every accelerated surface in the process agrees on one RHI backend
    # (docs/research/qml_hybrid_architecture.md §6). No-op by default. The pin's
    # original second client, the Motor-Stage GLViewWidget, is gone (2026-07-13).
    if os.environ.get("TCT_QML_SHELL") == "1":
        from gui.qml_shell import pin_opengl_rhi
        pin_opengl_rhi()
    # Alpha-carrying default window surface (before the QApplication) so a DWM
    # backdrop material can composite through a translucent QMainWindow client
    # — see the function docstring for why this is safe for the plot/QML stacks.
    _enable_translucent_window_surface()
    app = QApplication(sys.argv)
    app.setApplicationName("TCT Setup")
    # Apply the last-used theme before building the window so there is no flash.
    saved_theme = theme_mode()
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
