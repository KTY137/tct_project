# Candidate C — BOARD

> **Philosophy.** The app does not know what the operator is doing — so it stops guessing. It
> ships **situations**, not tabs, and lets the operator compose the cockpit. There is exactly one
> card they cannot evict.

**Optimizes for:** matching real lab workflow diversity, and reading the Vision Pro dashboard
plate literally — one container slab, cards floating on it, a header pill per group.
**Deliberately sacrifices:** uniformity. No two operators' cockpits look alike, which means
screenshots in a lab notebook become ambiguous, "click the thing in the top right" stops being
sayable, and layout becomes persisted state that can be corrupted, lost, or migrated wrong.

Open `candidate-board.html`. Click **✎ Arrange** in the rail — then try to remove the Safety card.

---

## 1. The problem this solves

Candidates A and B both answer "what should the operator look at?" with an opinion. A says *these
five vitals, always*. B says *the one thing you're doing*. Both opinions are mine, and §6 of both
documents admits I invented them without watching a TCT session.

Candidate C takes that ignorance seriously and turns it into the design. **There are twelve
panels because there are genuinely many jobs**: aligning a sensor under a camera has almost
nothing in common with running an overnight scan or ramping HV on a fresh device. A single fixed
layout serves one of those well and the others badly.

## 2. The design

### 2.1 Situations replace tabs

Four named boards: **Align · HV ramp · Scanning · Analysis**. Each is a saved arrangement of cards.
That is the IA: not "which of 12 panels do I want" but "**what am I doing right now**". Twelve
nouns become four verbs.

A scan starting does **not** silently switch the board (that would be the app moving the
operator's furniture mid-run). It offers.

### 2.2 The board — the Vision Pro plate, literally

One 12-column grid on a **container** slab. Cards float on it. Each panel exists at three
densities — **S** (a metric tile: caption + hero number), **M** (compact), **L** (full) — so the
same Bias panel is a 34 px `−400.0 V` tile on the Scanning board and a full control surface on the
HV-ramp board. One panel, three sizes; not three implementations.

### 2.3 The depth ladder — exactly three, forever

`container` (α .30 dark / .55 light, blurred) → `card` (α .62 / .86, softly blurred 10 px) →
`well` (α .55 / .06). **Text never sits directly on a blurred backdrop** — it sits on a card,
which sits on the container. That is the discipline the glassmorphism plate in `design_assets/`
*fails* (its white-on-white text is beautiful and unreadable), and it is exactly why I take the
plate's **edge highlight and radii** and reject its **contrast**.

At FLAT the three collapse to `canvas` / `panel` / `well` — three opaque tones that preserve the
same reading order. The ladder is real information; the blur is not.

### 2.4 The run header grows in place

When a scan runs, a header **grows at the top of the board** — progress, ETA, current point,
ABORT. It does not take over the screen, because during a scan the operator may still need bias,
the stage, or the scope. **The layout the operator built is the layout they get, running or not.**
This is the sharpest disagreement with candidate B, which makes the run *become* the screen.

### 2.5 The Safety card — pinned, opaque, non-evictable

The dangerous controls are a card on the board. It can be **moved**. It can never be **removed**:
in Arrange mode every other card grows a remove grip; Safety's is a disabled lock that says why.
It is painted `panel` — **opaque at every tier** — with a `crit` severity stripe.

Arm → Execute → 10 s auto-disarm, one at a time, plus `ABORT EVERYTHING`. The envelope of the next
action is printed at the bottom of the card in mono, always.

The rule, stated plainly: **a composable cockpit that can hide the abort button is not a
cockpit.** Composability stops exactly at the safety surface.

## 3. Justification

**Problem solved.** It is the only candidate that survives being *wrong about the workflow*,
because it does not have a theory of the workflow. If leakage current turns out to matter more
than I think, the operator puts it on the board. Neither A nor B can absorb that without a
redesign.

**Alternatives considered inside this candidate.**
- *Free-form drag/resize (a real dashboard).* Rejected: unbounded layouts produce unreadable
  cockpits and infinite support surface. A 12-column grid with three fixed card sizes bounds the
  damage.
- *Let the user delete the Safety card and warn them.* Rejected outright. A warning is not a
  guardrail.
- *Auto-switch board on scan start.* Rejected: the app must not rearrange the screen under a
  running experiment. It offers; the operator decides.
- *Per-user layouts.* Deferred, and I flag it as a trap — see §6.3.

**Safety implications.**
- Same tier-invariance law as A and B: the Safety card paints `panel`, never a material.
- The severity stripe (4 px, left edge) + chip + word give three redundant state channels on every
  card, all of which survive FLAT and greyscale.
- **The risk this candidate creates:** the safety card can be *moved*, therefore it can be moved
  somewhere stupid — bottom-right of a 3-monitor board, or onto a situation the operator rarely
  opens. It cannot be deleted, but "present" is not the same as "where you expect it". Candidate
  A's fixed armed rail is strictly safer on this axis and I will not pretend otherwise. A serious
  build needs a constraint like *"Safety must occupy a cell in the first screenful"*, which I have
  specified nowhere.

**Operational implications.** Layout is now persisted state (`QSettings`). It needs a schema
version, a migration path, and a **Reset to shipped situation** button that always works — because
the day a corrupted layout blob wedges the cockpit is the day the lab loses a shift.

**Why now.** The container→card→well ladder is precisely the material-*role* contract
`SYNTHESIS.md` §2 already demands (a panel declares a role; it never paints a material). This
candidate is the one that would *use* that contract rather than merely respect it.

## 4. Tokens

Existing tokens, plus `crit_ink_light = #C22A33`, `FONT_VITAL_PX = 34`, `RADIUS_CONTAINER = 28`,
`SPACE_XXL = 32` (as candidate A §4). Specific to this candidate:

| Token | Value | Derived from |
|---|---|---|
| `GLASS_CONTAINER_ALPHA` | `0.30` dark / `0.55` light | The slab under the cards. Lower than `_GLASS_CARD_ALPHA` (0.42) — it must read as *further away*. |
| `GLASS_CARD_ALPHA` | `0.62` dark / `0.86` light | Raised from 0.42/0.72 because a card now sits on the **container**, not on the canvas: to hold the same contrast against a live backdrop it must be more opaque. **This is the load-bearing number of the candidate.** |
| `BLUR_CARD_PX` | `10` | vs `28` on the container — a shallower blur reads as "closer", and keeps text off a heavily-blurred field. |

## 5. Contrast

Base ratios as candidate A §5. The number that matters here is the **card over the container over
a hostile backdrop**. With `GLASS_CARD_ALPHA = 0.62` over `GLASS_CONTAINER_ALPHA = 0.30`, the
effective backdrop transmission at a card's text is `0.38 × 0.70 ≈ 0.27` — i.e. a worst-case
white/black stripe field contributes ≈ 27 % of the pixel under the text. That is why ink holds
≥ 7:1 against the composite in the mockup. **Drop `GLASS_CARD_ALPHA` toward the prettier 0.42 and
this collapses** — the visual temptation and the accessibility floor point in opposite directions,
and this candidate resolves it in favour of the floor. Open the HTML, set **Backdrop → Worst
case**, and judge whether the price in beauty was worth it. That is a real decision and it is
Kaya's.

## 6. Weaknesses (attack these)

1. **It is the most expensive candidate by a wide margin, and the cost is not in the pixels.** It
   needs: a layout engine, three densities × twelve panels (36 render paths, vs 12 today), a
   persisted-layout schema with versioning and migration, a tray, an Arrange mode, four shipped
   situations, and a reset path that cannot fail. A and B are re-arrangements of what exists;
   C is a **new subsystem**. If the migration budget is one wave, this candidate does not fit and
   should be rejected on that ground alone.
2. **"Three densities per panel" is a promise I have not costed.** The mockup shows S and L for
   Bias and hand-waves M. Some panels have no sensible small form — what is the *tile* version of
   the Scan Planner? A grid editor does not have a hero number. I suspect **3–4 of the 12 panels
   simply have no S form**, which means the tray must gray them out at some sizes, which means the
   clean "one panel, three densities" story is a lie and the real story is a lookup table of what
   exists. I did not build that table. That is a hole in the candidate, not a detail.
3. **User-composed layouts destroy supportability.** "Where's the abort button?" now has *n*
   answers. A screenshot pasted into the lab logbook no longer proves what the operator saw.
   Training material goes stale the first time someone drags a card. Per-user layouts (§3) make
   this strictly worse and I deferred rather than solved it.
4. **The safety card can be moved somewhere stupid.** Non-evictable ≠ prominent. I have no
   constraint enforcing that it stays in the first screenful, and without one, this candidate is
   *less* safe than candidate A while claiming to be equally safe. This is the sharpest attack
   surface and I am pointing directly at it.
5. **It may simply be the wrong answer to Kaya's actual question.** He asked to iterate the design
   and layout toward visionOS-grade *accessibility and look*. Candidate C's answer is "you decide
   the layout" — which is arguably an **abdication** dressed as flexibility. A design forge that
   hands the composition problem back to the user has not solved the composition problem. If Kaya
   wanted a designed cockpit, this is a shrug with beautiful glass on it.
