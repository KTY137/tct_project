# Can instrument capabilities be auto-discovered generically over SCPI / VISA?

- **Date:** 2026-07-13
- **Researcher:** Prometheus (`researcher`)
- **Requested by:** Kaya, as a decision input for `docs/CAPABILITY_MODEL.md`
  (v0.2 → v0.3; the LabControl platform seed inherits it).
- **Exact question:** Can instrument capabilities be auto-discovered generically
  over SCPI / VISA — and if not, what *can* be discovered, at what cost, and what
  is the safety rule?
- **Scope:** SCPI/IEEE-488.2 command layer, VISA/LXI/IVI transport-and-typing
  layer, prior-art frameworks (QCoDeS, PyMeasure, ophyd, yaq, labscript), and our
  own drivers.
- **Confidence:** **mixed, stated per claim.** Standards text (IEEE 488.2, SCPI-99,
  LXI schema) = *official docs/standard*. Per-vendor implementation facts =
  *official manual* where I read the vendor manual, *secondary source* where only a
  catalog/wiki/forum confirmed it. Each section is tagged.

---

## TL;DR verdict

**No — there is no generic, reliable "ask any SCPI/VISA instrument what it can do"
mechanism.** The one command designed for exactly that (`SYSTem:CAPability?`)
exists on paper in SCPI-99 but is implemented by **almost nobody**, and even when
implemented returns a coarse class string ("`DCPSUPPLY WITH MEASURE`"), never a
machine-actionable typed model with ranges and units.

What *does* work, and is what every serious framework and our own drivers already
do, is a **two-part Tier-A pattern**:
1. `*IDN?` to establish identity and **verify the connected model** against a
   hand-written expectation (never to derive behavior generically), and
2. per-command **`MIN`/`MAX` query suffixes** (e.g. `VOLT? MAX`) to
   auto-*derive limits* on the specific commands a driver already knows exist.

Everything richer (parameter typing, units, channel topology, which subsystems
exist) is **declared by a hand-written per-model driver/descriptor**, not
discovered. "Discovery" in practice = "declaration + a few live limit queries."

---

## 1. What IS standardized and genuinely queryable

### 1.1 `*IDN?` — identity, 4 fields, nothing more *(official docs)*

`*IDN?` is one of the 13 **mandated** IEEE-488.2 common commands (with `*CLS`,
`*ESE`, `*ESR?`, `*OPC`, `*RST`, `*STB?`, `*TST?`, `*WAI`, …). Every 488.2/SCPI
instrument must answer it. It returns a comma-separated **4-field** string:

```
<manufacturer>, <model>, <serial number>, <firmware revision>
```

The LXI standard even requires these four to match the IEEE-488.2 identity fields
(LXI §9.2 RULE). That is *all* `*IDN?` guarantees.

**What it does NOT give you:** channel count, voltage/current/frequency ranges,
installed options, which subsystems exist, safety class, units. It is a nameplate,
not a capability model. Real-world caveat: the *content* is only loosely
constrained — some legacy/badly-formed instruments return fewer fields, extra
commas, or vendor junk (Keysight IO Libraries documents "Badly-Formed IDN String"
handling and legacy instruments that do not answer `*IDN?` at all). So even the
4-field promise is "usually," not "always."

The only honest generic use: **verify** that the model you hand-wrote a driver for
is the model actually on the wire. Every framework below uses it exactly this way.

### 1.2 `*OPT?` — installed options, but optional and unparseable-in-general *(official docs + manuals)*

`*OPT?` is **not** in the IEEE-488.2 mandated set — it is in the *optional* group
(SCPI-99 §4.1.2; Wikipedia SCPI article confirms `*OPT?` is optional, not
required). When implemented, it "returns a comma-separated list of all of the
instrument options currently installed" (Keysight N5106A common-commands help).

Reliability/parseability in practice:
- The **content is entirely vendor/model-specific**: option order, whether options
  appear as codes (`"0B7"`), keywords (`"MEMORY,SEC"`), or `"0"`/empty when none.
  There is **no cross-vendor schema** — you must know the model to interpret it.
- **Many SCPI-conformant instruments do not implement it at all.** The Magna-Power
  TS-series SCPI reference documents `*IDN?` but **not** `*OPT?`; the Rigol DG4000
  IEEE-488.2 list I read includes `*IDN?`, `*RST`, `*SAV`, `*RCL`, `*TRG` but not
  `*OPT?`.
- On instruments that *do* have installed hardware/software options (Keysight
  signal generators, scope bandwidth/serial-decode options), `*OPT?` is the right
  way to learn which are present — but only after you already know, from the model,
  what the option codes mean.

**Verdict:** useful as a per-model, manual-decoded field; useless as a generic
capability oracle.

### 1.3 `SYSTem:CAPability?` — the SCPI-99 capability string that (almost) nobody ships *(standard + manuals; prior CONFIRMED)*

SCPI-99 (Vol. 1) defines `SYSTem:CAPability?` to return an **instrument-class
specifier** using the "instrument class" grammar from SCPI Vol. 4, e.g.

```
(DCPSUPPLY WITH (MEASURE&MULTIPLE&TRIGGER))
```

Kaya's strong prior — *"almost nobody implements it"* — is **confirmed** by the
evidence:

| Instrument / family | `SYSTem:CAPability?` present? | Source |
|---|---|---|
| XP Power PLS600 PSU | **Yes** → returns `(DCPSUPPLY WITH MEASURE)` | PLS600 programming manual *(official manual)* |
| Magna-Power TS series PSU | **No** (SYSTem subsystem lists VERSion/ERRor/network only) | Magna-Power TS SCPI ref *(official docs)* |
| Keysight Infiniium scopes | **No** (not in programmer's guide command set) | Keysight prog. guide *(official docs, index-level)* |
| Rigol DG4000 AWG | **No** | DG4000 programming manual *(official manual)* |
| Tektronix 4/5/6-Series MSO | **No** | Tek MSO programmer manual *(official manual)* |
| iseg SCPI HV | **No** (uses `:READ:MODULE:*` for topology) | iseg SCPI Programmers Guide *(secondary — manual is PDF-locked; corroborated by our own note)* |

So the one instrument I found that implements it is a bench PSU, and its reply is
`(DCPSUPPLY WITH MEASURE)` — i.e. **"I am a DC power supply that can also
measure."** That is a coarse *class + feature-flag* string, not a typed capability
model: no channel count, no voltage range, no units. Even in the best case it
tells you *which optional SCPI subsystems* an instrument claims, never the numbers
you would drive a UI or a validator from.

**Verdict:** dead end for generic discovery. Adoption is near-zero, and the payload
is too coarse to matter even where present. Do **not** build on it.

### 1.4 `*LRN?` / `SYSTem:SET?` — learn strings are STATE, not capability *(official manuals)*

`*LRN?` (and its SCPI cousin `SYSTem:SETup?`) returns a **settings blob** — an
opaque, vendor-defined string/binary block that, sent back verbatim, restores the
instrument to its current configuration. Two hard facts make it useless as a
capability model:

1. **It is current state, not the space of possible states.** It tells you the
   knob positions *right now*, not the ranges, not the options, not the topology.
2. **It is deliberately incomplete.** Tektronix 4/5/6-Series MSO programmer manual,
   verbatim: *"the response to a `*LRN?` query will not normally include the
   instrument's complete command set,"* because the interface is **dynamic** —
   "the instrument will not recognize certain commands until the objects referenced
   by those commands actually exist… commands related to measurements are not
   recognized until measurements are added" (Measurement, Math, Bus, Search, Plot
   groups are absent in the default state). So even the *command set* is not fixed,
   let alone discoverable up front.

**Verdict:** a restore mechanism, not a capability source.

### 1.5 Command-tree introspection — exists on some vendors, not machine-typable *(official docs, index-level)*

Is there a standard "list your commands"? **No SCPI/488.2 standard command lists an
instrument's command tree.** A few vendors add proprietary ones:

- **Keysight Infiniium/InfiniiVision**: `SYSTem:HELP:HEADers?` returns a list of
  the instrument's command **headers**. *(official docs — command exists; I could
  not extract the exact return format from the PDF-locked programmer's guide, so
  the format specifics are **unresolved**.)*
- **Tektronix**: `HEADer ON` / `VERBose ON` make replies self-describing (echo the
  header with each response), and `:HELP` exists on some families — but per §1.4
  the command set is **dynamic**, so any enumeration is incomplete by design.

Crucially, even where a header list is returned, it is **just a list of command
spellings** — it does *not* carry parameter types, ranges, units, or which values
are legal. You cannot machine-parse `SYSTem:HELP:HEADers?` into
`SweepableParameter(unit="V", limits=(0, 1000))`. It answers "what can I spell,"
not "what can I do and within what bounds."

### 1.6 `MIN` / `MAX` / `DEF` query suffixes — THE real mechanism for limits *(standard + multiple official manuals)*

This is the single most useful, genuinely-portable discovery primitive, and it
deserves the serious assessment Kaya asked for.

SCPI-99 rule *(official docs)*: **"Individual commands are required to accept MIN
and MAX."** `DEFault`, `UP`, `DOWN`, `NAN`, `INF`, `NINF` are optional (designer's
discretion, must be noted in the manual). The **query form** — appending `MAX`,
`MIN`, or `DEF` to the query — returns that parameter's limit rather than its
current value:

```
VOLT? MAX          → maximum programmable voltage
VOLT:PROT? MIN     → minimum programmable OVP level
SOUR:FREQ? MAX     → maximum settable frequency
```

Confirmed as documented behavior across independent vendors:
- Keysight Truevolt / E3631A / 34980A programming guides *(official docs)* — the
  canonical "special numeric values" section: MIN/MAX accepted, query returns the
  limit.
- Magna-Power TS/SL SCPI reference *(official docs)*: *"The queries `VOLT? MAX` and
  `VOLT? MIN` return the maximum and minimum programmable immediate voltage
  levels."*
- EEZ/BB3 open PSU firmware and InstrumentKit's generic SCPI layer document the
  same pattern.

**How universal is it, honestly:**
- The *acceptance* of MIN/MAX is required per SCPI-99, so on a **SCPI-conformant**
  instrument it is broadly reliable — for the specific commands that take a numeric
  parameter.
- **But** (the caveats that keep it Tier A, not Tier C):
  - It is **per-command, not per-instrument**. You must already know the command
    exists and takes a numeric parameter — i.e. you need the hand-written driver
    first. It refines a *known* parameter's bounds; it does not enumerate
    parameters.
  - Coverage is **partial in practice**. Not-strictly-SCPI instruments (much of
    Tektronix's scope tree, LeCroy) do not honor `?  MAX` on every node; the Rigol
    DG4000 manual shows `[MINimum|MAXimum]` as an *optional set* modifier and does
    **not** clearly document the query-returns-limit form on every command.
  - `DEF` is optional, so you cannot rely on `? DEF`.
  - The returned number can be **mode-dependent** (e.g. max voltage depends on the
    selected range), so a single query is a snapshot, not an invariant.

**Verdict:** the one mechanism worth wiring. Use it to **auto-derive limits on
commands a driver already declares**, defensively (fall back to the config/manual
value if the query errors or returns nonsense). This is exactly Tier A below.

---

## 2. VISA-level discovery — a DIFFERENT layer (transport, not capability)

**Say it plainly: VISA discovery answers "what is plugged in and how do I address
it," never "what can it do."**

### 2.1 `ResourceManager.list_resources()` *(official docs)*

Returns a tuple of **VISA resource/address strings**, e.g.
`('ASRL1::INSTR', 'GPIB0::14::INSTR', 'TCPIP0::192.168.0.10::INSTR')`. That is
**enumeration of transports/addresses only**. PyVISA provides *no* model or
capability data in the listing; to learn anything you must open the resource and
`*IDN?` it. VISA attributes (`read_termination`, `baud_rate`, `timeout`,
interface type, USB VID/PID, GPIB primary address) describe **the link**, not the
instrument's function.

USBTMC/GPIB/LXI/TCPIP differ only in *how* you enumerate and address — USB VID/PID
and USBTMC give you vendor/product IDs (a hint at manufacturer/model, still not
capabilities); GPIB gives a bus address; LXI/TCPIP give an IP.

### 2.2 LXI / HiSLIP identification — richer identity, still zero capability *(official standard)*

An LXI (LAN) instrument publishes an XML identification document at
`http://<ip>/lxi/identification`, discoverable via mDNS/DNS-SD (`_lxi._tcp`,
historically `_vxi-11._tcp`/`_scpi-raw._tcp`). The LXI Instrument Identification
Schema (v1.0/2.0) carries: `Manufacturer`, `Model`, `SerialNumber`,
`FirmwareRevision`, `ManufacturerDescription`, `UserDescription`, network
`Interface` info (hostname, IP, MAC, connection methods: HiSLIP/VXI-11/socket/REST),
`LXIExtendedFunctions`, and `Subinstruments` (nested identity of contained
devices).

Crucially, per the schema itself: it carries **zero instrument-class or
measurement-capability information** — no channel counts, no voltage ranges, no
"this is a scope." As the schema's own intent puts it, it answers *"what and where
is this device,"* not *"what can it measure."* So even LXI, the most structured
discovery layer we have, is still **identity + addressing + LXI-framework
compliance flags**, not a capability model.

### 2.3 IVI instrument CLASSES — the industry's actual "typed capability" answer, and why we can't lean on it *(official docs + secondary)*

IVI (Interchangeable Virtual Instruments) is the real answer to "typed
capabilities." The IVI Foundation defines **13 instrument classes** — IviDmm,
**IviScope**, **IviFgen**, **IviDCPwr**, IviACPwr, IviSwtch, IviPwrMeter,
IviSpecAn, IviRFSigGen, IviUpconverter, IviDownconverter, **IviDigitizer**,
IviCounter — each prescribing a fixed set of methods, properties (typed, with
attributes), and behaviors a driver must implement to claim *class compliance*.
This is genuinely a standardized capability contract: an `IviDCPwr` driver exposes
`Voltage.Level`, `Current.Limit`, ranges, etc., in a vendor-independent way.

Why it does **not** solve our problem:
- **It is declaration, not discovery.** The typing lives in a **vendor-supplied
  driver** (IVI-C / IVI-COM / IVI.NET), not in the instrument. You still need a
  hand-written/vendor-shipped driver per model; IVI just standardizes its *shape*.
- **Compliance is loose.** Per the IVI Getting-Started guide: *"a driver may
  correctly claim IVI compliance without being class-compliant,"* and class drivers
  "usually also include numerous functions… beyond the scope of the class
  definition." So even an IVI driver does not guarantee the class-typed surface.
- **Platform reality:** IVI is a Windows-centric, C/COM/.NET ecosystem (IVI
  Compliance Package from NI/Keysight). There is **no maintained pure-Python IVI
  stack.** The Python `ivi` package (A. Forencich) reimplements *some* class
  drivers in pure Python but is effectively unmaintained and partial; `pyivi` wraps
  the IVI-COM/shared components (Windows-only, heavy). Neither is a dependency I
  would put under a safety-critical PySide6 lab app targeting simulation-first,
  cross-platform dev.

**Verdict:** IVI is the closest thing to what Kaya is asking for, and it confirms
the shape of the answer — *typed capabilities come from a per-class driver
contract, authored per model, not sniffed from the wire.* We should **borrow the
idea** (typed capability descriptors — which `CAPABILITY_MODEL.md` already does)
without taking the IVI runtime dependency.

---

## 3. What the prior art in our domain actually does

**Confirmed: they all hand-write a driver/parameter table per model; `*IDN?` is
used only to verify/snapshot, never to derive capabilities generically.** *(official
docs for each framework)*

- **QCoDeS**: base `Instrument` auto-creates an `IDN` parameter (overridable via
  `get_idn`) *"to verify that you are connected to the instrument and to get ID
  info for metadata snapshots."* Every real parameter is declared in driver code
  with a static validator (`vals.Numbers(min, max)`, `vals.Enum(...)`). QCoDeS docs
  explicitly recommend catching invalid values in software with validators *"since
  there is no standard for how an instrument responds to an out-of-bound value"* —
  i.e. they deliberately do **not** trust the instrument to self-report limits.
- **PyMeasure**: an `id` property returns `*IDN?`. Parameters are declared with
  `Instrument.control(...)` + validators (`strict_range`, `truncated_range`,
  `joined_validators` — which *can* pass `'MIN'`/`'MAX'` strings through, but the
  numeric range is written in the driver). Ranges are **static in driver code**,
  not queried at init.
- **ophyd / bluesky**, **yaq**, **labscript**: all use a hand-authored device
  class / component map per model. None auto-derive a capability model from the
  instrument.

I found **no** mainstream framework that auto-discovers capabilities. The closest
anyone gets is optionally *validating* against MIN/MAX at runtime — and even that
is opt-in per driver, not a discovery layer. This directly corroborates Kaya's
belief.

---

## 4. The verdict for us — three tiers

### Tier A — works today, cheap: identity-verify + limit auto-derive

- **Mechanism:** `*IDN?` → parse `(manufacturer, model, serial, firmware)`; match
  `model` against the driver's expected family (fail loudly / warn on mismatch);
  optionally derive a few facts from the model string (channel count regex).
  Then, on the specific numeric commands the driver already declares, issue
  `<PARAM>? MAX` / `<PARAM>? MIN` to **auto-derive limits**, with a fallback to the
  configured/manual value on error. `*OPT?` where the model's option codes are
  documented.
- **Cost:** low — a handful of extra queries at `connect()`, per driver. Must be
  defensive (timeouts, event-queue drain, fall back to config).
- **Buys:** correct per-unit limits without hand-transcribing every datasheet;
  auto-catch "wrong model connected"; auto-size channel-dependent UI. **This is
  exactly what our repo already does** (§6) and what I recommend we formalize.

### Tier B — per-vendor, medium: declarative per-model descriptor (YAML)

- **Mechanism:** a hand-authored per-model descriptor file (parameters, units,
  ranges, topology, safety class) that a driver loads. "Discovery" is replaced by
  **declaration**. This is precisely what QCoDeS/PyMeasure/IVI effectively do (they
  put the declaration in Python instead of YAML).
- **Cost:** medium — one descriptor per supported model, kept in sync with the
  manual; a validator to check it.
- **Buys:** full typed capability model for the UI/validator/provenance, without
  trusting the instrument. Tier A's live MIN/MAX queries can *tighten* the declared
  limits at runtime. **This is the natural home of `CAPABILITY_MODEL.md`'s
  descriptors** — they are declared, then optionally refined by Tier-A queries.

### Tier C — the dream, and why it fails: fully generic SCPI capability introspection

- **Why it does not work, plainly:**
  1. `SYSTem:CAPability?` is implemented by almost no one, and returns a coarse
     class string even where present (§1.3).
  2. There is **no standard command-tree enumeration**; the vendor ones that exist
     return command *spellings*, not typed parameters with ranges/units (§1.5).
  3. The command set can be **dynamic** (Tek: measurements/math/bus commands do not
     exist until objects are added), so even enumeration is incomplete by design
     (§1.4).
  4. `*IDN?`/`*OPT?`/`*LRN?` give identity / options / state, never a typed model
     (§1.1–1.4).
  5. **Blind probing is unsafe** on our hardware class (§5): an unrecognized or
     mis-issued query can wedge the session (our TBS1052C `CURVE?` incident).
- **Conclusion:** Tier C is a non-goal. Do not design for it. Anyone promising
  "plug in any SCPI box and we'll discover it" is selling the `SYSTem:CAPability?`
  fantasy.

**Recommendation for `CAPABILITY_MODEL.md`:** **adopt Tier B as the model, with
Tier A as an optional runtime refinement.** Descriptors are *declared* per model
(Tier B), and a driver MAY, at `connect()` (live session, never at descriptor
construction), tighten a descriptor's `limits` via MIN/MAX queries or set a
channel-dependent field from `*IDN?` (Tier A) — feeding a **driver attribute**
that the I/O-free descriptor then reads. Never Tier C.

---

## 5. The safety consequence (the part that matters most)

Auto-discovery touches a live, possibly-flaky, possibly-lying instrument over a
link we have already seen wedge. Two rules must go into the spec.

### 5.1 Discovery may only ADD or TIGHTEN — never widen or lower a safety class

**Proposed spec sentence (verbatim, for `CAPABILITY_MODEL.md`):**

> **LAW — auto-discovery is monotone-safe: a value read from an instrument's
> self-report (`*IDN?`, `*OPT?`, `? MAX`/`? MIN`, channel-count queries, or any
> live query) MAY only ADD information or TIGHTEN a limit (narrow a range, reduce
> a channel count) relative to the declared descriptor; it MUST NEVER widen a
> limit, raise a maximum, or lower a `SafetyClass`. The declared `safety_class`
> and declared limits are the FLOOR — the instrument's self-report is trusted
> only to make the operating envelope *smaller*, never larger, and a
> `SafetyClass` is NEVER derived from, or downgradable by, an instrument
> self-report or discovery query.**

Rationale: an instrument that lies, or a query that returns garbage on a flaky link
(`0`, `NaN`, a truncated reply from a half-wedged session), must be **incapable** of
downgrading a hazard. Clamp-down-only makes a bad read fail safe: worst case it
needlessly *shrinks* the envelope (a hidden channel, an over-tight limit), which is
annoying but never dangerous. This is the same discipline our oscilloscope driver
already enforces (§6): a detected channel count only ever *clamps the configured
count down*, never up. It also aligns with `CAPABILITY_MODEL.md` §7.2
("routing may only tighten, never loosen") and §5.5 (driver runtime gates stay
authoritative regardless of descriptor freshness).

### 5.2 Every discovery query must itself be manual-sourced (safety rule 4), and blind probing can wedge a device

Our Hardware Safety Rule 4 ("never invent instrument commands") applies to
**discovery queries too**: the probe you send to learn capabilities is itself an
instrument command and must come from the manual for the *specific model*. You
cannot fire a generic battery of `SYSTem:CAPability?` / `? MAX` / `*OPT?` at an
**unknown** instrument and hope.

Safety of the individual queries when sent blindly to an *unknown* SCPI instrument:

| Query | Safe to send blind? | Why / risk |
|---|---|---|
| `*IDN?` | **Yes** | IEEE-488.2 mandated; every conformant instrument answers. The one safe universal probe. Even here, guard the read with a timeout (a dead LAN peer blocks ≥5 s — cf. `gui/laser_panel.py`). |
| `*OPT?` | **Mostly** | Optional but common and read-only. On an instrument that lacks it, you get a command error into the event queue (harmless if drained) — but on a **strict** instrument a query with no response can cause a query-error/timeout. Prefer to send it only once identity is known. |
| `? MAX` / `? MIN` suffix | **Only on known commands** | You must already know the command exists and takes a numeric param — i.e. from the model's manual. Sent to a node that does not accept it → command error, or worse a malformed/unterminated reply. |
| `SYSTem:CAPability?` | **No** | Almost nobody implements it; sent blind it produces a command error at best and, on our scope class, risks an **unterminated output queue that needs a VISA device clear** — the exact `CURVE?`-wedge we hit on the TBS1052C (`oscilloscope.py::_recover_session` documents this failure mode). Not worth the risk for a near-useless payload. |
| `*LRN?` / `SYSTem:SET?` | **No (for discovery)** | Vendor-defined blob; large binary reply from an unknown instrument can desync the transport. It is a restore mechanism, not a discovery one. |

**Rule for the spec:** discovery queries are issued **only by a model-specific
driver against a model it has already verified via `*IDN?`**, each query
manual-sourced (rule 4), each guarded by a timeout and event-queue drain, each
result treated as *tighten-only* (§5.1). There is **no generic discovery pass** run
against an unidentified instrument.

---

## 6. What our own tree already discovers vs hard-codes

Our repo already implements Tier-A discovery, and — importantly — already
implements the **clamp-down-only** safety discipline of §5.1. Cite these as our
existing precedent in the spec.

**Discovered (live, from the instrument):**

- **Oscilloscope channel count from `*IDN?`** —
  `TCT_app/devices/oscilloscope.py::tek_channel_count_from_idn` +
  `Oscilloscope._apply_channel_count_from_idn`. Regex-derives analog channel count
  from the Tek model number (`TBS1052C → 2`, `MSO5204B → 4`) and, if the config
  asks for **more** channels than the IDN proves exist, **clamps the config DOWN**
  with a warning — because querying a nonexistent channel *wedges the VISA session*
  (bench 2026-07-06, CH3/CH4 on a 2-channel TBS1052C). This is textbook Tier-A
  discovery **and** textbook §5.1 monotone-safety: it only ever narrows. Unknown
  model → keep the default, never guess up.
- **Keithley model-family autodetect from `*IDN?`** —
  `TCT_app/devices/bias_supply_keithley.py::_select_cmds` picks the `24xx` vs
  `6xx7` SCPI command dialect from the IDN model number; unknown model → fall back
  to `24xx` **with a warning**. Discovery of *dialect*, not of limits.
- **iseg channel count from a live query** —
  `TCT_app/devices/bias_supply_iseg.py::IsegBiasSupply.channel_count` issues
  `:READ:MODULE:CHANNELNUMBER?` (per `docs/research/iseg_polarity_scpi.md`) and
  falls back to `1` on any error or in simulation. A real (non-`*IDN?`) capability
  query, defensively wrapped.
- **`*IDN?` as a link/identity check** — waveform generator, oscilloscope(s),
  laser panel, all use `*IDN?` purely to confirm the VISA link and log identity
  (`test_connection` methods). Verification, not derivation — exactly the framework
  pattern in §3.

**Hard-coded / config-declared (Tier B, by declaration):**

- HV limits: `voltage_range_V`, `compliance_A` are **config keys**, not queried
  (`bias_supply_keithley.py`, `configs/devices.yaml`). We do **not** currently
  derive them via `? MAX` even where the instrument would support it — a candidate
  Tier-A refinement (iseg exposes nominal V/I; Keithley/Magna-style `VOLT? MAX`).
- Scope `n_channels` is a config key (clamped by the IDN discovery above).
- Waveform-generator limits are hard-coded, including the **frequency-dependent
  minimum pulse width** (`waveform_generator.py` ~L460) — a physics limit we
  transcribe from the manual rather than query.
- All vendor command dialects (`_VENDOR_CMDS` in `oscilloscope.py`;
  `_CMDS` in `bias_supply_keithley.py`) are hand-written per family.

**Takeaway:** we are already a Tier-A + Tier-B shop. The spec should *name* this as
the adopted model, generalize the clamp-down-only rule into the §5.1 LAW, and
optionally schedule `? MAX`-based limit refinement for HV as a future Tier-A add
(behind the monotone-safety LAW).

---

## 7. Note on `CAPABILITY_MODEL.md` §2.4 (no I/O at construction) — a collision to resolve

The spec's §2 LAW forbids **any** instrument I/O at descriptor/binding/registry
construction (`describe_capabilities()` included). Tier-A discovery **is** I/O.
These do not conflict *if* the ordering is fixed explicitly:

1. Discovery I/O happens **only in the driver's `connect()`** (live session), never
   in descriptor construction — exactly as `oscilloscope.py` does today (it sets
   `self.n_channels` in `connect()` from `*IDN?`).
2. The result is stored as a **constructor-time driver attribute** (`n_channels`,
   a derived `limits` field).
3. The I/O-free descriptor, built later per §5.5, simply **reads that attribute**.

So the descriptor stays pure (no I/O, §2.4 satisfied), while discovery lives in the
driver's connect path. **Recommend the spec add one sentence making this ordering
explicit**, so a future implementer does not try to put a `? MAX` query inside
`describe_capabilities()` and violate §2.4.

---

## Sources

Standards / official docs:
- IEEE 488.2 mandated common commands & `*IDN?` 4-field format; `*OPT?` optional — Wikipedia SCPI article: https://en.wikipedia.org/wiki/Standard_Commands_for_Programmable_Instruments
- SCPI-1999 (SCPI-99) specification (SYSTem:CAPability?, MIN/MAX required, special numeric values), IVI Foundation copy: https://www.ivifoundation.org/downloads/SCPI/scpi-99.pdf
- Keysight "Introduction to the SCPI Language" (Truevolt) — MIN/MAX/DEF special values & query form: https://rfmw.em.keysight.com/bihelpfiles/Truevolt/WebHelp/US/Content/__I_SCPI/Scpi_introduction.htm
- Keysight 34980A "Introduction to SCPI Language": https://documentation.help/34980A/scpi_introduction.htm
- Keysight N5106A common commands (`*IDN?`, `*OPT?`, `*RST`, `*TST?`): https://helpfiles.keysight.com/csg/n5106a/scpi_commands_common.htm
- Keysight "Badly-Formed IDN String" / legacy no-`*IDN?` instruments: https://helpfiles.keysight.com/IO_Libraries_Suite/English/IOLS_Linux/IOLS/Content/ConnectivityGuide/Troubleshooting/Badly-Formed_IDN_String.htm
- LXI Instrument Identification Schema 2.0 (identity/network only, no capability): https://public.lxistandard.org/schemas/InstrumentIdentification/2.0.html
- LXI Device Specification 1.4: https://public.lxistandard.org/specifications/LXI_1.4_Specifications/LXI_Device_Specification_1.4_2011-05-18.pdf
- IVI Foundation Getting Started Guide (13 classes; compliance ≠ class-compliance): https://www.ivifoundation.org/downloads/IVI-GSG-CurrentVersion.pdf
- IVI IviScope Class Specification (typed class contract example): https://sites.science.oregonstate.edu/~hetheriw/whiki/ph415_s13/tasks/inst/files/scpi/IVI-4-1_Scope_Class_Specification_v3-0_2009-04.pdf
- PyVISA communication docs (`list_resources()` returns address strings): https://pyvisa.readthedocs.io/en/latest/introduction/communication.html

Vendor manuals (per-vendor implementation facts):
- XP Power PLS600 programming manual (implements `SYSTem:CAPability?` → `(DCPSUPPLY WITH MEASURE)`): https://www.xppower.com/products/series/resources/PLS600_Programming_Manual.pdf
- Magna-Power TS-series SCPI reference (`VOLT? MAX/MIN`; no `SYSTem:CAPability?`, no `*OPT?`): https://magna-power.com/assets/docs/html_ts/index-scpi.html
- Tektronix 4/5/6-Series MSO Programmer Manual (`*LRN?` incomplete; dynamic command set): https://download.tek.com/manual/4-5-6-MSO-6-LPD-Programmer-Manual-077130511.pdf
- Tektronix MSO54/56/58 Programmer Manual (dynamic command set quote): https://manualzz.com/doc/55414147/tektronix-mso54--mso56--mso58--mso58lp-programmer-s-manual
- Rigol DG4000 Series Programming Manual (`[MIN|MAX]` modifiers; no `SYSTem:CAPability?`/`*OPT?`): https://www.manualslib.com/manual/2521186/Rigol-Dg4000-Series.html
- Keysight Infiniium Oscilloscopes Programmer's Guide (`SYSTem:HELP:HEADers?` exists; header-list only): https://www.keysight.com/us/en/assets/9018-07141/programming-guides/9018-07141.pdf
- iseg SCPI Programmers Guide (`:READ:MODULE:CHANNELNUMBER?`, nominal V/I): https://iseg-hv.com/download/SOFTWARE/isegSCPI/SCPI_Programmers_Guide_en.pdf
- Agilent/Keysight E3631A User's Guide (MIN/MAX query examples): http://ece-research.unm.edu/jimp/650/instr_docs/AgilentE3631A.pdf

Prior-art frameworks:
- QCoDeS "Creating Instrument Drivers" (IDN for verify/snapshot; static validators): http://microsoft.github.io/Qcodes/examples/writing_drivers/Creating-Instrument-Drivers.html
- PyMeasure validators / adding-instruments (static ranges; `joined_validators` MIN/MAX passthrough): https://pymeasure.readthedocs.io/en/latest/api/instruments/validators.html
- InstrumentKit generic SCPI (MIN/MAX pattern): https://instrumentkit.readthedocs.io/en/latest/apiref/generic_scpi.html

In-repo precedent (read directly):
- `TCT_app/devices/oscilloscope.py` (`tek_channel_count_from_idn`, `_apply_channel_count_from_idn`, `_recover_session` wedge recovery)
- `TCT_app/devices/bias_supply_keithley.py` (`_select_cmds` IDN family autodetect)
- `TCT_app/devices/bias_supply_iseg.py` (`channel_count` via `:READ:MODULE:CHANNELNUMBER?`)
- `docs/research/tbs1000c_scpi.md` (TBS1052C `CURVE?` wedge / device-clear history)
- `docs/research/iseg_polarity_scpi.md` (`:READ:MODULE:CHANNELNUMBER?` as reliable channel count)
- `docs/CAPABILITY_MODEL.md` §2.4 (no-I/O-at-construction LAW), §5.5, §7.2 (tighten-only routing)
