"""Headless tests for ``gui/backdrop.py`` (Windows acrylic/mica backdrop core).

The suite runs under ``QT_QPA_PLATFORM=offscreen`` (no DWM, no real compositor),
so every test either drives the injectable support probes to exercise the
matrix, or monkeypatches the ``_dwm_*`` native-call functions with recording
stubs so no test ever touches ctypes/dwmapi.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

import gui.backdrop as backdrop


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_window() -> QWidget:
    _app()
    return QWidget()


def _force_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive is_backdrop_supported() to True regardless of the real host."""
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22621)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")


def _recording_dwm(monkeypatch: pytest.MonkeyPatch, extend_hr: int = 0,
                    attr_hr: int = 0):
    """Patch both DWM calls with recorders; returns the shared call log."""
    calls: list[tuple] = []

    def fake_extend(hwnd):
        calls.append(("extend", hwnd))
        return extend_hr

    def fake_set_attr(hwnd, attribute, value):
        calls.append(("set_attr", attribute, value))
        return attr_hr

    monkeypatch.setattr(backdrop, "_dwm_extend_frame", fake_extend)
    monkeypatch.setattr(backdrop, "_dwm_set_window_attribute", fake_set_attr)
    return calls


# --------------------------------------------------------------------------- #
# Support matrix                                                             #
# --------------------------------------------------------------------------- #

def test_unsupported_old_build(monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22000)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")
    assert backdrop.is_backdrop_supported() is False


def test_supported_on_win11_22h2_with_native_platform(monkeypatch):
    _force_supported(monkeypatch)
    assert backdrop.is_backdrop_supported() is True


def test_unsupported_offscreen_platform(monkeypatch):
    # Even with a fully qualifying build/OS, the offscreen Qt plugin (what
    # this whole suite runs under) must stay unsupported -- no DWM exists.
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22621)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "offscreen")
    assert backdrop.is_backdrop_supported() is False


def test_unsupported_non_windows(monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "linux")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 99999)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")
    assert backdrop.is_backdrop_supported() is False


# --------------------------------------------------------------------------- #
# apply_backdrop -- supported host, recorded DWM calls                       #
# --------------------------------------------------------------------------- #

def test_apply_mica_records_dwmsbt_mainwindow(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is True
    assert ("set_attr", 38, backdrop.DWMSBT_MAINWINDOW) in calls
    assert backdrop.DWMSBT_MAINWINDOW == 2


def test_apply_acrylic_records_dwmsbt_transientwindow(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "acrylic") is True
    assert ("set_attr", 38, backdrop.DWMSBT_TRANSIENTWINDOW) in calls
    assert backdrop.DWMSBT_TRANSIENTWINDOW == 3


def test_extend_frame_called_before_set_attribute(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    backdrop.apply_backdrop(w, "mica")

    kinds = [c[0] for c in calls]
    assert kinds.index("extend") < kinds.index("set_attr")


def test_translucent_attribute_set_only_after_both_dwm_calls_succeed(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch)
    w = _make_window()

    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False
    assert backdrop.apply_backdrop(w, "mica") is True
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True


# --------------------------------------------------------------------------- #
# Unsupported host                                                           #
# --------------------------------------------------------------------------- #

def test_unsupported_host_returns_false_and_never_touches_dwm(monkeypatch):
    monkeypatch.setattr(backdrop.sys, "platform", "win32")
    monkeypatch.setattr(backdrop, "_version_probe", lambda: 22000)
    monkeypatch.setattr(backdrop, "_platform_probe", lambda: "windows")
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is False
    assert calls == []
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


# --------------------------------------------------------------------------- #
# kind == "none" reset                                                       #
# --------------------------------------------------------------------------- #

def test_none_after_applied_backdrop_resets_and_clears_translucent(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "acrylic") is True
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True

    calls.clear()
    assert backdrop.apply_backdrop(w, "none") is True
    assert ("set_attr", 38, backdrop.DWMSBT_NONE) in calls
    assert backdrop.DWMSBT_NONE == 1
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


def test_none_without_a_prior_apply_is_a_true_noop(monkeypatch):
    _force_supported(monkeypatch)
    calls = _recording_dwm(monkeypatch)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "none") is True
    assert calls == []


# --------------------------------------------------------------------------- #
# Invalid kind                                                               #
# --------------------------------------------------------------------------- #

def test_invalid_kind_raises_value_error(monkeypatch):
    _force_supported(monkeypatch)
    w = _make_window()
    with pytest.raises(ValueError):
        backdrop.apply_backdrop(w, "glass")


# --------------------------------------------------------------------------- #
# DWM failure simulation                                                     #
# --------------------------------------------------------------------------- #

def test_dwm_nonzero_hresult_on_set_attribute_fails_safe(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch, extend_hr=0, attr_hr=1)  # nonzero HRESULT == failure
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is False
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


def test_dwm_nonzero_hresult_on_extend_frame_fails_safe(monkeypatch):
    _force_supported(monkeypatch)
    _recording_dwm(monkeypatch, extend_hr=1, attr_hr=0)
    w = _make_window()

    assert backdrop.apply_backdrop(w, "mica") is False
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


def test_dwm_extend_frame_raises_fails_safe(monkeypatch):
    _force_supported(monkeypatch)
    w = _make_window()

    def raising_extend(hwnd):
        raise OSError("simulated DWM failure")

    monkeypatch.setattr(backdrop, "_dwm_extend_frame", raising_extend)
    monkeypatch.setattr(backdrop, "_dwm_set_window_attribute",
                         lambda hwnd, attribute, value: 0)

    assert backdrop.apply_backdrop(w, "acrylic") is False
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


def test_dwm_set_attribute_raises_fails_safe(monkeypatch):
    _force_supported(monkeypatch)
    w = _make_window()

    def raising_set_attr(hwnd, attribute, value):
        raise OSError("simulated DWM failure")

    monkeypatch.setattr(backdrop, "_dwm_extend_frame", lambda hwnd: 0)
    monkeypatch.setattr(backdrop, "_dwm_set_window_attribute", raising_set_attr)

    assert backdrop.apply_backdrop(w, "acrylic") is False
    assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is False


# --------------------------------------------------------------------------- #
# BACKDROP_KINDS sanity                                                      #
# --------------------------------------------------------------------------- #

def test_backdrop_kinds_tuple():
    assert backdrop.BACKDROP_KINDS == ("none", "mica", "acrylic")
