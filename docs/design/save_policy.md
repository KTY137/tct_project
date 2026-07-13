# Modular Save Policy — design note (theme T4.5)

- **Date:** 2026-07-08
- **Author:** Prometheus (researcher / first-officer), design-first stress test
- **Status:** DESIGN — for Adam/Kaya ratification, then Jonathan builds. No app code touched.
- **Question:** Let a TCT scan store only derived DUT scalars (charge/amplitude/timing)
  instead of full waveforms — cutting big-raster file size ~10x — but make it
  **modular (pluggable)** and **honest (never silently drop data)**.
- **Confidence:** design grounded in repo file:line evidence (secondary source =
  the repo itself; no external manual involved).

This is a **format-contract change** to `SCAN_DATA_FORMAT.md`, hence design-before-build.

---

## 0. Grounding — how saving works today (cited)

- **`SaveOptions`** is a frozen dataclass of *per-group booleans*
  (`waveforms, positions, timestamp, analysis, bias, slow_control, camera_frame,
  run_metadata`); `waveforms`/`positions` are forced `True` in `from_config`
  (`data/save_options.py:16-37`). **There is no policy hook today** — the strategy
  must be added, but it builds cleanly on top of `SaveOptions`.
- **The writer** gates each group on a `save_options.*` bool
  (`data/hdf5_writer.py:70-108`). Waveforms are written by `_save_waveforms`
  (`data/hdf5_writer.py:128-141`), which appends `waveforms/ref_ch1` and
  `waveforms/dut_ch2` as extensible `(N,S)` f4 arrays and writes `waveforms/time_s`
  once from the first point.
- **Existing honesty gap (important):** `_save_waveforms` **silently `return`s**
  (skips the append) when a point's ref/dut length ≠ the first point's length
  (`data/hdf5_writer.py:138-139`), and when the first point has an empty time axis
  (`:135-136`). That produces `waveforms/ref_ch1` shorter than `points/x_mm` with
  **no record of why** — an *error* drop that is currently indistinguishable from
  "not stored". The policy work should close this at the same time (see §2).
- **`ScanResult`** already carries both the derived scalars and the raw arrays
  (`controller/scan_controller.py:128-153`): `ref_amplitude_V, ref_charge_pC,
  dut_amplitude_V, dut_charge_pC, dut_charge_norm, baseline_rms_V`, the four
  `*_time_s`, plus `ref_waveform, dut_waveform, time_axis`. The scalars are computed
  **live at acquire time** in `_acquire_core` (`:1317-1333`), *not* re-derived from
  the stored arrays.
- **Laser normalization does NOT depend on stored waveforms.** `normalise()` takes two
  scalars `dut_charge_pC / ref_charge_pC` (`analysis/laser_normalization.py:5-16`), and
  `ref_charge_pC` comes from the intensity monitor read live (`scan_controller.py:1307-1318`),
  stored as the `dut_charge_norm` / `ref_charge_pC` scalars in `/analysis`
  (`hdf5_writer.py:75-83`). **So `derived_only` does not break normalization** — the
  normalized value is already a stored scalar. (Full ref-*waveform* reprocessing offline
  is the only thing lost; see §5.)
- **The live map and the offline map are already scalar-only.** `ScanMapView` extracts
  `QUANTITIES = [dut_charge_pC, dut_charge_norm, dut_amplitude_V, ref_amplitude_V,
  baseline_rms_V, drift_time_s, rise_time_s, cfd_time_s]` from the `ScanResult`
  (`gui/scan_map_view.py:52-61`), and `AnalysisPanel._load_h5` reads **only** the
  `points` and `analysis` groups — **it never opens `waveforms/`**
  (`gui/analysis_panel.py:256-266`). **There is no waveform viewer in AnalysisPanel today.**
  ⇒ `derived_only` runs feed the live map and the offline map/CCE with zero code change;
  nothing downstream currently reads the arrays that `derived_only` drops.

**Consequence:** `derived_only` is *low-risk* precisely because everything on-screen
already consumes the scalars. The real work is honesty metadata + config wiring +
future-proofing the layout, not rescuing broken consumers.

---

## 1. The `SavePolicy` abstraction (strategy pattern)

Add to `data/save_options.py` (co-located with `SaveOptions`; the writer already
imports from there, `hdf5_writer.py:12`).

```python
@dataclass(frozen=True)
class WaveformDecision:
    store_dut: bool
    store_ref: bool

class SavePolicy(ABC):
    name: str                       # persisted verbatim as the run's policy attr
    def decide(self, result) -> WaveformDecision: ...   # per ScanResult
    def params(self) -> dict: ...   # JSON-able knobs, persisted for provenance
    @property
    def per_point(self) -> bool: ...  # False = uniform for whole run (full/derived/dut)
```

- The policy decides **only which waveforms to persist**. Scalars (`/analysis`,
  `/points`, `/bias`, …) are **never** touched by the policy — that is the entire
  point of the feature and keeps every existing consumer whole.
- `decide()` is called **per `ScanResult`** so `on_condition` (per-point) fits the
  same interface, but v1 policies are **uniform** (`per_point == False`), which lets
  the writer keep today's simple rectangular `(N,S)` arrays (no raggedness — see §5).

Concrete policies (v1 = first three; `on_condition` = stretch, §5/§6):

| `name`          | `decide()` returns          | Effect on disk |
|-----------------|-----------------------------|----------------|
| `full`          | `(store_dut=True, store_ref=True)` | Today's layout, byte-for-byte. **Default.** |
| `derived_only`  | `(False, False)`            | No `waveforms/ref_ch1`,`dut_ch2`,`time_s`. Scalars only. ~10x smaller. |
| `dut_only`      | `(True, False)`             | `waveforms/dut_ch2`+`time_s`; **no** `ref_ch1`. ~2x smaller. |
| `on_condition`  | `(f(result), f(result))` per point | **Stretch** — ragged; see §5. |

Writer integration (minimal, `save_point` / `_save_waveforms`,
`hdf5_writer.py:70-71,128-141`): the mandatory `save_options.waveforms` master
flag stays as a hard kill; when engaged, the writer asks the policy per point and
tracks three counters (§2):

```python
if self.save_options.waveforms:
    d = self.policy.decide(result)
    self._save_waveforms(f, idx, result, store_dut=d.store_dut, store_ref=d.store_ref)
```

`_save_waveforms` gains `store_dut`/`store_ref` params: it creates/appends `dut_ch2`
only if `store_dut`, `ref_ch1` only if `store_ref`, and writes `time_s` once if
*either* channel is stored. `SaveOptions` holds a `policy: SavePolicy` field
(default `FullPolicy()`), so `HDF5Writer(save_options=…)` needs no new constructor arg
and every existing test/instantiation keeps working.

---

## 2. HONESTY contract (Jonathan's non-negotiables) — exact attrs

**Principle:** "waveforms intentionally omitted by policy X" is a *first-class,
queryable, counted* state, and it must be distinguishable from "missing due to error".
Mirror the discipline already in `analysis/scan_grid.py`, where `n_missing`
(never sampled) and `n_nan_values` (sampled-but-invalid) are counted separately.

### 2a. Authoritative record — **root HDF5 attributes** (always written, one place)

Written in `HDF5Writer.close()` (so counts are final), alongside `stop_time`
(`hdf5_writer.py:53`):

| Root attr | Type | Meaning |
|-----------|------|---------|
| `save_policy` | str | Policy `name` in effect, e.g. `"derived_only"`. **Always present** (a `full` run writes `"full"`). |
| `save_policy_params` | str (JSON) | `policy.params()`, `"{}"` when none. Provenance for `on_condition` thresholds etc. |
| `waveforms_dut_stored` | bool | Whether **any** `dut_ch2` rows exist for this run. |
| `waveforms_ref_stored` | bool | Whether **any** `ref_ch1` rows exist for this run. |
| `n_points` | int | Points written (`self._n_points`) — lets a reader check array alignment. |
| `n_waveforms_omitted_by_policy` | int | Count of points whose waveform was **intentionally** not stored. |
| `n_waveforms_omitted_by_error` | int | Count of points whose waveform *should* have been stored but was **dropped** (length mismatch / empty axis — closes the `:138-139` silent-skip gap). |

Reader rule (unambiguous):
- `n_waveforms_omitted_by_policy > 0` ⇒ "not stored **on purpose**, per `save_policy`".
- `n_waveforms_omitted_by_error > 0` ⇒ **data loss / warn loudly** — a stored-intent
  waveform was dropped. (Today this is silent; the counter makes it visible.)
- Old files (pre-feature) have **none** of these attrs ⇒ reader defaults to
  `save_policy="full"`, both `*_stored=True`, both omit counts `0` (§4).

### 2b. Convenience marker — `/waveforms` group attrs (for `dut_only`/`derived_only`)

So a tool that opens `/waveforms` directly (not just root) also sees the truth,
**always create the `/waveforms` group** (even in `derived_only`, as a bare marker
carrying attrs) and mirror onto it: `policy`, `omitted_reason`
(`""` when fully stored, else e.g. `"intentional: policy=derived_only"`),
`n_omitted_by_policy`, `n_omitted_by_error`. This keeps "why is `ref_ch1` absent?"
answerable from inside the group a human is already inspecting in HDFView.

### 2c. Per-point mask — **only for `on_condition`** (stretch)

A per-point policy stores a *subset* of points, so the arrays no longer align with
point index. When `policy.per_point` is `True`, add:
- `waveforms/stored_index` — int `(M,)` mapping each stored waveform row → its point
  index (M ≤ N). This is the honest, compact answer to raggedness (do **not**
  NaN-pad to `(N,S)` — that throws away the size win). Uniform v1 policies keep the
  aligned `(N,S)` arrays and **do not** write this dataset.

---

## 3. `SCAN_DATA_FORMAT.md` impact + graceful downstream degradation

### On-disk layout per policy

| Group / dataset | `full` | `dut_only` | `derived_only` |
|---|---|---|---|
| `/points/*` | ✔ | ✔ | ✔ |
| `/analysis/*` (scalars) | ✔ | ✔ | ✔ |
| `/bias`, `/slow_control`, `/camera` | per existing toggles | per existing toggles | per existing toggles |
| `/waveforms/time_s` | ✔ | ✔ | ✖ (group present, dataset absent) |
| `/waveforms/dut_ch2` `(N,S)` | ✔ | ✔ | ✖ |
| `/waveforms/ref_ch1` `(N,S)` | ✔ | ✖ | ✖ |
| root honesty attrs (§2a) | ✔ | ✔ | ✔ |

`SCAN_DATA_FORMAT.md` edits: add a **"Save policy"** section documenting the three
policies + the §2a attrs; annotate the `/waveforms` table rows as
"present per `save_policy`"; update the "Choosing what to save" table to note the
policy key.

### Downstream must degrade gracefully (not crash)

- **`AnalysisPanel._load_h5` / `_replot_map`** (`analysis_panel.py:256-266,272-314`):
  already reads only `points`+`analysis` ⇒ **works unchanged** on `derived_only`.
  No action strictly required, but recommended: when a future waveform view exists,
  it must read `save_policy` and show **"derived-only run — waveform view
  unavailable (waveforms omitted by policy)"** rather than treating an empty
  `waveforms/` as an error. If `n_waveforms_omitted_by_error > 0`, surface a
  **red** "N waveforms lost to error" chip (distinct message).
- **Live `ScanMapView`** (`scan_map_view.py`): consumes the in-memory `ScanResult`
  scalars, never the file ⇒ **completely unaffected** by policy (the arrays it
  ignores are exactly the ones a policy drops).
- **Any waveform-dependent offline analysis** (none in-repo today; future
  reprocessing): must branch on `waveforms_dut_stored` / `waveforms_ref_stored`
  and fail with a clear "run stored under policy `derived_only` — no waveforms to
  reprocess" message, never an unguarded `f["waveforms/dut_ch2"]` KeyError.

---

## 4. Backward compatibility

- **Default stays `full`.** `SaveOptions.policy` defaults to `FullPolicy()`;
  a `devices.yaml` with no policy key ⇒ `full` ⇒ today's bytes, today's layout.
- **Existing full files still load.** They have `/waveforms` with datasets and none
  of the §2a attrs; readers apply the "absent attr ⇒ full" default (§2a last row).
  No migration, no re-write.
- **Config wiring:** add under `output.save` in `devices.yaml` (`configs/devices.yaml:126-136`):
  ```yaml
  output:
    save:
      # ...existing booleans...
      policy: full            # full | derived_only | dut_only
      policy_params: {}       # reserved (on_condition threshold, etc.)
  ```
  `SaveOptions.from_config` (`save_options.py:26-37`) parses `policy` via a
  name→class registry and builds the `SavePolicy`; unknown name ⇒ **raise/ERROR**,
  do **not** silently fall back (a silent fallback to `full` would surprise a user
  who asked for smaller files, and silent-anything violates the honesty rule).
- **Validation:** `config_validator.py` currently leaves the nested `save` dict to
  `SaveOptions.from_config` and does not typo-check its subkeys
  (`config_validator.py:110-114`). Add `policy`/`policy_params` to the accepted
  `output.save` keys and validate `policy ∈ {full, derived_only, dut_only}` with an
  ERROR (not WARN) on an unknown value, so a typo fails loudly at load, not at
  scan-save time.
- **GUI:** the Settings → Data/Saving panel gains a policy dropdown; a non-`full`
  choice shows the same **red "loses information that cannot be reconstructed
  offline"** warning already used for `bias`/`slow_control`
  (`SCAN_DATA_FORMAT.md:34-35`), worded "waveforms will not be saved — this cannot
  be undone offline."

---

## 5. Risks & edge cases

1. **Does `derived_only` break laser normalization?** — **No.** Normalization is a
   scalar op on `dut_charge_pC`/`ref_charge_pC` computed live and stored in
   `/analysis` (`laser_normalization.py:5-16`, `scan_controller.py:1317-1323`,
   `hdf5_writer.py:75-83`). Only *offline re-derivation from the ref waveform* is
   lost, and no in-repo code does that. **Document** in `SCAN_DATA_FORMAT.md`:
   "`derived_only`/`dut_only` keep the *normalized scalar* but drop the raw ref
   trace — you cannot recompute normalization with a different integration window
   offline." `dut_only` has the identical caveat and is the honest middle ground
   (keep DUT physics traces, drop the bulky ref).
2. **Per-run vs per-point policy.** v1 = **per-run, uniform** (`per_point=False`):
   one policy for the whole run, rectangular arrays, no mask. `on_condition` is the
   only per-point case and is deferred (needs `stored_index`, §2c). **Recommend v1
   per-run only.**
3. **Mid-scan policy change — forbid.** The policy is resolved once at
   `_begin_run` (`scan_controller.py:255-267`) and frozen for the run; the file's
   root attrs describe the *whole* run. Changing policy mid-run would make the root
   counts/attrs lie. `SaveOptions` is already `frozen=True` — keep the policy
   immutable per writer instance. (A GUI change takes effect on the **next** run.)
4. **Live map unaffected** — restated: it never reads the file (§3). No work.
5. **The existing silent length-mismatch skip** (`hdf5_writer.py:138-139`) becomes a
   *counted* `n_waveforms_omitted_by_error`, turning a latent honesty bug into a
   visible one. This is a real (small) behavior change to fold in.
6. **Empty-axis first point** (`hdf5_writer.py:135-136`): same treatment — count as
   error omission, not policy omission.
7. **`on_condition` array raggedness** (deferred): needs `stored_index` + a reader
   that gathers by index. Explicitly **out of v1** so we don't ship a ragged format
   half-built.

---

## 6. Recommended build order for Jonathan (smallest safe increments)

1. **`SavePolicy` + `WaveformDecision` + `FullPolicy` only**, wired so `full` is the
   default and **produces byte-identical output** to today. Existing tests
   (`tests/test_data_writer.py`, `tests/test_analysis_panel_load_run.py`) must pass
   unchanged. This is a pure refactor — no format change yet.
2. **Honesty counters + root/group attrs (§2a/2b)** written on every run, including
   `full`. Add a test asserting a `full` run reports `n_omitted_by_policy=0`,
   `*_stored=True`. Fold in the error-count for the length-mismatch skip.
3. **`DerivedOnlyPolicy`** + config `policy` key + validator enum check. Test:
   `derived_only` run has no `waveforms/*` datasets, correct root attrs, and
   `AnalysisPanel.load_run` still maps it (it will — scalar-only).
4. **`DutOnlyPolicy`.** Test: `dut_ch2`+`time_s` present, `ref_ch1` absent, attrs
   correct.
5. **`SCAN_DATA_FORMAT.md`** update (Kiroku/Samantha) + Settings dropdown + red
   warning (Noah).
6. *(Later / separate theme)* `on_condition` + `stored_index` ragged support + a
   waveform-view reader that honors the mask.

### Explicitly OUT of scope for v1
- `on_condition` and any **per-point** policy / ragged `stored_index`.
- **Waveform decimation / downsampling** ("or a decimated form" in the T4.5 blurb) —
  that is lossy-compression, a separate design; v1 is store-or-not, whole-trace only.
- Retro-active **re-writing / migrating** old runs to a new policy.
- Applying policy to `voltage_scan` / `z_focus` outputs (they store no per-point
  waveforms anyway — `hdf5_writer.py:113-126`); policy is XY-scan waveforms only.
- Compression-level tuning of the surviving datasets (already gzip; unchanged).

---

## Top 3 decisions Adam/Kaya must ratify before build

1. **Per-run uniform policy for v1, `on_condition` deferred.** Accepting this keeps
   arrays rectangular and the format simple; rejecting it (wanting `on_condition`
   now) pulls the ragged `stored_index` design into v1 and roughly doubles the work.
2. **Honesty attrs live at the HDF5 root (§2a) as the authoritative record**, with a
   duplicate marker on the `/waveforms` group (§2b), and the existing silent
   length-mismatch skip is reclassified as a **counted `omitted_by_error`**. Ratify
   the exact attr names now — they are the new format contract other tools will key on.
3. **Unknown `policy` value = hard ERROR at config load, never a silent fallback to
   `full`.** This is the honesty rule applied to config; confirm we prefer a loud
   refusal over "did something reasonable."
