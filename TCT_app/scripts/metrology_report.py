"""Self-contained HTML metrology report for a stage<->camera calibration (E5).

WHAT
----
:func:`write_report` renders ONE standalone ``.html`` file summarising a
:class:`~controller.repeatability.StageCameraCal` — the affine parameters,
derived px<->um scale, rotation/shear, residual quality, a PASS/FAIL verdict
against an operator-supplied tolerance, an inline-SVG residual quiver plot,
and (optionally) mosaic tile-placement diagnostics from
:func:`~analysis.mosaic_stitch.place_tiles`'s ``return_diagnostics=True``
path (see that function's "Diagnostics" docstring section for the exact
``n_clamped`` / ``mean_abs_offset_px`` / ``applied_offset_px`` contract this
module renders).

No named physics formula is reinvented here: the PASS/FAIL verdict is
:func:`analysis.camera_calibration.residual_summary` (the same function
:func:`~controller.repeatability.fit_stage_camera_affine` itself used to
populate ``cal.passes``), applied against THIS report's own ``tolerance_um``
argument -- which may differ from whatever tolerance (if any) the caller fit
``cal`` with. Everything else here (HTML/SVG layout, unit labelling) is
presentation, which is this module's actual job.

HOW TO RUN (as a library call, not a CLI -- there is no argparse entry point;
a caller already holds a ``StageCameraCal`` from the fit, e.g. from a REPL or
a calibration procedure script)::

    from scripts.metrology_report import write_report
    write_report(cal, "artifacts_claude/metrology/cal_report.html",
                 tile_diagnostics=diag, tolerance_um=5.0)

DEPENDENCIES
------------
stdlib + numpy only. No Qt (headless-safe, matches ``scripts/capture_panels.
py``'s "no hardware, no display required" spirit, minus the Qt bit -- this
module never imports PySide6). No external assets/CDN: CSS is inlined in a
``<style>`` block, the quiver plot is inline ``<svg>`` -- the resulting
``.html`` file is fully self-contained and opens offline in any browser.

DETERMINISM
------------
Two calls with the same ``cal``/``tile_diagnostics``/``tolerance_um`` (and
the same :func:`_now_iso` return value -- see below) byte-for-byte produce
the same file: no randomness, no wall-clock read baked into the SVG geometry,
fixed-precision number formatting throughout. The one place real time
appears is a plain-text "Generated: ..." line, produced by the module-level
:func:`_now_iso` hook (not a ``write_report`` parameter, to keep the public
signature exactly ``write_report(cal, path, *, tile_diagnostics=None,
tolerance_um=None)`` per the E5 brief) -- tests fix it deterministically via
``monkeypatch.setattr(metrology_report, "_now_iso", lambda: "...")``.
"""
from __future__ import annotations

import html
import math
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, TYPE_CHECKING

import numpy as np

from analysis.camera_calibration import AffineFit, residual_summary

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import
    from controller.repeatability import StageCameraCal

__all__ = ["write_report"]


# --------------------------------------------------------------------------- #
# Timestamp hook -- see module docstring "DETERMINISM"                        #
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    """Current UTC time, ISO-8601, second precision. Monkeypatch this
    function (not a ``write_report`` argument) to pin the report's
    "Generated: ..." line for deterministic tests."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #
def write_report(
    cal: "StageCameraCal",
    path: str | Path,
    *,
    tile_diagnostics: Mapping[str, Any] | None = None,
    tolerance_um: float | None = None,
) -> Path:
    """Render *cal* (and optionally *tile_diagnostics*) to a self-contained
    HTML metrology report at *path*.

    Parameters
    ----------
    cal : StageCameraCal-like
        Duck-typed on the attributes :func:`~controller.repeatability.
        fit_stage_camera_affine` returns: ``affine`` (``AffineFit | None``),
        ``backlash_mm``, ``rms_um``, ``passes``, ``n_points``, ``notes``.
        ``cal.affine is None`` (an aborted capture -- see
        :class:`~controller.repeatability.StageCameraCal`'s docstring) is
        handled explicitly: the report renders a prominent FAILED
        CALIBRATION banner plus ``cal.notes`` verbatim, and skips every
        affine-derived section (scale/rotation/shear, residual quiver,
        PASS/FAIL verdict -- there is no residual field to judge).
    path : str or Path
        Output ``.html`` file path. Parent directories are NOT created
        (mirrors ``open(path, "w")`` semantics) -- callers own directory
        setup, matching ``scripts/capture_panels.py``'s own
        ``mkdir(parents=True, exist_ok=True)`` convention at the call site.
    tile_diagnostics : Mapping, optional
        A :func:`~analysis.mosaic_stitch.place_tiles`
        ``return_diagnostics=True`` dict (``applied_offset_px``,
        ``n_clamped``, ``mean_abs_offset_px``) or any mapping with a subset
        of those keys -- rendered as an extra section when given. ``None``
        (default) omits the section entirely.
    tolerance_um : float, optional
        Tolerance (radial, micrometres) the residual quiver is judged
        against via :func:`analysis.camera_calibration.residual_summary`.
        ``None`` (default) renders "no tolerance set" with no PASS/FAIL
        verdict -- this is a report-generation-time judgement, independent
        of whatever tolerance (if any) ``cal`` itself was originally fit
        with (``cal.passes``).

    Returns
    -------
    Path
        *path*, as a :class:`~pathlib.Path` (for convenient chaining by the
        caller); the file has already been written when this returns.
    """
    out_path = Path(path)
    html_text = _render_html(cal, tile_diagnostics=tile_diagnostics, tolerance_um=tolerance_um)
    out_path.write_text(html_text, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- #
# HTML assembly                                                              #
# --------------------------------------------------------------------------- #
_CSS = """
:root {
  --ink: #1a1f26;
  --muted: #5b6673;
  --line: #d7dde3;
  --panel: #f6f8fa;
  --accent: #1f5fbf;   /* colorblind-safe blue -- quiver arrows, links */
  --fail: #b3261e;     /* red -- FAIL / FAILED CALIBRATION only */
  --pass-bg: #eaf3ea;
  --fail-bg: #fbe9e7;
  --neutral-bg: #f0f1f3;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", Arial, sans-serif;
  color: var(--ink);
  background: #ffffff;
  margin: 0;
  padding: 24px 32px 48px 32px;
  line-height: 1.45;
}
h1 { font-size: 1.5rem; margin-bottom: 2px; }
h2 { font-size: 1.15rem; margin-top: 28px; border-bottom: 1px solid var(--line); padding-bottom: 4px; }
.meta { color: var(--muted); font-size: 0.85rem; margin-bottom: 18px; }
.banner {
  padding: 14px 18px;
  border-radius: 8px;
  font-size: 1.1rem;
  font-weight: 600;
  margin: 12px 0 20px 0;
  border: 1px solid var(--line);
}
.banner.pass { background: var(--pass-bg); border-color: #8fbf8f; color: #1a4d1a; }
.banner.fail { background: var(--fail-bg); border-color: var(--fail); color: var(--fail); }
.banner.neutral { background: var(--neutral-bg); color: var(--muted); }
table { border-collapse: collapse; margin: 6px 0 18px 0; width: 100%; max-width: 760px; }
th, td { text-align: left; padding: 5px 12px 5px 0; border-bottom: 1px solid var(--line); font-size: 0.92rem; }
th { color: var(--muted); font-weight: 600; width: 46%; }
td.num { font-variant-numeric: tabular-nums; }
.notes { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 10px 14px; white-space: pre-wrap; font-family: Consolas, "SFMono-Regular", monospace; font-size: 0.86rem; }
.quiver-wrap { border: 1px solid var(--line); border-radius: 6px; padding: 10px; display: inline-block; background: #fff; }
.quiver-caption { color: var(--muted); font-size: 0.82rem; margin-top: 6px; max-width: 640px; }
svg text { font-family: -apple-system, "Segoe UI", Arial, sans-serif; }
"""


def _render_html(
    cal: Any,
    *,
    tile_diagnostics: Mapping[str, Any] | None,
    tolerance_um: float | None,
) -> str:
    affine = getattr(cal, "affine", None)
    generated = html.escape(_now_iso())

    sections = [
        _render_verdict_banner(cal, affine, tolerance_um),
        _render_summary_section(cal, affine),
    ]
    if affine is None:
        sections.append(
            '<h2>Residual quiver</h2>'
            '<p class="quiver-caption">Skipped -- no affine fit '
            '(<code>cal.affine is None</code>).</p>'
        )
    else:
        sections.append(_render_quiver_section(affine))
    if tile_diagnostics is not None:
        sections.append(_render_tile_diagnostics_section(tile_diagnostics))

    body = "\n".join(sections)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>Stage&harr;Camera Calibration Metrology Report</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        "<h1>Stage&harr;Camera Calibration Metrology Report</h1>\n"
        f'<div class="meta">Generated: {generated}</div>\n'
        f"{body}\n"
        "</body>\n</html>\n"
    )


def _render_verdict_banner(cal: Any, affine: AffineFit | None, tolerance_um: float | None) -> str:
    if affine is None:
        notes = html.escape(str(getattr(cal, "notes", "")))
        return (
            '<div class="banner fail">&#10007; FAILED CALIBRATION &mdash; no affine fit '
            "available (<code>cal.affine is None</code>)</div>\n"
            f'<div class="notes">{notes}</div>'
        )
    if tolerance_um is None:
        return '<div class="banner neutral">No tolerance set &mdash; no PASS/FAIL verdict.</div>'

    summary = residual_summary(affine.residuals_px, affine.mean_px_per_mm, tolerance_um=tolerance_um)
    passed = bool(summary["passes"])
    max_um = float(summary["max_abs_um"])
    cls = "pass" if passed else "fail"
    symbol = "&#10003;" if passed else "&#10007;"
    verdict = "PASS" if passed else "FAIL"
    return (
        f'<div class="banner {cls}">{symbol} {verdict} &mdash; max residual '
        f"{max_um:.3f}&nbsp;&micro;m vs tolerance {float(tolerance_um):.3f}&nbsp;&micro;m</div>"
    )


def _rotation_shear_deg(matrix_px_per_mm: np.ndarray) -> tuple[float, float]:
    """Rotation and shear (degrees) of a 2x2 mm->px affine matrix whose
    columns are the image-space response vectors to a +1 mm object motion
    along X (column 0) and Y (column 1) respectively (see
    :class:`~analysis.camera_calibration.AffineFit`'s docstring).

    ``rotation_deg`` is the angle of column 0 from the +u (horizontal image)
    axis. ``shear_deg`` is the deviation of the angle BETWEEN the two
    columns from a perfect 90 degrees (0 for an ideal, non-skewed
    calibration; the sign follows the standard CCW-positive convention)."""
    m = np.asarray(matrix_px_per_mm, dtype=np.float64)
    col_x = m[:, 0]
    col_y = m[:, 1]
    angle_x = math.degrees(math.atan2(float(col_x[1]), float(col_x[0])))
    angle_y = math.degrees(math.atan2(float(col_y[1]), float(col_y[0])))
    delta = ((angle_y - angle_x + 180.0) % 360.0) - 180.0
    return angle_x, delta - 90.0


def _render_summary_section(cal: Any, affine: AffineFit | None) -> str:
    n_points = getattr(cal, "n_points", None)
    notes = html.escape(str(getattr(cal, "notes", "")))
    backlash_mm = getattr(cal, "backlash_mm", None)
    rows = [("Calibration points", "" if n_points is None else str(int(n_points)))]

    if affine is not None:
        rotation_deg, shear_deg = _rotation_shear_deg(affine.matrix_px_per_mm)
        um_per_px_x = 1000.0 / affine.px_per_mm_x if affine.px_per_mm_x > 0.0 else float("inf")
        um_per_px_y = 1000.0 / affine.px_per_mm_y if affine.px_per_mm_y > 0.0 else float("inf")
        rows.extend([
            ("Scale X", f"{affine.px_per_mm_x:.4f} px/mm ({um_per_px_x:.4f} &micro;m/px)"),
            ("Scale Y", f"{affine.px_per_mm_y:.4f} px/mm ({um_per_px_y:.4f} &micro;m/px)"),
            ("Rotation", f"{rotation_deg:.3f}&deg;"),
            ("Shear", f"{shear_deg:.3f}&deg;"),
            ("RMS residual", f"{affine.rms_px:.4f} px ({affine.rms_um:.3f} &micro;m)"),
            ("Max |residual|", f"{affine.max_abs_px:.4f} px ({affine.max_abs_um:.3f} &micro;m)"),
            ("Fit rank", str(int(affine.rank))),
            (
                "Affine matrix (px/mm)",
                "[[{:.4f}, {:.4f}], [{:.4f}, {:.4f}]]".format(*affine.matrix_px_per_mm.flatten()),
            ),
            ("Offset (px)", "[{:.3f}, {:.3f}]".format(*affine.offset_px)),
        ])
    if backlash_mm is not None:
        bx, by = float(backlash_mm[0]), float(backlash_mm[1])
        rows.append(("Backlash (mm)", f"X={bx:.5f}, Y={by:.5f}"))

    row_html = "\n".join(
        f"<tr><th>{html.escape(k)}</th><td class=\"num\">{v}</td></tr>" for k, v in rows
    )
    return (
        "<h2>Calibration summary</h2>\n"
        f"<table>\n{row_html}\n</table>\n"
        f'<div class="notes">{notes}</div>'
    )


# --------------------------------------------------------------------------- #
# Residual quiver (inline SVG)                                               #
# --------------------------------------------------------------------------- #
_MARGIN = 60.0
_SPACING = 90.0
_MAX_ARROW_LEN = 0.42 * _SPACING  # keeps arrows from overlapping their grid neighbour
_LEGEND_H = 70.0


def _render_quiver_section(affine: AffineFit) -> str:
    n = len(affine.residuals_px)
    caption = (
        '<p class="quiver-caption">Base points are laid out on a synthetic '
        "index grid (row-major) -- the calibration object does not retain "
        "each point&#39;s absolute stage/image position, only its residual "
        "vector. Arrow direction/length is the fit residual "
        "(measured &minus; predicted), magnified for visibility; see the "
        "scale legend for the true px/&micro;m length it represents.</p>"
    )
    if n == 0:
        return "<h2>Residual quiver</h2>\n<p>No calibration points.</p>\n" + caption

    svg = _build_quiver_svg(affine)
    return f"<h2>Residual quiver</h2>\n<div class=\"quiver-wrap\">{svg}</div>\n{caption}"


def _build_quiver_svg(affine: AffineFit) -> str:
    residuals = np.asarray(affine.residuals_px, dtype=np.float64)
    n = len(residuals)
    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = max(1, int(math.ceil(n / cols)))

    width = 2.0 * _MARGIN + max(0, cols - 1) * _SPACING
    height = 2.0 * _MARGIN + max(0, rows - 1) * _SPACING + _LEGEND_H

    max_abs_px = float(affine.max_abs_px)
    arrow_scale = (_MAX_ARROW_LEN / max_abs_px) if max_abs_px > 1e-12 else 0.0

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.1f}" '
        f'height="{height:.1f}" viewBox="0 0 {width:.1f} {height:.1f}">',
        "<defs>"
        '<marker id="qarrow" markerWidth="8" markerHeight="8" refX="6" refY="3" '
        'orient="auto-start-reverse"><path d="M0,0 L6,3 L0,6 Z" fill="#1f5fbf"/></marker>'
        "</defs>",
        f'<rect x="0" y="0" width="{width:.1f}" height="{height:.1f}" fill="#ffffff"/>',
    ]

    for i in range(n):
        r, c = divmod(i, cols)
        bx = _MARGIN + c * _SPACING
        by = _MARGIN + r * _SPACING
        du, dv = float(residuals[i, 0]), float(residuals[i, 1])
        ex = bx + du * arrow_scale
        ey = by + dv * arrow_scale
        parts.append(f'<circle cx="{bx:.2f}" cy="{by:.2f}" r="2.4" fill="#5b6673"/>')
        parts.append(
            f'<line x1="{bx:.2f}" y1="{by:.2f}" x2="{ex:.2f}" y2="{ey:.2f}" '
            'stroke="#1f5fbf" stroke-width="1.6" marker-end="url(#qarrow)"/>'
        )

    parts.append(_quiver_legend_svg(width, height, arrow_scale, affine.mean_um_per_px))
    parts.append("</svg>")
    return "\n".join(parts)


def _quiver_legend_svg(width: float, height: float, arrow_scale: float, um_per_px: float) -> str:
    ly = height - _LEGEND_H / 2.0 - 6.0
    lx0 = _MARGIN
    ref_svg_len = _MAX_ARROW_LEN
    ref_px = (ref_svg_len / arrow_scale) if arrow_scale > 1e-12 else 0.0
    ref_um = ref_px * float(um_per_px) if math.isfinite(um_per_px) else float("nan")
    lx1 = lx0 + ref_svg_len
    label = f"scale: {ref_px:.4f} px = {ref_um:.4f} &micro;m" if math.isfinite(ref_um) else "scale: n/a"
    return (
        f'<line x1="{lx0:.2f}" y1="{ly:.2f}" x2="{lx1:.2f}" y2="{ly:.2f}" '
        'stroke="#1f5fbf" stroke-width="1.6" marker-end="url(#qarrow)"/>'
        f'<text x="{lx0:.2f}" y="{ly + 18:.2f}" font-size="11" fill="#1a1f26">{label}</text>'
    )


# --------------------------------------------------------------------------- #
# Tile diagnostics (E4 place_tiles(return_diagnostics=True))                 #
# --------------------------------------------------------------------------- #
def _render_tile_diagnostics_section(diag: Mapping[str, Any]) -> str:
    rows: list[tuple[str, str]] = []

    if "n_clamped" in diag:
        rows.append(("Seams clamped", str(int(diag["n_clamped"]))))
    if "mean_abs_offset_px" in diag:
        rows.append(("Mean |applied offset|", f"{float(diag['mean_abs_offset_px']):.4f} px"))
    offsets = diag.get("applied_offset_px")
    if isinstance(offsets, Sequence) and not isinstance(offsets, (str, bytes)):
        mags = [math.hypot(float(dy), float(dx)) for dy, dx in offsets]
        max_mag = max(mags) if mags else 0.0
        rows.append(("Tiles", str(len(offsets))))
        rows.append(("Max |applied offset|", f"{max_mag:.4f} px"))

    known = {"n_clamped", "mean_abs_offset_px", "applied_offset_px"}
    for key, value in diag.items():
        if key in known:
            continue
        rows.append((html.escape(str(key)), html.escape(str(value))))

    row_html = "\n".join(
        f"<tr><th>{html.escape(k)}</th><td class=\"num\">{v}</td></tr>" for k, v in rows
    )
    return "<h2>Mosaic tile-placement diagnostics</h2>\n<table>\n" + row_html + "\n</table>"
