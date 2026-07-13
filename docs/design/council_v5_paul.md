# Council v5 — Paul's seat (hardware-truth panels)

Scope: Motor Stage, Bias Supply, Laser/Trigger, Camera, Device Manager.
Grounded in the real driver surface, not the mockups. Reads:
`cockpit_design_system.md` (8 laws), `council_v5_codex.md`,
`feinschliff_gap_notes_adam.md`. Tokens from design-system §2.

## 1. State taxonomy — the canonical hardware state ladder

One ladder feeds EVERY chip/dot/banner/well. A device is in exactly one rung.
Fill = confident; hollow/dashed = "I can't read this". Red is spent nowhere but
HV-energized + trip + abort (law 2). Green is spent nowhere here (law 1/6).

| Rung | Meaning | Dot / chip treatment | Token |
|---|---|---|---|
| OFFLINE | confidently disconnected | faint SOLID dot, muted label | faint #5B657A |
| CONNECTING | handshake in flight | accent hollow dot, ONE live pulse | accent #5AA9FF |
| SIM | simulated backend live | **hatched-cyan ring** (marking only) | sim #41D8E4 |
| IDLE-nominal | real, connected, quiescent | muted SOLID dot, no color, calm | muted #98A1B5 |
| ACTIVE·motion | stage moving / armed / HV ramping-arm | amber fill | armed #FFB84D |
| ACTIVE·HV-live | output energized (ramping↑↓ / settled) | **red fill** | danger #FF5A61 |
| ACTIVE·benign | camera streaming / scope live-acquire | accent fill (NOT amber, NOT green) | accent #5AA9FF |
| UNKNOWN | connected but driver can't read this fact | **muted DASHED hollow ring + "?"**, desaturated, "unknown" caption | muted, no fill |
| TRIPPED/FAULT | trip / interlock / lost mid-op | red fill + ONE attention pulse, errorText surfaced | danger #FF5A61 |

UNKNOWN is the load-bearing new rung: it is NOT red (unknown ≠ danger) and NOT
a fill (a fill would claim a confident state we don't have). Dashed muted ring
distinguishes it from OFFLINE's confident solid dot and IDLE's confident solid
dot. HV-energized is the only steady red; a settled expected HV is still
live-dangerous, so red is correct there (law 1: "live-dangerous").

## 2. Per-panel rulings (hardware-truth angle)

**Motor Stage** — endorse Codex (stage-view hero + compact bottom command tray).
Never behind a drawer: live position readback, **limit-switch state**, homed
readiness, is_moving (amber), and **STOP** (loudest, always visible). Safe to
collapse: jog step presets, absolute-move entry. Truth: GRBL limit parse +
Marlin motion have no readback (design-system §6 backlog) → position/limits fall
to UNKNOWN, never a green "LIMIT OK". Adam gap: MOVE STAGE row is motion → amber,
never red. Offline Position slab → compact OFFLINE state, not an em-dash void.

**Bias Supply** — endorse Codex safety-dashboard (measured V + HV STATE hero
pair). Never behind a drawer: measured V (readback), **HV STATE chip**,
compliance/current, interlock/trip, and the **kill-switch (All-HV-off)**. Safe
to collapse: IV/CCE standalone sweeps ("advanced" card); polarity control hidden
when `supports_polarity_switch()` is False. **Kill-switch escalation ruling**
(the requested call): it is ALWAYS visible but escalates with real HV energy —
OFFLINE → ghost outline, muted, no fill (nothing to kill); connected + output-off
→ neutral outline (ready, inert); HV-live (ramping/settled) → **filled red,
full salience, one-tap instant**. Red arrives only with volts, never as chrome.
Adam gap fixed: the two red slabs while DISCONNECTED drop to quiet outline.

**Laser / Trigger** — endorse Codex split (truth banner ⟂ wavegen sheet). The
manual laser is `pc_controllable = False` → software CANNOT read emission; the
amber truth banner is mandatory and says "emission not readable — verify at the
laser," never a fake switch (law 7). Fix Adam's violations: "OUTPUT STATE
UNKNOWN" red → UNKNOWN taxonomy (muted dashed); "LOAD 50 Ω" green → neutral mono
config value. The wavegen DOES know its output bit → amber/neutral armed, kept
distinct from the un-knowable laser emission. Never hidden: the truth banner.

**Camera** — endorse Codex full-bleed well + glass overlay rail + collapsible
inspector. Fix Adam violation: "CAMERA NOT CONNECTED" red → OFFLINE neutral.
Never hidden: **saturation/clipping** on the image (promote from log), streaming
state, Live/Single/Stop. Streaming = ACTIVE·benign accent, not amber/green. Safe
to collapse: image-processing sheet, camera-info tiles.

**Device Manager** — see §3.

## 3. Device Manager — kill the 12-button zoo

Row grammar, one row per device:
`[state dot (taxonomy)]  Device name  [SIM badge if sim]  ······  [ single toggle ]`
- **State dot** = the §1 ladder (glanceable OFFLINE/SIM/IDLE/UNKNOWN/FAULT).
- **Single action**: one toggle labeled by current state (Connect / Disconnect) —
  replaces the CONNECT+DISCONNECT pair. No per-row color on the command itself.
- **SIM badge**: hatched-cyan chip inline (law 6), not a separate column.
- Header **Connect All** = one primary, **neutral/accent — NOT green** (Adam
  gap #2: color encodes state, never a command).
- Failed connect = inline EmptyState **error row** (design-system §6), not a
  QMessageBox.
- Names must not truncate ("OSCILL…") — intrinsic width, ellipsize last.

**Shell rail then still shows** (the always-on glance the dialog is not): the
per-device state dot (≥4 states), the "Connected N/M" chip, the persistent
sim ribbon, and any FAULT/TRIP pulse — so an operator never opens the dialog to
learn something went red. Dialog = manage; rail = monitor.

## 4. Trust boundaries (law 8 — never imply state we don't know)

| Where v5 risks a lie | Honest replacement |
|---|---|
| Monitor "ALL NOMINAL" with zero readings | NO-DATA / not-polling state (stale taxonomy); never green-nominal without data |
| Camera histogram fake flat line offline | designed empty canvas ("camera offline"), no drawn line |
| Scope/RefMon/Monitor fake −200..200 ns axes offline | dim empty canvas, no fake grid |
| Bias `_output_on` is a SOFTWARE bit, no HV readback | when unread → HV STATE = UNKNOWN, never assumed OFF (false-safe) nor red. `TODO(manual needed)`: output-on bit decode |
| Manual laser implied emission control | banner only; emission = UNKNOWN by construction |
| Motor "LIMIT OK"/green on GRBL/Marlin (no parse) | limit state UNKNOWN; Marlin motion = "moving (commanded, no readback)" |
| Motor position during Marlin move | measured-vs-commanded labeled apart (law 7) |

## 5. Law conflict flagged in other seats

**Codex Bias move #8** — "DangerGate envelope as a red-accented tray pinned to
the bottom." A permanently red tray while DISCONNECTED / output-off violates
law 1 (quiet nominal) and law 2 (red only when HV is live). The tray's red must
be **conditional**, escalating with real HV energy per my kill-switch ruling in
§2 — quiet outline until armed/live. Red as standing chrome is not permitted.
