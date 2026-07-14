"""WCAG contrast guard for the whole design-system palette.

WHY (the audit that produced this file, 2026-07-14): the LIGHT palette was
systemically below WCAG AA and two SAFETY tokens were among the failures —
``sim`` (law 6: "this data is SIMULATED") measured **3.18:1** on a panel and
**2.66:1** on the canvas, ``warn``/``armed`` (law 5: the motion/homing command
class) **4.07/3.40**, ``crit`` **4.19/3.50**, ``faint`` **2.73/2.28**, and the
white label on the HV/abort danger button **4.19 light — and 3.05 in DARK,
the pair nobody had ever checked**. A status colour that cannot be read is not
a status colour, and an unreadable Abort label is a hazard.

WHAT IS ENFORCED
----------------
Every (foreground token, background) pair the QSS in ``gui/style.py`` actually
paints together, in BOTH themes:

* **text** — 4.5:1. Includes the 18 px bold compact readout value: 18 px is
  BELOW WCAG's 18.66 px large-text cutoff, so it gets the full 4.5, not the
  lenient 3.0 floor.
* **non-text state indicators** (``StatusLamp``'s 9 px dot — a colour-only
  carrier with no label) — 3.0:1.

The background is often NOT a plain token: a status chip paints
``rgba(token, alpha)`` over its parent surface, so the effective background is
``_blend(token, surface, alpha)``. That is the pattern that broke the old
palette — ink painted on a wash **of itself** — and it is modelled explicitly
here (:data:`_WASHES`), because it is the case a naive token-vs-token audit
misses.

NON-VACUITY
-----------
The pair model below describes the DESIGN (which ink lands on which surface),
not the current hex values, and the two tokens the fix introduced
(``danger_fill``/``on_danger``) are looked up with a fallback that reproduces
the OLD behaviour (``crit`` as its own fill, a literal white label). So this
file runs meaningfully against the pre-fix palette as well — where it reports
26 failing pairs, including every one the audit named. See
``test_new_safety_tokens_exist`` for the assertion that the fallbacks are dead
in the shipped palette.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui import style
from gui.style import DARK, LIGHT, PLOT_BG, PLOT_FG, _blend

# --------------------------------------------------------------------------- #
# WCAG 2.1 relative luminance / contrast ratio (definition, not an approximation)
# --------------------------------------------------------------------------- #

AA_TEXT = 4.5
AA_NON_TEXT = 3.0


def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b))


def contrast(fg: str, bg: str) -> float:
    lf, lb = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


# --------------------------------------------------------------------------- #
# The pair model — what gui/style.py's QSS actually paints on what.
# --------------------------------------------------------------------------- #

# Opaque surfaces a chip / button / label can sit ON (its parent's fill).
_CARD_SURFACES = ("panel", "raised", "field", "chrome", "material", "hover")
# ... plus the window canvas, for labels that can land on the shell itself.
_SHELL_SURFACES = _CARD_SURFACES + ("canvas",)
# Recessed surfaces that carry text: input wells, the stale-readout cell,
# the segmented track, table headers.
_WELL_SURFACES = ("well", "sunk", "pressed", "disabled_bg", "strip", "chip")

# Alphas at which a SEMANTIC token is washed over its parent surface by the
# QSS (statusChip / state buttons / the motion-pulse hooks / readoutCell flash).
# Pinned against the real stylesheet by test_wash_alphas_match_the_qss below.
_WASHES = (0.07, 0.10, 0.12, 0.14, 0.16, 0.20, 0.24)

_SEMANTIC = ("good", "warn", "crit", "sim", "armed", "danger", "error")


def _p(mode: str) -> dict:
    return DARK if mode == "dark" else LIGHT


def _danger_fill(p: dict) -> str:
    # Fallback == the OLD design (the danger button was filled with `crit`),
    # so this module also runs against the pre-fix palette.
    return p.get("danger_fill", p["crit"])


def _on_danger(p: dict) -> str:
    return p.get("on_danger", "#ffffff")     # OLD: a literal `white` label


def _on_armed(p: dict) -> str:
    return p.get("on_armed", "#ffffff")


def text_pairs(mode: str) -> list[tuple[str, str, str, str]]:
    """(label, fg_hex, bg_hex, why) for every TEXT pair the QSS paints."""
    p = _p(mode)
    pairs: list[tuple[str, str, str, str]] = []

    def add(label, fg, bg, why):
        pairs.append((f"{mode}:{label}", fg, bg, why))

    # -- neutral inks ----------------------------------------------------- #
    for surf in _SHELL_SURFACES + _WELL_SURFACES:
        add(f"text-on-{surf}", p["text"], p[surf], "body/value ink")
        add(f"muted-on-{surf}", p["muted"], p[surf],
            "captions, chip labels, group titles, table headers")

    # -- accent ink (outline buttons, busy/checked chips, links) ---------- #
    # `canvas` and `chip` are included even though nothing paints accent text
    # there TODAY: leaving a surface out because "we happen not to use it" is how
    # the palette got here. Every surface an ink could plausibly land on is
    # measured, so a future panel cannot open a new failing pair silently.
    for surf in _SHELL_SURFACES + ("tint", "active", "chip"):
        add(f"accent-on-{surf}", p["accent"], p[surf],
            "secondary/connect button label, info+busy chip, checked toolbutton")

    # -- semantic ink on a PLAIN surface ---------------------------------- #
    # The motion command class (transparent motion button), the laser hazard
    # banner, the planner guard label, and — the important one — the hero
    # readout VALUE ink (ReadoutCell/MetricTile state ink, incl. the 18 px
    # bold compact variant, which is below the large-text cutoff).
    for tok in _SEMANTIC:
        for surf in _SHELL_SURFACES + ("chip",):
            add(f"{tok}-ink-on-{surf}", p[tok], p[surf],
                "motion button / hazard banner / hero readout state ink")

    # -- ink on a WASH OF ITS OWN COLOUR (the pattern that broke the palette) #
    # Chips and state buttons paint rgba(token, alpha) over their parent, then
    # put a label on top. The label ink is `text` for semantic states (the fix)
    # and `accent` for the accent-tinted info/busy family.
    for tok in _SEMANTIC:
        for surf in _CARD_SURFACES:
            for alpha in _WASHES:
                bg = _blend(p[tok], p[surf], alpha)
                add(f"chip-label-on-{tok}-wash{alpha}-{surf}", p["text"], bg,
                    "status-chip / state-button label on its coloured fill")
    # The accent family is the one place a same-hue ink survives, because its
    # wash is the OPAQUE, palette-computed `tint` token (a fixed 0.10/0.13 blend
    # over `panel`), not a live rgba over an arbitrary parent. Live rgba(accent)
    # fills under an accent label are forbidden — enforced mechanically against
    # the real stylesheet by test_no_qss_block_paints_ink_on_a_wash_of_itself.
    for tone in ("tint", "active"):
        add(f"accent-label-on-{tone}", p["accent"], p[tone],
            "info/busy chip, busy button, checked toolbutton")

    # -- ink on a SOLID accent / hazard fill ------------------------------ #
    add("on_accent-on-accent", p["on_accent"], p["accent"], "primary button label")
    add("on_accent-on-accent_strong", p["on_accent"], p["accent_strong"],
        "primary button hover label")
    add("ribbonMark", p["on_accent"], p["accent"], "the 'T' brand mark")

    fill = _danger_fill(p)
    for label, bg in (("danger-fill", fill),
                      ("danger-fill-hover", style._darken(fill, 0.12)),
                      ("danger-fill-pressed", style._darken(fill, 0.22))):
        add(f"on_danger-on-{label}", _on_danger(p), bg,
            "THE HV / scan-abort button label")

    add("on_armed-on-armed", _on_armed(p), p["armed"],
        "motion button, pressed (armed fill)")

    # -- the fixed dark instrument screen (both themes) -------------------- #
    add("plot_fg-on-plot_bg", PLOT_FG, PLOT_BG, "plot axis text")
    add("plot_accent-on-plot_bg", p.get("plot_accent", p["accent"]), PLOT_BG,
        "the motor position LCD (#readoutValue)")

    return pairs


def non_text_pairs(mode: str) -> list[tuple[str, str, str, str]]:
    """StatusLamp is a 9 px dot with NO label — its colour is the sole carrier
    of the state, so it owes 3:1 against every surface it sits on."""
    p = _p(mode)
    pairs = []
    for tok in ("good", "warn", "crit", "sim", "accent", "muted"):
        for surf in _SHELL_SURFACES:
            pairs.append((f"{mode}:lamp-{tok}-on-{surf}", p[tok], p[surf],
                          "StatusLamp dot / hollow ring"))
    # The danger button's fill must be identifiable against the surface it
    # sits on (WCAG 1.4.11 UI component).
    for surf in ("panel", "field"):
        pairs.append((f"{mode}:danger-fill-vs-{surf}", _danger_fill(p), p[surf],
                      "HV/abort button body"))
    return pairs


def _report(failures: list[tuple[str, float, float, str]]) -> str:
    lines = [f"{len(failures)} pair(s) below the WCAG floor:"]
    for name, got, need, why in failures:
        lines.append(f"  {name:<48s} {got:5.2f} < {need}  ({why})")
    return "\n".join(lines)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_every_text_pair_clears_wcag_aa(mode):
    failures = [
        (name, contrast(fg, bg), AA_TEXT, why)
        for name, fg, bg, why in text_pairs(mode)
        if contrast(fg, bg) < AA_TEXT
    ]
    assert not failures, _report(failures)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_every_non_text_state_indicator_clears_3to1(mode):
    failures = [
        (name, contrast(fg, bg), AA_NON_TEXT, why)
        for name, fg, bg, why in non_text_pairs(mode)
        if contrast(fg, bg) < AA_NON_TEXT
    ]
    assert not failures, _report(failures)


# --------------------------------------------------------------------------- #
# faint — RETIRED FOR TEXT (see gui/style.py's token comment)
# --------------------------------------------------------------------------- #

def test_faint_is_never_used_as_text_ink_in_the_qss():
    """``faint`` cannot clear AA as text on ANY surface in EITHER theme (light
    2.73/2.28, dark 3.23) — no amount of tuning fixes that without collapsing it
    onto ``muted``. So it is retired for text: the only rules allowed to name it
    are the ``:disabled`` ones (WCAG 1.4.3 exempts an INACTIVE UI component's
    text) and non-text decoration. This guard reads the real stylesheet."""
    for mode in ("light", "dark"):
        p = _p(mode)
        qss = style.build_qss(p)
        offenders = []
        for block in qss.split("}"):
            if p["faint"] not in block:
                continue
            # `color:` is the only property that makes it TEXT. A border/
            # background/outline use is non-text and judged by the 3:1 rule.
            if "color:" not in block:
                continue
            for line in block.splitlines():
                stripped = line.strip()
                if not stripped.startswith("color:") or p["faint"] not in stripped:
                    continue
                selector = block.split("{")[0].strip().replace("\n", " ")
                if ":disabled" not in selector:
                    offenders.append(f"{selector} -> {stripped}")
        assert not offenders, (
            f"[{mode}] `faint` used as TEXT ink outside a :disabled rule — it "
            f"measures {contrast(p['faint'], p['panel']):.2f}:1 on a panel and "
            f"{contrast(p['faint'], p['canvas']):.2f}:1 on the canvas, both "
            f"below AA. Use `muted`.\n  " + "\n  ".join(offenders))


def test_faint_still_fails_aa_so_the_retirement_is_not_decorative():
    """Pins WHY faint is retired. If a future pass darkens `faint` until it
    clears AA, this test fails and the author must decide deliberately whether
    the token still has a distinct role or has simply become `muted`."""
    for mode in ("light", "dark"):
        p = _p(mode)
        assert contrast(p["faint"], p["panel"]) < AA_TEXT


# --------------------------------------------------------------------------- #
# Guards on the model itself — a contrast test that drifts from the QSS is worse
# than no test at all.
# --------------------------------------------------------------------------- #

def test_no_qss_block_paints_ink_on_a_wash_of_itself():
    """THE regression guard for the bug class this beat fixed.

    A rule that sets ``color: X`` and ``background: rgba(X, a)`` paints ink on a
    tint OF ITSELF: the fill drags the background toward the ink, so the pair is
    capped far below the token's plain-surface contrast (light `good` on its own
    0.16 chip: 3.53:1). This walks the REAL stylesheet, resolves every such
    block, and measures it against the worst surface the fill could composite
    over — no hand-maintained pair list to drift out of date.
    """
    import re

    block_re = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
    rgba_re = re.compile(r"background:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\)")
    color_re = re.compile(r"(?:^|;|\s)color:\s*(#[0-9a-fA-F]{6})")

    failures = []
    for mode in ("light", "dark"):
        p = _p(mode)
        for selector, body in block_re.findall(style.build_qss(p)):
            bg = rgba_re.search(body)
            fg = color_re.search(body)
            if not (bg and fg):
                continue
            r, g, b, alpha = int(bg[1]), int(bg[2]), int(bg[3]), float(bg[4])
            wash = f"#{r:02x}{g:02x}{b:02x}"
            ink = fg[1].lower()
            if wash.lower() != ink:
                continue                     # not a wash of its own ink — fine
            for surf in _CARD_SURFACES:
                got = contrast(ink, _blend(wash, p[surf], alpha))
                if got < AA_TEXT:
                    failures.append(
                        (f"{mode}:{selector.strip().splitlines()[-1].strip()}"
                         f" [over {surf}]", got, AA_TEXT,
                         f"color:{ink} on rgba({ink},{alpha})"))
    assert not failures, _report(failures)


def test_wash_alphas_match_the_qss():
    """Every ``rgba(<semantic token>, a)`` alpha the stylesheet actually emits
    must be covered by :data:`_WASHES` — otherwise a new, stronger chip fill
    could ship with an unmeasured label on it."""
    import re

    for mode in ("light", "dark"):
        p = _p(mode)
        qss = style.build_qss(p)
        rgba = re.findall(r"rgba\((\d+), (\d+), (\d+), ([0-9.]+)\)", qss)
        semantic_rgb = set()
        for tok in _SEMANTIC:
            h = p[tok].lstrip("#")
            semantic_rgb.add(tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)))
        for r, g, b, a in rgba:
            if (int(r), int(g), int(b)) not in semantic_rgb:
                continue
            alpha = float(a)
            # Borders/outlines may use any alpha (non-text); only FILL alphas
            # (<= 0.30) put a label on top and must be modelled.
            if alpha <= 0.30:
                assert alpha in _WASHES, (
                    f"[{mode}] the QSS paints a semantic fill at alpha {alpha}, "
                    f"which the contrast model does not cover — add it to _WASHES "
                    f"(and check the label ink still clears AA on it)")


def test_new_safety_tokens_exist():
    """The fix's two new tokens must be real (not silently falling back to the
    old, failing behaviour through this module's compatibility shims)."""
    for mode in ("light", "dark"):
        p = _p(mode)
        assert "danger_fill" in p, mode
        assert "on_danger" in p, mode
        assert "on_armed" in p, mode
        assert "plot_accent" in p, mode
