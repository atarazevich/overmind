# Decisions

## 2026-09-17 — Substrate
Jev (TypeSafe System One) as the per-event judge instead of an LLM. Context: the April Overmind ran an LLM watcher and was too slow and expensive to run on every event; Jev returns typed probabilities in ~300 ms at ~$0.04/day. Local alternatives (GLiNER2.5, constrained-decoding on Qwen 1.5B) noted; not calibrated; to be compared later on the labels this project collects.

## 2026-09-17 — Observe first
Phases fixed as observe → label → inject. No action of any kind before the calibration curve exists.
