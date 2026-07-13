# Tektronix TBS1000C (TBS1052C) SCPI command reference

> **Live-verified 2026-07-06 (Adam, on the bench TBS1052C).** The four items
> Prometheus flagged for verification were probed directly against the
> instrument (read-only / restored). Results — these override the manual
> guesses above where they differ:
>
> | Flagged item | Manual guess | **Live result on TBS1052C** |
> |---|---|---|
> | External trigger source keyword | `AUX` (uncertain vs `EXT`) | **Both work**: `AUX` and `EXT` are accepted and both read back as `AUX`; only the long form `EXTernal` is rejected (event 141, invalid enumeration). Driver's `EXT` default is therefore safe. |
> | `ACQuire:NUMAVg` valid values | only `4/16/64/128` | **2, 4, 8, 16, 32, 64, 128, 256 all accepted** (no error, read back verbatim). `1`→coerced to `2`; `512`→coerced to `256`. The driver never sends `1` (it uses `ACQuire:MODe SAMple` for n≤1), so no snapping needed. |
> | `SELect:CH<x>` set form | `{ON\|OFF\|<NR1>}` | **Confirmed**: `SELect:CH1 ON`→reads `1`, `SELect:CH1 OFF`→reads `0`. |
> | Query header prefix | (not raised) | Bench unit had `HEADer OFF`, so `SELect:CH1?`→`1`. The driver now **forces `HEADer OFF`/`VERBose OFF` at connect** so this is deterministic across units, and the channel-active precheck parses the trailing token defensively regardless. |
>
> Verified with `scope_verify_scpi.py` (event-queue drain via `*ESR?`/`ALLEv?`
> after each write). Prometheus's core finding stands: the trigger tree is
> `TRIGger:A:*`, never the bare `TRIGger:MODE/...`.

- **Date:** 2026-07-06
- **Researcher:** Prometheus (research) + Adam (live verification)
- **Question:** Authoritative SCPI command set for the Tektronix TBS1052C (TBS1000C
  series) — edge-trigger config, channel display, single-sequence/average
  acquisition, waveform transfer, record length, capability/error queries — to
  fix the generic VISA driver (`TCT_app/devices/oscilloscope.py`) whose
  `TRIGger:MODE/SOURce/LEVel/SLOPe` commands are rejected with "Undefined header".
- **Instrument / firmware:** TBS1000C series (TBS1052C = 50 MHz, 2-channel,
  1 GS/s, 20 kpt record). All TBS1000C models (TBS1052C/1072C/1102C/1202C and
  the -EDU variants) are **2-channel**.

## Source reliability note (read first)

There is a real command-set split across Tektronix families, so sources are tiered:

1. **TBS1000C Programmer Manual, 077-1691-xx** (official, primary). Confirms which
   commands exist, their spelling, and page numbers. Two revisions seen:
   077-1691-00 (trigger group ~p.222-238) and 077-1691-02 (trigger group
   ~p.147-158; `HORizontal:RECOrdlength` p.105). I could read its front matter /
   command-group index and page map, but the PDF's detailed argument pages could
   not be text-extracted with available tooling, so **exact argument enums below
   are taken from same-engine manuals and flagged**.
2. **TBS2000 Series Programmer Manual, 077-1149-xx** (official). The TBS1000C uses
   the *same command engine* as the TBS2000 platform (`TRIGger:A:*`,
   `SELect:CH<x>`, `WFMOutpre?`, `HORizontal:RECOrdlength/SAMPLERate`,
   `ACQuire:*`). Used for exact `TRIGger:A` and `WFMOutpre?` argument text.
   **Difference vs TBS1000C:** TBS2000 has 2/4 channels and *no external/AUX
   trigger input*; TBS1000C has 2 channels + an AUX (external) trigger input.
3. **TBS1000B/EDU Programmer Manual, 077-0444-xx** (official). Predecessor family;
   used for `ACQuire`, `DATa`, `CURVe`, `WFMPre?` argument text (identical on
   TBS1000C). **Difference:** this family uses `TRIGger:MAIn:*`, record length 2500,
   and **no `HORizontal:RECOrdlength`** — do NOT copy its trigger syntax.
4. **TBS1000C User Manual (077-1571) and datasheet/Technical Reference (077-1583).**
   Prose confirmation of trigger types, sources, record length, acquisition modes.

Ground truth from Adam's live probing of the real TBS1052C: `TRIGger:A?`,
`TRIGger:A:EDGE?`, `ACQuire:STATE?/STOPAfter?/MODE?/NUMAVg?`, `HORizontal:SCAle?/
RECOrdlength?/SAMPLERate?`, `SELect:CH1?`, `CH1:SCAle?`, `WFMOutpre?`, `WFMPRE?`,
`CURVE?`, `DATa?`, `ALLEv?`, `*ESR?` all **work**; `HORizontal:FASTframe:*` is
**rejected** (no FastFrame). This confirms the `TRIGger:A` (not `TRIGger:MAIn`,
not bare `TRIGger:MODE`) command tree.

---

## 1. Edge trigger configuration

The driver's bug: TBS1000C has **no** `TRIGger:MODE`, `TRIGger:SOURce`,
`TRIGger:LEVel`, or `TRIGger:SLOPe` at the top level. Everything hangs off
`TRIGger:A:`.

| Purpose | Command (set) | Query | Arguments | Confidence |
|---|---|---|---|---|
| Trigger type | `TRIGger:A:TYPe {EDGe\|PULSe}` | `TRIGger:A:TYPe?` | `EDGe`, `PULSe` (TBS1000C also lists Runt under `TRIGger:A:PULse:CLAss {RUNt\|WIDth}`) | TBS2000 m/ p.258; TBS1000C user manual confirms Edge/Pulse Width/Runt |
| Trigger mode | `TRIGger:A:MODe {AUTO\|NORMal}` | `TRIGger:A:MODe?` | `AUTO`, `NORMal` | TBS2000 p.248 |
| Edge source | `TRIGger:A:EDGE:SOUrce {CH1\|CH2\|AUX\|LINE}` | `TRIGger:A:EDGE:SOUrce?` | `CH1`,`CH2`, external = `AUX`, `LINE` (AC line) | see note ▼ |
| Edge slope | `TRIGger:A:EDGE:SLOpe {RISe\|FALL}` | `TRIGger:A:EDGE:SLOpe?` | `RISe`, `FALL` | TBS2000 p.243; user manual confirms rising/falling |
| Edge coupling | `TRIGger:A:EDGE:COUpling {DC\|HFRej\|LFRej\|NOISErej}` | `TRIGger:A:EDGE:COUpling?` | `DC`,`HFRej`,`LFRej`,`NOISErej` (note: **no AC** on this engine) | TBS2000 p.242 |
| Trigger level (current source) | `TRIGger:A:LEVel {ECL\|TTL\|<NR3>}` | `TRIGger:A:LEVel?` | `<NR3>` = volts; `TTL` = +1.4 V preset; `ECL` = -1.3 V preset | TBS2000 p.246 |
| Per-channel level | `TRIGger:A:LEVel:CH<x> {ECL\|TTL\|<NR3>}` | `TRIGger:A:LEVel:CH<x>?` | as above, per channel `<x>`=1..2 | TBS2000 p.247; TBS1000C mfr manual lists it at p.227 (-00) |

**▼ External-source keyword (important, action item):** The driver defaults to
`trigger_source="EXT"`. On the TBS1000C the external input is the **AUX** connector
and the on-screen trigger-source menu option is literally **"AUX source"** (TBS1000C
User Manual, "Trigger on an external signal using the Aux input", p.92). The
same-platform TBS2000 has *no* external source at all (`{CH1|CH2|CH3|CH4|LINE}`,
077-1149 p.244), so `AUX` is a TBS1000C-specific addition. **Best evidence says the
enum keyword is `AUX`, not `EXT`.** This should be verified against TBS1000C
Programmer Manual `TRIGger:A:EDGE:SOUrce` (p.148 in 077-1691-02 / p.224 in
077-1691-00) — I could not text-extract that page. Recommendation: send `AUX`;
if rejected (check `ALLEv?`), fall back to `EXT`.

**AUX trigger level:** whether the AUX/external input has an adjustable level (and
its range/polarity) is **not confirmed** — verify in the manual / Technical
Reference before relying on a negative level (e.g. the TCT -0.41 V falling edge).
When source is a channel, `TRIGger:A:LEVel <NR3>` sets that channel's level.

**Recommended set order:** set `TYPe` before `EDGE:*`, and set `EDGE:SOUrce`
before `LEVel` (level applies to the selected source):

```
TRIGger:A:TYPe EDGe
TRIGger:A:MODe NORMal            ; or AUTO
TRIGger:A:EDGE:SOUrce AUX        ; CH1 | CH2 | AUX | LINE
TRIGger:A:EDGE:COUpling DC
TRIGger:A:EDGE:SLOpe FALL        ; RISe | FALL
TRIGger:A:LEVel -0.41            ; volts, applies to current source
```

---

## 2. Channel display on/off

| Command (set) | Query | Arguments | Confidence |
|---|---|---|---|
| `SELect:CH<x> {ON\|OFF\|<NR1>}` | `SELect:CH<x>?` | `ON`/`OFF`, or `<NR1>` (0 = off, non-zero = on) | TBS2000 p.230; live-probed `SELect:CH1?` works |

**Gotcha:** `SELect:CH<x>` "also resets the acquisition" (077-1149 p.230). Set
channel display *before* arming a single sequence, not during it. `SELect:CH<x>?`
returns whether the channel is displayed (not whether it is the "selected"
waveform).

---

## 3. Acquisition control

| Command (set) | Query | Arguments | Confidence |
|---|---|---|---|
| `ACQuire:STATE {OFF\|ON\|RUN\|STOP\|<NR1>}` | `ACQuire:STATE?` | `RUN`/`ON`/non-zero start; `STOP`/`OFF`/0 stop. Query returns 0/1 | TBS1000B p.60 |
| `ACQuire:STOPAfter {RUNSTop\|SEQuence}` | `ACQuire:STOPAfter?` | `RUNSTop` (free-run), `SEQuence` (single) | TBS1000B p.61 |
| `ACQuire:MODe {SAMple\|PEAKdetect\|AVErage}` | `ACQuire:MODe?` | 3 modes only — **no HIRes** on this family | TBS1000B p.58; user manual confirms Sample/Peak Detect/Average |
| `ACQuire:NUMAVg <NR1>` | `ACQuire:NUMAVg?` | **valid values: 4, 16, 64, 128** (discrete) | TBS1000B p.59-60 |
| `ACQuire:NUMACq?` | (query only) | number of acquisitions since start | TBS1000B p.59 |
| `ACQuire?` | (query only) | e.g. `:ACQUIRE:STOPAFTER RUNSTOP;STATE 1;MODE SAMPLE;NUMAVG 16` | TBS1000B p.57 |

**`RUN` vs `ON`:** both are accepted by `ACQuire:STATE` — the driver's
`ACQuire:STATE RUN` is valid. `ON` and `1` are equivalent.

**Average mode:** `ACQuire:MODe AVERAGE` then `ACQuire:NUMAVg {4|16|64|128}`. The
driver's `n_averages` (config) must be snapped to one of these four values — an
off-list value will be a command/execution error. With `STOPAfter SEQuence`, a
single "sequence" in AVERAGE mode acquires `NUMAVg` waveforms, then stops.

**Detecting single-sequence completion** (after `ACQuire:STOPAfter SEQuence` +
`ACQuire:STATE RUN`), pick one:
- **`ACQuire:STATE?` poll** → returns `1` while acquiring, `0` when the sequence
  finishes and the scope auto-stops. Simple and reliable (recommended).
- **`BUSY?`** → returns `1` while busy, `0` when idle/done (IEEE-488.2 status
  helper). Equivalent to state polling.
- **`*OPC` / `*OPC?`** → operation-complete synchronization; the TBS1000B
  `ACQuire:STATE` entry cites `*OPC` as the way to know a single sequence is done.
  `*OPC?` returns `1` when pending operations (the sequence) complete.

> Note: `BUSY?` polarity (1 = busy) is the Tektronix convention and matches the
> `*OPC`/state model, but I did not extract its exact manual page — prefer
> `ACQuire:STATE?` polling, which is directly documented.

---

## 4. Waveform transfer

| Command (set) | Query | Arguments / notes | Confidence |
|---|---|---|---|
| `DATa:SOUrce <wfm>` | `DATa:SOUrce?` | `CH<x>`, `MATH`, `REF<x>` (`FFT` on some) | TBS1000B p.90 |
| `DATa:ENCdg {ASCIi\|RIBinary\|RPBinary\|SRIbinary\|SRPbinary}` | `DATa:ENCdg?` | `RIBinary` = signed int, **MSB first (big-endian)** | TBS1000B p.89 |
| `DATa:WIDth {1\|2}` | `DATa:WIDth?` | 1 byte (8-bit) or 2 byte/point. TBS1000C ADC is 8-bit → use `1` | TBS1000B p.92 |
| `DATa:STARt <NR1>` | `DATa:STARt?` | first point, 1..record length | TBS1000B p.90 |
| `DATa:STOP <NR1>` | `DATa:STOP?` | last point, 1..record length (**20000 on TBS1000C**, 2500 on TBS1000B) | TBS1000B p.91 |
| `CURVe?` | (query) | returns IEEE block `#<x><yyy><data>` (`<x>` digits give byte count `<yyy>`) | TBS1000B p.87 |
| `WFMPre?` / `WFMOutpre?` | (query) | preamble; keyword=value pairs, `;`-separated | both live-probed OK |

**`WFMOutpre?` field order** (TBS2000/TBS1000C style; example return, 077-1149 p.275):
```
BYT_NR 2;BIT_NR 16;ENCDG ASCII;BN_FMT RI;BYT_OR MSB;WFID "Ch1, DC coupling,
100.0mV/div, 4.000us/div, 10000 points, Sample mode";NR_PT 10000;PT_FMT Y;
XUNIT "s";XINCR 4.0000E-9;XZERO -20.0000E-6;PT_OFF 0;YUNIT "V";YMULT 15.6250E-6;
YOFF 6.4000E+3;YZERO 0.0000
```
0-based positional order (split on `;` only): 0 `BYT_NR`, 1 `BIT_NR`, 2 `ENCDG`,
3 `BN_FMT`, 4 `BYT_OR`, 5 `WFID`, 6 `NR_PT`, 7 `PT_FMT`, 8 `XUNIT`, 9 `XINCR`,
10 `XZERO`, 11 `PT_OFF`, 12 `YUNIT`, 13 `YMULT`, **14 `YOFF`, 15 `YZERO`**.

**`WFMPre?` (legacy, TDS/TBS1000B) field order is DIFFERENT** (077-0444 p.227):
`WFID;PT_FMT;XINcr;PT_Off;XZEro;XUNit;YMUlt;YZEro;YOFf;YUNit;NR_Pt` — here
`YZEro` precedes `YOFf` and `NR_Pt` is last.

**Driver implications (important):**
- The two preamble queries return fields in **different orders**, AND the `WFID`
  field contains commas. So any *positional* parse that splits on `,` is unsafe.
  **Parse by keyword** (`XINCR`, `XZERO`, `YMULT`, `YOFF`, `YZERO`) — which
  `oscilloscope.py` already does first; that path is correct and robust.
- The driver's positional *fallback* assumes `parts[14]=YZERO, parts[15]=YOFF`,
  but `WFMOutpre?` is the reverse (`14=YOFF, 15=YZERO`). This is a latent bug that
  only bites if keyword parsing fails; leave keyword-first logic as the primary.
- Voltage decode `volts = (raw - YOFF)*YMULT + YZERO` is correct (Tek convention).
- `DATa:ENCdg RIBinary` + `DATa:WIDth 1` ⇒ read as signed 8-bit big-endian
  (`query_binary_values(datatype="b", is_big_endian=True)`) — matches the driver.
- Set `DATa:STOP` to the real record length (query `HORizontal:RECOrdlength?`,
  typically 20000). Sending `1000000` normally clamps to the max on Tek, but
  20000 is cleaner and unambiguous.

---

## 5. FastFrame / segmented memory — NOT present

TBS1000C has **no FastFrame / segmented memory** (`HORizontal:FASTframe:*`
rejected on the real unit). Instead:
- **Max record length: 20,000 points** (all TBS1000C models; datasheet /
  Technical Reference 077-1583).
- **Acquisition modes: Sample, Peak Detect, Average** (no HiRes, no Envelope on
  this family). Sample is default. (User manual + `ACQuire:MODe` enum.)

---

## 6. Record length control

- `HORizontal:RECOrdlength <NR1>` / `HORizontal:RECOrdlength?` — present on
  TBS1000C (TBS1000C Programmer Manual p.105 in 077-1691-02); **query works on the
  real unit**. The TBS2000 accepts `{2000|20000|200000|2000000|20000000}`, but the
  TBS1000C tops out at 20000, so its valid set is expected to be **{2000, 20000}**
  (settability/exact enum **not verified** — confirm on p.105 before writing it).
- `HORizontal:SAMPLERate?` also works (live-probed).
- If in doubt, treat record length as effectively 20000 and just read the whole
  record (`DATa:STARt 1; DATa:STOP 20000`).

---

## 7. Channel count / capability queries

- No dedicated "channel count" query on this family. Options:
  - `*IDN?` → e.g. `TEKTRONIX,TBS1052C,<serial>,CF:... FV:v...`; parse the model.
    **All TBS1000C are 2-channel**, so model ⇒ 2 channels is safe.
  - `*OPT?` → installed options string (not channel count).
  - Probe: `SELect:CH3?` / `CH3:SCAle?` on a 2-ch scope raises an error visible via
    `ALLEv?` — usable but noisier than model parsing.
- `HEADer {ON|OFF}` and `VERBose {ON|OFF}` control whether query replies include the
  command header and long-form keywords — relevant if parsing replies strictly.

---

## 8. Error / event queue (verifying commands were accepted)

`*IDN?`-family and event handling are standard IEEE-488.2 (live-probed `*ESR?`,
`ALLEv?`):

- `*ESR?` — Event Status Register (clears on read). Nonzero ⇒ something happened.
  Bit 5 (32) = **CME command error** (this is what "Undefined header" sets),
  bit 4 (16) = EXE execution error, bit 3 (8) = DDE device error, bit 2 (4) = QYE
  query error, bit 0 (1) = OPC.
- `ALLEv?` — returns **all** queued events as `code,"message"` pairs and clears the
  queue (TBS1000B p.61). Related: `*CLS, DESE, *ESE, *ESR?, EVENT?, EVMsg?, EVQty?,
  *SRE, *STB?`.
- `EVENT?` — next event **code** only; `EVMsg?` — next event `code,"message"`;
  `EVQty?` — number of events queued.

**Recommended verification pattern for the driver** (so a rejected command surfaces
instead of silently failing, as the old `TRIGger:MODE` did):
```
*CLS                          ; clear status at start of a config batch
...send configuration commands...
*ESR?                         ; nonzero ⇒ at least one command errored
ALLEv?                        ; fetch code+message(s) if *ESR? != 0
```
`*OPC?` (returns `1`) can also be used to serialize after a config batch.

---

## Recommended command sequences (copy for the driver)

**Edge trigger (TCT external, AUX, falling, -0.41 V):**
```
*CLS
TRIGger:A:TYPe EDGe
TRIGger:A:MODe NORMal
TRIGger:A:EDGE:SOUrce AUX      ; verify AUX vs EXT via ALLEv?
TRIGger:A:EDGE:COUpling DC
TRIGger:A:EDGE:SLOpe FALL
TRIGger:A:LEVel -0.41
*ESR?  / ALLEv?                ; confirm no "Undefined header"/exec error
```

**Single-sequence arm + wait:**
```
ACQuire:STOPAfter SEQuence
ACQuire:STATE RUN              ; RUN | ON | 1 all valid
; then poll until done:
ACQuire:STATE?                 ; -> 0 when the single sequence has stopped
; (alternatives: BUSY? -> 0, or *OPC? -> 1)
```

**Average mode:**
```
ACQuire:MODe AVERAGE
ACQuire:NUMAVg 16              ; ONLY 4 | 16 | 64 | 128
```

**Waveform read (per channel):**
```
DATa:SOUrce CH1
DATa:ENCdg RIBinary
DATa:WIDth 1
DATa:STARt 1
DATa:STOP 20000               ; = record length (query HORizontal:RECOrdlength?)
CURVe?                        ; IEEE block, signed 8-bit big-endian
WFMOutpre?                    ; parse XINCR/XZERO/YMULT/YOFF/YZERO by keyword
```

## Gotchas summary

- **`TRIGger:MODE/SOURce/LEVel/SLOPe` do not exist** — use `TRIGger:A:*`.
- **External source is `AUX`, not `EXT`** (strong evidence; verify on p.148/224).
- `SELect:CH<x>` **resets acquisition** — do channel setup before arming.
- `ACQuire:NUMAVg` accepts **only 4/16/64/128**.
- No **HiRes**, no **FastFrame**; record length **20000**.
- `WFMPre?` and `WFMOutpre?` have **different field orders**, and `WFID` contains
  commas — parse the preamble **by keyword**, never by comma position.
- `ACQuire:STATE RUN` is correct; polling `ACQuire:STATE?` (→0) is the documented
  single-sequence-done test.

## Sources

- [TBS1000C Series Oscilloscopes Programmer Manual (077-1691) — tek.com landing](https://www.tek.com/en/manual/oscilloscope/tbs1000c-series-oscilloscopes-programmer-manual-tbs1000) — official; command names, page map (HORizontal:RECOrdlength p.105; TRIGger:A group p.147-158 in -02 / 222-238 in -00). *official manual (index/page map read; detail-page argument text not text-extractable).*
- [TBS1000C Series Programmer Manual PDF (077-1691-00), ujaen.es mirror](https://www.ujaen.es/departamentos/ingele/sites/departamento_ingele/files/uploads/node_seccion_de_micrositio/2021-01/osciloscopio%20TBS1052C%20manual%20del%20programador.pdf) — official manual mirror.
- [TBS1000C Series User Manual (077-1571), ManualsLib](https://www.manualslib.com/manual/1956669/Tektronix-Tbs1000c-Series.html) — trigger types (Edge/Pulse Width/Runt), rising/falling slope, external trigger via **AUX input / "AUX source"** (p.70, p.92). *official manual.*
- [TBS2000 Series Programmer's Manual (077-1149), ManualsLib](https://www.manualslib.com/manual/1291718/Tektronix-Tbs2000-Series.html) — exact `TRIGger:A:*` args (MODe p.248, EDGE:SLOpe p.243, EDGE:COUpling p.242, EDGE:SOUrce p.244, LEVel p.246, LEVel:CH<x> p.247, TYPe p.258, PULse:CLAss p.250), `SELect:CH<x>` p.230, `WFMOutpre?` order p.275. *official manual, same command engine — cross-referenced (external source differs).* 
- [TBS1000B/EDU Programmer's Manual (077-0444), ManualsLib](https://www.manualslib.com/manual/1298717/Tektronix-Tbs1000b-Edu.html) — exact `ACQuire:*` args (MODe p.58, NUMAVg p.59-60, STATE p.60, STOPAfter p.61, ACQuire? p.57), `DATa:*` (ENCdg p.89, SOUrce/STARt p.90, STOP p.91, WIDth p.92), `CURVe?` p.87, `WFMPre?` order p.227, `ALLEv?` p.61. *official manual, shared command engine (but uses `TRIGger:MAIn`, record length 2500).* 
- [TBS1000C Series Datasheet, tek.com](https://www.tek.com/en/datasheet/digital-storage-oscilloscope-tbs1000c-series-datasheet) — 20 kpt record length, 1 GS/s, 2-channel, acquisition modes. *official.*
- Live probing of the physical TBS1052C (supplied by Adam) — confirmed working/rejected command set.

**Overall confidence:** command tree + `ACQuire`/`DATa`/`CURVe`/`WFMPre`/`SELect`
argument syntax = **official manual**. `TRIGger:A` argument enums =
**official manual (same-engine TBS2000/TBS1000B), cross-referenced**. The exact
external-source keyword `AUX` and the TBS1000C `HORizontal:RECOrdlength` value set =
**secondary/needs final verification** against TBS1000C Programmer Manual detail
pages (p.148/224 and p.105).
