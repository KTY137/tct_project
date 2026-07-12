"""Theme editor dialog (View ▸ Theme…) — browse presets and configure the
theme: colors, fonts, corner radius, and the glass<->opaque material amount
(Kaya request 2026-07-12).

All state lives in ``gui/style.py``'s override layer (apply_theme_overrides /
set_glass_amount / apply_typography / apply_radius_scale) — this dialog is
pure view/wiring on top of it, persisted via QSettings("TCT", "TCTSetup")
under ``theme/*``. Applying routes through the SAME machinery as the View
menu's dark-mode toggle (tct_gui._toggle_theme, via the ``applyRequested``
signal), so QSS regeneration, the QML Theme singleton, and every panel's
``refresh_theme`` all fire exactly as they do today.

Safety palette (danger/armed/sim/error — laws 1/2/6) is rendered as locked,
read-only swatches with no color-dialog path; ``style.sanitize_overrides``
additionally drops any such key from a loaded preset JSON, so there is no
override path even by hand-editing the registry.

This dialog is also the first consumer of the settings-row grammar: label on
the left, compact control on the right (``_settings_row`` below).

No inline hex anywhere in this module (guard: tests/test_no_inline_hex_gui.py)
— every color is resolved at runtime from ``style.palette(mode)`` or picked by
the user through ``QColorDialog``.
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSlider,
    QSpinBox, QVBoxLayout, QWidget,
)

from gui import style
from gui.panel_kit import Card, SegmentedControl
from gui.style import RADIUS_XS, SPACE_MD, SPACE_SM, SPACE_XS

PRESETS_KEY = "theme/presets"

# Editable swatch rows: (token group, human label) — token groups are
# style.EDITABLE_TOKENS; one swatch fans out per style._OVERRIDE_FANOUT.
_COLOR_ROWS: tuple[tuple[str, str], ...] = (
    ("accent", "Accent"),
    ("canvas", "Background / canvas"),
    ("panel", "Panel"),
    ("well", "Input well / sunk"),
    ("text", "Text"),
    ("muted", "Muted text"),
    ("hairline", "Hairlines"),
)

# Locked, read-only safety swatches (laws 1/2/6). crit/warn are byte-aliases
# of danger/armed and are locked in style.SAFETY_TOKENS too; only the four
# canonical names are shown.
_LOCKED_ROWS: tuple[tuple[str, str], ...] = (
    ("danger", "Danger"),
    ("armed", "Armed"),
    ("sim", "Simulated"),
    ("error", "Error"),
)

_SWATCH_W, _SWATCH_H = 44, 22


def builtin_presets() -> list[dict]:
    """The two shipped presets — the untouched token sets of each theme."""
    return [
        {"name": "Cockpit Dark", "mode": "dark", "overrides": {},
         "glass": style.DEFAULT_GLASS_AMOUNT,
         "typography": {"sans": None, "mono": None, "hinting": None, "base_px": None},
         "radius": "m", "builtin": True},
        {"name": "Lab Light", "mode": "light", "overrides": {},
         "glass": style.DEFAULT_GLASS_AMOUNT,
         "typography": {"sans": None, "mono": None, "hinting": None, "base_px": None},
         "radius": "m", "builtin": True},
    ]


def _sanitize_preset(item) -> dict | None:
    """Validate one preset dict from JSON. Safety-token overrides are
    silently dropped (style.sanitize_overrides); malformed presets return
    None and are skipped entirely."""
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    mode = "dark" if str(item.get("mode", "dark")).lower() == "dark" else "light"
    overrides = style.sanitize_overrides(item.get("overrides"))
    try:
        glass = max(0.0, min(1.0, float(item.get("glass", style.DEFAULT_GLASS_AMOUNT))))
    except (TypeError, ValueError):
        glass = style.DEFAULT_GLASS_AMOUNT
    typo_raw = item.get("typography")
    typo = typo_raw if isinstance(typo_raw, dict) else {}
    radius = str(item.get("radius", "m")).lower()
    if radius not in style.RADIUS_SCALES:
        radius = "m"
    return {
        "name": name, "mode": mode, "overrides": overrides, "glass": glass,
        "typography": {k: typo.get(k) for k in ("sans", "mono", "hinting", "base_px")},
        "radius": radius, "builtin": False,
    }


def load_user_presets(settings: QSettings) -> list[dict]:
    """User presets from QSettings JSON (``theme/presets``), each sanitized."""
    try:
        raw = json.loads(str(settings.value(PRESETS_KEY, "") or "[]"))
    except (TypeError, ValueError):
        return []
    presets: list[dict] = []
    if isinstance(raw, list):
        for item in raw:
            preset = _sanitize_preset(item)
            if preset is not None:
                presets.append(preset)
    return presets


def save_user_presets(settings: QSettings, presets: list[dict]) -> None:
    settings.setValue(PRESETS_KEY, json.dumps(
        [{k: v for k, v in p.items() if k != "builtin"} for p in presets]))
    settings.sync()


def _settings_row(label_text: str, control: QWidget,
                  trailing: QWidget | None = None) -> QWidget:
    """Settings-row grammar (first consumer): label left, stretch, compact
    control right. *trailing* slots a second small widget after the control
    (e.g. a lock glyph before a locked swatch sits BEFORE it — pass order
    via the caller)."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SPACE_SM)
    label = QLabel(label_text)
    lay.addWidget(label)
    lay.addStretch(1)
    if trailing is not None:
        lay.addWidget(trailing)
    lay.addWidget(control)
    row.label = label  # type: ignore[attr-defined]
    return row


class ThemeEditorDialog(QDialog):
    """Non-modal "Theme" dialog: preset list on the left; material / colors /
    typography / radius rows on the right; Apply / Save as preset… / Reset to
    preset / Close in the footer. Emits ``applyRequested(mode)`` after
    committing state to gui/style.py — the main window routes that through
    its dark-toggle machinery so the whole app repaints."""

    applyRequested = Signal(str)

    def __init__(self, mode: str = "dark", settings: QSettings | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Theme")
        self.setModal(False)
        self._settings = settings if settings is not None else QSettings("TCT", "TCTSetup")
        self._mode = "dark" if str(mode).lower() == "dark" else "light"

        # Drafts — uncommitted control state; committed only by _apply().
        self._draft_overrides: dict[str, str] = dict(style.theme_overrides(self._mode))
        self._draft_glass: float = style.get_glass_amount()

        self._swatches: dict[str, QPushButton] = {}
        self._locked_swatches: dict[str, QLabel] = {}

        self._build_ui()
        self._load_presets_into_list(select="Cockpit Dark" if self._mode == "dark"
                                     else "Lab Light")
        self._sync_controls_from_drafts()

    # ------------------------------------------------------------------ #
    # UI construction                                                    #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        outer.setSpacing(SPACE_MD)

        split = QHBoxLayout()
        split.setSpacing(SPACE_MD)
        outer.addLayout(split, 1)

        # LEFT — preset list
        left = QVBoxLayout()
        left.setSpacing(SPACE_XS)
        presets_caption = QLabel("PRESETS")
        presets_caption.setObjectName("eyebrow")
        left.addWidget(presets_caption)
        self._preset_list = QListWidget()
        self._preset_list.setFixedWidth(170)
        self._preset_list.itemSelectionChanged.connect(self._on_preset_selected)
        left.addWidget(self._preset_list, 1)
        split.addLayout(left)

        # RIGHT — grouped setting cards in a scroll area
        column_host = QWidget()
        column = QVBoxLayout(column_host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACE_MD)
        column.addWidget(self._build_material_card())
        column.addWidget(self._build_colors_card())
        column.addWidget(self._build_typography_card())
        column.addWidget(self._build_radius_card())
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(column_host)
        scroll.setMinimumWidth(430)
        split.addWidget(scroll, 1)

        # FOOTER
        footer = QHBoxLayout()
        footer.setSpacing(SPACE_SM)
        self._btn_apply = QPushButton("Apply")
        self._btn_apply.setProperty("state", "primary")
        self._btn_apply.clicked.connect(self._apply)
        self._btn_save_preset = QPushButton("Save as preset…")
        self._btn_save_preset.clicked.connect(self._save_preset)
        self._btn_reset = QPushButton("Reset to preset")
        self._btn_reset.clicked.connect(self._reset_to_preset)
        self._btn_close = QPushButton("Close")
        self._btn_close.clicked.connect(self.close)
        footer.addWidget(self._btn_apply)
        footer.addWidget(self._btn_save_preset)
        footer.addWidget(self._btn_reset)
        footer.addStretch(1)
        footer.addWidget(self._btn_close)
        outer.addLayout(footer)
        self.resize(680, 560)

    def _build_material_card(self) -> Card:
        card = Card("Material")
        self._glass_slider = QSlider(Qt.Orientation.Horizontal)
        self._glass_slider.setRange(0, 100)
        self._glass_slider.setFixedWidth(180)
        self._glass_slider.setToolTip(
            "0% = fully opaque surfaces, 100% = the full glass material")
        self._glass_value_label = QLabel("100%")
        # Live preview, throttled: a full restyle is a global QSS repolish,
        # so drag updates debounce (250 ms) and release applies immediately.
        self._glass_timer = QTimer(self)
        self._glass_timer.setSingleShot(True)
        self._glass_timer.setInterval(250)
        self._glass_timer.timeout.connect(self._preview_glass)
        self._glass_slider.valueChanged.connect(self._on_glass_changed)
        self._glass_slider.sliderReleased.connect(self._preview_glass)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(SPACE_SM)
        hl.addWidget(self._glass_slider)
        hl.addWidget(self._glass_value_label)
        card.add_widget(_settings_row("Glass amount", holder))
        hint = QLabel("Plots and the camera stay opaque at any glass amount.")
        hint.setObjectName("metricTileCaption")
        card.add_widget(hint)
        return card

    def _build_colors_card(self) -> Card:
        card = Card("Colors")
        for token, label in _COLOR_ROWS:
            swatch = QPushButton()
            swatch.setFixedSize(_SWATCH_W, _SWATCH_H)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.clicked.connect(lambda *_, t=token, l=label: self._pick_color(t, l))
            self._swatches[token] = swatch
            card.add_widget(_settings_row(label, swatch))
        for token, label in _LOCKED_ROWS:
            swatch = QLabel()
            swatch.setFixedSize(_SWATCH_W, _SWATCH_H)
            self._locked_swatches[token] = swatch
            lock = QLabel("\N{LOCK}")
            lock.setToolTip("Locked — safety palette")
            row = _settings_row(label, swatch, trailing=lock)
            row.label.setEnabled(False)  # type: ignore[attr-defined]
            card.add_widget(row)
        caption = QLabel("safety palette — fixed by laws 1/2/6")
        caption.setObjectName("metricTileCaption")
        card.add_widget(caption)
        return card

    def _build_typography_card(self) -> Card:
        card = Card("Typography")
        base = style.base_typography()
        all_families = list(QFontDatabase.families())

        self._sans_combo = QComboBox()
        self._sans_combo.addItem(f"App default ({base['sans'][0]})", None)
        for fam in base["sans"] + [f for f in all_families if f not in base["sans"]]:
            self._sans_combo.addItem(fam, fam)
        card.add_widget(_settings_row("Sans family", self._sans_combo))

        self._mono_combo = QComboBox()
        self._mono_combo.addItem(f"App default ({base['mono'][0]})", None)
        for fam in base["mono"] + [f for f in all_families if f not in base["mono"]]:
            self._mono_combo.addItem(fam, fam)
        card.add_widget(_settings_row("Mono family", self._mono_combo))

        self._hinting_combo = QComboBox()
        for label, value in (("Vertical (default)", "vertical"),
                             ("None (soft)", "none"),
                             ("Full (crisp)", "full")):
            self._hinting_combo.addItem(label, value)
        card.add_widget(_settings_row("Font hinting", self._hinting_combo))

        self._size_spin = QSpinBox()
        self._size_spin.setRange(base["base_px"] - 2, base["base_px"] + 2)
        self._size_spin.setValue(base["base_px"])
        self._size_spin.setSuffix(" px")
        card.add_widget(_settings_row("Base size", self._size_spin))
        return card

    def _build_radius_card(self) -> Card:
        card = Card("Radius")
        self._radius_seg = SegmentedControl(
            [("s", "S"), ("m", "M"), ("l", "L")], current=style.radius_scale())
        card.add_widget(_settings_row("Corner radius", self._radius_seg))
        return card

    # ------------------------------------------------------------------ #
    # Swatches / control sync                                            #
    # ------------------------------------------------------------------ #

    def _swatch_css(self, color: str, p: dict) -> str:
        return (f"background: {color}; border: 1px solid {p['hairline_strong']}; "
                f"border-radius: {RADIUS_XS}px;")

    def _update_swatch(self, token: str) -> None:
        p = style.palette(self._mode)
        color = self._draft_overrides.get(token, p[token])
        self._swatches[token].setStyleSheet(self._swatch_css(color, p))
        self._swatches[token].setToolTip(color)

    def _refresh_all_swatches(self) -> None:
        p = style.palette(self._mode)
        for token in self._swatches:
            self._update_swatch(token)
        for token, swatch in self._locked_swatches.items():
            swatch.setStyleSheet(self._swatch_css(p[token], p))
            swatch.setToolTip(f"{p[token]} — safety palette, fixed by laws 1/2/6")

    def _sync_controls_from_drafts(self) -> None:
        """Push draft state into every control without firing live previews."""
        self._glass_slider.blockSignals(True)
        self._glass_slider.setValue(int(round(self._draft_glass * 100)))
        self._glass_slider.blockSignals(False)
        self._glass_value_label.setText(f"{int(round(self._draft_glass * 100))}%")
        typo = style.typography()
        for combo, key in ((self._sans_combo, "sans"), (self._mono_combo, "mono"),
                           (self._hinting_combo, "hinting")):
            idx = combo.findData(typo[key])
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        base_px = style.base_typography()["base_px"]
        self._size_spin.setValue(typo["base_px"] or base_px)
        self._radius_seg.set_current(style.radius_scale())
        self._refresh_all_swatches()

    # ------------------------------------------------------------------ #
    # Color picking                                                      #
    # ------------------------------------------------------------------ #

    def _pick_color(self, token: str, label: str) -> None:
        current = self._draft_overrides.get(token, style.palette(self._mode)[token])
        color = QColorDialog.getColor(QColor(current), self, f"Theme color — {label}")
        if color.isValid():
            self._set_draft_color(token, color.name())

    def _set_draft_color(self, token: str, hex_value: str) -> None:
        """Programmatic draft setter (also the test seam — no QColorDialog).
        Refuses safety tokens and anything not in style.EDITABLE_TOKENS,
        mirroring style.apply_theme_overrides."""
        if token in style.SAFETY_TOKENS:
            raise ValueError(
                f"{token!r} is safety palette — fixed by laws 1/2/6")
        clean = style.sanitize_overrides({token: hex_value})
        if token not in clean:
            raise ValueError(
                f"{token!r} / {hex_value!r} is not an editable token + '#rrggbb' pair")
        self._draft_overrides[token] = clean[token]
        self._update_swatch(token)

    # ------------------------------------------------------------------ #
    # Glass preview                                                      #
    # ------------------------------------------------------------------ #

    def _on_glass_changed(self, value: int) -> None:
        self._glass_value_label.setText(f"{value}%")
        self._glass_timer.start()

    def _sync_glass_from_slider(self) -> None:
        """The slider is the source of truth for the glass draft — Apply /
        save-preset may land before the preview debounce timer has fired."""
        self._glass_timer.stop()
        self._draft_glass = self._glass_slider.value() / 100.0

    def _preview_glass(self) -> None:
        """Live material preview: commit ONLY the glass amount (not colors/
        fonts) and request a repaint through the main window's machinery.
        Not persisted until Apply."""
        self._sync_glass_from_slider()
        style.set_glass_amount(self._draft_glass)
        self.applyRequested.emit(self._mode)

    # ------------------------------------------------------------------ #
    # Presets                                                            #
    # ------------------------------------------------------------------ #

    def _load_presets_into_list(self, select: str | None = None) -> None:
        self._preset_list.blockSignals(True)
        self._preset_list.clear()
        for preset in builtin_presets() + load_user_presets(self._settings):
            item = QListWidgetItem(preset["name"])
            item.setData(Qt.ItemDataRole.UserRole, preset)
            item.setToolTip("Built-in preset" if preset.get("builtin")
                            else "User preset")
            self._preset_list.addItem(item)
        if select:
            matches = self._preset_list.findItems(select, Qt.MatchFlag.MatchExactly)
            if matches:
                self._preset_list.setCurrentItem(matches[0])
        self._preset_list.blockSignals(False)

    def _selected_preset(self) -> dict | None:
        item = self._preset_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _on_preset_selected(self) -> None:
        preset = self._selected_preset()
        if preset is not None:
            self._load_preset(preset)

    def _load_preset(self, preset: dict) -> None:
        """Load a (sanitized) preset into the drafts + controls. Nothing is
        committed until Apply / Reset-to-preset."""
        self._mode = preset.get("mode", self._mode)
        self._draft_overrides = dict(style.sanitize_overrides(preset.get("overrides")))
        try:
            self._draft_glass = max(0.0, min(1.0, float(
                preset.get("glass", style.DEFAULT_GLASS_AMOUNT))))
        except (TypeError, ValueError):
            self._draft_glass = style.DEFAULT_GLASS_AMOUNT
        self._glass_slider.blockSignals(True)
        self._glass_slider.setValue(int(round(self._draft_glass * 100)))
        self._glass_slider.blockSignals(False)
        self._glass_value_label.setText(f"{int(round(self._draft_glass * 100))}%")
        typo = preset.get("typography") or {}
        for combo, key in ((self._sans_combo, "sans"), (self._mono_combo, "mono"),
                           (self._hinting_combo, "hinting")):
            idx = combo.findData(typo.get(key))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        base_px = style.base_typography()["base_px"]
        try:
            self._size_spin.setValue(int(typo.get("base_px") or base_px))
        except (TypeError, ValueError):
            self._size_spin.setValue(base_px)
        self._radius_seg.set_current(str(preset.get("radius", "m")))
        self._refresh_all_swatches()

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        name = str(name).strip()
        if ok and name:
            self._save_preset_named(name)

    def _save_preset_named(self, name: str) -> None:
        """Serialize the current drafts as a user preset (same-name presets
        are replaced; built-in names are shadowed in the user list but the
        built-ins always render first)."""
        self._sync_glass_from_slider()
        preset = _sanitize_preset({
            "name": name,
            "mode": self._mode,
            "overrides": dict(self._draft_overrides),
            "glass": self._draft_glass,
            "typography": {
                "sans": self._sans_combo.currentData(),
                "mono": self._mono_combo.currentData(),
                "hinting": self._hinting_combo.currentData(),
                "base_px": self._size_spin.value(),
            },
            "radius": self._radius_seg.current_key() or "m",
        })
        if preset is None:
            return
        presets = [p for p in load_user_presets(self._settings)
                   if p["name"] != preset["name"]]
        presets.append(preset)
        save_user_presets(self._settings, presets)
        self._load_presets_into_list(select=preset["name"])

    def _reset_to_preset(self) -> None:
        """Reload the selected preset over the drafts and apply it."""
        preset = self._selected_preset()
        if preset is not None:
            self._load_preset(preset)
            self._apply()

    # ------------------------------------------------------------------ #
    # Apply / theme refresh                                              #
    # ------------------------------------------------------------------ #

    def _apply(self) -> None:
        """Commit drafts to gui/style.py's override layer, persist under
        theme/*, and request the app-wide repaint (same path as the
        dark-mode toggle — see tct_gui._on_theme_editor_apply)."""
        self._sync_glass_from_slider()
        style.apply_theme_overrides(dict(self._draft_overrides), self._mode,
                                    merge=False)
        style.set_glass_amount(self._draft_glass)
        style.apply_typography(
            sans=self._sans_combo.currentData(),
            mono=self._mono_combo.currentData(),
            hinting=self._hinting_combo.currentData(),
            base_px=self._size_spin.value(),
        )
        style.apply_radius_scale(self._radius_seg.current_key() or "m")
        style.save_theme_customization(self._settings)
        self.applyRequested.emit(self._mode)
        self._refresh_all_swatches()

    def refresh_theme(self, mode: str) -> None:
        """Re-resolve cached swatch colors after a live theme switch. Only a
        REAL mode change retargets the editor (drafts reload from the
        committed override set for the new mode) — a same-mode refresh (e.g.
        the glass-preview round trip through _toggle_theme) must not stomp
        in-progress drafts."""
        mode = "dark" if str(mode).lower() == "dark" else "light"
        if mode != self._mode:
            self._mode = mode
            self._draft_overrides = dict(style.theme_overrides(mode))
            self._draft_glass = style.get_glass_amount()
            self._sync_controls_from_drafts()
        else:
            self._refresh_all_swatches()
