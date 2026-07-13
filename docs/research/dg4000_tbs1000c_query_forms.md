# DG4000 output-state / load queries, TBS1000C probe & coupling queries, DG4000 error query

- **Date:** 2026-07-08
- **Researcher:** Prometheus (research)
- **Purpose:** Close the `TODO(manual needed)` at `TCT_app/devices/waveform_generator.py:296`
  (output-state query for the armed indicator) and back two bench-checklist items
  (`:OUTPut:LOAD?` readback; TBS1052C `CH:PRObe:GAIN?` / `CH:COUPling?` fallbacks)
  with cited manual facts. External research only; no code edits.
- **Hardware:** Rigol **DG4162** (DG4000 series) function/arb generator; Tektronix
  **TBS1052C** (TBS1000C series) oscilloscope.
- **Primary manuals:**
  - RIGOL **DG4000 Series Programming Manual** (ManualsLib id 2521186, 646 pp.).
  - Tektronix **TBS1000C Series Programmer Manual, 077-1691-xx** (part-number
    correction: the brief guessed 077-1499; the real TBS1000C programmer manual is
    **077-1691**, confirmed by mirror filename `P077169100`).
  - Tektronix **TBS2000 Series Programmer Manual, 077-1149-xx** — the *same command
    engine* as TBS1000C (already established as authoritative for this engine in
    `docs/research/tbs1000c_scpi.md`); used for exact argument/return text where the
    TBS1000C PDF's detail pages are image-only.

---

## Q1a — DG4162 output-state QUERY: does `:OUTPut[1|2][:STATe]?` exist, and what does it return?

**Answer: YES, it exists, and it returns `ON` or `OFF` (a keyword, not `1`/`0`).**

- The DG4000 `:OUTPut` subsystem index (DG4000 Programming Manual, p.199) lists both
  the set and query forms verbatim:
  ```
  :OUTPut[<n>][:STATe] ON|OFF
  :OUTPut[<n>][:STATe]?
  ```
  `<n>` = channel 1 or 2; if omitted the operation targets CH1 by default.
- **Return format = `ON` / `OFF`.** The DG4000 manual uses one uniform template for
  every boolean `[:STATe]` command. The sibling command on the same subsystem,
  `:OUTPut[<n>]:NOISe[:STATe]?` (detail p.208), states verbatim:
  *"The query returns ON or OFF."* `[:STATe]` and `:SYNC[:STATe]` share the identical
  grammar and template, so `:OUTPut[<n>][:STATe]?` likewise returns `ON`/`OFF`.
  (The dedicated STATe detail page, ~p.211-212, carries the heading but its body is
  image-only and did not text-extract; the return format is therefore taken from the
  identical sibling command + the subsystem grammar, not guessed.)
- Short form is valid (bracketed nodes optional): **`:OUTP1?`** ⇔ `:OUTPut1:STATe?`.

**Confidence:** official manual (command existence + return format via the identical
same-subsystem sibling `NOISe[:STATe]?` verbatim text). The bare-STATe detail page
itself is image-only.

**Driver guidance (for Paul):** on connect, query `:OUTPut{ch}:STATe?` (or `:OUTP{ch}?`)
and resolve the armed indicator to real `True`/`False` instead of tri-state `None`.
**Parse defensively:** strip whitespace, uppercase, map `ON`/`1` → True and
`OFF`/`0` → False. (Manual documents `ON`/`OFF`; parsing `1`/`0` too costs nothing and
guards against a firmware that answers numerically.) This is a read-only query — it
does **not** change the output and does not violate the "connect must not arm the
laser trigger" safety rule.

## Q1b — DG4162 `:OUTPut:LOAD?` query form + return format

**Answer: `:OUTPut[<n>]:LOAD? [MINimum|MAXimum]` returns the impedance as a plain
number in ohms, or the word `INFINITY` for High-Z.**

From the DG4000 Programming Manual, `:OUTPut[<n>]:LOAD` detail (p.202-203):
- **Syntax:** `:OUTPut[<n>]:LOAD <ohms>|INFinity|MINimum|MAXimum`
- **Query:** `:OUTPut[<n>]:LOAD? [MINimum|MAXimum]`
- **Parameter:** integer, **1 Ω to 10000 Ω, default 50 Ω**.
- **Return Format (verbatim):** *"The query returns the specific impedance value or
  INFINITY (HighZ)."*
- **Example (verbatim):** set `:OUTPut2:LOAD 100` → query `:OUTPut2:LOAD?` returns `100`.

**Confidence:** official manual (verbatim return format + example).

**Bench-checklist guidance:** after the driver sends `:OUTP:LOAD 50`, verifying with
`:OUTP:LOAD?` should read back `50` (bare integer, **no unit suffix**). A unit left in
High-Z reads the literal token `INFINITY` (not a number) — the checklist/parse must
accept that non-numeric case. This confirms the load-doubling guard from
`docs/research/pdl800_trigger_wavegen_lan.md` §Q2 is verifiable in software.

---

## Q2 — TBS1052C (TBS1000C series): do `CH<x>:PRObe:GAIN?` and `CH<x>:COUPling?` exist, and what are the forms/returns?

**Answer: YES — both exist on the TBS1000C series, in exactly the forms the driver
already uses. They are the correct TBS1000C commands, not just tolerated fallbacks.**

Both appear in the **TBS1000C Programmer Manual (077-1691)** Vertical command group
(command index: `CH<x>:COUPling` ~p.53, `CH<x>:PRObe:GAIN` ~p.56). The TBS1000C PDF's
per-command *detail* pages are image-only (same limitation noted in
`tbs1000c_scpi.md`), so the exact argument/return text below is quoted from the
**same-engine TBS2000 Programmer Manual (077-1149)**, which `tbs1000c_scpi.md` already
establishes as authoritative for this command engine.

### `CH<x>:COUPling`
- **Syntax:** `CH<x>:COUPling {AC|DC|GND}` / query `CH<x>:COUPling?`
- Sets/queries the input-attenuator coupling of channel `<x>`.
- **Query returns** one of `AC` / `DC` / `GND`. Example (concatenated query with
  header ON): `CH1:COUPling;BANdwidth` → `:CH1:COUPLING DC;:CH1:BANDWIDTH ON`; with
  header OFF → `DC;ON`.
- **Driver match:** `oscilloscope.py:424` sends `CH{ch}:COUPling {DC|AC|GND}`; the read
  path (`CH1:COUPling?`, line 489) takes the **last whitespace-token** — correct,
  because with `HEADer ON` the reply is `:CH1:COUPLING DC` and the trailing token is
  the value. **Confirmed correct.**

### `CH<x>:PRObe:GAIN`
- **Syntax:** `CH<x>:PRObe:GAIN <NR3>` / query `CH<x>:PRObe:GAIN?`
- Sets/queries the probe **gain** = 1 / attenuation factor.
- **Query returns** a floating-point gain. Example (verbatim, TBS2000): `CH2:PROBE:GAIN?`
  returns `:CH2:PROBE:GAIN 0.1000E+00` — i.e. a **10× probe delivers 1 V to the BNC per
  10 V at the probe tip**, so gain `0.1`.
- **Driver match:** `oscilloscope.py:413` sends `CH{ch}:PRObe:GAIN {1.0/factor}`, and
  the read path (line 484-487) reads `CH1:PRObe:GAIN?` as a gain then computes
  `probe_factor = round(1.0/gain, 3)`. **Confirmed correct** (gain 0.1 ↔ factor 10).

**Family trap (why the fallbacks exist):** the *legacy* TDS1000/2000 and TBS1000**B**
family use `CH<x>:PRObe <factor>` (probe *attenuation*, e.g. `10`), **not**
`CH<x>:PRObe:GAIN`. TBS1000**C** follows the TBS2000 `PRObe:GAIN` (gain = 1/attenuation)
form. So on the TBS1052C the driver's `CH:PRObe:GAIN` is the *primary correct* command;
the `CH:PRObe`-style fallback is only for a legacy scope and should never fire on the
bench TBS1052C.

**Confidence:** official manual (command existence + Vertical-group index on TBS1000C
077-1691) with argument/return text cross-referenced from the same-engine TBS2000
077-1149. Not yet live-probed on the bench unit — recommend adding `CH1:COUPling?` and
`CH1:PRObe:GAIN?` to the next `scope_verify_scpi.py` pass to promote to "live-verified"
(the existing note live-verified `CH1:SCAle?` but not these two).

---

## Q3 — DG4000 `:SYSTem:ERRor?` supported? (low priority, confirm syntax)

**Answer: YES.** DG4000 Programming Manual, `:SYSTem` subsystem (detail p.568):
- **Syntax:** `:SYSTem:ERRor?` (query only; **bare form, no `[:NEXT]` node** on DG4000).
- **Description (verbatim):** *"Query the error event queue."*
- **Return Format (verbatim):** *"The query returns the error event information, such as
  `-113,'Undefined header; keyword cannot be found'`. If error does not exist, the query
  returns `0,'No Error'`."*
- Format is `<code>,"<message>"`; pops one event per query (drain in a loop until
  `0,"No Error"`).

**Confidence:** official manual (verbatim). Confirms the driver's existing usage; note
the DG4000 spelling is the bare `:SYSTem:ERRor?` (not `:SYSTem:ERRor:NEXT?`).

---

## Actionable updates (Adam routes; do not edit code/ledgers from here)

1. **CLOSE `TODO(manual needed)` at `waveform_generator.py:296`** → Paul. The query
   `:OUTPut{ch}:STATe?` (short `:OUTP{ch}?`) is manual-confirmed and returns `ON`/`OFF`.
   On connect, query it and set the armed indicator to real `True`/`False` (parse
   `ON`/`1`→True, `OFF`/`0`→False, case-insensitive, stripped) instead of `None`.
   Read-only — safe on connect.
2. **BENCH_CHECKLIST — add `:OUTP:LOAD?` readback** → Paul/Kiroku. After `:OUTP:LOAD 50`,
   `:OUTP:LOAD?` must read `50` (bare integer, no unit); High-Z reads literal `INFINITY`.
   Verifies the load-doubling guard from `pdl800_trigger_wavegen_lan.md`.
3. **TBS1052C bench TODO / BENCH_CHECKLIST** → Paul/Kiroku. `CH:PRObe:GAIN?` and
   `CH:COUPling?` are now manual-cited as the correct TBS1000C forms (077-1691 Vertical
   group; args/returns via same-engine 077-1149). The `oscilloscope.py` guards can stay
   as defensive, but the "TODO: confirm the correct TBS1000C-specific form" is resolved.
   Optional: add both to the next `scope_verify_scpi.py` live pass to reach
   "live-verified".
4. **Doc fix** → Kiroku. Where the TBS1000C programmer manual was referenced as
   `077-1499`, correct to **077-1691**.

---

## Sources

- [RIGOL DG4000 Series Programming Manual (ManualsLib id 2521186)](https://www.manualslib.com/manual/2521186/Rigol-Dg4000-Series.html)
  — `:OUTPut` subsystem index p.199 (`:OUTPut[<n>][:STATe] ON|OFF` / query);
  `:OUTPut:LOAD` return format + example p.202-203;
  `:OUTPut:NOISe[:STATe]?` "returns ON or OFF" p.208 (sibling confirming the STATe
  return template); `:SYSTem:ERRor?` return format p.568. *official manual (browsable
  page view; STATe detail page image-only, return format via identical sibling).*
- [Tektronix TBS1000C Series Programmer Manual 077-1691-00 (ujaen.es mirror)](https://www.ujaen.es/departamentos/ingele/sites/departamento_ingele/files/uploads/node_seccion_de_micrositio/2021-01/osciloscopio%20TBS1052C%20manual%20del%20programador.pdf)
  — Vertical command group lists `CH<x>:COUPling` (~p.53) and `CH<x>:PRObe:GAIN`
  (~p.56). *official manual; detail pages image-only.*
- [Tektronix TBS1000C Series Programmer Manual — tek.com landing](https://www.tek.com/en/manual/oscilloscope/tbs1000c-series-oscilloscopes-programmer-manual-tbs1000)
  — official part-number confirmation (077-1691).
- [Tektronix TBS2000 Series Programmer Manual 077-1149 (ManualsLib id 1291718)](https://www.manualslib.com/manual/1291718/Tektronix-Tbs2000-Series.html)
  — exact `CH<x>:COUPling {AC|DC|GND}` args/returns and `CH<x>:PRObe:GAIN?` →
  `:CH2:PROBE:GAIN 0.1000E+00` example. *official manual, same command engine as
  TBS1000C.*
- Related in-repo notes: `docs/research/pdl800_trigger_wavegen_lan.md` (DG4162 SET
  commands + load-doubling), `docs/research/tbs1000c_scpi.md` (TBS1000C command engine
  = TBS2000; live-verified trigger/acq set).

**Overall confidence:** official manual for all three questions. Only caveat: the
DG4162 `[:STATe]?` and TBS1052C `CH:PRObe:GAIN?`/`CH:COUPling?` *detail* pages are
image-only in their native manuals, so their exact return text is sourced from the
identical same-subsystem sibling (DG4000 `NOISe[:STATe]?`) and the same-engine TBS2000
manual respectively — not guessed. Recommend a one-line bench probe of each to promote
to live-verified.
