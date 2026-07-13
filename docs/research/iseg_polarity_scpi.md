# iseg HV channel polarity over iseg SCPI

- **Date:** 2026-07-06
- **Requested by:** Adam (for `TCT_app/devices/bias_supply_iseg.py`)
- **Exact question:** How do you *read*, *set/reverse*, and *safely gate* channel
  output polarity on iseg SHR / NHR / EHS / SR desktop HV modules over iseg SCPI
  (LAN socket or ASRL serial, CR-LF)? Which modules can reverse in software, how
  do you detect that programmatically, and how do you enumerate channels?
- **Applies to:** iseg SCPI general instruction set (SHR, NHR, NHS, MICC families).
  Reference doc: *iseg SCPI Programmers Guide* (general instruction set), last
  changed 2025-07-17; NHS-series Programmer's Manual (same SCPI set, ManualsLib
  reproduction); *SHR Technical documentation* last changed 2024-04-03.
- **Overall confidence:** official manual for command syntax, the switching
  precondition, and the channel-status bit map; official docs for channel
  addressing and the reversible-vs-fixed model split. Items I could not confirm
  from a rendered official page are flagged **[UNVERIFIED]** below.

> SAFETY: this is HV. Every command below is cited. Do **not** add uncited
> commands. Polarity reversal must be gated behind the OFF + discharged
> precondition in section 3 and behind explicit user confirmation in the UI.

---

## 1. Command table

All commands use the iseg SCPI channel-suffix form `(@<ch>)` and CR-LF framing
(already handled by the driver). Query replies are ASCII.

| Purpose | Command | Reply / arg | Notes |
|---|---|---|---|
| Query current polarity | `:CONF:OUTP:POL? (@ch)` | `p` or `n` | `p`=positive, `n`=negative. Long form `:CONF:OUTPut:POLarity?`. |
| List available polarities (capability) | `:CONF:OUTP:POL:LIST? (@ch)` | `p,n` (reversible) or a single value (fixed) | This is the runtime reversible-vs-fixed test — see section 4. |
| Set / reverse polarity | `:CONF:OUTP:POL <p\|n>,(@ch)` | (no data) | e.g. `:CONF:OUTP:POL n,(@0)`. Same `value,(@ch)` arg order as `:VOLT`/`:CURR`. Only accepted under the precondition in section 3. |
| Query output mode (NHR/SHR) | `:CONF:OUTP:MODE? (@ch)` | e.g. `2` | Range/mode select; shares the same OFF+discharged switching gate as polarity. Not polarity, listed for completeness. |
| List available output modes | `:CONF:OUTP:MODE:LIST? (@ch)` | e.g. `1,2,3` | |
| Persist polarity/mode (SHR) | `:SYST:USER:CONFIG SAVE` | (no data) | On SHR, saves changed output mode/polarity to `icsConfig.xml`. |
| Channel status word | `:READ:CHAN:STAT? (@ch)` | UINT32 (UI4) | Bit map in section 6; **bit 0 = Is Positive**. |
| Number of channels on module | `:READ:MODULE:CHANNELNUMBER?` | integer (e.g. `4`) | Use to enumerate channels — section 5. |

Notes:
- Long/short SCPI forms are equivalent: `:CONF:OUTPut:POLarity` == `:CONF:OUTP:POL`.
- The polarity/mode commands are documented under the manual's **"Commands for
  NHR and SHR"** section, i.e. they are meaningful on the polarity-switchable
  families. On fixed-polarity modules treat them as possibly unsupported
  (wrap in try/except; a missing/one-value list means "fixed").

---

## 2. Set / reverse polarity — syntax

```
:CONF:OUTP:POL p,(@0)     # force positive on channel 0
:CONF:OUTP:POL n,(@0)     # force negative on channel 0
```

To "reverse", read `:CONF:OUTP:POL? (@ch)` and write the opposite letter.
After writing, re-query `:CONF:OUTP:POL? (@ch)` (and/or bit 0 of the channel
status word) to confirm the relay actually moved before ramping HV.

---

## 3. Hard constraints for a legal reversal (SAFETY-CRITICAL)

Verbatim from the official iseg documentation (SHR Technical documentation /
SCPI guide, "Commands for NHR and SHR"):

> "Switching the polarity or output mode is only allowed if the corresponding
> channel is switched off and discharged below 0.002 · Vnom. The module blocks
> all switching attempts if these conditions are not satisfied."

Concretely, before sending `:CONF:OUTP:POL`:

1. **Channel output must be OFF** (`:VOLT OFF,(@ch)`; status bit 3 "Is On" == 0).
2. **Output must be discharged below 0.002 × Vnom** — i.e. |V_meas| < 0.2 % of the
   channel's nominal voltage (for a 2 kV channel that is < ~4 V). Verify via
   `:MEAS:VOLT? (@ch)`, not just the setpoint.
3. Only then issue `:CONF:OUTP:POL <p|n>,(@ch)`.

If these are not met the module **silently blocks the switch** (the command is
rejected / ignored — it does not force a relay under load). So a reversal sent
while ramped up simply does nothing rather than damaging the relay; but you must
not rely on that — always gate on OFF + discharged and then verify the polarity
actually changed.

**Recommended safe sequence for the driver / UI:**
1. Confirm with the user (dangerous action).
2. `:VOLT 0,(@ch)` then `:VOLT OFF,(@ch)`.
3. Poll `:MEAS:VOLT? (@ch)` until |V| < 0.002 × Vnom (and status bit 3 == 0).
4. `:CONF:OUTP:POL <new>,(@ch)`.
5. Re-query `:CONF:OUTP:POL? (@ch)` (and status bit 0) to confirm.
6. (SHR, optional) `:SYST:USER:CONFIG SAVE` to persist.
7. Only after confirmation, allow the user to set a new voltage and ramp.

**[UNVERIFIED]** The exact relay settling / switch time is **not** stated in the
sources I could read. Treat the polarity change as non-instantaneous: after the
write, wait and re-query `:CONF:OUTP:POL?` / status bit 0 rather than assuming it
took effect immediately. Do not ramp until confirmed.

---

## 4. Which modules can reverse polarity, and how to detect it

iseg's naming convention (the trailing letter encodes polarity capability):

| Family | Polarity | Software-reversible? |
|---|---|---|
| **SHR** (desktop, up to 4 ch) | electronically reversible | **Yes** — "electronically reversible polarity". |
| **NHR** (NIM module) | electronically switchable | **Yes** — "polarity electronically switchable", "reversible polarity". |
| **EHR** (ECH/crate module) | polarity-switchable variant | **Yes** — iseg product name: "EHR – Polarity switchable High Precision HV Module". |
| **NHS** (NIM) | fixed | **No** — "channels of fixed polarity" (set at order). |
| **EHS** (crate module) | fixed | **No** — polarity ordered as positive or negative; the *reversible* counterpart is EHR, not EHS. |
| **SR** (older desktop) | fixed **[UNVERIFIED]** | Assume **No** unless the POL:LIST? test below says otherwise. |

Heuristic: **"…HR" = reversible, "…HS"/SR = fixed.** But do **not** rely on the
model name alone.

**Authoritative runtime detection (use this):**
```
:CONF:OUTP:POL:LIST? (@ch)
```
- Reply contains **both** `p` and `n`  → channel polarity is **software-reversible**.
- Reply contains a **single** value (only `p` or only `n`) → **fixed polarity**;
  hide/disable the reverse control for that channel.
- Command **errors / unsupported / times out** → treat as **fixed** (fail safe:
  do not offer reversal). Wrap in try/except and default to fixed.

This query is safe (read-only, no HV action) and works per-channel, which also
covers mixed-population crates.

---

## 5. Multi-channel addressing & enumeration

- **Channel suffix:** channels are numbered `0 .. ChannelNumber-1`; address with
  `(@<ch>)`. The driver already does this (`(@{self._ch})`).
- **Range / list forms (official SCPI guide):**
  - range: `(@0-3)`
  - list: `(@0,1,3,5)`
  - combined: `(@0-2,5-7)` → operates on 0,1,2,5,6,7.
  - Answer parts for multi-channel queries are comma-separated.
- **Number of channels on the module:**
  ```
  :READ:MODULE:CHANNELNUMBER?    -> e.g. 4
  ```
  Enumerate `ch = 0 .. N-1` from this. This is the safe way for a multi-channel
  UI to build its channel list rather than hard-coding channel 0/1.
- **`*IDN?`** returns identification; for iCS-based systems it contains the iCS
  version plus firmware name/release of the CC24 / SHR (iCSmini controllers
  report no firmware info). Useful for logging and the model-name heuristic in
  section 4, but `:READ:MODULE:CHANNELNUMBER?` is the reliable channel count.

**[UNVERIFIED]** Exact `*IDN?` field layout differs between direct-SHR, iCS, and
iCSmini front-ends; parse defensively and prefer `:READ:MODULE:CHANNELNUMBER?`
for counting channels.

---

## 6. Channel status word `:READ:CHAN:STAT? (@ch)` (UINT32)

Bit map (from the NHS/SHR Programmer's Manual channel-status table). The example
reply `152` = 128 + 16 + 8 = bits 7 + 4 + 3 ("Is Constant Voltage", "Is Voltage
Ramp", "Is On"), which confirms the low-bit assignments below.

| Bit | Value | Name | Meaning |
|---|---|---|---|
| 0 | 1 | **Is Positive** | 1 = positive output polarity, 0 = negative. **Use this to confirm the relay position after a reversal.** |
| 1 | 2 | Is Arc | Arc detected |
| 2 | 4 | Is Input Error | Input/parameter error |
| 3 | 8 | **Is On** | Channel switched on (`:VOLT ON`). Must be 0 to switch polarity. |
| 4 | 16 | Is Voltage Ramp | Voltage is ramping |
| 5 | 32 | Is Emergency Off | Set to emergency off (`:VOLT EMCY OFF`) |
| 6 | 64 | **Is Constant Current** | Channel is current-controlled (in compliance) |
| 7 | 128 | **Is Constant Voltage** | Channel is voltage-controlled (normal) |
| 8 | 256 | Is Low Current Range | Low current measurement range active |
| 9 | 512 | Is Arc Error | Arc error latched |
| 10 | 1024 | Is Current Bounds | Current outside bounds tube |
| 11 | 2048 | Is Voltage Bounds | Voltage outside bounds tube |
| 12 | 4096 | Is External Inhibit | External inhibit asserted |
| 13 | 8192 | Is Current Trip | Current trip triggered |
| 14 | 16384 | Is Current Limit | Measured current at/above limit |
| 15 | 32768 | Is Voltage Limit | Measured voltage at/above limit |
| 16 | 65536 | Is Current Ramp | (NHR/SHR) current ramping |
| 17 | 131072 | Is Current Ramp Up | (NHR/SHR) |
| 18 | 262144 | Is Current Ramp Down | (NHR/SHR) |
| 19 | 524288 | Is Voltage Ramp Up | (NHR/SHR) |
| 20 | 1048576 | Is Voltage Ramp Down | (NHR/SHR) |
| 21 | 2097152 | Is Voltage Bound Upper | (NHR/SHR) |
| 23 | 8388608 | Is Voltage Bound Lower | (NHR/SHR) |

Polarity-relevant bits to surface in the UI:
- **Bit 0 "Is Positive"** — actual relay/polarity position (confirms a reversal
  took effect). Combine with `:CONF:OUTP:POL?` for a cross-check.
- **Bit 3 "Is On"** — must be clear before a legal polarity switch.
- **Bit 7 "Is Constant Voltage" / Bit 6 "Is Constant Current"** — whether the
  channel is voltage- or current-controlled (the "is voltage/current controlled"
  status the brief asked about).

**[UNVERIFIED]** Bits 22, 24-31 are reserved / model-specific in the source table;
mask them off and only decode the bits above.

---

## 7. Practical guidance for `bias_supply_iseg.py`

- Add capability detection at connect: `:CONF:OUTP:POL:LIST? (@ch)` → store
  `polarity_reversible: bool` and `available_polarities`. On error, mark fixed.
- Add `get_polarity()` → `:CONF:OUTP:POL? (@ch)` (returns `'p'`/`'n'`).
- Add `set_polarity(pol)` that enforces: connected → output OFF → poll
  `:MEAS:VOLT?` until |V| < 0.002 × `voltage_range_V` → `:CONF:OUTP:POL <pol>,(@ch)`
  → re-query to confirm. Refuse (raise) if not discharged; never force.
- The configured `voltage_range_V` (2000) is a reasonable Vnom proxy for the
  0.002·Vnom threshold, but prefer the module's own nominal if queryable.
- For multi-channel UIs, enumerate via `:READ:MODULE:CHANNELNUMBER?`.
- Gate `set_polarity` behind explicit UI confirmation (dangerous action), same as
  HV enable/ramp.

---

## Sources

- iseg SCPI Programmers Guide (general instruction set), last changed 2025-07-17 —
  polarity commands, channel addressing `(@0-3)`/`(@0,1,3)`, output mode:
  https://iseg-hv.com/download/SOFTWARE/isegSCPI/SCPI_Programmers_Guide_en.pdf
  *(confidence: official docs; PDF could not be rendered locally — content read
  via its published examples + ManualsLib reproduction below.)*
- iseg NHS Series Programmer's Manual (same SCPI set), ManualsLib — command
  examples (`:CONF:OUTP:POL?`→`n`, `:CONF:OUTP:POL:LIST?`→`p,n`,
  `:CONF:OUTP:MODE:LIST?`→`1,2,3`), channel status register bit table,
  `:READ:MODULE:CHANNELNUMBER?`→`4`, `(@0..4)` addressing:
  https://www.manualslib.com/manual/2413390/Iseg-Nhs-Series.html (p.45–46) and
  https://www.manualslib.com/manual/2119878/Iseg-Nhs-Series.html?page=25
  *(confidence: official manual reproduction.)*
- iseg SHR Technical documentation, last changed 2024-04-03 — "Switching the
  polarity or output mode is only allowed if the corresponding channel is
  switched off and discharged below 0.002 · Vnom…"; "electronically reversible
  polarity"; SHR `SYST:USER:CONFIG SAVE` → `icsConfig.xml`:
  https://iseg-hv.com/download/AC_DC/SHR/iseg_manual_SHR_en.pdf
  *(confidence: official manual; constraint sentence read via search extraction
  of this official PDF, not a locally rendered page.)*
- iseg NHR Series Technical documentation, ManualsLib — "polarity electronically
  switchable", "reversible polarity":
  https://www.manualslib.com/manual/1772706/Iseg-Nhr-Series.html
  *(confidence: official docs.)*
- iseg EHR product page — "EHR – Polarity switchable High Precision HV Module"
  (the reversible counterpart to the fixed EHS):
  https://iseg-hv.com/en/products/detail/EHR
  *(confidence: official docs.)*
