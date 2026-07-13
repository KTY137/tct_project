# Codex Masterplan Review R1

Model note: this lane could not pin the requested "Codex 5.6 Sol"; review ran with the available Codex model. Scope: full read of `docs/ROADMAP_MASTERPLAN.md`, including the bounce ledger, avoiding already-integrated findings unless the current text still leaves an executor-grade failure mode.

## Findings

### BLOCKER-1 - Capability execution is still setters, not a staged plan
Evidence: the binding carries `setter/getter` only (`docs/ROADMAP_MASTERPLAN.md:82`), while the first pilot is a live wavegen sweep (`docs/ROADMAP_MASTERPLAN.md:183`). QCoDeS/ophyd-style control needs stage/apply/wait/verify/abort semantics and transport reservation, not just callable setpoints.
Failure case: the executor sends duty-cycle, starts scope acquisition before the serial/VISA write is applied, then records the new commanded value against a waveform taken at the old duty.
Amendment: before P1/D1 exit, add a `CapabilityBinding` lifecycle: `reserve -> prepare -> apply -> wait_settled -> verify_or_skip -> abort`, with per-transport lock/status and a simulated delayed-apply test.

### BLOCKER-2 - QWidget safety controls can exist but lose event authority under QML
Evidence: the plan preserves QWidget STOP/ALL-OFF/Abort instances (`docs/ROADMAP_MASTERPLAN.md:261`) and adds QML boot/viewmodel smokes (`docs/ROADMAP_MASTERPLAN.md:264`), but never gates mouse, keyboard, focus, z-order, or shortcut delivery across `QQuickWidget` chrome.
Failure case: a migrated panel passes because STOP exists, while QML focus owns Esc/Space or an overlay accepts mouse events above the re-parented QWidget; the safety control is visually present but unreachable during a fault.
Amendment: add a U-stage "safety event authority" gate: QML-focused key injection, mouse-hit tests at STOP/Abort coordinates, z-order assertions, and a rule that emergency shortcuts are owned by the top-level QWidget path.

### MAJOR-1 - `safety_class` is one-dimensional where hazards are not
Evidence: the sketch has one `SafetyClass` field (`docs/ROADMAP_MASTERPLAN.md:41`) and routes `safety_class >= MOTION` through DangerGate/envelope (`docs/ROADMAP_MASTERPLAN.md:71`). The Volundr addendum adds ordering later (`docs/ROADMAP_MASTERPLAN.md:333`) but not hazard facets.
Failure case: a capability is both motion-adjacent and emitting, or has a benign getter and hazardous setter. A total order can over-gate harmless reads or under-gate composite actions because "HV vs EMITTING vs MOTION" is not a single ladder.
Amendment: make safety policy per operation (`read`, `set`, `arm`, `start`, `stop`) with hazard facets or explicit route names (`danger_gate`, `motion_envelope`, `hv_lock`, `emission_interlock`), then test mixed-hazard capabilities before generated UI exists.

### MAJOR-2 - P0' can become a bad equivalence oracle for wavegen sweeps
Evidence: P0' is a day-sized direct patch writing wavegen settings into `run_metadata` (`docs/ROADMAP_MASTERPLAN.md:183`), then P1 is behavior-equality-gated against P0' (`docs/ROADMAP_MASTERPLAN.md:187`).
Failure case: P0' supports only a run-level wavegen setting while users expect a point-varying duty ramp; P1 can faithfully reproduce that shortcut and still pass equality.
Amendment: either define P0' as static-per-run only, or require a per-point command trace in P0' and make P1 equality compare command order, point index, and final HDF5 `swept/` rows.

### MAJOR-3 - Provenance lacks timing and atomic completion semantics
Evidence: `swept/{capability_id}` stores values/readback flags (`docs/ROADMAP_MASTERPLAN.md:75`), while run manifest/audit publication is post-seed (`docs/ROADMAP_MASTERPLAN.md:327`). There is no required monotonic timestamp for command issued, settled, acquisition start/end, or writer-commit.
Failure case: a downstream LabControl importer sees a complete-looking HDF5 after a crash, or cannot tell whether a value was settled before acquisition; both corrupt analysis without tripping current gates.
Amendment: seed DA1/DA2 should include a minimal per-point timing/status contract plus an atomic completion marker written only after HDF5 close.

### MAJOR-4 - Dual-shell persistence is not part of the QML gate
Evidence: classic and QML shells coexist behind `TCT_SHELL=classic|qml` (`docs/ROADMAP_MASTERPLAN.md:300`), while portability relies on QSettings abstracting storage (`docs/ROADMAP_MASTERPLAN.md:274`).
Failure case: QML writes geometry, tab, dock, theme, or panel-state keys that classic later reads with different assumptions, causing a boot failure that clean-QSettings smokes never cover.
Amendment: namespace shell-specific settings, freeze shared keys in `app_settings`, and add a dirty-settings round trip: classic writes -> qml boots -> qml writes -> classic boots.

### MAJOR-5 - Linux/offscreen/QML portability is undersold
Evidence: the plan says offscreen tests are Linux-native and OpenGL RHI is the Linux default (`docs/ROADMAP_MASTERPLAN.md:274`), with PORT1 rated S/M (`docs/ROADMAP_MASTERPLAN.md:280`).
Failure case: PySide6 widgets pass in an Ubuntu container, but Qt Quick scene graph creation fails without Xvfb/EGL/Mesa, or silently falls back to software rendering and invalidates the RHI/GL probe.
Amendment: PORT1 needs an explicit graphics stack recipe, `QSG_INFO=1` log parser, pixel-smoke capture for QML and pyqtgraph/GL, and a separate AlmaLinux sim-only verdict. Treat it as at least M/L until proven.

### MINOR-1 - Several effort labels are optimistic enough to distort staging
Evidence: D1 includes a new package, adapters, registry, taxonomy review, and CAPABILITY_MODEL gate as M (`docs/ROADMAP_MASTERPLAN.md:157`); D4 replaces fixed composition with config-driven composition as M (`docs/ROADMAP_MASTERPLAN.md:173`).
Failure case: executors spend the M budget on model code, then discover late that lifecycle, persistence, tests, and migration docs are the hard part.
Amendment: split D1 into contract/model and adapter/registry beats, and mark D4 config-driven composition L unless a prior spike proves the existing panel lifecycle can be expressed without special cases.

### MINOR-2 - The e4control license issue is not actually resolved for a seed
Evidence: the plan says there is no formal license text but treats informal open-source intent as resolved (`docs/ROADMAP_MASTERPLAN.md:161`), then puts an e4control adapter pattern into the seed (`docs/ROADMAP_MASTERPLAN.md:310`).
Failure case: the seed publishes command mappings or structure derived from an unlicensed repo, and a third party cannot safely reuse the platform package.
Amendment: make the seed clean-room from vendor manuals unless an upstream license or written grant exists before the tag; otherwise move the adapter pattern to a private TCT-only appendix.

## Holds

The trunk/gate repair holds: Phase 0.5, bucket manifests, routine corpus, durable Mary/Kaya evidence, and bench serial-resource accounting are concrete enough to execute. The metrology stream also holds because it admits zero measured precision in-repo and keeps closed-loop positioning behind measured go/no-go.
