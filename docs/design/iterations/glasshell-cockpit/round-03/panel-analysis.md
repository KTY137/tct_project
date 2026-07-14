# PANEL — ANALYSIS (a program in a panel costume, 2203 lines)

> **What it proves:** the language survives complexity. A panel that is really an application — file
> loader, three analysis modes, two embedded plots, a 1D slicer, a survey mosaic — does not need 13
> dialects. It needs the *same* five surfaces, nested. Depth by containment, not by invention.

Open [`panel-analysis.html`](panel-analysis.html). It is the busiest surface in the app; count the
component types and confirm there are still only five.

---

## 1. The panel today (ground truth, `gui/analysis_panel.py`, `dark/10_analysis.png`)

`panel_header` → a compact **run-header `Card`** (Browse + file label + four status chips) → a
`QStackedWidget`: index 0 the **recent-runs empty state** (`Card("Recent runs")` + a `QListWidget`),
index 1 the **loaded page** — a `SegmentedControl` (2D map / CCE vs bias / Survey) over a mode stack.
Two of the three modes host a pyqtgraph plot (`ScanMapView`, CCE); the survey mode builds a mosaic. The
build code is careful about weak slots and hot-path fade-swaps — that machinery is correct and untouched.

## 2. The design — depth by containment

The whole insight: **a complex panel is not more component types; it is more nesting of the same
types.** The kit's concentric-radius law (`r_outer = r_inner + gap`) is what makes deep nesting read as
depth instead of noise. Analysis nests three levels and it still resolves, because each level steps the
radius down by one gap.

```
shelf  (r24)  ── the panel
 ├─ run-header card (r20)     Browse well · file label · 4 chips
 └─ workspace card (r20)
     ├─ SegmentedControl      2D map · CCE vs bias · Survey
     └─ mode body
         ├─ MAP:    toolbar (wells + segmented)  +  ISLAND (r12, the map)  +  1D-slice ISLAND
         ├─ CCE:    quantity wells  +  ISLAND (the CCE plot)
         └─ SURVEY: a grid of mini-cards, each a small ISLAND thumbnail
```

### 2.1 The run header is a card, its Browse is a well, its state is four chips
The header stays one glass card. Browse is a `raised` button; the file path is `muted` text (chrome, so
it may live on glass); the four status chips (File / Dataset / Map / Export) are `chip` primitives —
glyph + word + colour, each. Nothing here is a value, so nothing here needs a well.

### 2.2 The empty state is a designed room, not a blank card
The recent-runs list is a `Card("Recent runs")` whose rows are `well`-toned, each row `text`-inked with
a `muted` timestamp. This is the panel an operator sees most (analysis usually starts cold), so it gets
the `EmptyState` treatment: a large quiet headline, the list, and one accent Browse button.

### 2.3 The two embedded plots are islands, full stop
`ScanMapView` and the CCE plot are **islands** — opaque `PLOT_BG`, every tier, `hairline_strong`
outline, `edge_shade` inner top, 12 px gutter. The map's colorbar is part of the island (it is data).
The 1D slice plot is a second, smaller island beside the map. The fade-swap between modes stays a pixmap
cross-fade (never a `QGraphicsEffect` on a plot) — the kit does not change that; it only frames the
result.

### 2.4 The survey mosaic — the stress test
The survey mode is a grid of thumbnails, each a run's map. Each thumbnail is a **mini-card whose body is
a mini-island**: a `card` (r20) containing a small `island` (r12) plus a `text`-inked caption and a
`chip` for pass/fail. This is where "one panel, five surfaces" is really tested — a wall of nested
card-over-island cells — and it holds because every cell is the same two primitives.

### 2.5 The map toolbar
Quantity selector (a `well`-backed dropdown), Replot / Export (`raised` buttons), Freeze-levels
(a checkbox chip). All chrome, all on the workspace card, off the island.

## 3. Justification

**Problem solved.** The analysis panel is where a naive "make it glass" goes to die: with 800+ widgets
and two live plots, adding a bespoke look per sub-section would produce exactly the "13 dialects"
Kaya fears. Depth-by-containment means the entire 2203-line panel is expressible as five surfaces
nested three deep. A new analysis mode added next year is *another mode body* in the same grammar, not a
new visual language.

**Alternatives considered within this candidate.**
- *Give the workspace its own darker "sub-canvas" so the plots sit on a distinct ground.* Rejected: a
  second ground breaks the band law and the single-ground bake. The island's own `edge_shade` recess
  gives the "sunk into the surface" read for free.
- *Float the map toolbar over the top of the map (visionOS-style).* Rejected: same island law as the
  scope — a toolbar over the map is a pane over data.
- *Make the survey thumbnails glass cards with translucent plot previews.* Rejected hard: translucent
  plot previews are the 1.80 : 1 failure multiplied by forty cells. Thumbnails are opaque mini-islands.

**Safety implications.** No hazard on this panel (offline analysis of saved runs — it never imports
`controller/`). The relevant law is the hot-path one: two live plots, both islands, both opaque, both
tier-invariant. During a live scan an operator may glance at analysis of a prior run; the glass here
never contends with the running acquisition because the ground frost is static.

**Operational implications.** No new persisted state. The `QStackedWidget` / mode-stack / weak-slot
machinery is unchanged; only the surfaces are kit primitives. The concentric-radius law is already
satisfied by the shipped scale (`RADIUS_MD + SPACE_SM = RADIUS_XL`), so nesting needs no new radius
below the shelf.

**Why now.** If the language survives 2203 lines and two plots and a forty-cell mosaic, it survives the
other twelve panels. This is the proof that the kit is a *system*, not a coat of paint on the easy panels.

## 4. Weaknesses (attack these)

1. **Three levels of nesting is exactly two more than most operators can hold.** Card-in-card-in-shelf
   is defensible geometrically (the radius law makes it *read*), but "where am I" gets harder the deeper
   the nesting goes, and the survey mode is card-in-card-in-card-in-shelf (four deep). I claim the radius
   ladder rescues it; I have not tested that claim on anyone who is not me.
2. **The survey mosaic could be forty live islands, and forty opaque `PLOT_BG` rectangles on one glass
   shelf is a lot of dark.** The panel's overall value goes *down* as the mosaic fills — it becomes a
   wall of black thumbnails with thin glass gutters. The glass identity of the panel is strongest when
   it is emptiest, which is backwards from where an operator spends time.
3. **The run-header's four chips can all be `neutral` at once (cold start), and four grey chips in a row
   carry almost no information** — they are placeholders wearing the state-indicator costume. I have not
   decided whether an unloaded panel should show four inert chips or none; showing them is honest about
   what *will* be tracked but adds visual noise to the emptiest, most-seen state.
4. **Depth-by-containment assumes the shipped radius scale never changes.** The whole "nesting reads as
   depth" argument rests on `RADIUS_MD + SPACE_SM = RADIUS_XL` holding exactly. The theme editor exposes
   a radius density preset (s/m/l); at the "large" preset that arithmetic may break and the nesting
   would flatten into concentric rectangles that no longer read as contained. I have not checked the
   preset extremes.
</content>
