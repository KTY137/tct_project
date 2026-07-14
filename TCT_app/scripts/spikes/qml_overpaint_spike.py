"""SPIKE — WHICH WIDGET paints over the glass in the shipped QML shell?

THE FINDING UNDER TEST (``qml_restore_material_spike``, 20260714T014500Z)
------------------------------------------------------------------------
With ``TCT_QML_SHELL=1`` — the DEFAULT since 76c2370 — 0.05 % of the cockpit's
pixels track the backdrop while ACTIVE. The classic shell, same machine, same
moment: 9.9 %. And the window state is HEALTHY (alpha=8, material attached,
glassCanvas="true", attr38=3, hr=0 everywhere). So the material is not lost:
**something is painting an opaque pixel where the glass should be.**

The prior rig answered "is there glass ANYWHERE in this window" (one number).
That question cannot name a culprit. This one adds the missing axis — WHERE —
by turning the same two grabs into a **per-pixel mask** and scoring it against
the LIVE widget geometry:

    band:chrome   the QML chrome QQuickWidget (QML shell) / the classic
                  #systemRibbon strip (classic shell)
    band:tabs     the DetachableTabWidget's rect (incl. its native tab bar,
                  which the QML shell HIDES)
    band:frame    everything else inside the client area — i.e. the window's
                  own unclaimed canvas: the 12 px picture-frame margin and the
                  ribbon↔tabs gutter the classic shell's layout leaves open
                  (``tct_gui._build_central``: margins 12/spacing 10 classic,
                  0/0 in QML mode)

A fraction per band, and each band's SHARE of all tracking pixels. If the
classic shell's glass lives in ``band:frame`` + the exposed tab-bar strip and
the QML shell scores ~0 in every band, the culprit is not "a" painter — it is
that the QML shell replaced every canvas-exposing surface with opaque paint.

METHOD — inherited verbatim, never forked
-----------------------------------------
The Decoy, the two capture methods (GDI BitBlt + ``QScreen.grabWindow``, which
must AGREE), the topmost pinning, the z-order audit, the ``WindowFromPoint``
occlusion oracle, the moved-between-grabs check and the ``pos()``-not-
``geometry()`` nudge all come from ``qml_restore_material_spike`` /
``qml_multieffect_glass_spike`` by import. Every one of them exists because it
already caught a confident false positive in this codebase; re-implementing any
of them is how you get a fourth.

The window is ACTIVATED before every measurement: DWM composites a system
backdrop live only for the ACTIVE window and drops an inactive one to a flat
fallback solid ([84,84,84]) — measured, same rig, 20260714T014500Z. An
inactive-window measurement is not evidence about the app.

RUN (real desktop session only — refuses under offscreen/minimal)::

    cd TCT_app
    .venv/Scripts/python.exe scripts/spikes/qml_overpaint_spike.py            # both shells
    .venv/Scripts/python.exe scripts/spikes/qml_overpaint_spike.py --shell qml

NOT app code. NOT imported by the app. NOT part of the test suite. Simulated
devices only (it refuses to construct anything against a non-simulated config)
and it snapshots/restores every QSettings key it touches.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_SPIKES = Path(__file__).resolve().parent
_SCRIPTS = _SPIKES.parent
_TCT_APP = _SCRIPTS.parent
_REPO_ROOT = _TCT_APP.parent
for _p in (str(_TCT_APP), str(_SCRIPTS), str(_SPIKES)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QSurfaceFormat  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import capture_onscreen as cap  # noqa: E402
from gui import backdrop  # noqa: E402

# The rig — imported, never forked (see the module docstring).
from qml_multieffect_glass_spike import METHODS, Decoy, _delta, _mean_rgb  # noqa: E402
from qml_restore_material_spike import (  # noqa: E402
    _activation_now, _grab_rect, _widget_nudge, force_foreground, hwnd_at,
    pin_topmost, zorder_intruders)

logger = logging.getLogger("qml_overpaint_spike")

CONFIG_PATH = str(_TCT_APP / "configs" / "devices.yaml")

# A pixel "tracks the backdrop" when its max channel delta between the striped
# and the flat decoy exceeds this. Same threshold as the prior rig's
# ``_frac_changed`` — so the headline fraction is directly comparable to its
# 0.0988 (classic) / 0.0005 (QML).
TRACK_THRESH = 10.0


# --------------------------------------------------------------------------- #
# Geometry — the live widget tree, never a hard-coded rect                     #
# --------------------------------------------------------------------------- #
def band_rects(win) -> dict[str, list[int]]:
    """The three bands, in CLIENT-LOCAL DIP coordinates, read off the live tree.

    ``band:frame`` is deliberately NOT a rect — it is "the client area minus the
    other two", i.e. exactly the window's own unclaimed canvas. It is returned as
    the client rect and subtracted in :func:`score_bands`."""
    out: dict[str, list[int]] = {}
    client = win.rect()
    out["client"] = [client.x(), client.y(), client.width(), client.height()]

    chrome = getattr(win, "_qml_chrome", None)
    if chrome is None:
        chrome = getattr(win, "_ribbon", None)
    if chrome is not None and chrome.isVisible():
        tl = chrome.mapTo(win, QPoint(0, 0))
        out["chrome"] = [tl.x(), tl.y(), chrome.width(), chrome.height()]

    tabs = getattr(win, "_tabs", None)
    if tabs is not None and tabs.isVisible():
        tl = tabs.mapTo(win, QPoint(0, 0))
        out["tabs"] = [tl.x(), tl.y(), tabs.width(), tabs.height()]
    return out


def score_bands(mask: np.ndarray, bands: dict[str, list[int]], *,
                client_offset: tuple[int, int], dpr: float) -> dict:
    """Fraction of tracking pixels per band, and each band's SHARE of them all.

    ``mask`` is over the FRAME rect (physical px); the bands are client-local DIP
    rects. Mixing the two coordinate systems is the classic way to produce a
    confident number about the wrong pixels, so the conversion is explicit and
    every derived rect is clipped to the mask."""
    h, w = mask.shape
    ox, oy = client_offset

    def _phys(r: list[int]) -> tuple[int, int, int, int]:
        x = int(round((r[0] + ox) * dpr))
        y = int(round((r[1] + oy) * dpr))
        return (max(0, x), max(0, y),
                min(w, x + int(round(r[2] * dpr))),
                min(h, y + int(round(r[3] * dpr))))

    out: dict = {"total": {"frac": round(float(mask.mean()), 4),
                           "tracking_px": int(mask.sum()),
                           "px": int(mask.size)}}
    claimed = np.zeros_like(mask, dtype=bool)
    for name in ("chrome", "tabs"):
        r = bands.get(name)
        if r is None:
            out[name] = {"absent": True}
            continue
        x0, y0, x1, y1 = _phys(r)
        sel = np.zeros_like(mask, dtype=bool)
        sel[y0:y1, x0:x1] = True
        claimed |= sel
        n = int(sel.sum())
        out[name] = {
            "frac_of_band": round(float(mask[sel].mean()), 4) if n else None,
            "tracking_px": int((mask & sel).sum()),
            "band_px": n,
        }
    # band:frame = the client area minus chrome and tabs = the window's own canvas.
    cr = bands.get("client")
    if cr is not None:
        x0, y0, x1, y1 = _phys(cr)
        client_sel = np.zeros_like(mask, dtype=bool)
        client_sel[y0:y1, x0:x1] = True
        frame_sel = client_sel & ~claimed
        n = int(frame_sel.sum())
        out["frame"] = {
            "frac_of_band": round(float(mask[frame_sel].mean()), 4) if n else None,
            "tracking_px": int((mask & frame_sel).sum()),
            "band_px": n,
            "note": "the window's own unclaimed canvas (margins + gutters)",
        }
    total_tracking = max(1, int(mask.sum()))
    for name in ("chrome", "tabs", "frame"):
        entry = out.get(name)
        if isinstance(entry, dict) and "tracking_px" in entry:
            entry["share_of_all_tracking"] = round(
                entry["tracking_px"] / total_tracking, 3)
    return out


def save_mask(mask: np.ndarray, path: Path) -> None:
    rgb = np.zeros((*mask.shape, 3), dtype=np.uint8)
    rgb[mask] = (57, 217, 138)          # tracking = green
    rgb[~mask] = (24, 24, 28)
    img = QImage(np.ascontiguousarray(rgb).data, mask.shape[1], mask.shape[0],
                 mask.shape[1] * 3, QImage.Format.Format_RGB888)
    img.copy().save(str(path))


# --------------------------------------------------------------------------- #
# The measurement                                                              #
# --------------------------------------------------------------------------- #
def measure(win, decoy: Decoy, tag: str, out_dir: Path) -> dict:
    """Whole-window mask: which pixels change when ONLY what is BEHIND changes."""
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio()
    hwnd = int(win.winId())

    decoy.set_pattern("stripes")
    _widget_nudge(win)
    pin_topmost(int(decoy.winId()))
    cap._settle(100)
    pin_topmost(hwnd)
    cap._settle(500)

    frame = win.frameGeometry()
    client = win.geometry()
    bands = band_rects(win)
    intruders = zorder_intruders(hwnd, int(decoy.winId()), frame)
    center = QPoint(frame.x() + frame.width() // 2, frame.y() + frame.height() // 2)
    there = hwnd_at(center)
    act = _activation_now(hwnd)
    on_stripes = _grab_rect(screen, frame)

    decoy.set_pattern("flat")
    _widget_nudge(win)
    pin_topmost(int(decoy.winId()))
    cap._settle(100)
    pin_topmost(hwnd)
    cap._settle(700)
    moved = win.frameGeometry() != frame
    on_flat = _grab_rect(screen, frame)
    decoy.set_pattern("stripes")
    cap._settle(200)

    entry: dict = {
        "stage": tag,
        "frame_rect": [frame.x(), frame.y(), frame.width(), frame.height()],
        "bands_dip": bands,
        "activation_at_grab": act,
        "zorder_intruders": intruders,
        "hwnd_on_screen_at_center": f"0x{there:X}",
        "probe_hits_target": there == hwnd,
        "window_moved_between_grabs": moved,
        "per_method": {},
    }
    offset = (client.x() - frame.x(), client.y() - frame.y())
    for m in METHODS:
        a, b = on_stripes[m], on_flat[m]
        if a is None or b is None or a.shape != b.shape:
            entry["per_method"][m] = {"error": "grab failed / shape mismatch"}
            continue
        mask = np.abs(a - b).max(axis=2) > TRACK_THRESH
        entry["per_method"][m] = {
            "d_behind": round(_delta(a, b), 2),
            "frac_pixels_changed": round(float(mask.mean()), 4),
            "mean_rgb_stripes": _mean_rgb(a),
            "mean_rgb_flat": _mean_rgb(b),
            "bands": score_bands(mask, bands, client_offset=offset, dpr=dpr),
        }
        if m == "bitblt":
            save_mask(mask, out_dir / f"{tag}_mask.png")
            cap._save(cap._grab("bitblt", screen, frame.x(), frame.y(),
                                frame.width(), frame.height()),
                      out_dir / f"{tag}_window.png")

    fracs = [entry["per_method"][m].get("frac_pixels_changed")
             for m in METHODS if "frac_pixels_changed" in entry["per_method"][m]]
    if moved:
        entry["verdict"] = "REJECTED (the window moved between the two grabs)"
    elif intruders:
        entry["verdict"] = f"REJECTED (a window sat between the decoy and the app: {intruders})"
    elif there != hwnd:
        entry["verdict"] = (f"REJECTED (the window on screen at the probe centre is "
                            f"0x{there:X}, not the app 0x{hwnd:X})")
    elif len(fracs) == 2 and abs(fracs[0] - fracs[1]) > 0.02:
        entry["verdict"] = f"DISAGREE (bitblt vs grabwindow: {fracs})"
    else:
        entry["verdict"] = "OK"
    return entry


class _LogTrap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith("gui."):
                self.records.append(f"{record.levelname} {record.name}: "
                                    f"{record.getMessage()}")
        except Exception:
            pass


def run_child(shell: str, out_dir: Path) -> dict:
    from gui import app_settings, style

    cap._assert_all_simulated(CONFIG_PATH)      # simulation only, before any device
    trap = _LogTrap()
    logging.getLogger().addHandler(trap)
    logging.getLogger().setLevel(logging.INFO)

    settings = app_settings.settings()
    snapshot = cap.snapshot_settings(settings)

    report: dict = {"shell": shell}
    win = None
    decoy = Decoy()
    try:
        avail = QGuiApplication.primaryScreen().availableGeometry()
        decoy.setGeometry(avail)
        decoy.show()
        cap._settle(400)
        pin_topmost(int(decoy.winId()))
        cap._settle(200)

        w = min(1100, avail.width() - 120)
        h = min(680, avail.height() - 120)

        style.reset_theme_customization()
        from tct_gui import TCTMainWindow
        win = TCTMainWindow(config_path=CONFIG_PATH)
        win.resize(w, h)
        win.move(avail.x() + 40, avail.y() + 40)
        win.show()
        cap._settle(1200)
        pin_topmost(int(win.winId()))
        cap._settle(300)

        # Acrylic + the Glass preset, through the SAME slots the Settings/Theme UI
        # drives (capture_onscreen owns that path — no new GUI logic here).
        cap._apply_scenario_state(win, cap.Scenario(
            key="glass_acrylic", backdrop="acrylic", theme="dark",
            preset="Glass", canvas="A"))
        cap._settle(900)
        pin_topmost(int(win.winId()))
        cap._settle(300)

        # ACTIVE, or the measurement is about DWM's inactive fallback solid.
        act = force_foreground(int(win.winId()))
        cap._settle(700)
        report["activation"] = act

        try:
            from glass_probe import window_diag
            report["window_diag"] = window_diag(win, "TCTMainWindow")
        except Exception as exc:
            report["window_diag"] = {"unavailable": f"{type(exc).__name__}: {exc}"}

        report["measurement"] = measure(win, decoy, f"{shell}", out_dir)
        report["app_log_tail"] = trap.records[-25:]
        return report
    finally:
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
        decoy.close()
        cap.restore_settings(settings, snapshot)
        logging.getLogger().removeHandler(trap)
        cap._settle(300)


# --------------------------------------------------------------------------- #
# Manifest                                                                     #
# --------------------------------------------------------------------------- #
def _fmt(shell: str, p: dict) -> list[str]:
    L = [f"[{shell}]"]
    if "FAILED" in p:
        L.append(f"  FAILED: {p['FAILED']}")
        return L
    m = p.get("measurement", {})
    d = p.get("window_diag", {})
    L.append(f"  verdict={m.get('verdict')}  active_at_grab="
             f"{m.get('activation_at_grab', {}).get('is_active_window')}")
    L.append(f"  window: alpha={d.get('alphaBufferSize')} "
             f"glassCanvas={d.get('glassCanvas_property')} "
             f"central_glassCanvas={d.get('central_glassCanvas_property')} "
             f"has_material={d.get('backdrop.window_has_material')}")
    for meth in METHODS:
        pm = m.get("per_method", {}).get(meth, {})
        if "frac_pixels_changed" not in pm:
            L.append(f"  {meth}: {pm}")
            continue
        L.append(f"  {meth}: FRAC_TRACKING={pm['frac_pixels_changed']}  "
                 f"d_behind={pm['d_behind']}  rgb={pm['mean_rgb_stripes']}")
        b = pm.get("bands", {})
        for name in ("chrome", "tabs", "frame"):
            e = b.get(name, {})
            if e.get("absent"):
                L.append(f"      band:{name:<7s} ABSENT")
                continue
            L.append(f"      band:{name:<7s} frac={e.get('frac_of_band')}  "
                     f"share_of_all_tracking={e.get('share_of_all_tracking')}  "
                     f"band_px={e.get('band_px')}")
    return L


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="WHERE does the shipped cockpit track the backdrop — per band, "
                    "per shell?")
    ap.add_argument("--shell", default="both", choices=["both", "classic", "qml"])
    ap.add_argument("--tag", default="", help="label for the artifact directory "
                                              "(e.g. 'before' / 'after')")
    ap.add_argument("--emit", default=None, metavar="DIR", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    reason = cap.check_environment()
    if reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        return 2

    # ---- CHILD: one shell, its own pristine process (the env var AND the RHI pin
    #      must precede the QApplication — that is the very ordering law at issue).
    if args.emit:
        shell = args.shell
        os.environ["TCT_QML_SHELL"] = "1" if shell == "qml" else "0"
        if shell == "qml":
            from gui.qml_shell import pin_opengl_rhi
            pin_opengl_rhi()
        fmt = QSurfaceFormat.defaultFormat()
        if fmt.alphaBufferSize() < 8:
            fmt.setAlphaBufferSize(8)
            QSurfaceFormat.setDefaultFormat(fmt)
        app = QApplication.instance() or QApplication(sys.argv[:1])
        reason = cap.check_environment(app)
        if reason:
            print(f"REFUSED: {reason}", file=sys.stderr)
            return 2
        out_dir = Path(args.emit)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            entry = run_child(shell, out_dir)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            entry = {"FAILED": f"{type(exc).__name__}: {exc}"}
        (out_dir / f"probe_{shell}.json").write_text(
            json.dumps(entry, indent=2, default=str), encoding="utf-8")
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"qml_overpaint_{args.tag}_{ts}" if args.tag else f"qml_overpaint_{ts}"
    out_dir = _REPO_ROOT / "artifacts_claude" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    shells = ["classic", "qml"] if args.shell == "both" else [args.shell]
    report: dict = {"spike": "qml_overpaint_spike", "utc": ts, "tag": args.tag,
                    "windows_build": sys.getwindowsversion().build,  # type: ignore[attr-defined]
                    "probes": {}}
    for shell in shells:
        print(f"\n--- shell: {shell} (own process) ---")
        sys.stdout.flush()
        # NOT ``cap._settle`` here. That helper spins a ``QEventLoop``, and THIS
        # process (the parent) deliberately never builds a ``QApplication`` — the
        # RHI pin and ``TCT_QML_SHELL`` must both precede the one in each CHILD.
        # A QEventLoop with no application object does not settle; it burns a core
        # forever (measured: 29 minutes of CPU, zero children spawned, no output).
        time.sleep(0.8)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--shell", shell,
             "--emit", str(out_dir)], timeout=600)
        path = out_dir / f"probe_{shell}.json"
        if proc.returncode != 0 or not path.exists():
            report["probes"][shell] = {"FAILED": f"child exit {proc.returncode}"}
            continue
        report["probes"][shell] = json.loads(path.read_text(encoding="utf-8"))

    lines = [f"qml_overpaint_spike — WHERE does the cockpit track the backdrop?  "
             f"tag={args.tag or '-'}  utc={ts}",
             "FRAC_TRACKING = fraction of the window's pixels that CHANGE when only "
             "what is BEHIND the window changes.",
             "Target: the classic shell's 9.9 %. Both capture methods must agree; a "
             "z-order intruder / occlusion / a moved window REJECTS the measurement.",
             ""]
    for shell, p in report["probes"].items():
        lines += _fmt(shell, p) + [""]
    (out_dir / "manifest.txt").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str),
                                         encoding="utf-8")
    print("\n".join(lines))
    print(f"artifacts: {out_dir}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
