# Council seat: Ollama (qwen2.5-coder:14b, GPU lane, raw advisory) — 2026-07-12

Key accepted points (Adam's filter):
- Colorblind safety: red/green must never be hue-only — pair every state
  color with the LED dot + text label (chips already comply; tiles keep
  LED+label; consider pattern/shape on map legends).
- Hold-to-arm: keep the visible fill progress; consider a numeric countdown;
  watch total hold time (900ms) vs glove operation; keep dialog text explicit.
- Glove-friendly hit targets on bench-critical controls (≥36-40px).
- Text opacity floors on dark (labels ≥ ~85% ink) for 8h shifts.
- Animation discipline @1 Hz: value changes are NOT animated; only state
  TRANSITIONS get a ~200ms color/opacity ease; only live states may pulse.
- Soft low-opacity shadows / subtle vertical gradients acceptable; no glow
  on non-interactive surfaces.
Rejected: blanket "blinking indicators" (conflicts with calm-first; pulse is
reserved for live/scanning states only).
