# Nachtbericht — Big-Wave-Session 2026-07-13 (04:15 → 10:00)

**Für:** Kaya · **Von:** Adam · **Branch:** `design/cockpit-v5` · **Stand:** 09:55
(Addenda unten, falls nach Redaktionsschluss noch Beats gelandet sind.)

## TL;DR

**28 Beats gelandet, alle vier Feature-Tracks des ratifizierten Plans geliefert
oder überliefert.** Der **Scan Sequencer ist komplett und safety-signiert**
(Mary: CLOSED, nach zwei von ihr erzwungenen Nachbesserungen — genau wofür sie
da ist). E-Feld-Fitqualität komplett, HDF5-Ehrlichkeit komplett, echte
Transparenz softwarefertig (wartet nur auf dein Auge), Metrologie bis zur
Affine-Selbstkalibration gelandet. **Ein ehrliches Rot zum Schluss:** das
finale Bench-Gate fand einen echten Thread-Teardown-Race in A5.1s neuem
ALL-OFF-Pfad (1 failed / 1690 passed) — Fix war bei Redaktionsschluss in
flight. Origin steht deshalb bewusst noch auf dem letzten grünen Set.

## Was gelandet ist (git log ist die Quelle; Mamoru-Audit siehe unten)

### Track A — Scan Sequencer (KOMPLETT, Mary: CLOSED)
- `f83b184` A1 kombiniertes Queue-Envelope (`envelope_from_plans`, jede Routine
  im Arm-Text; deine Ratifikation umgesetzt)
- `e2ba013` A2 pure Queue-Engine (fail-closed: alles außer „finished" hält die
  Nacht an; Preflight-Hook als Interface für die spätere Kamera-Korrektur)
- `ba6128b`+`7b32dc3` A3/A3.1 `park_safe()` — parkt zwischen Einträgen JEDEN
  Bias-Kanal (Marys MAJOR), keine Auto-Motion
- `c1fc0c2` A4 SequenceCoordinator (Union-Gate beweisbar privat, Deep-Copy-
  Snapshots, kein hängendes `sequence_active`)
- `1ca5677` A5 SequencerPanel (ArmLatch, rote Abort-Outline, Modal-Suppression
  — die Nacht kann nicht mehr an einem Dialog hängen)
- `7061e97` A5.1 chirurgische Locks — **NOT-AUS bleibt immer scharf** (Motor
  STOP, Output-OFF, ALL-OFF; funktional bewiesen: Klick während Lock feuert)
- `88f500f`+`6e691fd` A5.2 `manual_pause` kann nie in eine unbeaufsichtigte
  Queue (Validator-ERROR an 3 Eintrittspunkten + Dialog-Guard mit Auto-Abort)

### Track B — Planner-Ausbau + HDF5-Ehrlichkeit (KOMPLETT)
- `06de0dc` B1: `frame_point_index`, Drop-Zähler `n_frames_omitted`, **kein
  Zero-Backfill mehr** — ein verlorener Frame kann nie wieder als Dark Frame
  durchgehen; `set_camera_calibration` für die Metrologie
- `f3b0457` B2: `capture_photo`-Block end-to-end (Palette-Row + `camera_available`
  in `1ca5677` mitverdrahtet). §6 acquire-measurements bewusst vertagt.

### Track C — Echte Transparenz (SOFTWAREFERTIG)
- `df43ca9` C1 DWM-Kern (Mica/Acrylic, fail-safe Ordering, headless no-op)
- `c66ee05` C2 Settings + Theme-Editor-Combo + Grau-Blitz-Fix (die sichere
  Variante — `setPalette(app.palette())` hätte einen klebrigeren Bug erzeugt)
- `d100650` C3-mini: letzter Streu-Hex weg, Guard mit Per-Wert-Zähnen
- **Default ist „none"** — nichts ändert sich, bis du den Toggle kippst.
  Deine 6-Punkte-Eyeball-Checkliste: `docs/BENCH_CHECKLIST.md` §8.

### Track D — E-Feld ehrlich gemacht (KOMPLETT)
- `95b27c7` D1 `DepletionFitResult` (σ, Bracket, Ambiguität, Qualität 0-1;
  alte API als Wrapper unangetastet)
- `a3449be` D2 CCE-Unsicherheit (Ref-Streuung propagiert; `q_term_included`
  sagt ehrlich, was heute NICHT schätzbar ist)
- `419a0a0` D3 Tiles im CCE-View (V_dep±σ · Quality · Flags · Ref-σ; das
  `try/except: pass` ist tot; Ref-σ zeigt heute by design 0.0 % — bitte nie
  in Fake-Präzision „fixen")
- `00d53bc` D4 Referenzkanal-Baseline (Kings-Retro-RISK zu; Formel kanonisch in
  `analysis/`, byte-identischer Devices-Spiegel per Test gepinnt; Sim injiziert
  jetzt permanent einen DC-Offset als Regressionswache)

### Track E — Metrologie + Kamera + Survey (bis E3/E6a gelandet)
- `f1e1712`+`00abe9c` E1 Kamera-Fixes: dein **Mono16-Aliasing** (fixe `>>4`-
  Truncation → Perzentil-Fensterung) und das **Weißbild bei Binning 2/4**
  (Average-Mode-Versuch + Display-Rescale). Prometheus-Befund (`f284d06`):
  klassischer BFLY ist hardware-seitig Sum-only — die Display-Fensterung IST
  der Fix; SpinView-Check am Gerät steht in `BENCH_CHECKLIST.md` §9.
- `b5b8051` E2 `prepare_metrology_roi` (Vignette-Killer für Phasenkorrelation;
  unterwegs gefundener NaN-Poisoning-Bug getötet + getestet)
- `fb7ee7c` E3 Stage↔Kamera-**Affine-Selbstkalibration**, danger-gated (ein
  Confirm für die ganze Treppe; Denial = null Bewegung, spy-bewiesen; Sim
  rekonstruiert Ground-Truth-Affine auf 0.0085 px rms). **Mary: APPROVE**,
  zwei Vorab-RISKs für die GUI-Verdrahtung notiert (`should_stop`-Hook,
  `affine is None`-Guard).
- `d2050e3` E6a `plan_survey` (Schlangengitter Move+Foto aus `plan_grid`,
  kamera-only, Geometrie reist im Plan mit)
- E4 (Affine-Mosaik + Refine): **Erstversuch am 64k-Output-Limit gestorben
  (nichts beschädigt), Retry bei Redaktionsschluss in flight** — Addendum.

### Governance / Hygiene
- `a99829e` deine Test-Ökonomie hart in CLAUDE.md („one execution per truth")
- `88907a4` sechs Ratifikationen formell in DECISIONS.md
- `a84adbd` W3-Batch 1: Rot heißt wieder ausschließlich Gefahr (Kamera-offline
  neutral; 2 von 3 Census-Items waren schon zu — Paul hat Zähne statt Diffs
  geliefert)
- `26bcf95`+`034c176` Phase 1: StateMachine-Race zu (xdist-Mislabel-Quelle),
  `output_on`-Footgun entschärft (`enable_output`/`is_output_on`, Tippfehler
  ⇒ AttributeError statt HV)
- Mamorus Suite-Audit: **kein Aufräumbedarf** — 994 Tests, null Duplikate
  (Überlappung = gestaffelte Verteidigung), null Leichen. Deine Frage von
  gestern Nacht ist damit datenbasiert beantwortet: die Akkumulation ist
  Panzerung.

## Reviews (alle Safety-Klasse hatte Mary)

| Review | Verdict |
|---|---|
| HV-Tor-Set (df10f8e+0f1c012) | APPROVE — 7 Fail-Safe-Pfade tracet |
| Phase 1 (26bcf95+034c176) | APPROVE (2 NITs) |
| Track-A-Set (A1-A3) | REQUEST-CHANGES → Fixes gelandet |
| Sequencer-Closure (A4/A5/A3.1/W3) | REQUEST-CHANGES (2 MAJORs) → Fixes gelandet |
| Endverifikation (A5.1+A5.2) | **CLOSED** |
| E3 Gate/Motion | **APPROVE** (2 Vorab-RISKs für GUI-Wiring) |

## Bench-Gates (ehrlich)

| HEAD | Ergebnis |
|---|---|
| `88907a4` (HV-Tor-Set) | **GRÜN — 1349 passed** |
| `ee9f48d` (Phase-1-Set) | **GRÜN — 1372 passed** · = aktueller origin-Stand |
| `a68e289` (Nacht-Endstand) | **ROT — 1 failed / 1690 passed** |

Der eine Rote: `test_multi_bias_lock_forwards_to_children_and_keeps_all_off_live`
— A5.1s eigener neuer Test. `QThread::wait: Thread tried to wait on itself`:
ein echter Teardown-Race im neuen ALL-OFF-Thread (Busy-Clear eines Kindes
verliert unter xdist-Last gegen den Thread-Cleanup; seriell lokal grün). Das
ist **die bekannte WorkerThread-Debt-Klasse**, vom Bench exakt dort erwischt,
wo er sie erwischen soll. Fix-Beat (Noah, Opus, Root-Cause-Pflicht +
20x-Wiederholungs-Verifikation) bei Redaktionsschluss in flight — Addendum
unten. **Origin bleibt bis zum grünen Gate auf `ee9f48d`** (Ledger-Regel:
Real-HV-Readiness gilt nur für verifizierte Sets — das sind weiterhin
`88907a4` und `ee9f48d`).

## Abweichungen & Lektionen der Nacht

1. **Codex-Lane-Protokoll:** Inline-Objectives prallen ab — die Lane führt nur
   `CODEX_QUEUE.md`-Tasks aus. Style-Audit als Task S1 neu eingereiht;
   Lektion dauerhaft im Daedalus-Memory. (Erster Anlauf kostete ~2 h Latenz.)
2. **E4-Agent am 64k-Output-Limit gestorben** — nichts auf Disk beschädigt;
   Retry mit Inkrementell-Edit-Auflagen.
3. **B2-Writer-Abweichung** (additives `save_camera_frame`): mit Probe-Beweis
   akzeptiert, von Jonathan mit Direktreproduktion approved — der stille
   Zero-Backfill wäre schlimmer als der Crash gewesen.
4. **Mein eigener Fehltritt:** Ich habe einmal quer über Pauls halbfertigen
   Rename getestet (Fehlalarm). Regel steht jetzt in CLAUDE.md: nie in fremde
   File-Locks hineintesten.

## Was DICH braucht (nichts davon blockiert die Tagschicht)

1. **Backdrop-Eyeball** (`BENCH_CHECKLIST.md` §8): Mica/Acrylic am echten
   Display, Kandidat A/B (`_CANVAS_MODE`), Opacity×Backdrop, Titlebar, Drag.
2. **Bench-Hardware-Checks** §9/§10: SpinView Binning-Nodes (SN 19112408),
   Ref-Baseline-Fenster pulsfrei am echten Timebase.
3. **Geparkt aus dem Handoff:** v5-Ratifikation (14 Artefakte),
   Slow-Control-UNAVAILABLE-Eskalation, Metrologie-Präzisionsziel (2 µm?
   braucht Glas/Chrom-Slide), Ollama-Watcher mit GPU-Env.

## Tagschicht-Queue (fertig gebrieft, sofort zündbar)

1. **Bench-Fix landen** (falls nicht schon im Addendum grün) → Gate → Push.
2. **E4** Affine-Mosaik (Retry läuft/Addendum) → **E5** Distortion-Report-
   Artefakt → **E6b** Mosaik-View (+ `frame_pos_mm`-Writer-Entscheidung,
   Jonathan) — dann ist dein **Stitched Image** komplett sichtbar.
3. **E7b/c Sensor-Pose:** OpenCV-Pin ratifiziert + recherchiert
   (`opencv-python-headless==4.9.0.80`, DICT_4X4_50, Pose-Leiter in
   `docs/research/sensor_alignment_cv.md`) — bewusst NICHT nachts um 9 als
   natives Dependency eingespielt.
4. Trailing: WorkerThread-Primitive (der Bench-Rote ist ihr bester Verkäufer),
   `app_settings.py`-Accessor, W3-Batch 2/3, `scan_map_view`-Throttle,
   Marys E3-RISKs vor GUI-Wiring, Codex-S1-Verdicts einarbeiten.

## Externes Audit (Mamoru, Regel 4 — der Orchestrator wird geprüft)

**Alle 37 behaupteten Commits in `git log` verifiziert — keine einzige
Falschbehauptung.** Dirty Tree vollständig durch In-Flight-Beats erklärt;
`origin` korrekt auf dem letzten grünen Set gehalten. Zwei fehlende
ARCHITECTURE-Changelog-Zeilen gefunden (Timing-Lücken) — behoben.

**Dabei von mir entdeckt und sofort korrigiert:** Kirokus Final-Sweep hatte
mehrere Changelog-Texte **konfabuliert** (erfundene APIs, und „:613 primary
channel only" war das exakte Gegenteil des A3.1-Fixes). Mamoru prüfte
Hash-Präsenz, nicht Text-Wahrheit. Alle 17 Zeilen des Sweeps sind jetzt aus
erster Hand korrigiert. **Prozess-Lektion für die Tagschicht:**
Haiku-Changelog-Zeilen brauchen einen Text-gegen-Commit-Message-Check, nicht
nur einen Hash-Check; Kirokus Batch-2-Zeilen (weiter unten im Changelog)
sollten denselben Audit bekommen.

## Addenda (nach Redaktionsschluss)

- _Bench-Fix (Noah), E4-Retry (Jonathan), Codex S1: bei Redaktionsschluss in
  flight — wird hier ergänzt._
