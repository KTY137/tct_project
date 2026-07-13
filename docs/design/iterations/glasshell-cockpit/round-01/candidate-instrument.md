# Candidate A — INSTRUMENT

> **Philosophy.** The cockpit is an *instrument face*. Depth is **structural** — four fixed
> layers, each of which means something, none of which ever move. The glass is a finish on a
> machine that already works without it.

**Optimizes for:** glanceability across the room, muscle memory, and safety by *position*.
**Deliberately sacrifices:** screen real estate (the vitals bar and the phase rail are a
permanent tax, ≈ 166 px of the 1080 px a lab monitor really has), and any notion of the operator
reconfiguring their cockpit. Everyone's TCT looks identical, forever. That is the point, and it
is also the cost.

Open `candidate-instrument.html`. Toggle **Tier → Flat** and **Backdrop → Worst case**.

---

## 1. The problem this solves

I read the running app, not an idea of it (`artifacts_claude/ui_onscreen_20260713T202649Z/`).
Four defects are visible in the screenshots and are the brief:

1. **Five stacked chrome bands.** Native title bar → menu bar (File/View/Devices/Help) → toolbar
   (Connect All / Disconnect All / Device Manager / Settings / Show Log / Show Device Debug) →
   the QML status island → the 12-pill tab shelf. That is ≈ 290 px of 2180 px — **13 % of the
   screen is chrome**, and it is redundant chrome: `State: DISCONNECTED` appears in the toolbar
   *and* the device chips appear in the island.
2. **The island is clipped.** In both the dark and light captures the `MOTION` group runs off the
   right edge — the word "Motion" is literally cut in half. The island does not fit its content
   at the app's own default width.
3. **Twelve peer tabs that are not peers.** Motor Stage, Reference Monitor, Camera, Oscilloscope,
   Laser/Trigger, Scan Viewer, Scan Planner, Scan Sequencer, Bias Supply, Calibration, Monitor,
   Analysis. Some are setup, some are run, some are post-hoc study. Flat tabs force the operator
   to hold that taxonomy in their head.
4. **Nothing owns "is the beam on".** The most safety-relevant facts in the room — HV state,
   laser state, whether a scan is moving the stage — are rendered as 12 px chips reading `off`.
   You cannot read that from two metres away. This is an instrument someone watches while a beam
   is on.

## 2. The design

### 2.1 The four layers (this *is* the candidate)

| # | Layer | Owns | Material | Height |
|---|---|---|---|---|
| 1 | **Vitals bar** | Bias · Leakage · Stage · Laser · Scan | `chrome` (glass) | 88 px, fixed |
| 2 | **Phase rail** | Which panel is on the stage | `chrome` (glass) | 78 px wide, fixed |
| 3 | **Stage** | The panels themselves, as cards | `panel` (glass) | fills |
| 4 | **Armed rail** | Every dangerous action, forever | **`panel` — OPAQUE, ALWAYS** | 64 px, fixed |

Layer 1 replaces the title bar, the menu bar, the toolbar *and* the status island. Five bands
become one. The menu collapses to a single `⋯` button; the drag region is the bar itself.

### 2.2 The vitals bar — the number is the hero

Straight from the Vision Pro dashboard plate: a tiny tracked uppercase caption, then a **huge
tabular-mono value**, then a small unit. Not `HV --` in 12 px; **`−400.0 V` in 34 px**.

Five vitals, chosen because they are the five things that can hurt you or invalidate the run:
Bias (HV) · Leakage (with a sparkline — the trend is the tell) · Stage position · Laser · Scan
progress. Each carries a **filled left stripe** (3 px) plus a **dot** plus a **word**
(`HV ON`, `ARMED`, `RUNNING`). Three redundant channels, none of them the material.

### 2.3 The phase rail — 12 tabs become 3 phases

`SET UP` (Stage, Bias, Laser, Scope, Camera, Devices) · `RUN` (Planner, Sequence, Scan, Monitor) ·
`STUDY` (Analysis, Calibration). Hairline dividers, group captions at 9 px. The rail is the IA
fix: the taxonomy now lives on screen instead of in the operator's memory.

The selected tab is a **solid opaque accent fill**, not a glass tint — the visionOS rule from
`Core-Components-and-Interactions-1.png`: the *committed* thing is solid; glass is for the
passive. It therefore reads identically at FLAT.

### 2.4 The armed rail — safety by position

Every dangerous action lives in the same strip, at the bottom, forever. `Arm HV` · `Arm Motion` ·
`Arm Scan` · `ABORT`. Arming reveals a **separate** Execute button and starts a 10 s countdown
that **expires closed**. Only one thing can be armed at a time. The left half of the rail is the
**envelope** — what the next action will actually do, in words, before you can do it.

This is not a new gate. It is `gui/arm_latch.py` (Arm → hold → the danger-red Execute appears)
given a permanent home instead of being buried inside whichever panel happens to be showing.

## 3. Justification

**Problem solved.** Chrome collapses 5 bands → 1. The IA collapses 12 peers → 3 phases. The
across-the-room question ("is the beam on?") gets a 34 px answer. The dangerous controls stop
moving around.

**Alternatives considered inside this candidate.**
- *Vitals as a bottom bar.* Rejected: the eye goes to the top-left first, and a bottom bar
  competes with the armed rail for the "always look here" slot. One reflex per edge.
- *Rail on the right.* Rejected: LTR scanning puts navigation left; the right edge is where a
  detached panel gets dragged out to.
- *Merge the armed rail into the vitals bar* (one band, top). Rejected on safety grounds: reading
  and acting must not share a surface. If the place you *look* is the place you *click*, a glance
  can become a press.

**Safety implications.**
- The armed rail is painted with the `panel` **token**, never a material, at every tier. I state
  this as a law: **the hazard surface is tier-invariant.** On RDP, in high contrast, on the full
  glass build, the danger controls are byte-identical. Muscle memory is a safety feature; a
  surface that changes appearance by environment corrodes it.
- Hazard state is carried by stripe + dot + word + colour. Remove colour entirely (greyscale
  print, deuteranopia) and `HV ON` still reads. Remove the glass (FLAT) and nothing at all
  changes.
- The abort button is the only control in the app that is *always* one click away. Everything
  dangerous is two.

**Operational implications.** The vitals bar is a fixed 88 px cost. On a 1080 p lab monitor that
is 8 % of height, spent to make the other 92 % safe to leave unattended. The phase rail is 78 px
of width (4 %) and removes a 12-item tab strip that was 44 px of height anyway — close to a wash.

**Why now.** The measured correction of 2026-07-14 (`SYNTHESIS.md` banner) says the main window
*can* frost on the OpenGL RHI. A fixed-layer shell is the cheapest thing to build on that: the
layers map 1:1 onto the material roles the glass contract already defines.

## 4. Tokens

Existing tokens only, except:

| Token | Value | Derived from |
|---|---|---|
| `crit_ink_light` | `#C22A33` | `WARN_RED_LIGHT` (`#DE434B`) darkened ≈ 22 %. **Fixes a live AA failure** — see §5. |
| `FONT_VITAL_PX` | `34` | `FONT_VALUE_PX` (26) × 1.3 — the across-the-room readout size. |
| `WEIGHT_VITAL` | `600` | = `WEIGHT_VALUE`. |
| `RADIUS_CONTAINER` | `28` | `RADIUS_LG` (16) + `SPACE_MD` (12) — concentric: a 12 px-inset child at radius 16 nests exactly. |
| `SPACE_XXL` | `32` | 2 × `SPACE_LG`. |

## 5. Contrast — measured, not asserted

Dark, on `panel` `#0D111A`: ink `#E9EDF5` **15.9:1** · muted `#98A1B5` **7.2:1** ·
accent `#5AA9FF` **7.6:1** · crit `#FF5A61` **6.1:1** · armed `#FFB84D` **10.9:1** ·
good `#3DD68C` **10.0:1**. Dark ink `#0A0D13` on a `crit` fill: **6.4:1**.

**Two failures I found in the current token set, and did not paper over:**

1. `faint` `#5B657A` on dark `panel` = **3.2:1**. That is below AA for normal text. It is legal
   only for ≥ 18.66 px bold / 24 px text, or as non-text (hairlines, disabled marks). Today it is
   used for small captions. **Any candidate that adopts it for body text is broken.** In this
   design `faint` appears only at ≥ 24 px or as a non-text stripe.
2. **Light-mode `crit` `#DE434B` fails AA as text**: **4.19:1** on `panel` (white) and **3.50:1**
   on `canvas` `#E6EBF3`. Both below 4.5. White text *on* a `#DE434B` fill is also only 4.19:1.
   This is a live accessibility bug in the shipped light theme — the very theme the screenshots
   already show as broken (jog-arrow glyphs vanish white-on-white; plot titles ghost out).
   The new `crit_ink_light` `#C22A33` gives **5.7:1** on panel, **4.8:1** on canvas, and **5.7:1**
   for white ink on the fill. All pass. `crit` `#DE434B` survives as the *graphic* token (stripes,
   dots, 3:1 non-text).

## 6. Weaknesses (attack these)

1. **The permanent tax is real and I cannot argue it away.** 88 px + 78 px are gone before a
   single waveform is drawn. On a 1080 p monitor with the scope card open, the trace loses ~15 %
   of its height compared to today. An operator doing 6 hours of alignment — where none of the
   five vitals ever change — pays that tax for nothing. **The design has no answer for the case
   where the vitals are boring.** A collapsible vitals bar would answer it and would also destroy
   the entire premise (a safety readout you can hide is not a safety readout). I have no third
   option, and I am not going to pretend I do.
2. **Five vitals is a guess, and it is probably wrong.** I picked Bias / Leakage / Stage / Laser /
   Scan by reasoning about hazard, not by watching anyone run a TCT measurement. Leakage current
   in particular may be a *diagnostic* the operator checks deliberately rather than a *vital* that
   must be resident — in which case one fifth of my most expensive real estate is wasted. Temp/
   humidity might belong up there instead. This needs Kaya, not me. If the five are wrong, the
   whole top band is wrong.
3. **The armed rail makes three dangerous actions permanently visible and permanently clickable.**
   Two clicks from resting state to HV. Candidate B's summoned ceremony is *unambiguously* harder
   to trigger by accident, and I cannot claim otherwise. My defence is muscle memory and the
   10-second expiry — but "the button is always there" is exactly the property a critic should
   attack, and a sleeve-brush on a touchscreen-equipped lab PC is a real failure mode I have not
   designed against. If Kaya's lab has a touch monitor, this candidate is in trouble.
4. **Twelve panels do not fit a 78 px rail with real labels.** At 9.5 px, "Sequence" and
   "Calib." are already truncations. Either the rail widens (more tax) or the labels degrade to
   icon-only (and icon-only navigation for a domain with no icon conventions — what is the icon
   for "Reference Monitor"? — is a discoverability disaster). The mockup papers over this with
   abbreviations. A real build has to choose.
5. **It is the most conservative of the three.** It is the current app, cleaned up and given a
   spine. If Kaya's ask ("match the design_assets like VisionOS more") means *feel different*,
   this candidate under-delivers on ambition — it delivers rigour instead. That is a legitimate
   thing to reject it for.
