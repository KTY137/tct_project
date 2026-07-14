# Candidate B — STAGE

> **Philosophy.** At any moment you are doing exactly *one* thing. The cockpit shows **that**,
> full-bleed, and demotes everything else to a summoned periphery. Chrome is not resident — it is
> called. Danger is not a button you can reach — it is a **ceremony that takes the stage away from
> you**.

**Optimizes for:** focus, screen area for the data, and a danger gate that is genuinely hard to
trigger by accident. It is also the only candidate that will actually *look* like the visionOS
plates — content floating in space with almost nothing around it.
**Deliberately sacrifices:** peripheral awareness and discoverability. You cannot watch bias
*while* aligning; you get a 15 px stub instead. A new grad student facing a command palette
instead of a tab strip has nowhere to click.

Open `candidate-stage.html`. Press **Space** to dismiss/summon the capsule. Click **⚡ HV…** or
State → **HV ceremony**.

---

## 1. The problem this solves

Same ground truth as candidate A (five chrome bands ≈ 13 % of height, a clipped status island, 12
flat tabs, nothing readable across the room). Candidate B attacks it from the opposite end: rather
than *organising* the chrome, it **deletes** it.

The bet: in a TCT session the operator is nearly always in one of a few single-minded modes —
aligning the stage under the camera, tuning the scope trace, watching a scan run. In each mode
exactly one panel matters and the other eleven are noise that happens to be occupying pixels.

## 2. The design

### 2.1 The ribbon — 38 px, and that is all the resident chrome there is

One strip: brand, HV, leakage, XYZ, laser, scan. Mono, tabular, quiet.

The mechanism that makes this safe: **a cell in a hazard state does not tint — it FILLS.** It
becomes an opaque colour block with inverted ink and a glyph. `HV −400.0 V ON` is a solid red
block. `LASER ARMED` is a solid amber block. Print the screen in greyscale and those two cells are
still the only *filled* things on the strip — the state survives as **form**, not hue. This is the
answer to "never encode state by colour alone", and it is also why the material can never be
involved: the fill is painted at every tier.

### 2.2 The stage

One panel, full bleed, generous margins (32 px), with the visionOS typographic move: a tiny
tracked eyebrow (`SET UP · OSCILLOSCOPE · CH1`), a large light title, and then the **readouts as
hero numbers** underneath the canvas — Peak / Rise / Decay τ / Charge at 34 px mono, each on a
2 px left rule. No card borders, no nested boxes. The trace gets ~2× the height it gets today.

### 2.3 The summoned capsule

Straight out of `Core-Components-and-Interactions-1.png`: a floating rounded capsule of icon
buttons that appears near the bottom of the stage and dissolves. Space summons/dismisses it.
Panel switching is `⌘K` — a command palette, not a tab strip.

The capsule's HV control is styled deliberately unlike the others: it is an outlined
**key**, not a filled button, and it is the *only* thing in the capsule that does not perform an
action. It **opens the ceremony**. Nothing in the resting UI can enable HV.

### 2.4 The peek stubs

The demoted eleven live as 15 px-tall stubs on the right edge, each showing only its headline
number and a 3 px state stripe. Click one and it takes the stage; the previous stage becomes a
stub. Nothing is hidden — it is *ranked*.

### 2.5 The ceremony (the heart of this candidate)

An HV enable is not a dialog. It is a **takeover**: the stage is scrimmed, and an **opaque**
danger slab replaces it. Three gates, in order:

1. **The envelope, stated.** Target, ramp rate, compliance, channel, sensor, interlock — the
   machine tells you exactly what it is about to do, before you can agree to it.
2. **Three acknowledgements.** Not one "are you sure?" — three specific, checkable, *physical*
   claims about the room ("the dark box is closed", "nobody is touching the probe station",
   "−400 V is within this sensor's rated envelope"). The hold button is **dead** until all three
   are ticked.
3. **A 2-second hold.** Release early and it aborts. The bar fills; the label counts down.

Cancel, Escape, and a click on the scrim all fail **closed**. This is strictly *more* ceremony
than `gui/qt_danger_gate.py` provides today — a modal Yes/No. It is slower, on purpose.

## 3. Justification

**Problem solved.** Chrome drops from ~290 px to 38 px — the data gets the screen. And the
danger surface stops being *ambient*: there is no state of the resting UI from which one click
enables high voltage.

**Alternatives considered inside this candidate.**
- *Auto-hiding ribbon.* Rejected: a safety readout that hides itself is not a safety readout. The
  ribbon is the one thing that never goes away.
- *Peeks on the left.* Rejected: they would collide with the natural reading start of the stage.
- *Ceremony as a non-modal side sheet.* Rejected: a side sheet leaves the stage live, and "the
  operator was looking at the scope while agreeing to HV" is precisely the failure to design out.
  The takeover is the mechanism.

**Safety implications.**
- The ceremony slab is `panel` — **opaque at every tier**, with a 2 px `crit_ink` border. Same law
  as candidate A: *the hazard surface is tier-invariant.* At FLAT the scrim goes from
  `rgba(0,0,0,.42)` + blur to a flat `rgba(0,0,0,.72)` — **darker, not weaker**, because at FLAT
  there is no blur to do the separating work, and the modal must still read as modal.
- The material never carries hazard. The ribbon's fills are token colours; the ceremony's red is a
  token colour; the blur is decoration in both.
- **The risk this candidate creates, honestly:** the ribbon is 38 px. That is *smaller* than
  today's chips. Its filled-cell mechanic is legible up close, but at 12 px mono a red block from
  four metres says "something is red", not "HV is at −400 V". Candidate A is unambiguously better
  across the room. This is the trade.

**Operational implications.** A command palette is a power-user instrument. It is superb for a
PhD student who runs this daily and hostile to a visiting collaborator. That is a real
organisational choice, not a UI detail.

**Why now.** The measured spike (`SYNTHESIS.md` correction banner, commit `353072f`) says a
`QQuickWindow` with `color: "transparent"` on the **OpenGL** RHI renders real glass. A minimal-
chrome shell is where that measurement pays off most visibly: with almost nothing on screen, the
glass *is* the interface.

## 4. Tokens

Existing tokens only, plus `crit_ink_light = #C22A33` (see candidate A §4/§5 — it fixes a live AA
failure), `FONT_VITAL_PX = 34`, `RADIUS_CONTAINER = 28`, `SPACE_XXL = 32`. One more, specific to
this candidate:

| Token | Value | Derived from |
|---|---|---|
| `SCRIM_ALPHA_GLASS` / `SCRIM_ALPHA_FLAT` | `0.42` / `0.72` | The FLAT scrim must be darker: with blur removed, alpha alone must carry the modal separation. |

## 5. Contrast

Ratios as in candidate A §5 (same tokens). Specific to this candidate:
- `on_crit` `#FFFFFF` on the `crit_ink_light` `#C22A33` ceremony header: **5.7:1** — passes AA.
  (On the *old* `crit` `#DE434B` it would be **4.19:1** — a fail. This candidate cannot ship
  without the new token.)
- Dark ceremony header: `on_crit` `#0A0D13` on `crit` `#FF5A61` = **6.4:1**.
- Ribbon filled cells carry ≥ 5.7:1 (light) / ≥ 6.4:1 (dark) for their inverted ink.

## 6. Weaknesses (attack these)

1. **The core bet may simply be false, and if it is, the candidate is worthless.** "The operator
   does one thing at a time" is *my assumption*, and I have not watched anyone run a TCT
   measurement. A plausible reality: during a slow HV ramp the operator watches leakage current
   *and* the scope trace *and* the ramp progress simultaneously, because a runaway shows up in the
   relationship between them. If that is the real workflow, peek stubs are an insult and this
   design actively obstructs safety monitoring. **Every other weakness below is survivable; this
   one is fatal.** It is an empirical question and I cannot settle it from the repo.
2. **The command palette is a wall.** Removing the tab strip means a new user has *no visible
   inventory of what the app can do*. `⌘K` is discoverable only to people who already know it
   exists. Candidate A's rail is strictly better for onboarding, and labs are full of people who
   use the software four times a year.
3. **The ribbon is too small to be the across-the-room surface, and I said so above.** It fails the
   "glance-readable across the room" constraint as a *readout* — it passes only as an *alarm*
   (a filled block is visible; its content is not). If Kaya reads that constraint strictly, this
   candidate is disqualified as written and needs a fourth resident element it currently refuses
   to have.
4. **Summoned chrome and gloves do not mix.** Space-to-summon assumes a keyboard within reach. A
   gloved operator at a probe station with a mouse only has to hunt for a capsule that is not
   there. I have no hover-corner fallback designed.
5. **The ceremony is heavy enough to be routed around.** Three checkboxes and a 2 s hold, every
   single time, for an operator who ramps HV thirty times a day, produces *checkbox blindness* —
   the exact opposite of the intent. There is a real argument that a ceremony this heavy makes the
   lab **less** safe by training people to click through it without reading. I believe the
   trade is right for HV; I am much less sure it is right for stage motion, and the design applies
   the same weight to both.
